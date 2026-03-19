from __future__ import annotations

import json
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


class OllamaHintService:
    def generate_hint(self, *, stage: int, context: HintContext) -> str:
        prompt = self._build_prompt(stage=stage, context=context)
        payload = json.dumps(
            {
                "model": settings.ollama_model,
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
        return hint

    def get_cached_hints(
        self,
        *,
        cached_hints: list[GeneratedHint],
        unlocked_stages: set[int],
        latest_submission: Optional[Submission],
    ) -> dict[int, str]:
        if latest_submission is None:
            return {}
        return {
            hint.stage: hint.content
            for hint in cached_hints
            if hint.submission_id == latest_submission.id and hint.stage in unlocked_stages
        }

    def build_hint_response(self, *, unlocked_stages: set[int], generated_hints: dict[int, str], problem: Problem) -> dict[str, object]:
        return {
            "problem_id": problem.problem_id,
            "unlocked_stage": max(unlocked_stages, default=0),
            "unlocked_stages": sorted(unlocked_stages),
            "conceptual": generated_hints.get(1) if 1 in unlocked_stages else None,
            "strategic": generated_hints.get(2) if 2 in unlocked_stages else None,
            "syntactic": generated_hints.get(3) if 3 in unlocked_stages else None,
        }

    def _build_prompt(self, *, stage: int, context: HintContext) -> str:
        submission = context.latest_submission
        submission_code = submission.code if submission is not None else "No submission available."
        failure_category = submission.failure_category if submission is not None else context.progress.last_failure_category
        execution_feedback = submission.feedback if submission is not None else "No execution feedback available."
        error_line = submission.error_line if submission is not None else None
        error_excerpt = submission.error_excerpt if submission is not None else None

        stage_instructions = {
            1: (
                "Give a conceptual hint only. Explain the underlying idea or misconception without revealing the algorithm, line-level edits, or the final code."
            ),
            2: (
                "Give a strategic hint only. Describe a plan of attack or debugging approach without writing the exact solution."
            ),
            3: (
                "Give a syntactic hint only. Focus strictly on the reported syntax or definition issue. Do not mention any other bug unless it is directly supported by the reported error details."
            ),
        }

        return "\n".join(
            [
                "You are helping a student solve a Python programming problem.",
                f"Hint stage: {STAGE_LABELS[stage]}",
                stage_instructions[stage],
                "Keep the hint concise, specific, and educational.",
                "Answer in 2-4 sentences or short bullets.",
                "Do not mention test answers directly unless necessary to explain a syntax or definition issue.",
                "Do not invent missing parentheses, indentation errors, or definition mistakes that are not present in the error evidence.",
                "If the error evidence points to a specific line, anchor the hint to that line only.",
                "",
                f"Problem title: {context.problem.title}",
                f"Problem prompt: {context.problem.prompt}",
                f"Required function name: {context.problem.function_name}",
                f"Difficulty: {context.problem.difficulty}",
                f"Failure category: {failure_category or 'Unknown'}",
                f"Execution feedback: {execution_feedback}",
                f"Reported error line: {error_line if error_line is not None else 'Unknown'}",
                f"Reported error excerpt: {error_excerpt or 'Unknown'}",
                f"Valid failed attempts so far: {context.progress.valid_failed_attempts}",
                "",
                "Student submission:",
                submission_code,
            ]
        )

    def determine_highlight_stage(
        self,
        *,
        unlocked_stages: set[int],
        available_hints: dict[int, str],
        context: HintContext,
    ) -> Optional[int]:
        missing_stages = [stage for stage in sorted(unlocked_stages) if stage not in available_hints]
        if not missing_stages:
            return min(unlocked_stages) if unlocked_stages else None

        failure_category = context.latest_submission.failure_category if context.latest_submission is not None else context.progress.last_failure_category
        if failure_category in {"SyntaxError", "DefinitionError"} and 3 in missing_stages:
            return 3

        for stage in missing_stages:
            return stage
        return None


def cache_generated_hint(*, db, user: User, problem: Problem, submission: Submission, stage: int, content: str) -> GeneratedHint:
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
