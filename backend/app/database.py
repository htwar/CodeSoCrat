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
    # FastAPI dependency that opens one SQLAlchemy session per request and
    # guarantees cleanup afterward.
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Apply lightweight schema evolution for local SQLite databases created by
# earlier project versions so new fields can be used without manual migrations.
def ensure_schema_evolution() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "submissions" not in table_names:
        return

    statements = []
    if "submissions" in table_names:
        submission_columns = {column["name"] for column in inspector.get_columns("submissions")}
        if "execution_type" not in submission_columns:
            statements.append("ALTER TABLE submissions ADD COLUMN execution_type TEXT DEFAULT 'Submit'")
        if "error_line" not in submission_columns:
            statements.append("ALTER TABLE submissions ADD COLUMN error_line INTEGER")
        if "error_excerpt" not in submission_columns:
            statements.append("ALTER TABLE submissions ADD COLUMN error_excerpt TEXT")

    if "users" in table_names:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "auth_provider" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN auth_provider TEXT DEFAULT 'local'")
        if "google_sub" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN google_sub TEXT")
        if "display_name" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN display_name TEXT")

    if "problems" in table_names:
        problem_columns = {column["name"] for column in inspector.get_columns("problems")}
        if "is_active" not in problem_columns:
            statements.append("ALTER TABLE problems ADD COLUMN is_active BOOLEAN DEFAULT 1")
        if "is_deleted" not in problem_columns:
            statements.append("ALTER TABLE problems ADD COLUMN is_deleted BOOLEAN DEFAULT 0")
        if "updated_at" not in problem_columns:
            statements.append("ALTER TABLE problems ADD COLUMN updated_at DATETIME")

    if "user_problem_progress" in table_names:
        progress_columns = {column["name"] for column in inspector.get_columns("user_problem_progress")}
        if "timed_mode_enabled" not in progress_columns:
            statements.append("ALTER TABLE user_problem_progress ADD COLUMN timed_mode_enabled BOOLEAN DEFAULT 0")
        if "timed_mode_started_at" not in progress_columns:
            statements.append("ALTER TABLE user_problem_progress ADD COLUMN timed_mode_started_at DATETIME")
        if "timed_mode_expires_at" not in progress_columns:
            statements.append("ALTER TABLE user_problem_progress ADD COLUMN timed_mode_expires_at DATETIME")
        if "timed_mode_paused_at" not in progress_columns:
            statements.append("ALTER TABLE user_problem_progress ADD COLUMN timed_mode_paused_at DATETIME")

    if "generated_hints" in table_names:
        generated_hint_columns = {column["name"] for column in inspector.get_columns("generated_hints")}
        if "revealed" not in generated_hint_columns:
            statements.append("ALTER TABLE generated_hints ADD COLUMN revealed BOOLEAN DEFAULT 0")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

        if "problems" in table_names:
            connection.execute(text("UPDATE problems SET is_active = COALESCE(is_active, 1), is_deleted = COALESCE(is_deleted, 0)"))
            connection.execute(text("UPDATE problems SET updated_at = COALESCE(updated_at, created_at)"))
        if "users" in table_names:
            connection.execute(text("UPDATE users SET auth_provider = COALESCE(auth_provider, 'local')"))
        if "user_problem_progress" in table_names:
            connection.execute(text("UPDATE user_problem_progress SET timed_mode_enabled = COALESCE(timed_mode_enabled, 0)"))
        if "generated_hints" in table_names:
            connection.execute(text("UPDATE generated_hints SET revealed = COALESCE(revealed, 0)"))
