import os
import secrets
from pathlib import Path

from pydantic import BaseModel


def load_env_file() -> None:
    project_root = Path(__file__).resolve().parents[2]
    env_path = project_root / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


load_env_file()


class Settings(BaseModel):
    app_name: str = "CodeSoCrat API"
    database_url: str = os.getenv("CODESOCRAT_DATABASE_URL", "sqlite:///./codesocrat.db")
    secret_key_current: str = os.getenv("CODESOCRAT_SECRET_KEY_CURRENT", os.getenv("CODESOCRAT_SECRET_KEY", "")) or secrets.token_urlsafe(48)
    secret_key_previous: list[str] = [
        key.strip()
        for key in os.getenv("CODESOCRAT_SECRET_KEY_PREVIOUS", "").split(",")
        if key.strip()
    ]
    cors_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CODESOCRAT_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",")
        if origin.strip()
    ]
    starter_problems_path: Path = Path(__file__).resolve().parents[2] / "data" / "starter_problems.json"
    evaluation_timeout_seconds: int = 2
    evaluation_memory_bytes: int = 128 * 1024 * 1024
    docker_startup_timeout_seconds: int = int(os.getenv("CODESOCRAT_DOCKER_STARTUP_TIMEOUT_SECONDS", "10"))
    docker_image: str = os.getenv("CODESOCRAT_DOCKER_IMAGE", "python:3.11-alpine")
    docker_cpus: str = os.getenv("CODESOCRAT_DOCKER_CPUS", "0.5")
    docker_pids_limit: int = int(os.getenv("CODESOCRAT_DOCKER_PIDS_LIMIT", "64"))
    ollama_base_url: str = os.getenv("CODESOCRAT_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("CODESOCRAT_OLLAMA_MODEL", "qwen2.5-coder:14b")
    ollama_timeout_seconds: int = int(os.getenv("CODESOCRAT_OLLAMA_TIMEOUT_SECONDS", "30"))
    rate_limit_window_seconds: int = int(os.getenv("CODESOCRAT_RATE_LIMIT_WINDOW_SECONDS", "60"))
    rate_limit_ip_public: int = int(os.getenv("CODESOCRAT_RATE_LIMIT_IP_PUBLIC", "60"))
    rate_limit_ip_authenticated: int = int(os.getenv("CODESOCRAT_RATE_LIMIT_IP_AUTHENTICATED", "120"))
    rate_limit_user_authenticated: int = int(os.getenv("CODESOCRAT_RATE_LIMIT_USER_AUTHENTICATED", "90"))
    login_rate_limit_ip: int = int(os.getenv("CODESOCRAT_LOGIN_RATE_LIMIT_IP", "10"))
    login_rate_limit_user: int = int(os.getenv("CODESOCRAT_LOGIN_RATE_LIMIT_USER", "5"))


settings = Settings()
