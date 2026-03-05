from __future__ import annotations

import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests
import urllib3
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


def _load_dotenv() -> None:
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if not key:
                    continue
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except OSError:
        return


_load_dotenv()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    tronclass_base_url: str
    cas_login_path: str
    cas_logout_path: str
    service_callback_path: str
    app_session_ttl_seconds: int
    login_state_ttl_seconds: int
    cors_allowed_origins: str
    tronclass_ssl_verify: str


settings = Settings(
    tronclass_base_url=os.getenv("TRONCLASS_BASE_URL", "https://elearn2.fju.edu.tw/"),
    cas_login_path=os.getenv("CAS_LOGIN_PATH", "/cas/login"),
    cas_logout_path=os.getenv("CAS_LOGOUT_PATH", "/cas/logout"),
    service_callback_path=os.getenv("SERVICE_CALLBACK_PATH", "/login?next=/user/index"),
    app_session_ttl_seconds=_env_int("APP_SESSION_TTL_SECONDS", 60 * 60),
    login_state_ttl_seconds=_env_int("LOGIN_STATE_TTL_SECONDS", 10 * 60),
    cors_allowed_origins=os.getenv("CORS_ALLOWED_ORIGINS", "https://whl.tw"),
    tronclass_ssl_verify=os.getenv("TRONCLASS_SSL_VERIFY", "true"),
)


@dataclass
class LoginState:
    created_at: float
    service_url: str
    login_action_url: str
    lt: str
    execution: str
    event_id: str
    captcha_url: str
    cookies: dict[str, str]


@dataclass
class AppSession:
    created_at: float
    cookies: dict[str, str]


class MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._login_states: dict[str, LoginState] = {}
        self._sessions: dict[str, AppSession] = {}

    def put_login_state(self, value: LoginState) -> str:
        key = secrets.token_urlsafe(24)
        with self._lock:
            self._login_states[key] = value
        return key

    def pop_login_state(self, key: str) -> LoginState | None:
        with self._lock:
            return self._login_states.pop(key, None)

    def peek_login_state(self, key: str) -> LoginState | None:
        with self._lock:
            return self._login_states.get(key)

    def put_session(self, value: AppSession) -> str:
        key = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[key] = value
        return key

    def get_session(self, key: str) -> AppSession | None:
        with self._lock:
            return self._sessions.get(key)

    def delete_session(self, key: str) -> AppSession | None:
        with self._lock:
            return self._sessions.pop(key, None)

    def cleanup_expired(self) -> None:
        now = time.time()
        with self._lock:
            self._login_states = {
                key: value
                for key, value in self._login_states.items()
                if now - value.created_at <= settings.login_state_ttl_seconds
            }
            self._sessions = {
                key: value
                for key, value in self._sessions.items()
                if now - value.created_at <= settings.app_session_ttl_seconds
            }


store = MemoryStore()
app = FastAPI(title="FJU TronClass Auth Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        item.strip()
        for item in settings.cors_allowed_origins.split(",")
        if item.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PreloginResponse(BaseModel):
    login_state_id: str
    captcha_path: str
    expires_in_seconds: int
    message: str


class LoginRequest(BaseModel):
    login_state_id: str
    username: str
    password: str
    captcha: str


class LoginResponse(BaseModel):
    token: str
    expires_in_seconds: int
    message: str


def _base_url() -> str:
    return settings.tronclass_base_url.rstrip("/") + "/"


def _service_url() -> str:
    return urljoin(_base_url(), settings.service_callback_path.lstrip("/"))


def _cas_login_url(service_url: str) -> str:
    path = settings.cas_login_path.lstrip("/")
    return urljoin(_base_url(), f"{path}?{urlencode({'service': service_url})}")


def _cas_logout_url(service_url: str) -> str:
    path = settings.cas_logout_path.lstrip("/")
    return urljoin(_base_url(), f"{path}?{urlencode({'service': service_url})}")


def _extract_first_match(pattern: str, html: str) -> str:
    matched = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    if not matched:
        return ""
    return matched.group(1).strip()


def _extract_login_form(html: str, page_url: str) -> tuple[str, str, str, str, str]:
    form_match = re.search(r"<form[^>]*>(.*?)</form>", html, re.IGNORECASE | re.DOTALL)
    if not form_match:
        raise HTTPException(status_code=502, detail="CAS login form not found")
    form_html = form_match.group(0)

    action = _extract_first_match(r"<form[^>]*action=[\"']([^\"']+)[\"']", form_html)
    login_action_url = urljoin(page_url, action)

    def read_input(name: str, default: str = "") -> str:
        pattern = rf"<input[^>]*name=[\"']{re.escape(name)}[\"'][^>]*value=[\"']([^\"']*)[\"']"
        value = _extract_first_match(pattern, form_html)
        return value or default

    lt = read_input("lt")
    execution = read_input("execution")
    event_id = read_input("_eventId", "submit")

    captcha_src = _extract_first_match(
        r"<img[^>]*id=[\"']captchaImg[\"'][^>]*src=[\"']([^\"']+)[\"']", html
    )
    if not captcha_src:
        captcha_src = _extract_first_match(
            r"<img[^>]*alt=[\"']captcha[\"'][^>]*src=[\"']([^\"']+)[\"']", html
        )
    if not captcha_src:
        captcha_src = _extract_first_match(
            r"<img[^>]*src=[\"']([^\"']*captcha[^\"']*)[\"']",
            html,
        )

    captcha_url = urljoin(page_url, captcha_src) if captcha_src else ""
    return login_action_url, lt, execution, event_id, captcha_url


def _is_login_success(final_url: str) -> bool:
    parsed = urlparse(final_url)
    if "cas/login" in parsed.path:
        return False
    query = parse_qs(parsed.query)
    return bool(query.get("ticket")) or parsed.path.endswith("/user/index")


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(
            status_code=401, detail="Authorization must be Bearer token"
        )
    token = authorization[len(prefix) :].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is empty")
    return token


def _ssl_verify_option() -> bool | str:
    raw = settings.tronclass_ssl_verify.strip()
    lowered = raw.lower()
    if lowered in {"0", "false", "no", "off"}:
        return False
    if lowered in {"1", "true", "yes", "on", ""}:
        return True
    return raw


if _ssl_verify_option() is False:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _client_with_cookies(cookies: dict[str, str]) -> requests.Session:
    session = requests.Session()
    session.cookies.update(cookies)
    return session


@app.get("/health")
def health() -> dict[str, bool | str]:
    store.cleanup_expired()
    return {"ok": True, "service": "fju-tronclass-auth-bridge"}


@app.post("/auth/fju/prelogin", response_model=PreloginResponse)
def prelogin() -> PreloginResponse:
    store.cleanup_expired()
    service_url = _service_url()
    cas_url = _cas_login_url(service_url)

    with requests.Session() as client:
        try:
            response = client.get(cas_url, timeout=20, verify=_ssl_verify_option())
        except requests.exceptions.SSLError as exc:
            raise HTTPException(
                status_code=502,
                detail="Upstream TLS verification failed. Set TRONCLASS_SSL_VERIFY=false for test only, or provide CA bundle path.",
            ) from exc
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=502, detail="Failed to connect to TronClass CAS"
            ) from exc
        response.raise_for_status()
        login_action_url, lt, execution, event_id, captcha_url = _extract_login_form(
            response.text, response.url
        )

        login_state = LoginState(
            created_at=time.time(),
            service_url=service_url,
            login_action_url=login_action_url,
            lt=lt,
            execution=execution,
            event_id=event_id,
            captcha_url=captcha_url,
            cookies=client.cookies.get_dict(),
        )

    login_state_id = store.put_login_state(login_state)
    return PreloginResponse(
        login_state_id=login_state_id,
        captcha_path=f"/auth/fju/captcha/{login_state_id}",
        expires_in_seconds=settings.login_state_ttl_seconds,
        message="Fetch captcha via captcha_path, then submit login with captcha text",
    )


@app.get("/auth/fju/captcha/{login_state_id}")
def get_captcha(login_state_id: str) -> Response:
    store.cleanup_expired()
    state = store.peek_login_state(login_state_id)
    if state is None:
        raise HTTPException(
            status_code=404, detail="login_state_id not found or expired"
        )
    if not state.captcha_url:
        raise HTTPException(status_code=400, detail="captcha URL not found in CAS page")

    with _client_with_cookies(state.cookies) as client:
        try:
            response = client.get(
                state.captcha_url, timeout=20, verify=_ssl_verify_option()
            )
        except requests.exceptions.SSLError as exc:
            raise HTTPException(
                status_code=502,
                detail="Upstream TLS verification failed while fetching CAPTCHA",
            ) from exc
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=502, detail="Failed to fetch CAPTCHA from CAS"
            ) from exc
        if response.status_code >= 400:
            raise HTTPException(
                status_code=502, detail="Failed to fetch captcha from CAS"
            )
        state.cookies = client.cookies.get_dict()

    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", "image/png"),
    )


@app.post("/auth/fju/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    store.cleanup_expired()
    state = store.pop_login_state(payload.login_state_id)
    if state is None:
        raise HTTPException(
            status_code=404, detail="login_state_id not found or expired"
        )

    form_data = {
        "username": payload.username,
        "password": payload.password,
        "captcha": payload.captcha,
        "lt": state.lt,
        "execution": state.execution,
        "_eventId": state.event_id,
    }

    with _client_with_cookies(state.cookies) as client:
        try:
            response = client.post(
                state.login_action_url,
                data=form_data,
                timeout=20,
                allow_redirects=True,
                verify=_ssl_verify_option(),
            )
        except requests.exceptions.SSLError as exc:
            raise HTTPException(
                status_code=502,
                detail="Upstream TLS verification failed during CAS login",
            ) from exc
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=502, detail="Failed to submit CAS login request"
            ) from exc

        final_url = response.url
        if not _is_login_success(final_url):
            detail = (
                "Login failed: invalid credentials/captcha or CAS challenge changed"
            )
            raise HTTPException(status_code=401, detail=detail)

        cookies = client.cookies.get_dict()

    token = store.put_session(AppSession(created_at=time.time(), cookies=cookies))
    return LoginResponse(
        token=token,
        expires_in_seconds=settings.app_session_ttl_seconds,
        message="Login success",
    )


@app.get("/auth/fju/courses")
def list_courses(
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | list[Any]:
    store.cleanup_expired()
    token = _extract_bearer_token(authorization)
    session = store.get_session(token)
    if session is None:
        raise HTTPException(status_code=401, detail="Session token invalid or expired")

    endpoint = urljoin(_base_url(), "api/my-courses")
    with _client_with_cookies(session.cookies) as client:
        try:
            response = client.get(endpoint, timeout=20, verify=_ssl_verify_option())
        except requests.exceptions.SSLError as exc:
            raise HTTPException(
                status_code=502,
                detail="Upstream TLS verification failed while fetching courses",
            ) from exc
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=502, detail="Failed to call TronClass course API"
            ) from exc
        if response.status_code == 401:
            raise HTTPException(
                status_code=401, detail="Upstream TronClass session expired"
            )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=502, detail=f"TronClass API failed: {response.status_code}"
            )
        session.cookies = client.cookies.get_dict()

    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502, detail="Unexpected non-JSON response"
        ) from exc


@app.post("/auth/fju/logout")
def logout(authorization: str | None = Header(default=None)) -> dict[str, bool | str]:
    token = _extract_bearer_token(authorization)
    session = store.delete_session(token)
    if session is None:
        return {"ok": True, "message": "Already logged out"}

    with _client_with_cookies(session.cookies) as client:
        try:
            client.get(
                _cas_logout_url(_service_url()),
                timeout=20,
                verify=_ssl_verify_option(),
            )
        except requests.RequestException:
            return {
                "ok": True,
                "message": "Local session removed; CAS logout request failed",
            }
    return {"ok": True, "message": "Logout requested to CAS"}
