from __future__ import annotations

import json
import re
from typing import Any
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.security import normalize_multiline_text, normalize_text, validate_email

DIFFICULTIES = {"Easy", "Medium", "Hard"}
PROBLEM_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginRequest(StrictModel):
    email: str
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email_field(cls, value: str) -> str:
        return validate_email(value)

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, value: str) -> str:
        return normalize_text(value, "password", max_length=128)


class RegisterRequest(StrictModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email_field(cls, value: str) -> str:
        return validate_email(value)

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, value: str) -> str:
        return normalize_text(value, "password", max_length=128)

    @field_validator("confirm_password")
    @classmethod
    def validate_confirm_password_field(cls, value: str) -> str:
        return normalize_text(value, "confirm_password", max_length=128)

    @model_validator(mode="after")
    def validate_password_match(self) -> "RegisterRequest":
        if self.password != self.confirm_password:
            raise ValueError("password and confirm_password must match.")
        return self


class LoginResponse(StrictModel):
    token: str
    user_id: str
    role: str


class ProblemSummary(StrictModel):
    problem_id: str
    title: str
    prompt: str
    difficulty: str
    function_name: str
    starter_code: Optional[str]
    source: str

    model_config = ConfigDict(from_attributes=True)


class ProblemListResponse(StrictModel):
    problems: list[ProblemSummary]


class SubmissionRequest(StrictModel):
    problem_id: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=10000)
    timed_mode: bool = False

    @field_validator("problem_id")
    @classmethod
    def validate_problem_identifier(cls, value: str) -> str:
        if not PROBLEM_ID_PATTERN.fullmatch(value):
            raise ValueError("problem_id may only contain letters, numbers, underscores, and hyphens.")
        return value

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        return normalize_multiline_text(value, "code", max_length=10000)


class SubmissionResponse(StrictModel):
    submission_id: str
    result: str
    failure_category: Optional[str]
    runtime_ms: int
    memory_mb: int
    valid_failed_attempts: int
    hint_stage_unlocked: int
    answer_key_unlocked: bool
    feedback: str


class HintResponse(StrictModel):
    problem_id: str
    unlocked_stage: int
    unlocked_stages: list[int]
    highlight_stage: Optional[int] = None
    conceptual: Optional[str]
    strategic: Optional[str]
    syntactic: Optional[str]


class ProblemTestCasePayload(StrictModel):
    input: list[Any]
    expected: Any

    @field_validator("input")
    @classmethod
    def validate_input_is_json_serializable(cls, value: list[Any]) -> list[Any]:
        try:
            json.dumps(value)
        except TypeError as exc:
            raise ValueError("Each test case input must be JSON-serializable.") from exc
        return value

    @field_validator("expected")
    @classmethod
    def validate_expected_is_json_serializable(cls, value: Any) -> Any:
        try:
            json.dumps(value)
        except TypeError as exc:
            raise ValueError("Each test case expected value must be JSON-serializable.") from exc
        return value


class AnswerKeyPayload(StrictModel):
    solution_code: str = Field(min_length=1, max_length=10000)
    explanation: str = Field(min_length=1, max_length=2000)

    @field_validator("solution_code")
    @classmethod
    def validate_solution_code(cls, value: str) -> str:
        return normalize_multiline_text(value, "answer_key.solution_code", max_length=10000)

    @field_validator("explanation")
    @classmethod
    def validate_explanation(cls, value: str) -> str:
        return normalize_multiline_text(value, "answer_key.explanation", max_length=2000)


class ProblemUploadPayload(StrictModel):
    problem_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=4000)
    difficulty: str
    function_name: str
    starter_code: Optional[str] = Field(default=None, max_length=10000)
    test_cases: list[ProblemTestCasePayload] = Field(min_length=1)
    hints: Optional[dict[str, str]] = None
    answer_key: Optional[AnswerKeyPayload] = None

    @field_validator("problem_id")
    @classmethod
    def validate_problem_id(cls, value: str) -> str:
        if not PROBLEM_ID_PATTERN.fullmatch(value):
            raise ValueError("problem_id may only contain letters, numbers, underscores, and hyphens.")
        return value

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, value: str) -> str:
        if value not in DIFFICULTIES:
            raise ValueError("difficulty must be one of Easy, Medium, or Hard.")
        return value

    @field_validator("function_name")
    @classmethod
    def validate_function_name(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("function_name must be a valid Python identifier.")
        return value

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return normalize_text(value, "title", max_length=200)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        return normalize_multiline_text(value, "prompt", max_length=4000)

    @field_validator("starter_code")
    @classmethod
    def validate_starter_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return normalize_multiline_text(value, "starter_code", max_length=10000)

    @field_validator("hints")
    @classmethod
    def validate_hints(cls, value: Optional[dict[str, str]]) -> Optional[dict[str, str]]:
        if value is None:
            return value

        allowed_stages = {"1", "2", "3"}
        invalid_stages = set(value.keys()) - allowed_stages
        if invalid_stages:
            raise ValueError("hints may only contain stages 1, 2, and 3.")

        for stage, content in value.items():
            value[stage] = normalize_multiline_text(content, f"hint stage {stage}", max_length=1200)
        return value

    @model_validator(mode="after")
    def validate_problem_shape(self) -> "ProblemUploadPayload":
        if self.answer_key is not None and self.function_name not in self.answer_key.solution_code:
            raise ValueError("answer_key.solution_code must contain the required function name.")

        seen_cases = set()
        for test_case in self.test_cases:
            case_key = (json.dumps(test_case.input, sort_keys=True), json.dumps(test_case.expected, sort_keys=True))
            if case_key in seen_cases:
                raise ValueError("test_cases must not contain duplicates.")
            seen_cases.add(case_key)

        return self


class ProblemUploadResponse(StrictModel):
    success: bool
    problem_id: str


class ResetProgressResponse(StrictModel):
    success: bool
    problem_id: str
