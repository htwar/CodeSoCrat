from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional
from urllib import error, request

from app.config import settings
from app.models import Problem, Submission, UserProblemProgress


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

    def build_hint_response(self, *, unlocked_stages: set[int], generated_hints: dict[int, str], problem: Problem) -> dict[str, object]:
        return {
            "problem_id": problem.problem_id,
            "unlocked_stage": max(unlocked_stages, default=0),
            "conceptual": generated_hints.get(1) if 1 in unlocked_stages else None,
            "strategic": generated_hints.get(2) if 2 in unlocked_stages else None,
            "syntactic": generated_hints.get(3) if 3 in unlocked_stages else None,
        }

    def _build_prompt(self, *, stage: int, context: HintContext) -> str:
        submission = context.latest_submission
        submission_code = submission.code if submission is not None else "No submission available."
        failure_category = submission.failure_category if submission is not None else context.progress.last_failure_category
        execution_feedback = submission.feedback if submission is not None else "No execution feedback available."

        stage_instructions = {
            1: (
                "Give a conceptual hint only. Explain the underlying idea or misconception without revealing the algorithm, line-level edits, or the final code."
            ),
            2: (
                "Give a strategic hint only. Describe a plan of attack or debugging approach without writing the exact solution."
            ),
            3: (
                "Give a syntactic hint only. Point out likely syntax, function signature, or small code-shape issues without providing a full final answer unless absolutely necessary."
            ),
        }

        return "\n".join(
            [
                "You are helping a student solve a Python programming problem.",
                f"Hint stage: {STAGE_LABELS[stage]}",
                stage_instructions[stage],
                "Keep the hint concise, specific, and educational.",
                "Do not mention test answers directly unless necessary to explain a syntax or definition issue.",
                "",
                f"Problem title: {context.problem.title}",
                f"Problem prompt: {context.problem.prompt}",
                f"Required function name: {context.problem.function_name}",
                f"Difficulty: {context.problem.difficulty}",
                f"Failure category: {failure_category or 'Unknown'}",
                f"Execution feedback: {execution_feedback}",
                f"Valid failed attempts so far: {context.progress.valid_failed_attempts}",
                "",
                "Student submission:",
                submission_code,
            ]
        )
