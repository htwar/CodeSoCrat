from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, selectinload

from app.auth import create_token, get_current_user, require_author, verify_password
from app.config import settings
from app.database import Base, SessionLocal, engine, get_db
from app.models import Hint, Problem, Submission, TestCase, User
from app.schemas import (
    HintResponse,
    LoginRequest,
    LoginResponse,
    ProblemListResponse,
    ProblemSummary,
    ProblemUploadPayload,
    ProblemUploadResponse,
    SubmissionRequest,
    SubmissionResponse,
)
from app.services.bootstrap import persist_problem, seed_default_users, seed_starter_problems
from app.services.evaluation import EvaluationService
from app.services.hints import build_hint_response, generate_fallback_hint
from app.services.progress import ProgressService

evaluation_service = EvaluationService()
progress_service = ProgressService()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_default_users(db)
        seed_starter_problems(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    return LoginResponse(token=create_token(user), user_id=str(user.id), role=user.role)


@app.get("/problems", response_model=ProblemListResponse)
def list_problems(
    difficulty: Optional[str] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProblemListResponse:
    query = db.query(Problem).order_by(Problem.difficulty, Problem.title)
    if difficulty:
        query = query.filter(Problem.difficulty == difficulty)
    problems = query.all()
    return ProblemListResponse(problems=[ProblemSummary.model_validate(problem) for problem in problems])


@app.post("/submissions", response_model=SubmissionResponse)
def submit_code(
    payload: SubmissionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubmissionResponse:
    problem = (
        db.query(Problem)
        .options(selectinload(Problem.test_cases), selectinload(Problem.answer_key), selectinload(Problem.hints))
        .filter(Problem.problem_id == payload.problem_id)
        .first()
    )
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found.")

    test_cases = [(json.loads(case.input_json), json.loads(case.expected_json)) for case in problem.test_cases]
    evaluation = evaluation_service.evaluate(
        code=payload.code,
        function_name=problem.function_name,
        test_cases=test_cases,
    )

    progress = progress_service.get_or_create(db, user=user, problem=problem)
    progress_service.apply_submission_outcome(
        progress=progress,
        result=evaluation.result,
        failure_category=evaluation.failure_category,
        valid_attempt=evaluation.valid_attempt,
    )

    submission = Submission(
        user_id=user.id,
        problem_id=problem.id,
        code=payload.code,
        timed_mode=payload.timed_mode,
        result=evaluation.result,
        failure_category=evaluation.failure_category,
        runtime_ms=evaluation.runtime_ms,
        memory_mb=evaluation.memory_mb,
        feedback=evaluation.feedback,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    db.refresh(progress)

    return SubmissionResponse(
        submission_id=str(submission.id),
        result=evaluation.result,
        failure_category=evaluation.failure_category,
        runtime_ms=evaluation.runtime_ms,
        memory_mb=evaluation.memory_mb,
        valid_failed_attempts=progress.valid_failed_attempts,
        hint_stage_unlocked=progress.unlocked_stage,
        answer_key_unlocked=progress.answer_key_unlocked,
        feedback=evaluation.feedback,
    )


@app.get("/hints", response_model=HintResponse)
def get_hints(
    problem_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HintResponse:
    problem = db.query(Problem).options(selectinload(Problem.hints)).filter(Problem.problem_id == problem_id).first()
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found.")

    progress = progress_service.get_or_create(db, user=user, problem=problem)
    if progress.unlocked_stage == 0:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No hints unlocked yet.")

    existing_stages = {hint.stage for hint in problem.hints}
    for stage in range(1, progress.unlocked_stage + 1):
        if stage not in existing_stages:
            db.add(
                Hint(
                    problem_id=problem.id,
                    stage=stage,
                    content=generate_fallback_hint(stage, progress.last_failure_category, problem),
                )
            )
    db.commit()
    problem = db.query(Problem).options(selectinload(Problem.hints)).filter(Problem.id == problem.id).first()

    return HintResponse.model_validate(build_hint_response(problem, progress))


@app.post("/author/problems/upload", response_model=ProblemUploadResponse)
def upload_problem(
    payload: ProblemUploadPayload,
    user: User = Depends(require_author),
    db: Session = Depends(get_db),
) -> ProblemUploadResponse:
    existing = db.query(Problem).filter(Problem.problem_id == payload.problem_id).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate problem_id.")

    persist_problem(db=db, payload=payload, source="author", author_id=user.id)
    db.commit()
    return ProblemUploadResponse(success=True, problem_id=payload.problem_id)
