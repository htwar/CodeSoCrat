# CodeSoCrat Backend

This repository now contains a starter backend for the CodeSoCrat application described in the design document.

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

## Seed accounts

- Student: `student@codesocrat.dev` / `studentpass`
- Author: `author@codesocrat.dev` / `authorpass`

## Run locally

```bash
python3 -m uvicorn app.main:app --reload --app-dir backend
```

The API will start at `http://127.0.0.1:8000`.

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
