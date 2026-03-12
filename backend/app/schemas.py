from __future__ import annotations

import json
import re
from typing import Any
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DIFFICULTIES = {"Easy", "Medium", "Hard"}
PROBLEM_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    role: str


class ProblemSummary(BaseModel):
    problem_id: str
    title: str
    prompt: str
    difficulty: str
    function_name: str
    starter_code: Optional[str]
    source: str

    model_config = ConfigDict(from_attributes=True)


class ProblemListResponse(BaseModel):
    problems: list[ProblemSummary]


class SubmissionRequest(BaseModel):
    problem_id: str
    code: str
    timed_mode: bool = False


class SubmissionResponse(BaseModel):
    submission_id: str
    result: str
    failure_category: Optional[str]
    runtime_ms: int
    memory_mb: int
    valid_failed_attempts: int
    hint_stage_unlocked: int
    answer_key_unlocked: bool
    feedback: str


class HintResponse(BaseModel):
    problem_id: str
    unlocked_stage: int
    conceptual: Optional[str]
    strategic: Optional[str]
    syntactic: Optional[str]


class ProblemTestCasePayload(BaseModel):
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


class AnswerKeyPayload(BaseModel):
    solution_code: str
    explanation: str


class ProblemUploadPayload(BaseModel):
    problem_id: str = Field(min_length=1, max_length=100)
    title: str
    prompt: str
    difficulty: str
    function_name: str
    starter_code: Optional[str] = None
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
            if not content.strip():
                raise ValueError(f"hint stage {stage} must not be empty.")
        return value

    @model_validator(mode="after")
    def validate_problem_shape(self) -> "ProblemUploadPayload":
        if not self.title.strip():
            raise ValueError("title must not be empty.")
        if not self.prompt.strip():
            raise ValueError("prompt must not be empty.")
        if self.starter_code is not None and not self.starter_code.strip():
            raise ValueError("starter_code must be omitted or contain code.")
        if self.answer_key is not None and self.function_name not in self.answer_key.solution_code:
            raise ValueError("answer_key.solution_code must contain the required function name.")

        seen_cases = set()
        for test_case in self.test_cases:
            case_key = (json.dumps(test_case.input, sort_keys=True), json.dumps(test_case.expected, sort_keys=True))
            if case_key in seen_cases:
                raise ValueError("test_cases must not contain duplicates.")
            seen_cases.add(case_key)

        return self


class ProblemUploadResponse(BaseModel):
    success: bool
    problem_id: str
