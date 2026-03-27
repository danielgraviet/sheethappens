# OhSheet — Dev Notes

## Running locally

```bash
# Install deps (first time or after pyproject.toml changes)
uv sync

# Start the API server
uv run python main.py
# → http://localhost:8000
```

## Testing with ngrok

The Google OAuth callback and the Apps Script/bookmarklet all need a public
HTTPS URL. Use ngrok to expose the local server:

```bash
# In a second terminal (while main.py is running)
ngrok http 8000
# → Forwarding: https://abc123.ngrok-free.app -> localhost:8000
```

Then update `.env`:
```
APP_BASE_URL=https://abc123.ngrok-free.app
GOOGLE_REDIRECT_URI=https://abc123.ngrok-free.app/auth/google/callback
```

Restart the server after changing `.env`. The ngrok URL changes every time
you restart ngrok (unless you have a paid static domain).

## Environment

Copy `.env.example` to `.env` and fill in the values. Required vars:

| Variable | Description |
|---|---|
| `DATABASE_URL` | Neon Postgres connection string |
| `GOOGLE_OAUTH_CLIENT_ID` | Google Cloud OAuth client ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google Cloud OAuth client secret |
| `GOOGLE_REDIRECT_URI` | Must match what's set in Google Cloud Console |
| `APP_BASE_URL` | Your public URL (ngrok URL when testing locally) |
| `SESSION_SECRET_KEY` | Any long random string |
| `FERNET_KEY` | Run `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `CANVAS_TOKEN` | Legacy single-tenant only |
| `CANVAS_DOMAIN` | Legacy single-tenant only |
| `SPREADSHEET_ID` | Legacy single-tenant only |
| `REDIS_URL` | Legacy single-tenant only |
| `GOOGLE_CREDS_JSON` | Path to service account JSON, legacy only |

## Frontend (React setup app)

```bash
# Dev server with hot reload (proxies API to localhost:8000)
npm run setup:dev

# Production build → app/static/setup-app/
npm run setup:build
```

Commit the built output (`app/static/setup-app/`) — Railway does not run
the frontend build step.

## Package manager

Use `uv` for everything Python-related. Do not use `pip` directly.

```bash
uv add <package>       # add a dependency
uv add --dev <package> # add a dev dependency
uv sync                # install all deps from lockfile
uv run <command>       # run a command in the venv
```
