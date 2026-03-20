from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    submissions: Mapped[list["Submission"]] = relationship(back_populates="user")
    created_problems: Mapped[list["Problem"]] = relationship(back_populates="author")
    progress_records: Mapped[list["UserProblemProgress"]] = relationship(back_populates="user")


class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    problem_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    prompt: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(32))
    function_name: Mapped[str] = mapped_column(String(100))
    starter_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="starter")
    author_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    author: Mapped[Optional[User]] = relationship(back_populates="created_problems")
    test_cases: Mapped[list["TestCase"]] = relationship(back_populates="problem", cascade="all, delete-orphan")
    hints: Mapped[list["Hint"]] = relationship(back_populates="problem", cascade="all, delete-orphan")
    answer_key: Mapped[Optional["AnswerKey"]] = relationship(back_populates="problem", cascade="all, delete-orphan", uselist=False)
    submissions: Mapped[list["Submission"]] = relationship(back_populates="problem")
    progress_records: Mapped[list["UserProblemProgress"]] = relationship(back_populates="problem")


class TestCase(Base):
    __tablename__ = "test_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), index=True)
    input_json: Mapped[str] = mapped_column(Text)
    expected_json: Mapped[str] = mapped_column(Text)

    problem: Mapped[Problem] = relationship(back_populates="test_cases")


class Hint(Base):
    __tablename__ = "hints"
    __table_args__ = (UniqueConstraint("problem_id", "stage", name="uq_hint_problem_stage"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), index=True)
    stage: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)

    problem: Mapped[Problem] = relationship(back_populates="hints")


class AnswerKey(Base):
    __tablename__ = "answer_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), unique=True, index=True)
    solution_code: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)

    problem: Mapped[Problem] = relationship(back_populates="answer_key")


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), index=True)
    execution_type: Mapped[str] = mapped_column(String(16), default="Submit")
    code: Mapped[str] = mapped_column(Text)
    timed_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[str] = mapped_column(String(16))
    failure_category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    runtime_ms: Mapped[int] = mapped_column(Integer, default=0)
    memory_mb: Mapped[int] = mapped_column(Integer, default=0)
    feedback: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="submissions")
    problem: Mapped[Problem] = relationship(back_populates="submissions")


class UserProblemProgress(Base):
    __tablename__ = "user_problem_progress"
    __table_args__ = (UniqueConstraint("user_id", "problem_id", name="uq_user_problem_progress"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), index=True)
    unlocked_stage: Mapped[int] = mapped_column(Integer, default=0)
    valid_failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    answer_key_unlocked: Mapped[bool] = mapped_column(Boolean, default=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_failure_category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="progress_records")
    problem: Mapped[Problem] = relationship(back_populates="progress_records")


class GeneratedHint(Base):
    __tablename__ = "generated_hints"
    __table_args__ = (UniqueConstraint("user_id", "problem_id", "submission_id", "stage", name="uq_generated_hint_cache"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    stage: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
