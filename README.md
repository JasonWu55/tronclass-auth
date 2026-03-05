# FJU TronClass Auth Bridge

## Language

- Traditional Chinese: `README.zh-TW.md`

This service provides a safe integration pattern for FJU TronClass login where CAPTCHA is required.

It does not bypass CAPTCHA. It uses a human-in-the-loop flow:

1. create prelogin state
2. fetch CAPTCHA image
3. submit username/password/CAPTCHA
4. use returned app token to call TronClass course APIs

## Why this design

- FJU TronClass (`https://elearn2.fju.edu.tw`) uses CAS + CAPTCHA.
- Unattended login automation is fragile and risky with campus SSO protections.
- This bridge keeps credentials and CAS cookies server-side, and exposes only a short-lived app token to your frontend.

## Endpoints

- `POST /auth/fju/prelogin`
  - Creates one login state and parses hidden CAS form fields (`lt`, `execution`, `_eventId`).
  - Returns `login_state_id` and `captcha_path`.

- `GET /auth/fju/captcha/{login_state_id}`
  - Proxies the current CAPTCHA image from CAS using the same state cookies.

- `POST /auth/fju/login`
  - Body: `login_state_id`, `username`, `password`, `captcha`
  - Submits CAS form.
  - On success returns `token` (app session token).

- `GET /auth/fju/courses`
  - Header: `Authorization: Bearer <token>`
  - Calls TronClass `/api/my-courses` with saved session cookies.

- `POST /auth/fju/logout`
  - Header: `Authorization: Bearer <token>`
  - Calls CAS logout and clears app session.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Frontend integration (Vue on `whl.tw`)

Recommended flow:

1. Call `POST /auth/fju/prelogin`.
2. Render CAPTCHA from returned `captcha_path` image URL.
3. User types account/password/CAPTCHA.
4. Submit to `POST /auth/fju/login`.
5. Store returned app token in httpOnly cookie or secure memory storage.
6. Fetch course list from `GET /auth/fju/courses`.
7. Logout using `POST /auth/fju/logout`.

## Full API document

See `docs/login-api.md` for full endpoint contract, examples, and error codes.

## Interactive test (input account/password/captcha, then get courses)

Run:

```bash
python3 scripts/test_login_and_courses.py --base-url http://127.0.0.1:8000
```

The script will:

1. call `prelogin`
2. download CAPTCHA to `./captcha.png`
3. prompt for account/password/captcha
4. login and print raw course list JSON

## Notes

- Current store is in-memory. For production, replace with Redis.
- Keep this service server-to-server only; do not expose raw CAS cookies to browser.
- Add rate limits, audit logs, and IP allowlist before production rollout.
- If your server cannot validate FJU cert chain, set `TRONCLASS_SSL_VERIFY=false` for testing only.
- Better production option: set `TRONCLASS_SSL_VERIFY=/path/to/ca-bundle.pem`.
