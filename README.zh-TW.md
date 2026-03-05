# 輔仁 TronClass 登入橋接服務

本專案提供一個可落地的「輔仁 TronClass（CAS + CAPTCHA）」登入橋接 API，供你自己的網站使用。

## 語言版本

- English: `README.md`

## 專案目標

- 支援輔仁 TronClass 的 CAS 登入流程
- 不繞過 CAPTCHA，採「使用者手動輸入驗證碼」模式
- 將 CAS Cookie 留在後端，前端只拿短效 Bearer Token
- 提供修課列表 API（代理 `api/my-courses`）

## API 一覽

- `POST /auth/fju/prelogin`：建立登入狀態，解析 `lt/execution/_eventId`
- `GET /auth/fju/captcha/{login_state_id}`：取得驗證碼圖片
- `POST /auth/fju/login`：送出帳號/密碼/captcha 並登入
- `GET /auth/fju/courses`：帶 Bearer Token 取得修課列表
- `POST /auth/fju/logout`：登出（清除本地 session 並呼叫 CAS logout）
- `GET /health`：健康檢查

完整接口文件請看：`docs/login-api.md`

## 快速啟動

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8100
```

## 重要環境變數

- `TRONCLASS_BASE_URL`（預設 `https://elearn2.fju.edu.tw/`）
- `CAS_LOGIN_PATH`（預設 `/cas/login`）
- `CAS_LOGOUT_PATH`（預設 `/cas/logout`）
- `SERVICE_CALLBACK_PATH`（預設 `/login?next=/user/index`）
- `CORS_ALLOWED_ORIGINS`（預設 `https://whl.tw`）
- `TRONCLASS_SSL_VERIFY`（預設 `true`）
  - `true`：正常驗證 TLS 憑證
  - `false`：關閉 TLS 驗證（僅測試用）
  - `/path/to/ca-bundle.pem`：指定 CA 憑證檔

## 測試：輸入帳密與 CAPTCHA，取得修課列表

```bash
python3 scripts/test_login_and_courses.py --base-url http://127.0.0.1:8100
```

腳本會自動：

1. 呼叫 `prelogin`
2. 下載 CAPTCHA 到 `./captcha.png`
3. 請你輸入 `Username`、`Password`、`CAPTCHA`
4. 自動登入並印出修課列表 JSON

## Vue 串接建議流程

1. 呼叫 `POST /auth/fju/prelogin`
2. 用回傳的 `captcha_path` 顯示驗證碼圖片
3. 使用者輸入帳密與驗證碼
4. 呼叫 `POST /auth/fju/login` 取得 token
5. 呼叫 `GET /auth/fju/courses` 取得課程資料
6. 登出時呼叫 `POST /auth/fju/logout`

## 注意事項

- `login_state_id` 為一次性，登入失敗請重新 `prelogin`
- 目前 session store 是記憶體版，正式環境建議換 Redis
- 正式環境請啟用 rate limit、audit log、IP allowlist
