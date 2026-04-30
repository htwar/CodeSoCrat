from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import settings
from app.models import AnswerKey, ExampleCase, Hint, Problem, TestCase, User
from app.schemas import ProblemUploadPayload


def seed_default_users(db: Session) -> None:
    # Keep predictable demo accounts available for local development and demos.
    if not settings.seed_demo_users:
        return

    defaults = [
        (settings.demo_student_email, settings.demo_student_password, "Student", "Student Demo"),
        (settings.demo_author_email, settings.demo_author_password, "Author", "Author Demo"),
    ]
    for email, password, role, display_name in defaults:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            if not existing.display_name:
                existing.display_name = display_name
            continue
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                role=role,
                auth_provider="local",
                display_name=display_name,
            )
        )
    db.commit()


def seed_starter_problems(db: Session) -> None:
    # Re-apply the starter catalog on boot so bundled content stays in sync with
    # the JSON source file without duplicating rows.
    starter_items = json.loads(settings.starter_problems_path.read_text())
    for item in starter_items:
        payload = ProblemUploadPayload.model_validate(item)
        existing_problem = db.query(Problem).filter(Problem.problem_id == payload.problem_id, Problem.source == "starter").first()
        if existing_problem is None:
            persist_problem(db=db, payload=payload, source="starter", author_id=None)
            continue

        existing_problem.title = payload.title
        existing_problem.prompt = payload.prompt
        existing_problem.difficulty = payload.difficulty
        existing_problem.function_name = payload.function_name
        existing_problem.starter_code = payload.starter_code
        existing_problem.is_active = True
        existing_problem.is_deleted = False

        db.query(ExampleCase).filter(ExampleCase.problem_id == existing_problem.id).delete()
        db.query(TestCase).filter(TestCase.problem_id == existing_problem.id).delete()
        db.query(Hint).filter(Hint.problem_id == existing_problem.id).delete()
        db.query(AnswerKey).filter(AnswerKey.problem_id == existing_problem.id).delete()

        for example_case in payload.example_cases:
            db.add(
                ExampleCase(
                    problem_id=existing_problem.id,
                    input_json=json.dumps(example_case.input),
                    expected_json=json.dumps(example_case.expected),
                )
            )

        for test_case in payload.test_cases:
            db.add(
                TestCase(
                    problem_id=existing_problem.id,
                    input_json=json.dumps(test_case.input),
                    expected_json=json.dumps(test_case.expected),
                )
            )

        if payload.hints:
            for stage_str, content in payload.hints.items():
                db.add(Hint(problem_id=existing_problem.id, stage=int(stage_str), content=content))

        if payload.answer_key:
            db.add(
                AnswerKey(
                    problem_id=existing_problem.id,
                    solution_code=payload.answer_key.solution_code,
                    explanation=payload.answer_key.explanation,
                )
            )
    db.commit()


def persist_problem(db: Session, payload: ProblemUploadPayload, source: str, author_id: Optional[int]) -> Problem:
    # Shared helper for starter seeding and author-created problems.
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

    for example_case in payload.example_cases:
        db.add(
            ExampleCase(
                problem_id=problem.id,
                input_json=json.dumps(example_case.input),
                expected_json=json.dumps(example_case.expected),
            )
        )

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


def replace_problem_contents(db: Session, problem: Problem, payload: ProblemUploadPayload) -> Problem:
    # Replace related rows instead of mutating them in place so the stored test
    # data always mirrors the uploaded JSON payload exactly.
    problem.title = payload.title
    problem.prompt = payload.prompt
    problem.difficulty = payload.difficulty
    problem.function_name = payload.function_name
    problem.starter_code = payload.starter_code

    db.query(ExampleCase).filter(ExampleCase.problem_id == problem.id).delete()
    db.query(TestCase).filter(TestCase.problem_id == problem.id).delete()
    db.query(Hint).filter(Hint.problem_id == problem.id).delete()
    db.query(AnswerKey).filter(AnswerKey.problem_id == problem.id).delete()

    for example_case in payload.example_cases:
        db.add(
            ExampleCase(
                problem_id=problem.id,
                input_json=json.dumps(example_case.input),
                expected_json=json.dumps(example_case.expected),
            )
        )

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
