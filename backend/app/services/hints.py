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
    recommended_stage: Optional[int] = None
    submission_code: str = ""
    failure_category: Optional[str] = None
    execution_feedback: str = ""
    error_line: Optional[int] = None
    error_excerpt: Optional[str] = None


class BaseHintService(ABC):
    provider_name = "base"

    @abstractmethod
    def generate_hint(self, *, stage: int, context: HintContext) -> str:
        raise NotImplementedError

    def classify_failure_stage(self, *, context: HintContext) -> int:
        failure_category = context.failure_category or (
            context.latest_submission.failure_category if context.latest_submission is not None else context.progress.last_failure_category
        )
        if failure_category in {"SyntaxError", "DefinitionError"}:
            return 3
        if failure_category in {"RuntimeError", "TimeLimitExceeded"}:
            return 2
        if failure_category == "IncorrectOutput":
            return 1
        return self._fallback_logic_stage(code=self._submission_code(context))

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

    def build_hint_response(
        self,
        *,
        unlocked_stages: set[int],
        revealed_stages: set[int],
        generated_hints: dict[int, str],
        problem: Problem,
    ) -> dict[str, object]:
        # The frontend expects one payload with all unlocked stages so it can
        # render the hint panel without extra shape-mapping.
        return {
            "problem_id": problem.problem_id,
            "unlocked_stage": max(unlocked_stages, default=0),
            "unlocked_stages": sorted(unlocked_stages),
            "revealed_stages": sorted(revealed_stages),
            "conceptual": generated_hints.get(1) if 1 in revealed_stages else None,
            "strategic": generated_hints.get(2) if 2 in revealed_stages else None,
            "syntactic": generated_hints.get(3) if 3 in revealed_stages else None,
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
        if context.recommended_stage in unlocked_stages:
            return context.recommended_stage

        # Otherwise prefer the next missing hint.
        missing_stages = [stage for stage in sorted(unlocked_stages) if stage not in available_hints]
        if not missing_stages:
            return min(unlocked_stages) if unlocked_stages else None

        for stage in missing_stages:
            return stage
        return None

    def _sanitize_generated_hint(self, *, stage: int, hint: str, context: HintContext) -> str:
        cleaned = " ".join(hint.split())
        if stage not in {1, 2}:
            return cleaned

        if self._contains_solution_like_content(cleaned):
            stricter_prompt = "\n".join(
                [
                    "You are helping a student with a Python problem. Give one short hint.",
                    "Do NOT mention any specific operator, constant, variable name, return expression, or corrected code.",
                    "Do NOT say exactly what expression to write, what exact condition to test, or what exact rule to use.",
                    "Do NOT say what to return or what exact value to compare against.",
                    "Only describe the concept or strategy the student is missing in plain English.",
                    f"Problem: {context.problem.title}",
                    f"Task: {self._condense_text(context.problem.prompt, limit=280)}",
                    f"Hint type: {'Conceptual' if stage == 1 else 'Strategic'}",
                    "Student code:",
                    self._build_submission_excerpt(self._submission_code(context)),
                ]
            )
            try:
                return self.generate_hint_from_prompt(prompt=stricter_prompt, stage=stage, context=context)
            except Exception:
                pass

        cleaned = re.sub(r"`[^`]+`", "that expression", cleaned)
        return cleaned

    def _contains_solution_like_content(self, hint: str) -> bool:
        lower_hint = hint.lower()
        forbidden_phrases = [
            "return ",
            "`return",
            "use: return",
            "replace it with",
            "change it to",
            "change the line to",
            "rewrite the line as",
            "the exact code is",
            "your code should be",
        ]
        if any(phrase in lower_hint for phrase in forbidden_phrases):
            return True

        forbidden_patterns = [
            r"`[^`]+`",
            r"\breturn\s+[A-Za-z0-9_\(].+",
            r"\b(use|try|write)\s+.+[=+\-*/%<>!]{1,2}.+",
            r"\b(compare|check|set)\s+.+\bto\b\s+[-]?\d+",
        ]
        return any(re.search(pattern, hint, flags=re.IGNORECASE) for pattern in forbidden_patterns)

    def _build_prompt(self, *, stage: int, context: HintContext) -> str:
        submission = context.latest_submission
        submission_code = self._build_submission_excerpt(self._submission_code(context))
        failure_category = context.failure_category or (submission.failure_category if submission is not None else context.progress.last_failure_category)
        execution_feedback = context.execution_feedback or (submission.feedback if submission is not None else "No execution feedback available.")
        error_line = context.error_line if context.error_line is not None else (submission.error_line if submission is not None else None)
        error_excerpt = context.error_excerpt if context.error_excerpt is not None else (submission.error_excerpt if submission is not None else None)

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

    def _submission_code(self, context: HintContext) -> str:
        if context.submission_code:
            return context.submission_code
        if context.latest_submission is not None:
            return context.latest_submission.code
        return ""

    def _fallback_logic_stage(self, *, code: str) -> int:
        if not code:
            return 1
        try:
            import ast

            tree = ast.parse(code)
        except SyntaxError:
            return 1

        strategic_nodes = (ast.Compare, ast.BoolOp, ast.If, ast.IfExp)
        uses_strategy_structure = any(isinstance(node, strategic_nodes) for node in ast.walk(tree))
        if uses_strategy_structure:
            return 2
        return 1

    def _parse_stage_label(self, raw: str) -> Optional[int]:
        normalized = raw.strip().upper()
        if "STRATEGIC" in normalized or normalized == "2":
            return 2
        if "CONCEPTUAL" in normalized or normalized == "1":
            return 1
        return None

    def _condense_text(self, text: str, *, limit: int) -> str:
        # Collapse long prompt text into a short single-line summary for hints.
        collapsed = " ".join(text.split())
        if len(collapsed) <= limit:
            return collapsed
        return f"{collapsed[: limit - 3].rstrip()}..."

class OllamaHintService(BaseHintService):
    provider_name = "ollama"

    def classify_failure_stage(self, *, context: HintContext) -> int:
        base_stage = super().classify_failure_stage(context=context)
        failure_category = context.failure_category or (
            context.latest_submission.failure_category if context.latest_submission is not None else context.progress.last_failure_category
        )
        if failure_category != "IncorrectOutput":
            return base_stage

        prompt = "\n".join(
            [
                "You are a Python tutor classifying a student's mistake.",
                "Reply with exactly one word: CONCEPTUAL or STRATEGIC.",
                "",
                "Definitions:",
                "CONCEPTUAL means the student's code is based on the wrong core idea, wrong main operation, wrong property, wrong formula, or wrong interpretation of the task.",
                "STRATEGIC means the student's code is based on the right core idea, but one or more implementation details are wrong.",
                "",
                "Decision process:",
                "1. Identify the core requirement of the task from the problem statement.",
                "2. Identify the main idea used in the student's code.",
                "3. If the student's main idea is different from the task's core requirement, choose CONCEPTUAL.",
                "4. If the student's main idea matches the task's core requirement but the implementation is wrong, choose STRATEGIC.",
                "",
                "Choose CONCEPTUAL when:",
                "- the code solves a different problem than the task asks",
                "- the code uses the wrong main operation",
                "- the code checks the wrong main property",
                "- the code applies the wrong formula or rule",
                "- the code uses an unrelated condition",
                "- the approach would need to be replaced, not just adjusted",
                "",
                "Choose STRATEGIC when:",
                "- the code uses the right main operation but applies it incorrectly",
                "- the code checks the right main property but compares it to the wrong value",
                "- the code uses the right variables but combines them incorrectly",
                "- the code has flipped return values",
                "- the code prints instead of returns",
                "- the code has incomplete branching or misses a case",
                "- the code has an off-by-one error or wrong boundary",
                "- the code has steps in the wrong order",
                "- the approach is recognizable as correct but needs refinement",
                "",
                "Important distinctions:",
                "- A wrong operator is CONCEPTUAL if that operator is the central operation required by the task.",
                "- A wrong operator is STRATEGIC if the overall approach is still correct and the operator is only a local implementation detail.",
                "- A wrong constant or comparison value is STRATEGIC if the code is checking the correct general property.",
                "- A wrong constant or comparison value is CONCEPTUAL if it changes the code to check a different core property.",
                "- If the code is close enough that a small correction would preserve the same approach, choose STRATEGIC.",
                "- If the code needs a different approach or different core idea, choose CONCEPTUAL.",
                "",
                "Do not explain your answer.",
                "",
                f"Problem title: {context.problem.title}",
                f"Problem statement: {self._condense_text(context.problem.prompt, limit=420)}",
                f"Required function name: {context.problem.function_name}",
                f"Failure category: {failure_category}",
                f"Execution feedback: {context.execution_feedback or 'No execution feedback available.'}",
                "Student code:",
                self._build_submission_excerpt(self._submission_code(context)),
            ]
        )
        payload = json.dumps(
            {
                "model": settings.hint_model or settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": settings.ollama_keep_alive,
                "options": {
                    "num_predict": 8,
                    "temperature": 0,
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
            stage = self._parse_stage_label(body.get("response") or "")
            return stage or base_stage
        except Exception:
            return base_stage

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


def build_hint_service() -> BaseHintService:
    provider_factories = {
        "ollama": OllamaHintService,
    }
    provider = settings.hint_provider.lower()
    factory = provider_factories.get(provider)
    if factory is None:
        supported = ", ".join(sorted(provider_factories))
        raise RuntimeError(
            f"Unsupported hint provider `{settings.hint_provider}`. "
            f"Implement a BaseHintService subclass and register it in build_hint_service(). "
            f"Current built-in providers: {supported}."
        )
    return factory()


def cache_generated_hint(*, db, user: User, problem: Problem, submission: Submission, stage: int, content: str, revealed: bool = False) -> GeneratedHint:
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
        if revealed and not cached.revealed:
            cached.revealed = True
        return cached

    cached = GeneratedHint(
        user_id=user.id,
        problem_id=problem.id,
        submission_id=submission.id,
        stage=stage,
        content=content,
        revealed=revealed,
    )
    db.add(cached)
    db.flush()
    return cached