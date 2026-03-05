from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive test: input account/password/captcha, then fetch course list"
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Auth bridge base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--captcha-output",
        default="./captcha.png",
        help="Local path to save CAPTCHA image",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    captcha_output = Path(args.captcha_output)

    session = requests.Session()

    print("[1/4] Create login state...")
    prelogin_resp = session.post(f"{base_url}/auth/fju/prelogin", timeout=20)
    if prelogin_resp.status_code != 200:
        print(f"Prelogin failed: HTTP {prelogin_resp.status_code}")
        print(prelogin_resp.text)
        return 1
    prelogin = prelogin_resp.json()

    login_state_id = prelogin["login_state_id"]
    captcha_path = prelogin["captcha_path"]

    print("[2/4] Download CAPTCHA image...")
    captcha_resp = session.get(f"{base_url}{captcha_path}", timeout=20)
    if captcha_resp.status_code != 200:
        print(f"CAPTCHA fetch failed: HTTP {captcha_resp.status_code}")
        print(captcha_resp.text)
        return 1
    captcha_output.write_bytes(captcha_resp.content)
    print(f"CAPTCHA saved to: {captcha_output.resolve()}")
    print("Open the image, then type the CAPTCHA text.")

    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    captcha = input("CAPTCHA: ").strip()

    print("[3/4] Submit login...")
    login_payload = {
        "login_state_id": login_state_id,
        "username": username,
        "password": password,
        "captcha": captcha,
    }
    login_resp = session.post(
        f"{base_url}/auth/fju/login", json=login_payload, timeout=20
    )
    if login_resp.status_code != 200:
        print(f"Login failed: HTTP {login_resp.status_code}")
        print(login_resp.text)
        return 1

    token = login_resp.json()["token"]

    print("[4/4] Fetch courses...")
    courses_resp = session.get(
        f"{base_url}/auth/fju/courses",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    courses_resp.raise_for_status()
    courses = courses_resp.json()

    print("\n=== Course List (raw JSON) ===")
    print(json.dumps(courses, ensure_ascii=False, indent=2))

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
