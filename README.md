# Back Office

Back Office is Synx's email-processing agent. It watches a Gmail mailbox, matches a configured keyword in the subject or body, downloads attachments from matching messages, and uploads those files to one Google Drive folder. Every step is recorded in the database and shown on an authenticated monitoring dashboard.

Keyword matching is ordinary Python. DeepSeek is optional and never decides whether a message matches.

## Architecture

One FastAPI process owns the HTTP API, the dashboard, and a single background poller.

```
Gmail poller
  -> fetch recent messages
  -> deterministic keyword match
  -> validate attachments
  -> optional DeepSeek summary
  -> upload to the configured Drive folder
  -> database row
  -> JSON log
```

Google access uses the OAuth refresh token already issued for this application. The process refreshes access tokens itself. A database lock (`worker_locks`) plus an in-process lock keep two cycles from uploading the same file. Idempotency uses the Gmail message id, the Gmail attachment id, a unique database constraint, and a private Drive app property. An upload is marked successful only after Drive returns a file id.

`drive.file` can only see files this application created. A folder created in the Drive website is not visible. Create the destination folder from the dashboard, then set `GOOGLE_DRIVE_FOLDER_ID`.

## Project structure

```
app/
  main.py                 application factory and lifespan
  api/                    health, records, manual run, config, OAuth
  core/                   settings, sessions, redaction, JSON logs
  database/               models, sessions, repository, Alembic runner
  integrations/           Gmail, Drive, DeepSeek
  services/               trigger, parsing, validation, upload, pipeline
  workers/gmail_poller.py background loop and run lock
  dashboard/              server-rendered monitor
alembic/                  migration 0001_initial
tests/                    unit, integration, and a fake end-to-end workflow
main.py                   process entrypoint (honors Render PORT)
Dockerfile
render.yaml
```

## Environment

Copy `.env.example` to `.env`. `.env` is gitignored. The process refuses to start when required values are missing or too short, and it does not print those values.

Required in every environment:

| Variable | Purpose |
|---|---|
| `APP_SECRET_KEY` | Signs the dashboard session. At least 32 characters. |
| `DASHBOARD_USERNAME` | Dashboard sign-in name. |
| `DASHBOARD_PASSWORD` | Dashboard sign-in password. Production requires at least 12 characters. |
| `DATABASE_URL` | `sqlite:///./backoffice.db` locally. PostgreSQL on Render. |
| `TRIGGER_KEYWORD` | Comma-separated phrases. Default `back office,backoffice`. |

Required in production, and required before live processing locally:

| Variable | Purpose |
|---|---|
| `GOOGLE_CLIENT_ID` | OAuth client id. |
| `GOOGLE_CLIENT_SECRET` | OAuth client secret. |
| `GOOGLE_REFRESH_TOKEN` | Refresh token minted for this app's redirect URI. |
| `GOOGLE_OAUTH_REDIRECT_URI` | Exact callback registered on the OAuth client. |
| `GOOGLE_DRIVE_FOLDER_ID` | Folder created by this application. |
| `GOOGLE_GMAIL_USER` | Mailbox the refresh token must belong to. |

Optional:

| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY` | Enables AI only when the model is also set. |
| `DEEPSEEK_MODEL` | Exact model id. The app checks it against the model list. |
| `DEEPSEEK_BASE_URL` | Default `https://api.deepseek.com`. |
| `POLL_INTERVAL_SECONDS` | Default 60. Minimum 15. |
| `EMAIL_LOOKBACK_MINUTES` | Default 10. |
| `MAX_ATTACHMENT_BYTES` | Default 25 MB. |
| `ALLOWED_MIME_TYPES` | Comma-separated allowlist. |
| `LOG_TO_FILE` | Defaults to true in development and false in production. |

`PORT` overrides `APP_PORT` when Render sets it. Production binds `0.0.0.0`. Development binds `APP_HOST` (default `127.0.0.1`).

Generate a secret:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Local setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# fill .env
alembic upgrade head
python main.py
```

Open `http://127.0.0.1:8000` and sign in. The dashboard is not public.

On startup the app applies Alembic migrations, checks the database, and starts the poller unless `POLL_ENABLED=false`. Missing Google credentials do not stop the web process in development. Health shows `not_configured`. Production refuses to boot until Google, Postgres, the dashboard password, and the redirect URI are set.

## Google OAuth

Use a Web application OAuth client with both scopes:

- `https://www.googleapis.com/auth/gmail.readonly`
- `https://www.googleapis.com/auth/drive.file`

Register the real callback, for example:

```
http://127.0.0.1:8000/oauth/google/callback
https://<your-service>.onrender.com/oauth/google/callback
```

Do not register or reuse the OAuth Playground callback. Playground tokens belong to Google's client, not this application.

After the client id, secret, and redirect URI are in `.env`, sign in to the dashboard and use **Connect Google**. The callback shows a refresh token once. Put it in `GOOGLE_REFRESH_TOKEN` and restart. It is not written to the database or the logs.

Then use **Create folder**, copy the returned id into `GOOGLE_DRIVE_FOLDER_ID`, and restart. Until that id is set, matching mail is not uploaded.

If a token, client secret, or API key was pasted into a chat, ticket, or the OAuth Playground, revoke it in Google Account security (and in the DeepSeek console) and issue a new one before filling `.env`.

### Seven-day refresh tokens

A refresh token is not permanent access. Google expires refresh tokens after 7 days when the OAuth consent screen is in **Testing** and the user is a test user. `gmail.readonly` is a restricted scope, so an unverified **External** app can only be used by test users and inherits that 7-day limit.

Before production, check the consent screen in Google Cloud:

1. If Synx uses Google Workspace, set the app **User type** to **Internal**. Internal apps are limited to that organization, skip restricted-scope verification, and do not use the 7-day testing expiry.
2. If the app must be External, publish it and complete Google's verification for `gmail.readonly`. Until verification finishes, expect to mint a new refresh token every 7 days.
3. Refresh tokens also die if the user revokes access, the token is unused for 6 months, or the client/user pair exceeds Google's refresh-token limit (the oldest is revoked).

An expired or revoked token surfaces as `invalid_grant`. The cycle stops, the dashboard shows the reason, and nothing is marked uploaded. Mint a new token with this app's redirect URI. Do not point the app at the Playground.

## Trigger and attachments

Matching is case-insensitive and uses the phrase as a whole word sequence. `Back Office - November Invoice` matches. `Please send this to the back office.` matches. `Personal Conversation` does not. `back officer` does not, because the phrase is not a free substring of a longer word.

Messages without the keyword are stored as ignored and never uploaded. Matching messages with no attachments are stored as skipped. Multiple attachments are processed independently. Filenames are reduced to a basename and stripped of control characters. The bytes are not opened, rendered, or executed. Disallowed MIME types and oversize files are skipped.

The same Gmail attachment is not uploaded again after a restart. If Drive already has the file (the database write was lost), the existing file id is recorded and the bytes are not sent again.

## DeepSeek

Set both `DEEPSEEK_API_KEY` and `DEEPSEEK_MODEL`. On startup, and from the integrations health check, the app lists models and reports whether the configured id is present. Do not guess the model name.

The model receives the subject, sender, filenames, MIME types, and a short body excerpt. It does not receive attachment bytes, environment variables, or permission to change configuration. Its JSON is stored as a summary and labels. If the call fails, upload continues. Repeated failures pause AI calls for 10 minutes.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

The automated suite covers keyword matching, parsing, filename safety, token redaction, OAuth `invalid_grant`, DeepSeek JSON parsing, the upload pipeline, duplicate polling, Drive failure, AI failure, the database lock, and dashboard authentication. Google and DeepSeek are faked. A passing suite does not mean a live mailbox was reached.

### Live check, after credentials exist

1. Start the app locally and confirm Gmail and Drive are `operational` on the dashboard.
2. Create the Drive folder from the dashboard and set its id.
3. Send a message to the monitored mailbox with `back office` in the subject and a sample PDF. Do not use a confidential document.
4. Wait for the poll, or press **Run cycle**.
5. Confirm the PDF is in the Drive folder, the attachment row is `uploaded`, and the activity log shows the upload.
6. Restart the app and run another cycle. The same PDF must not appear twice.
7. Also send a message without the keyword, one with the keyword and no attachment, and one with two attachments.
8. Confirm a wrong MIME type is skipped, and that stopping DeepSeek does not stop the upload.

## Render

`render.yaml` describes one web service and one Postgres database. The container runs `python main.py`, which binds `PORT` and applies migrations on startup.

1. Push the repository to a private Git remote.
2. Create the Render service from `render.yaml`, or create a Docker web service plus Postgres yourself.
3. Set the secret environment variables in Render. Do not commit them. Use the **internal** database URL.
4. Set `APP_ENV=production`, `LOG_TO_FILE=false`, and `GOOGLE_OAUTH_REDIRECT_URI` to `https://<service>.onrender.com/oauth/google/callback`. Register that URI on the Google client.
5. Deploy. `GET /health` must return 200. It checks the process and the database, not Google, so a Google outage does not restart the service.
6. Sign in, connect Google, create the Drive folder, set `GOOGLE_DRIVE_FOLDER_ID`, and redeploy or restart.
7. Confirm `/health/integrations` (after sign-in) shows Gmail and Drive as operational.
8. Send the sample message from the live check above and read the stdout logs in Render.

Keep one web instance unless you accept lock contention. The database lock stops a second instance from uploading the same attachment, but it should not be treated as a reason to run several pollers.

Render's disk is ephemeral. Production logs go to stdout. Leave `LOG_TO_FILE=false` unless you attach persistent storage.

The Render Postgres URL may start with `postgres://`. The app rewrites it to `postgresql+psycopg://`.

## Security

- Credentials stay in the environment. API responses and logs are redacted.
- The dashboard, `/api/*`, and `/health/integrations` require the session cookie. `GET /health` is the only public probe.
- There is no form for editing secrets.
- Filenames cannot choose a path. Attachment bytes are kept in memory and discarded after the upload attempt.
- Email text is untrusted. It cannot change settings, send mail, delete mail, or choose a Drive folder.
- AI output is stored text. It is not executed.
- Unexpected errors return `Internal server error` without a stack trace.
- Login and manual runs are rate-limited per process.

## Known limitations

- Live Gmail, Drive, and DeepSeek were not called in this workspace. No credentials were present, and none should be pasted into chat.
- `drive.file` cannot adopt an existing personal-drive folder.
- Testing-mode refresh tokens expire in about 7 days. Confirm Internal vs External before production.
- The rate limiter and the run lock live in process memory. The database lock is what covers a second process.
- DeepSeek never sees file contents. Classification is based on the filename, type, and a truncated excerpt.
- Only the first 512 KB of message text is used for matching.
- The dashboard is one shared password, not SSO.

## Operations

Manual cycle: `POST /api/agent/run` with `{"reprocess_failed": false}`.

Retry skipped or failed attachments once: `{"reprocess_failed": true}`. Successful uploads are not sent again.

Useful routes:

| Method | Path | Auth |
|---|---|---|
| GET | `/health` | Public liveness |
| GET | `/health/integrations` | Session |
| GET | `/api/emails` | Session |
| GET | `/api/attachments` | Session |
| GET | `/api/logs?status=all\|success\|failed\|pending` | Session |
| GET | `/api/stats` | Session |
| GET | `/api/config/status` | Session |
| POST | `/api/agent/run` | Session |
| POST | `/api/drive/folder` | Session |
| GET | `/oauth/google/start` | Session |

# drivedumpagent
