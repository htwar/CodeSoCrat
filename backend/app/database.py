from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema_evolution() -> None:
    inspector = inspect(engine)
    if "submissions" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("submissions")}
    statements = []
    if "error_line" not in existing_columns:
        statements.append("ALTER TABLE submissions ADD COLUMN error_line INTEGER")
    if "error_excerpt" not in existing_columns:
        statements.append("ALTER TABLE submissions ADD COLUMN error_excerpt TEXT")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
