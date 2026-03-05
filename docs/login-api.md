# FJU TronClass Login API Documentation

## Overview

This API bridges FJU TronClass CAS login with CAPTCHA for your own site.

- Base target: `https://elearn2.fju.edu.tw`
- Auth mechanism: CAS + LDAP + CAPTCHA
- Bridge behavior: keep CAS cookies server-side, return short-lived app token to client

## Base URL

Use your deployed bridge host, for example:

`https://auth.whl.tw`

All endpoint paths below are relative to this base URL.

## Environment Variables

- `TRONCLASS_BASE_URL` (default: `https://elearn2.fju.edu.tw/`)
- `SERVICE_CALLBACK_PATH` (default: `/login?next=/user/index`)
- `CORS_ALLOWED_ORIGINS` (default: `https://whl.tw`)
- `TRONCLASS_SSL_VERIFY` (default: `true`)
  - `true`: normal TLS verification
  - `false`: disable verification (test only)
  - `/path/to/ca-bundle.pem`: use custom CA bundle

## Security Model

- Client never receives CAS cookies directly.
- Client only receives bridge token from `/auth/fju/login`.
- Pass token through `Authorization: Bearer <token>`.
- CAPTCHA is human-entered. No CAPTCHA bypass.

## Endpoint List

1. `POST /auth/fju/prelogin`
2. `GET /auth/fju/captcha/{login_state_id}`
3. `POST /auth/fju/login`
4. `GET /auth/fju/courses`
5. `POST /auth/fju/logout`
6. `GET /health`

---

## 1) Create Login State

`POST /auth/fju/prelogin`

### Purpose

- Open CAS login page
- Parse hidden fields (`lt`, `execution`, `_eventId`)
- Create temporary login state
- Return CAPTCHA fetch path

### Request

- Method: `POST`
- Headers: none required
- Body: none

### Success Response (`200`)

```json
{
  "login_state_id": "RANDOM_STATE_ID",
  "captcha_path": "/auth/fju/captcha/RANDOM_STATE_ID",
  "expires_in_seconds": 600,
  "message": "Fetch captcha via captcha_path, then submit login with captcha text"
}
```

### Errors

- `502`: CAS login page or form cannot be parsed

---

## 2) Get CAPTCHA Image

`GET /auth/fju/captcha/{login_state_id}`

### Purpose

- Proxy CAPTCHA image from CAS using same login-state cookies

### Request

- Method: `GET`
- Path param: `login_state_id`

### Success Response (`200`)

- Binary image (`image/png` or upstream content type)

### Errors

- `404`: `login_state_id` not found or expired
- `400`: CAPTCHA URL not found in parsed CAS page
- `502`: upstream CAPTCHA fetch failed

---

## 3) Submit Login

`POST /auth/fju/login`

### Purpose

- Submit CAS credentials and CAPTCHA
- On success store CAS cookies as app session
- Return bridge token

### Request

- Method: `POST`
- Header: `Content-Type: application/json`
- Body:

```json
{
  "login_state_id": "RANDOM_STATE_ID",
  "username": "your_student_id",
  "password": "your_password",
  "captcha": "ABCD"
}
```

### Success Response (`200`)

```json
{
  "token": "RANDOM_BEARER_TOKEN",
  "expires_in_seconds": 3600,
  "message": "Login success"
}
```

### Errors

- `404`: `login_state_id` not found/expired/already used
- `401`: login failed (wrong account/password/captcha or upstream challenge changed)

### Notes

- `login_state_id` is one-time use (consumed on login call).
- If login fails, call `prelogin` again and fetch a new CAPTCHA.

---

## 4) Get Course List

`GET /auth/fju/courses`

### Purpose

- Use stored CAS session to call TronClass `/api/my-courses`

### Request

- Method: `GET`
- Header: `Authorization: Bearer <token>`

### Success Response (`200`)

Returns upstream TronClass JSON payload from `/api/my-courses`.

Example (shape may vary by account):

```json
[
  {
    "id": 12345,
    "name": "Course Name",
    "course_code": "ABCD1234"
  }
]
```

### Errors

- `401`: missing/invalid/expired bearer token
- `401`: upstream TronClass session expired
- `502`: upstream API error or non-JSON response

---

## 5) Logout

`POST /auth/fju/logout`

### Purpose

- Clear bridge session token
- Trigger CAS logout (`/cas/logout`)

### Request

- Method: `POST`
- Header: `Authorization: Bearer <token>`

### Success Response (`200`)

```json
{
  "ok": true,
  "message": "Logout requested to CAS"
}
```

If token already invalid:

```json
{
  "ok": true,
  "message": "Already logged out"
}
```

---

## 6) Health Check

`GET /health`

### Success Response (`200`)

```json
{
  "ok": true,
  "service": "fju-tronclass-auth-bridge"
}
```

---

## Recommended Frontend Flow (Vue)

1. `POST /auth/fju/prelogin`
2. Render `<img :src="captchaUrl">` with returned `captcha_path`
3. Collect user input: `username`, `password`, `captcha`
4. `POST /auth/fju/login`
5. Store `token` in secure storage (prefer httpOnly cookie via backend)
6. `GET /auth/fju/courses` with bearer token
7. `POST /auth/fju/logout` on logout

---

## cURL Examples

### Prelogin

```bash
curl -X POST "http://127.0.0.1:8000/auth/fju/prelogin"
```

### Fetch CAPTCHA

```bash
curl "http://127.0.0.1:8000/auth/fju/captcha/<LOGIN_STATE_ID>" --output captcha.png
```

### Login

```bash
curl -X POST "http://127.0.0.1:8000/auth/fju/login" \
  -H "Content-Type: application/json" \
  -d '{
    "login_state_id": "<LOGIN_STATE_ID>",
    "username": "<ACCOUNT>",
    "password": "<PASSWORD>",
    "captcha": "<CAPTCHA>"
  }'
```

### Courses

```bash
curl "http://127.0.0.1:8000/auth/fju/courses" \
  -H "Authorization: Bearer <TOKEN>"
```

### Logout

```bash
curl -X POST "http://127.0.0.1:8000/auth/fju/logout" \
  -H "Authorization: Bearer <TOKEN>"
```
