# CodeSoCrat

This repository now contains a starter backend and a basic React frontend for the CodeSoCrat application described in the design document.

## What is implemented

- FastAPI application scaffold
- SQLite database schema managed by SQLAlchemy models
- Seeded student and author accounts
- Starter problems loaded on first run
- Login endpoint with bearer-token auth
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

## Environment files

The backend now loads variables from a root `.env` file automatically.

Important values:

- `CODESOCRAT_SECRET_KEY_CURRENT`
- `CODESOCRAT_SECRET_KEY_PREVIOUS`
- `CODESOCRAT_DOCKER_IMAGE`
- `CODESOCRAT_DOCKER_AUTO_PULL`
- `CODESOCRAT_DOCKER_PULL_TIMEOUT_SECONDS`
- `CODESOCRAT_OLLAMA_BASE_URL`
- `CODESOCRAT_OLLAMA_MODEL`
- `CODESOCRAT_RATE_LIMIT_*`

The frontend uses `frontend/.env` for:

- `VITE_API_BASE_URL`

## Security Notes

- The API now rejects unexpected request fields and applies stricter length and format validation to user input.
- Rate limiting is enforced on public endpoints with IP-based limits and additional user-based limits for authenticated traffic and login attempts.
- Session signing secrets are environment-driven. Rotate them by setting a new `CODESOCRAT_SECRET_KEY_CURRENT` and moving the prior value into `CODESOCRAT_SECRET_KEY_PREVIOUS`.

## Database schema

The backend creates these tables on startup:

- `users`
- `problems`
- `test_cases`
- `hints`
- `answer_keys`
- `submissions`
- `user_problem_progress`

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
