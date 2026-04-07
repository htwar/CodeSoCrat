# CodeSoCrat

CodeSoCrat is a web application for Python coding practice. Students can work through problems, run or submit solutions, receive adaptive hints, and unlock answer keys after repeated valid failed submissions. The app is built with a React frontend, a FastAPI backend, a SQL database, Docker-based code execution, and Ollama-powered hint generation.

## Features

- Student registration and login with secure cookie-based sessions
- Difficulty-based problem browsing
- Monaco editor for student code and author JSON uploads
- Separate `Run` and `Submit` actions
- Adaptive conceptual, strategic, and syntactic hints
- Hidden grading test cases with visible sample cases
- Answer key unlocking after repeated valid failed submissions
- Optional timed mode with difficulty-based countdowns and auto-submit on expiry
- Author-only problem uploads with schema validation
- Docker sandbox execution for Python code
- Production deployment path with PostgreSQL, Caddy, and Docker Compose

## Tech Stack

- Frontend: React + Vite + Monaco
- Backend: FastAPI + SQLAlchemy
- Database: SQLite for local development, PostgreSQL-ready for production
- Sandbox: Docker
- Hint generation: Ollama
- Reverse proxy / HTTPS: Caddy

## Local Development

1. Create local env files from the templates:

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env
```

If you want Google login, put your Google OAuth client id in `.env`:

```env
CODESOCRAT_GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
```

This is the only project file change needed for local Google configuration. The backend already reads `.env` automatically and the frontend asks the backend whether Google auth is enabled.

2. Start the backend:

```bash
python3 -m uvicorn app.main:app --reload --app-dir backend
```

3. Start the frontend:

```bash
cd frontend
npm install
npm run dev
```

4. Open the app at `http://127.0.0.1:5173`.

## Author JSON Uploads

Authors can add problems in two ways from the dashboard:

- Load a JSON file into the Monaco editor, review or edit it, then upload
- Upload a `.json` problem file directly

Each file must contain exactly one problem payload matching the CodeSoCrat problem schema. The backend parses the uploaded JSON and uses the file's `difficulty`, `function_name`, test cases, hints, and answer key fields to create the problem.

## Production Deployment

The repository includes a production path with:

- [docker-compose.yml](/Users/htwarreh/Documents/CodeSoCrat/docker-compose.yml)
- [Caddyfile](/Users/htwarreh/Documents/CodeSoCrat/Caddyfile)
- [backend/Dockerfile](/Users/htwarreh/Documents/CodeSoCrat/backend/Dockerfile)
- [frontend/Dockerfile](/Users/htwarreh/Documents/CodeSoCrat/frontend/Dockerfile)
- [frontend/nginx.conf](/Users/htwarreh/Documents/CodeSoCrat/frontend/nginx.conf)
- [.env.production.example](/Users/htwarreh/Documents/CodeSoCrat/.env.production.example)

Basic deployment flow:

1. Copy the production template:

```bash
cp .env.production.example .env.production
```

2. Update the production env values for your domain, database, and secrets.
3. Point your DNS record at the server.
4. Open ports `80` and `443`.
5. Start the stack:

```bash
docker compose --env-file .env.production up -d --build
```

Caddy will handle HTTPS automatically once the domain resolves correctly.

## Security

- Strict schema validation rejects unexpected fields
- Rate limiting on public endpoints
- `HttpOnly` cookie sessions
- CSRF protection on state-changing routes
- Docker sandbox with network disabled and resource limits
- Environment-based secret management
