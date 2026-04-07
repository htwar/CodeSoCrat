from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.auth import (
    create_csrf_token,
    create_token,
    get_current_user,
    hash_password,
    require_author,
    require_csrf,
    verify_google_id_token,
    verify_password,
)
from app.database import Base, SessionLocal, engine, ensure_schema_evolution, get_db
from app.models import GeneratedHint, Problem, Submission, User, UserProblemProgress
from app.rate_limit import enforce_login_identity_rate_limit, enforce_rate_limit
from app.schemas import (
    AnswerKeyResponse,
    AuthorProblemListResponse,
    GoogleAuthRequest,
    HintResponse,
    LoginRequest,
    LoginResponse,
    ProblemListResponse,
    ProblemSummary,
    ProblemUpdateResponse,
    ProblemUploadPayload,
    ProblemUploadResponse,
    RegisterRequest,
    ResetProgressResponse,
    SubmissionRequest,
    SubmissionResponse,
)
from app.security import validate_email
from app.config import settings
from app.services.bootstrap import persist_problem, replace_problem_contents, seed_default_users, seed_starter_problems
from app.services.evaluation import EvaluationService
from app.services.hints import HintContext, OllamaHintService, cache_generated_hint
from app.services.progress import ProgressService

evaluation_service = EvaluationService()
progress_service = ProgressService()
hint_service = OllamaHintService()


# Application startup seeds demo users and starter problems so the local app is
# usable immediately after the API boots.
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
    # Apply centralized throttling before the request reaches the route handler.
    try:
        enforce_rate_limit(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers or {})
    return await call_next(request)


def _set_session_cookie(response: Response, token: str) -> None:
    # Set both the signed session cookie and the matching CSRF cookie used by
    # the frontend for POST/PUT/DELETE requests.
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        max_age=settings.session_cookie_max_age_seconds,
        path="/",
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=create_csrf_token(token),
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        max_age=settings.session_cookie_max_age_seconds,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    # Remove both auth-related cookies during logout.
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )
    response.delete_cookie(
        key=settings.csrf_cookie_name,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


def _build_login_response(user: User) -> LoginResponse:
    # Normalize the session payload shape shared by login, register, Google
    # auth, and session-restore endpoints.
    return LoginResponse(
        user_id=str(user.id),
        email=user.email,
        role=user.role,
        display_name=user.display_name,
        auth_provider=user.auth_provider,
    )


# Problem responses are tailored to the current viewer so author users can see
# which custom problems they are allowed to manage.
def _serialize_problem(problem: Problem, *, viewer: User) -> ProblemSummary:
    can_manage = viewer.role == "Author" and problem.author_id == viewer.id and problem.source != "starter"
    return ProblemSummary(
        problem_id=problem.problem_id,
        title=problem.title,
        prompt=problem.prompt,
        difficulty=problem.difficulty,
        function_name=problem.function_name,
        starter_code=problem.starter_code,
        example_cases=[
            {
                "input": json.loads(example_case.input_json),
                "expected": json.loads(example_case.expected_json),
            }
            for example_case in problem.example_cases
        ],
        source=problem.source,
        is_active=problem.is_active,
        is_deleted=problem.is_deleted,
        author_id=str(problem.author_id) if problem.author_id is not None else None,
        author_email=problem.author.email if problem.author is not None else None,
        can_edit=can_manage and not problem.is_deleted,
        can_disable=can_manage and not problem.is_deleted,
        can_delete=can_manage and not problem.is_deleted,
    )


def _get_visible_problem(problem_id: str, db: Session) -> Problem:
    # Fetch a problem the learner is actually allowed to attempt.
    problem = (
        db.query(Problem)
        .options(
            selectinload(Problem.test_cases),
            selectinload(Problem.answer_key),
            selectinload(Problem.hints),
            selectinload(Problem.example_cases),
        )
        .filter(
            Problem.problem_id == problem_id,
            Problem.is_deleted.is_(False),
            Problem.is_active.is_(True),
        )
        .first()
    )
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found.")
    return problem


def _get_manageable_problem(problem_id: str, *, user: User, db: Session) -> Problem:
    # Fetch one author-owned custom problem and enforce that starter problems
    # remain read-only.
    problem = (
        db.query(Problem)
        .options(selectinload(Problem.example_cases), selectinload(Problem.author))
        .filter(Problem.problem_id == problem_id)
        .first()
    )
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found.")
    if problem.source == "starter":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Starter problems are read-only.")
    if problem.author_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You may only manage your own uploaded problems.")
    return problem


@app.get("/health")
def health_check() -> dict[str, str]:
    # Minimal readiness endpoint for local checks and container health probes.
    return {"status": "ok"}


@app.get("/auth/google/config")
def get_google_auth_config() -> dict[str, str | bool]:
    # Let the frontend know whether the Google button should be rendered.
    return {
        "enabled": bool(settings.google_client_id),
        "client_id": settings.google_client_id,
    }


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> LoginResponse:
    # Authenticate a local email/password account and issue fresh cookies.
    enforce_login_identity_rate_limit(payload.email)
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    _set_session_cookie(response, create_token(user))
    return _build_login_response(user)


@app.post("/auth/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)) -> LoginResponse:
    # Create a new student account, then sign it in immediately.
    enforce_login_identity_rate_limit(payload.email)
    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with that email already exists.")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role="Student",
        auth_provider="local",
        display_name=payload.email.split("@", 1)[0],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _set_session_cookie(response, create_token(user))
    return _build_login_response(user)


@app.post("/auth/google", response_model=LoginResponse)
def google_auth(payload: GoogleAuthRequest, response: Response, db: Session = Depends(get_db)) -> LoginResponse:
    # Sign in with a verified Google credential, linking to an existing account
    # when the email or Google subject already exists.
    claims = verify_google_id_token(payload.credential)
    email = validate_email(str(claims["email"]))
    enforce_login_identity_rate_limit(email)

    user = (
        db.query(User)
        .filter(or_(User.google_sub == str(claims["sub"]), User.email == email))
        .first()
    )

    if user is None:
        user = User(
            email=email,
            password_hash=None,
            role="Student",
            auth_provider="google",
            google_sub=str(claims["sub"]),
            display_name=claims.get("name") or email.split("@", 1)[0],
        )
        db.add(user)
    else:
        user.google_sub = str(claims["sub"])
        user.display_name = claims.get("name") or user.display_name
        if user.auth_provider == "local":
            user.auth_provider = "local+google"
        elif user.auth_provider != "local+google":
            user.auth_provider = "google"

    db.commit()
    db.refresh(user)
    _set_session_cookie(response, create_token(user))
    return _build_login_response(user)


@app.get("/auth/session", response_model=LoginResponse)
def get_session(response: Response, request: Request, user: User = Depends(get_current_user)) -> LoginResponse:
    # Restore the current user from the session cookie and refresh cookie age.
    session_token = request.cookies.get(settings.session_cookie_name)
    if session_token:
        _set_session_cookie(response, session_token)
    return _build_login_response(user)


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(_csrf: None = Depends(require_csrf)) -> Response:
    # Clear cookies so the browser is no longer authenticated.
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookie(response)
    return response


@app.get("/problems", response_model=ProblemListResponse)
def list_problems(
    difficulty: Optional[str] = Query(default=None, pattern="^(Easy|Medium|Hard)$"),
    source: Optional[str] = Query(default=None, pattern="^(starter|author)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProblemListResponse:
    # Return the active problem catalog filtered by difficulty and optional
    # source for the currently logged-in user.
    query = (
        db.query(Problem)
        .options(selectinload(Problem.example_cases), selectinload(Problem.author))
        .filter(Problem.is_deleted.is_(False), Problem.is_active.is_(True))
        .order_by(Problem.difficulty, Problem.title)
    )
    if difficulty:
        query = query.filter(Problem.difficulty == difficulty)
    if source:
        query = query.filter(Problem.source == source)

    problems = query.all()
    return ProblemListResponse(problems=[_serialize_problem(problem, viewer=user) for problem in problems])


# All code execution paths share the same backend evaluation flow so run,
# submit, and timed auto-submit produce the same result structure.
def _execute_code(
    *,
    execution_type: str,
    payload: SubmissionRequest,
    user: User,
    db: Session,
) -> SubmissionResponse:
    problem = _get_visible_problem(payload.problem_id, db)
    test_cases = [(json.loads(case.input_json), json.loads(case.expected_json)) for case in problem.test_cases]
    evaluation = evaluation_service.evaluate(
        code=payload.code,
        function_name=problem.function_name,
        test_cases=test_cases,
    )

    progress = progress_service.get_or_create(db, user=user, problem=problem)
    progress_service.apply_submission_outcome(
        progress=progress,
        execution_type=execution_type,
        result=evaluation.result,
        failure_category=evaluation.failure_category,
        valid_attempt=evaluation.valid_attempt,
    )

    submission = Submission(
        user_id=user.id,
        problem_id=problem.id,
        execution_type=execution_type,
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
        execution_type=execution_type,
        result=evaluation.result,
        failure_category=evaluation.failure_category,
        runtime_ms=evaluation.runtime_ms,
        memory_mb=evaluation.memory_mb,
        valid_failed_attempts=progress.valid_failed_attempts,
        hint_stage_unlocked=progress.unlocked_stage,
        answer_key_unlocked=progress.answer_key_unlocked,
        feedback=evaluation.feedback,
        counts_toward_progress=execution_type == "Submit" and evaluation.result == "Fail" and evaluation.valid_attempt,
    )


@app.post("/run", response_model=SubmissionResponse)
def run_code(
    payload: SubmissionRequest,
    _csrf: None = Depends(require_csrf),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubmissionResponse:
    # Practice-only execution path that does not advance durable progress.
    return _execute_code(execution_type="Run", payload=payload, user=user, db=db)


@app.post("/submit", response_model=SubmissionResponse)
def submit_code(
    payload: SubmissionRequest,
    _csrf: None = Depends(require_csrf),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubmissionResponse:
    # Full submission path that updates attempts, hints, and answer-key unlocks.
    return _execute_code(execution_type="Submit", payload=payload, user=user, db=db)


@app.post("/submissions", response_model=SubmissionResponse)
def submit_code_legacy(
    payload: SubmissionRequest,
    _csrf: None = Depends(require_csrf),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubmissionResponse:
    # Backward-compatible alias for older clients that still post to
    # `/submissions`.
    return _execute_code(execution_type="Submit", payload=payload, user=user, db=db)


@app.get("/hints", response_model=HintResponse)
def get_hints(
    problem_id: str = Query(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"),
    stage: Optional[int] = Query(default=None, ge=1, le=3),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HintResponse:
    # Return currently unlocked hints and optionally generate one specific stage
    # on demand for the latest failing submission.
    problem = db.query(Problem).filter(Problem.problem_id == problem_id, Problem.is_deleted.is_(False)).first()
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
        .filter(
            Submission.user_id == user.id,
            Submission.problem_id == problem.id,
            Submission.execution_type == "Submit",
        )
        .order_by(Submission.created_at.desc(), Submission.id.desc())
        .first()
    )

    context = HintContext(problem=problem, progress=progress, latest_submission=latest_submission)
    cached_hints = db.query(GeneratedHint).filter(GeneratedHint.user_id == user.id, GeneratedHint.problem_id == problem.id).all()
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


@app.get("/answer-key", response_model=AnswerKeyResponse)
def get_answer_key(
    problem_id: str = Query(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnswerKeyResponse:
    # Reveal the stored answer key only after the learner has unlocked it.
    problem = (
        db.query(Problem)
        .options(selectinload(Problem.answer_key))
        .filter(Problem.problem_id == problem_id, Problem.is_deleted.is_(False))
        .first()
    )
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found.")
    if problem.answer_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Answer key not available for this problem.")

    progress = progress_service.get_or_create(db, user=user, problem=problem)
    if not progress.answer_key_unlocked:
        return AnswerKeyResponse(problem_id=problem.problem_id, unlocked=False, solution_code=None, explanation=None)

    return AnswerKeyResponse(
        problem_id=problem.problem_id,
        unlocked=True,
        solution_code=problem.answer_key.solution_code,
        explanation=problem.answer_key.explanation,
    )


@app.get("/author/problems", response_model=AuthorProblemListResponse)
def list_author_dashboard_problems(
    source: str = Query(default="all", pattern="^(all|starter|author)$"),
    include_deleted: bool = False,
    user: User = Depends(require_author),
    db: Session = Depends(get_db),
) -> AuthorProblemListResponse:
    # Drive the author dashboard list, combining starter problems with the
    # current author's own custom uploads.
    query = db.query(Problem).options(selectinload(Problem.example_cases), selectinload(Problem.author))
    if not include_deleted:
        query = query.filter(Problem.is_deleted.is_(False))

    if source == "starter":
        query = query.filter(Problem.source == "starter")
    elif source == "author":
        query = query.filter(Problem.source == "author", Problem.author_id == user.id)
    else:
        query = query.filter(or_(Problem.source == "starter", Problem.author_id == user.id))

    problems = query.order_by(Problem.source, Problem.difficulty, Problem.title).all()
    return AuthorProblemListResponse(problems=[_serialize_problem(problem, viewer=user) for problem in problems])


@app.get("/author/problems/{problem_id}", response_model=ProblemUploadPayload)
def get_author_problem(
    problem_id: str,
    user: User = Depends(require_author),
    db: Session = Depends(get_db),
) -> ProblemUploadPayload:
    # Load one author-owned custom problem back into editable JSON.
    problem = (
        db.query(Problem)
        .options(
            selectinload(Problem.example_cases),
            selectinload(Problem.test_cases),
            selectinload(Problem.hints),
            selectinload(Problem.answer_key),
        )
        .filter(Problem.problem_id == problem_id)
        .first()
    )
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found.")
    if problem.source == "starter" or problem.author_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You may only view editable payloads for your own uploaded problems.")

    hints = {str(hint.stage): hint.content for hint in sorted(problem.hints, key=lambda item: item.stage)}
    return ProblemUploadPayload(
        problem_id=problem.problem_id,
        title=problem.title,
        prompt=problem.prompt,
        difficulty=problem.difficulty,
        function_name=problem.function_name,
        starter_code=problem.starter_code,
        example_cases=[
            {
                "input": json.loads(example_case.input_json),
                "expected": json.loads(example_case.expected_json),
            }
            for example_case in problem.example_cases
        ],
        test_cases=[
            {
                "input": json.loads(test_case.input_json),
                "expected": json.loads(test_case.expected_json),
            }
            for test_case in problem.test_cases
        ],
        hints=hints or None,
        answer_key=(
            {
                "solution_code": problem.answer_key.solution_code,
                "explanation": problem.answer_key.explanation,
            }
            if problem.answer_key is not None
            else None
        ),
    )


@app.post("/author/problems/upload", response_model=ProblemUploadResponse)
def upload_problem(
    payload: ProblemUploadPayload,
    _csrf: None = Depends(require_csrf),
    user: User = Depends(require_author),
    db: Session = Depends(get_db),
) -> ProblemUploadResponse:
    # Create a new custom problem from the JSON currently in the author editor.
    existing = db.query(Problem).filter(Problem.problem_id == payload.problem_id).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate problem_id.")

    persist_problem(db=db, payload=payload, source="author", author_id=user.id)
    db.commit()
    return ProblemUploadResponse(success=True, problem_id=payload.problem_id)


@app.post("/author/problems/upload-file", response_model=ProblemUploadResponse)
async def upload_problem_file(
    file: UploadFile = File(...),
    _csrf: None = Depends(require_csrf),
    user: User = Depends(require_author),
    db: Session = Depends(get_db),
) -> ProblemUploadResponse:
    # Import one JSON file directly through multipart upload for author users.
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload a single .json problem file.")

    try:
        raw = (await file.read()).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Problem file must be valid UTF-8 JSON.") from exc

    try:
        payload = ProblemUploadPayload.model_validate(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Uploaded file is not valid JSON: {exc.msg}.") from exc

    existing = db.query(Problem).filter(Problem.problem_id == payload.problem_id).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate problem_id.")

    persist_problem(db=db, payload=payload, source="author", author_id=user.id)
    db.commit()
    return ProblemUploadResponse(success=True, problem_id=payload.problem_id)


@app.put("/author/problems/{problem_id}", response_model=ProblemUpdateResponse)
def update_problem(
    problem_id: str,
    payload: ProblemUploadPayload,
    _csrf: None = Depends(require_csrf),
    user: User = Depends(require_author),
    db: Session = Depends(get_db),
) -> ProblemUpdateResponse:
    # Replace an existing custom problem with the edited JSON payload.
    if payload.problem_id != problem_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="problem_id in the payload must match the selected problem.")

    problem = _get_manageable_problem(problem_id, user=user, db=db)
    replace_problem_contents(db=db, problem=problem, payload=payload)
    db.commit()
    db.refresh(problem)
    return ProblemUpdateResponse(success=True, problem_id=problem.problem_id, is_active=problem.is_active, is_deleted=problem.is_deleted)


@app.post("/author/problems/{problem_id}/disable", response_model=ProblemUpdateResponse)
def disable_problem(
    problem_id: str,
    _csrf: None = Depends(require_csrf),
    user: User = Depends(require_author),
    db: Session = Depends(get_db),
) -> ProblemUpdateResponse:
    # Hide a custom problem from the learner catalog without deleting it.
    problem = _get_manageable_problem(problem_id, user=user, db=db)
    problem.is_active = False
    db.commit()
    db.refresh(problem)
    return ProblemUpdateResponse(success=True, problem_id=problem.problem_id, is_active=problem.is_active, is_deleted=problem.is_deleted)


@app.post("/author/problems/{problem_id}/enable", response_model=ProblemUpdateResponse)
def enable_problem(
    problem_id: str,
    _csrf: None = Depends(require_csrf),
    user: User = Depends(require_author),
    db: Session = Depends(get_db),
) -> ProblemUpdateResponse:
    # Make a previously disabled custom problem visible again.
    problem = _get_manageable_problem(problem_id, user=user, db=db)
    problem.is_active = True
    db.commit()
    db.refresh(problem)
    return ProblemUpdateResponse(success=True, problem_id=problem.problem_id, is_active=problem.is_active, is_deleted=problem.is_deleted)


@app.delete("/author/problems/{problem_id}", response_model=ProblemUpdateResponse)
def delete_problem(
    problem_id: str,
    _csrf: None = Depends(require_csrf),
    user: User = Depends(require_author),
    db: Session = Depends(get_db),
) -> ProblemUpdateResponse:
    # Soft-delete a custom problem so historical data stays intact.
    problem = _get_manageable_problem(problem_id, user=user, db=db)
    problem.is_active = False
    problem.is_deleted = True
    db.commit()
    db.refresh(problem)
    return ProblemUpdateResponse(success=True, problem_id=problem.problem_id, is_active=problem.is_active, is_deleted=problem.is_deleted)


@app.delete("/progress/{problem_id}", response_model=ResetProgressResponse)
def reset_problem_progress(
    problem_id: str,
    _csrf: None = Depends(require_csrf),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResetProgressResponse:
    # Wipe one learner's submissions, hints, and unlocks for a problem so they
    # can start fresh.
    problem = db.query(Problem).filter(Problem.problem_id == problem_id, Problem.is_deleted.is_(False)).first()
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found.")

    submission_ids = [
        submission_id
        for (submission_id,) in db.query(Submission.id)
        .filter(Submission.user_id == user.id, Submission.problem_id == problem.id)
        .all()
    ]

    if submission_ids:
        db.query(GeneratedHint).filter(
            GeneratedHint.user_id == user.id,
            GeneratedHint.problem_id == problem.id,
            GeneratedHint.submission_id.in_(submission_ids),
        ).delete(synchronize_session=False)

    db.query(Submission).filter(
        Submission.user_id == user.id,
        Submission.problem_id == problem.id,
    ).delete(synchronize_session=False)

    db.query(UserProblemProgress).filter(
        UserProblemProgress.user_id == user.id,
        UserProblemProgress.problem_id == problem.id,
    ).delete(synchronize_session=False)

    db.commit()
    return ResetProgressResponse(success=True, problem_id=problem.problem_id)
