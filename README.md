# CodeSoCrat

This repository now contains a starter backend and a basic React frontend for the CodeSoCrat application described in the design document, plus a production-ready deployment path with Docker Compose, PostgreSQL, and a reverse proxy.

## What is implemented

- FastAPI application scaffold
- SQLite database schema managed by SQLAlchemy models
- Seeded student and author accounts
- Starter problems loaded on first run
- Login, registration, session restore, and logout with `HttpOnly` cookie auth
- Problem listing endpoint
- Author-only problem upload endpoint with schema validation
- Submission evaluation pipeline with syntax, definition, runtime, timeout, and incorrect-output classification
- Docker sandbox execution with no network access and resource limits
- Hint unlocking and retrieval

## Frontend

- React + Vite frontend
- Student login flow
- Problem browser
- Code editor and submission workspace
- Visible sample cases in the problem view while grading cases remain hidden
- Result and hint display
- Author-only JSON upload panel

## Seed accounts

- Student: `student@codesocrat.dev` / `studentpass`
- Author: `author@codesocrat.dev` / `authorpass`

## Run locally

Create env files first:

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env
```

Start the backend:

```bash
python3 -m uvicorn app.main:app --reload --app-dir backend
```

Then start the frontend:

```bash
cd frontend
npm install
npm run dev
```

The API will start at `http://127.0.0.1:8000` and the React app will start at `http://127.0.0.1:5173`.

## Production deployment

Production deployment files are included for:

- PostgreSQL
- FastAPI backend
- built React frontend
- Caddy reverse proxy with automatic HTTPS

Files added for production:

- [docker-compose.yml](/Users/htwarreh/Documents/CodeSoCrat/docker-compose.yml)
- [Caddyfile](/Users/htwarreh/Documents/CodeSoCrat/Caddyfile)
- [backend/Dockerfile](/Users/htwarreh/Documents/CodeSoCrat/backend/Dockerfile)
- [frontend/Dockerfile](/Users/htwarreh/Documents/CodeSoCrat/frontend/Dockerfile)
- [frontend/nginx.conf](/Users/htwarreh/Documents/CodeSoCrat/frontend/nginx.conf)
- [.env.production.example](/Users/htwarreh/Documents/CodeSoCrat/.env.production.example)

### Production steps

1. Copy the production env file:

```bash
cp .env.production.example .env.production
```

2. Set a real domain and secure secrets in `.env.production`:

- `CODESOCRAT_DOMAIN`
- `POSTGRES_PASSWORD`
- `CODESOCRAT_SECRET_KEY_CURRENT`
- `CODESOCRAT_CORS_ORIGINS`

3. Point your DNS record to the server IP:

- `A` record for `app.example.com` -> your server IP

4. Make sure ports `80` and `443` are open on the server.

5. Start the stack:

```bash
docker compose --env-file .env.production up -d --build
```

6. Caddy will request and renew HTTPS certificates automatically once the domain resolves publicly.

### Production architecture

- `reverse-proxy`
  Caddy terminates HTTPS and routes `/api/*` to FastAPI.
- `frontend`
  Nginx serves the built React app.
- `backend`
  FastAPI runs the application API.
- `db`
  PostgreSQL stores application data.

### Notes

- The backend is PostgreSQL-ready through `CODESOCRAT_DATABASE_URL`.
- The backend mounts `/var/run/docker.sock` so it can launch the sandbox container on the host Docker daemon.
- The backend maps `host.docker.internal` to the host gateway so a locally running Ollama service can still be reached from the container.
- For production, keep `CODESOCRAT_SESSION_COOKIE_SECURE=true`.

## Environment files

The backend now loads variables from a root `.env` file automatically.

Important values:

- `CODESOCRAT_SECRET_KEY_CURRENT`
- `CODESOCRAT_SECRET_KEY_PREVIOUS`
- `CODESOCRAT_SESSION_COOKIE_NAME`
- `CODESOCRAT_CSRF_COOKIE_NAME`
- `CODESOCRAT_CSRF_HEADER_NAME`
- `CODESOCRAT_SESSION_COOKIE_SECURE`
- `CODESOCRAT_SESSION_COOKIE_SAMESITE`
- `CODESOCRAT_SESSION_COOKIE_MAX_AGE_SECONDS`
- `CODESOCRAT_DOCKER_IMAGE`
- `CODESOCRAT_DOCKER_AUTO_PULL`
- `CODESOCRAT_DOCKER_PULL_TIMEOUT_SECONDS`
- `CODESOCRAT_OLLAMA_BASE_URL`
- `CODESOCRAT_OLLAMA_MODEL`
- `CODESOCRAT_OLLAMA_HINT_MAX_TOKENS`
- `CODESOCRAT_OLLAMA_HINT_CODE_PREVIEW_LINES`
- `CODESOCRAT_RATE_LIMIT_*`

For production, see `.env.production.example` as the main template.

The frontend uses `frontend/.env` for:

- `VITE_API_BASE_URL`

## Security Notes

- The API now rejects unexpected request fields and applies stricter length and format validation to user input.
- Rate limiting is enforced on public endpoints with IP-based limits and additional user-based limits for authenticated traffic and login attempts.
- Session signing secrets are environment-driven. Rotate them by setting a new `CODESOCRAT_SECRET_KEY_CURRENT` and moving the prior value into `CODESOCRAT_SECRET_KEY_PREVIOUS`.
- Authentication now uses an `HttpOnly` session cookie. For production HTTPS deployments, set `CODESOCRAT_SESSION_COOKIE_SECURE=true`.
- State-changing cookie-authenticated routes now require a matching CSRF cookie and `X-CSRF-Token` header.

## Database schema

The backend creates these tables on startup:

- `users`
- `problems`
- `test_cases`
- `hints`
- `answer_keys`
- `submissions`
- `user_problem_progress`

## PostgreSQL path

The app no longer has to rely on SQLite. To use PostgreSQL locally or in production, set:

```env
CODESOCRAT_DATABASE_URL=postgresql+psycopg://codesocrat:your-password@db:5432/codesocrat
```

The included Docker Compose stack already uses PostgreSQL by default.

## Docker sandbox

Submissions are executed with `docker run` using:

- `--network none`
- `--read-only`
- `--tmpfs /tmp`
- memory and CPU limits
- `--pids-limit`
- dropped Linux capabilities

Make sure Docker Desktop or the Docker daemon is running before submitting code through the API.
If the sandbox image is missing locally, the backend now attempts to pull `CODESOCRAT_DOCKER_IMAGE` automatically by default.
