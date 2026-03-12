from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import settings
from app.models import AnswerKey, Hint, Problem, TestCase, User
from app.schemas import ProblemUploadPayload


def seed_default_users(db: Session) -> None:
    defaults = [
        ("student@codesocrat.dev", "studentpass", "Student"),
        ("author@codesocrat.dev", "authorpass", "Author"),
    ]
    for email, password, role in defaults:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            continue
        db.add(User(email=email, password_hash=hash_password(password), role=role))
    db.commit()


def seed_starter_problems(db: Session) -> None:
    if db.query(Problem).filter(Problem.source == "starter").first():
        return

    starter_items = json.loads(settings.starter_problems_path.read_text())
    for item in starter_items:
        payload = ProblemUploadPayload.model_validate(item)
        persist_problem(db=db, payload=payload, source="starter", author_id=None)
    db.commit()


def persist_problem(db: Session, payload: ProblemUploadPayload, source: str, author_id: Optional[int]) -> Problem:
    problem = Problem(
        problem_id=payload.problem_id,
        title=payload.title,
        prompt=payload.prompt,
        difficulty=payload.difficulty,
        function_name=payload.function_name,
        starter_code=payload.starter_code,
        source=source,
        author_id=author_id,
    )
    db.add(problem)
    db.flush()

    for test_case in payload.test_cases:
        db.add(
            TestCase(
                problem_id=problem.id,
                input_json=json.dumps(test_case.input),
                expected_json=json.dumps(test_case.expected),
            )
        )

    if payload.hints:
        for stage_str, content in payload.hints.items():
            db.add(Hint(problem_id=problem.id, stage=int(stage_str), content=content))

    if payload.answer_key:
        db.add(
            AnswerKey(
                problem_id=problem.id,
                solution_code=payload.answer_key.solution_code,
                explanation=payload.answer_key.explanation,
            )
        )

    return problem
