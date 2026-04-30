# CodeSoCrat

CodeSoCrat is a web app for practicing Python function problems with guided feedback. Students can run code without affecting progress, submit official attempts, unlock hints as they struggle, and eventually reveal the answer key. Authors can upload new problems through a JSON-based workflow.

The project uses:

- React + Vite on the frontend
- FastAPI + SQLAlchemy on the backend
- Docker to run student code in an isolated Python sandbox
- a configurable local LLM provider layer for hint generation
- SQLite for local development and PostgreSQL for deployment

## What it does

- student registration and login
- secure cookie-based sessions with CSRF protection
- optional Google sign-in
- easy / medium / hard problem selection
- Monaco editor for student code and author JSON editing
- separate `Run` and `Submit` actions
- timed mode with countdown and auto-submit on expiry
- conceptual, strategic, and syntactic hints
- answer key unlock after repeated valid failed submits
- author-only problem upload, edit, disable, enable, and delete flows

## Project structure

```text
backend/   FastAPI app, database models, evaluation, hints, tests
frontend/  React app built with Vite
data/      starter problem set
```

## Local setup

### 1. Install backend dependencies

From the repo root:

```bash
python3 -m pip install -r requirements.txt
```

### 2. Create a local backend env file

Create a `.env` file in the project root. A minimal local setup looks like this:

```env
CODESOCRAT_DATABASE_URL=sqlite:///./codesocrat.db
CODESOCRAT_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
CODESOCRAT_SESSION_COOKIE_SECURE=false
CODESOCRAT_HINT_PROVIDER=ollama
CODESOCRAT_OLLAMA_BASE_URL=http://127.0.0.1:11434
CODESOCRAT_HINT_MODEL=qwen2.5-coder:14b
```

If you want Google sign-in, also add:

```env
CODESOCRAT_GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
```

### 3. Create a local frontend env file

Create `frontend/.env` with:

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_CSRF_COOKIE_NAME=codesocrat_csrf
VITE_CSRF_HEADER_NAME=X-CSRF-Token
```

If you use cookie auth locally, keep the frontend and backend on the same hostname. For example:

- frontend: `http://localhost:5173`
- backend: `http://localhost:8000`

Do not mix `localhost` and `127.0.0.1` in the same session.

### 4. Start the backend

```bash
python3 -m uvicorn app.main:app --reload --app-dir backend
```

### 5. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open the app at [http://localhost:5173](http://localhost:5173).

## Docker sandbox note

Student code runs in a Docker container using the image `python:3.11-alpine`.

If that image is missing locally, the backend is configured to pull it automatically when needed. Docker still needs to be installed and running.

## Running tests

Backend:

```bash
python3 -m unittest backend.tests.test_api backend.tests.test_unit_services backend.tests.test_system_workflows
```

Frontend build check:

```bash
cd frontend
npm run build
```

## Hint provider setup

Hint generation is provider-based now. Ollama is the default built-in provider, and the backend is structured so another LLM can be added by implementing the shared hint-service interface and registering it in the provider factory.

For Ollama:

```env
CODESOCRAT_HINT_PROVIDER=ollama
CODESOCRAT_OLLAMA_BASE_URL=http://127.0.0.1:11434
CODESOCRAT_HINT_MODEL=qwen2.5-coder:14b
```

## Author problem format

Authors upload one JSON problem at a time. A problem can include:

- `problem_id`
- `title`
- `prompt`
- `difficulty`
- `function_name`
- `starter_code`
- `example_cases`
- `test_cases`
- `hints`
- `answer_key`

Example cases are visible to students. Test cases are kept hidden for grading.

## Production deployment

The repo includes a production deployment path with:

- [docker-compose.yml](docker-compose.yml)
- [Caddyfile](Caddyfile)
- [backend/Dockerfile](backend/Dockerfile)
- [frontend/Dockerfile](frontend/Dockerfile)
- [frontend/nginx.conf](frontend/nginx.conf)

The production stack uses:

- PostgreSQL
- FastAPI backend
- Nginx-served frontend
- Caddy as the reverse proxy with HTTPS

Typical deployment command:

```bash
docker compose --env-file .env.production up -d --build
```

Your `.env.production` should define values such as:

```env
CODESOCRAT_DOMAIN=your-domain.example
POSTGRES_DB=codesocrat
POSTGRES_USER=codesocrat
POSTGRES_PASSWORD=change-me
CODESOCRAT_DATABASE_URL=postgresql+psycopg://codesocrat:change-me@db:5432/codesocrat
CODESOCRAT_SECRET_KEY_CURRENT=replace-this-with-a-long-random-secret
CODESOCRAT_CORS_ORIGINS=https://your-domain.example
```

## Security notes

The app currently includes:

- schema-based request validation
- rate limiting
- `HttpOnly` session cookies
- CSRF protection on state-changing routes
- role-based author access
- Docker-based sandbox execution
- environment-based secret configuration

## Demo accounts

Local demo users are optional. By default the backend seeds one student account and one author account for development, but you can change or disable them with environment variables:

```env
CODESOCRAT_SEED_DEMO_USERS=true
CODESOCRAT_DEMO_STUDENT_EMAIL=student@codesocrat.dev
CODESOCRAT_DEMO_STUDENT_PASSWORD=studentpass
CODESOCRAT_DEMO_AUTHOR_EMAIL=author@codesocrat.dev
CODESOCRAT_DEMO_AUTHOR_PASSWORD=authorpass
```

If you do not want seeded demo users, set:

```env
CODESOCRAT_SEED_DEMO_USERS=false
```
