from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, selectinload

from app.auth import create_token, get_current_user, require_author, verify_password
from app.config import settings
from app.database import Base, SessionLocal, engine, ensure_schema_evolution, get_db
from app.models import GeneratedHint, Problem, Submission, TestCase, User
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
from app.services.hints import HintContext, OllamaHintService, cache_generated_hint
from app.services.progress import ProgressService
from app.rate_limit import enforce_login_identity_rate_limit, enforce_rate_limit

evaluation_service = EvaluationService()
progress_service = ProgressService()
hint_service = OllamaHintService()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema_evolution()
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


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Apply a lightweight per-IP and per-user throttle before route execution.
    try:
        enforce_rate_limit(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers or {})
    return await call_next(request)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    enforce_login_identity_rate_limit(payload.email)
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    return LoginResponse(token=create_token(user), user_id=str(user.id), role=user.role)


@app.get("/problems", response_model=ProblemListResponse)
def list_problems(
    difficulty: Optional[str] = Query(default=None, pattern="^(Easy|Medium|Hard)$"),
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
        error_line=evaluation.error_line,
        error_excerpt=evaluation.error_excerpt,
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
    problem_id: str = Query(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"),
    stage: Optional[int] = Query(default=None, ge=1, le=3),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HintResponse:
    problem = db.query(Problem).filter(Problem.problem_id == problem_id).first()
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found.")

    progress = progress_service.get_or_create(db, user=user, problem=problem)
    unlocked_stages = progress_service.get_unlocked_stages(progress)
    if not unlocked_stages:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No hints unlocked yet.")
    if stage is not None and stage not in unlocked_stages:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="That hint stage is not unlocked yet.")

    latest_submission = (
        db.query(Submission)
        .filter(Submission.user_id == user.id, Submission.problem_id == problem.id)
        .order_by(Submission.created_at.desc(), Submission.id.desc())
        .first()
    )

    context = HintContext(
        problem=problem,
        progress=progress,
        latest_submission=latest_submission,
    )

    cached_hints = (
        db.query(GeneratedHint)
        .filter(GeneratedHint.user_id == user.id, GeneratedHint.problem_id == problem.id)
        .all()
    )
    generated_hints = hint_service.get_cached_hints(
        cached_hints=cached_hints,
        unlocked_stages=unlocked_stages,
        latest_submission=latest_submission,
    )

    try:
        if stage is not None and latest_submission is not None and stage not in generated_hints:
            generated_hints[stage] = hint_service.generate_hint(stage=stage, context=context)
            cache_generated_hint(
                db=db,
                user=user,
                problem=problem,
                submission=latest_submission,
                stage=stage,
                content=generated_hints[stage],
            )
            db.commit()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    payload = hint_service.build_hint_response(
        unlocked_stages=unlocked_stages,
        generated_hints=generated_hints,
        problem=problem,
    )
    payload["highlight_stage"] = hint_service.determine_highlight_stage(
        unlocked_stages=unlocked_stages,
        available_hints=generated_hints,
        context=context,
    )
    return HintResponse.model_validate(payload)


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
