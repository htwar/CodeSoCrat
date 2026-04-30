from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from urllib import error, request

from app.config import settings
from app.models import GeneratedHint, Problem, Submission, User, UserProblemProgress


STAGE_LABELS = {
    1: "Conceptual",
    2: "Strategic",
    3: "Syntactic",
}


@dataclass
class HintContext:
    problem: Problem
    progress: UserProblemProgress
    latest_submission: Optional[Submission]


class BaseHintService(ABC):
    provider_name = "base"

    @abstractmethod
    def generate_hint(self, *, stage: int, context: HintContext) -> str:
        raise NotImplementedError

    def get_cached_hints(
        self,
        *,
        cached_hints: list[GeneratedHint],
        unlocked_stages: set[int],
        latest_submission: Optional[Submission],
    ) -> dict[int, str]:
        # Once a learner reveals a hint for a problem, keep showing the most
        # recently generated version of that stage until the problem progress
        # is reset. Prefer the current submission's hint when it exists, then
        # fall back to the newest cached hint from earlier attempts.
        if not cached_hints:
            return {}

        generated_hints: dict[int, str] = {}
        sorted_hints = sorted(
            cached_hints,
            key=lambda hint: (
                1 if latest_submission is not None and hint.submission_id == latest_submission.id else 0,
                hint.created_at,
                hint.id,
            ),
            reverse=True,
        )
        for hint in sorted_hints:
            if hint.stage not in unlocked_stages or hint.stage in generated_hints:
                continue
            generated_hints[hint.stage] = hint.content
        return generated_hints

    def build_hint_response(self, *, unlocked_stages: set[int], generated_hints: dict[int, str], problem: Problem) -> dict[str, object]:
        # The frontend expects one payload with all unlocked stages so it can
        # render the hint panel without extra shape-mapping.
        return {
            "problem_id": problem.problem_id,
            "unlocked_stage": max(unlocked_stages, default=0),
            "unlocked_stages": sorted(unlocked_stages),
            "conceptual": generated_hints.get(1) if 1 in unlocked_stages else None,
            "strategic": generated_hints.get(2) if 2 in unlocked_stages else None,
            "syntactic": generated_hints.get(3) if 3 in unlocked_stages else None,
        }

    def determine_highlight_stage(
        self,
        *,
        unlocked_stages: set[int],
        available_hints: dict[int, str],
        context: HintContext,
    ) -> Optional[int]:
        # Prefer syntax guidance first when the latest failure is a parsing or
        # definition blocker, even if other hints are already available.
        failure_category = context.latest_submission.failure_category if context.latest_submission is not None else context.progress.last_failure_category
        if failure_category in {"SyntaxError", "DefinitionError"} and 3 in unlocked_stages:
            return 3

        # Otherwise prefer the next missing hint.
        missing_stages = [stage for stage in sorted(unlocked_stages) if stage not in available_hints]
        if not missing_stages:
            return min(unlocked_stages) if unlocked_stages else None

        for stage in missing_stages:
            return stage
        return None

    def _sanitize_generated_hint(self, *, stage: int, hint: str, context: HintContext) -> str:
        # Guard against over-revealing hints for beginner problems by stripping
        # exact solution patterns from conceptual and strategic hints.
        cleaned = " ".join(hint.split())
        if stage not in {1, 2}:
            return cleaned

        lower_hint = cleaned.lower()
        forbidden_markers = [
            "return ",
            "`return",
            "use: return",
            "replace it with",
            "modulo 2",
            "% 2",
            "== 0",
            "divided by 2",
            "remainder of",
        ]
        if any(marker in lower_hint for marker in forbidden_markers):
            hint_name = STAGE_LABELS[stage].lower()
            if stage == 1:
                return (
                    f"This {hint_name} hint should stay high level. Focus on what property separates valid cases from invalid ones, "
                    "and make sure the function returns a boolean answer instead of restating the full rule."
                )
            return (
                f"This {hint_name} hint should guide the next step without giving the final condition away. "
                "Re-check what relationship the function needs to test, then rewrite the return statement so it evaluates that property directly."
            )

        # Strip stray inline code fragments even when the rest of the hint is usable.
        cleaned = re.sub(r"`[^`]+`", "that expression", cleaned)
        return cleaned

    def _build_prompt(self, *, stage: int, context: HintContext) -> str:
        submission = context.latest_submission
        submission_code = self._build_submission_excerpt(submission.code if submission is not None else "")
        failure_category = submission.failure_category if submission is not None else context.progress.last_failure_category
        execution_feedback = submission.feedback if submission is not None else "No execution feedback available."
        error_line = submission.error_line if submission is not None else None
        error_excerpt = submission.error_excerpt if submission is not None else None

        stage_instructions = {
            1: (
                "Give a conceptual hint only. Explain the underlying idea or misconception without revealing the algorithm, specific operators, specific constants, line-level edits, or the final code."
            ),
            2: (
                "Give a strategic hint only. Describe a plan of attack or debugging approach without writing the exact solution, exact condition, or exact return expression."
            ),
            3: (
                "Give a syntactic hint only. Focus strictly on the reported syntax or definition issue. Explain what kind of token, operator, delimiter, or function-name fix is needed, but do not provide the exact corrected line or a complete replacement expression."
            ),
        }

        evidence_lines = [
            f"Failure category: {failure_category or 'Unknown'}",
        ]
        if error_line is not None:
            evidence_lines.append(f"Reported error line: {error_line}")
        if error_excerpt:
            evidence_lines.append(f"Reported error excerpt: {error_excerpt}")
        if execution_feedback:
            evidence_lines.append(f"Execution feedback: {execution_feedback}")

        problem_context = [
            f"Problem: {context.problem.title}",
            f"Required function: {context.problem.function_name}",
        ]
        if stage in {1, 2}:
            problem_context.append(f"Prompt: {self._condense_text(context.problem.prompt, limit=420)}")
        else:
            problem_context.append(f"Prompt summary: {self._condense_text(context.problem.prompt, limit=180)}")

        return "\n".join(
            [
                "You are helping a student solve one Python problem.",
                f"Hint type: {STAGE_LABELS[stage]}",
                stage_instructions[stage],
                "Write at most 2 short bullets.",
                "Be concrete, concise, and educational.",
                "Do not reveal the full solution.",
                "Do not provide a fully corrected code line.",
                "Do not provide the exact final return expression.",
                "Do not provide a specific operator-and-constant rule unless the student has explicitly unlocked the answer key.",
                "Do not name the final operator sequence unless the parser error already explicitly identifies it.",
                "For conceptual and strategic hints, do not mention the exact arithmetic test, exact divisor, exact constant, or exact comparison needed for the final solution.",
                "Do not mention any bug not supported by the evidence.",
                "",
                *problem_context,
                *evidence_lines,
                "",
                "Student code excerpt:",
                submission_code,
            ]
        )

    def _build_submission_excerpt(self, code: str) -> str:
        # Limit the amount of student code sent to the model so prompts stay
        # short and focused.
        if not code:
            return "No submission available."
        lines = code.splitlines()
        limit = settings.ollama_hint_code_preview_lines
        if len(lines) <= limit:
            return code
        head = lines[: max(6, limit - 4)]
        tail = lines[-2:]
        return "\n".join([*head, "...", *tail])

    def _condense_text(self, text: str, *, limit: int) -> str:
        # Collapse long prompt text into a short single-line summary for hints.
        collapsed = " ".join(text.split())
        if len(collapsed) <= limit:
            return collapsed
        return f"{collapsed[: limit - 3].rstrip()}..."


class OllamaHintService(BaseHintService):
    provider_name = "ollama"

    def generate_hint(self, *, stage: int, context: HintContext) -> str:
        prompt = self._build_prompt(stage=stage, context=context)
        payload = json.dumps(
            {
                "model": settings.hint_model or settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": settings.ollama_keep_alive,
                "options": {
                    "num_predict": settings.ollama_hint_max_tokens,
                    "temperature": 0.2,
                },
            }
        ).encode("utf-8")
        endpoint = f"{settings.ollama_base_url}/api/generate"
        http_request = request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=settings.ollama_timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            raise RuntimeError(f"Ollama is unavailable at {settings.ollama_base_url}.") from exc
        except TimeoutError as exc:
            raise RuntimeError("Ollama hint generation timed out.") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama returned an unreadable hint response.") from exc

        hint = (body.get("response") or "").strip()
        if not hint:
            raise RuntimeError("Ollama returned an empty hint.")
        return self._sanitize_generated_hint(stage=stage, hint=hint, context=context)


class GPT4AllHintService(BaseHintService):
    provider_name = "gpt4all"

    def generate_hint(self, *, stage: int, context: HintContext) -> str:
        model_name = settings.gpt4all_model_path or settings.hint_model
        if not model_name:
            raise RuntimeError("Set CODESOCRAT_GPT4ALL_MODEL_PATH or CODESOCRAT_HINT_MODEL before using the GPT4All hint provider.")

        try:
            from gpt4all import GPT4All
        except ImportError as exc:
            raise RuntimeError("GPT4All support requires the `gpt4all` package to be installed in the backend environment.") from exc

        prompt = self._build_prompt(stage=stage, context=context)

        try:
            model = GPT4All(
                model_name=model_name,
                device=settings.gpt4all_device,
                allow_download=settings.gpt4all_allow_download,
            )
        except TypeError:
            # Older GPT4All builds do not expose `allow_download`.
            model = GPT4All(
                model_name=model_name,
                device=settings.gpt4all_device,
            )
        except Exception as exc:
            raise RuntimeError(f"GPT4All could not load the model `{model_name}`.") from exc

        try:
            with model.chat_session():
                hint = model.generate(
                    prompt,
                    max_tokens=settings.ollama_hint_max_tokens,
                    temp=0.2,
                    n_threads=settings.gpt4all_threads,
                )
        except Exception as exc:
            raise RuntimeError("GPT4All hint generation failed.") from exc

        hint_text = str(hint).strip()
        if not hint_text:
            raise RuntimeError("GPT4All returned an empty hint.")
        return self._sanitize_generated_hint(stage=stage, hint=hint_text, context=context)


def build_hint_service() -> BaseHintService:
    provider = settings.hint_provider.lower()
    if provider == "ollama":
        return OllamaHintService()
    if provider == "gpt4all":
        return GPT4AllHintService()
    raise RuntimeError(f"Unsupported hint provider `{settings.hint_provider}`.")


def cache_generated_hint(*, db, user: User, problem: Problem, submission: Submission, stage: int, content: str) -> GeneratedHint:
    # Reuse an existing row when the same submission already produced a hint for
    # that stage, which keeps the cache idempotent.
    cached = (
        db.query(GeneratedHint)
        .filter(
            GeneratedHint.user_id == user.id,
            GeneratedHint.problem_id == problem.id,
            GeneratedHint.submission_id == submission.id,
            GeneratedHint.stage == stage,
        )
        .first()
    )
    if cached is not None:
        return cached

    cached = GeneratedHint(
        user_id=user.id,
        problem_id=problem.id,
        submission_id=submission.id,
        stage=stage,
        content=content,
    )
    db.add(cached)
    db.flush()
    return cached
