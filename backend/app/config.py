import os
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "CodeSoCrat API"
    database_url: str = os.getenv("CODESOCRAT_DATABASE_URL", "sqlite:///./codesocrat.db")
    secret_key: str = os.getenv("CODESOCRAT_SECRET_KEY", "dev-secret-change-me")
    cors_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CODESOCRAT_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",")
        if origin.strip()
    ]
    starter_problems_path: Path = Path(__file__).resolve().parents[2] / "data" / "starter_problems.json"
    evaluation_timeout_seconds: int = 2
    evaluation_memory_bytes: int = 128 * 1024 * 1024
    docker_image: str = os.getenv("CODESOCRAT_DOCKER_IMAGE", "python:3.11-alpine")
    docker_cpus: str = os.getenv("CODESOCRAT_DOCKER_CPUS", "0.5")
    docker_pids_limit: int = int(os.getenv("CODESOCRAT_DOCKER_PIDS_LIMIT", "64"))


settings = Settings()
