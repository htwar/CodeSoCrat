from __future__ import annotations

from typing import Optional, Union

from app.models import Hint, Problem, UserProblemProgress


def build_hint_response(problem: Problem, progress: UserProblemProgress) -> dict[str, Union[str, int, None]]:
    hint_map = {hint.stage: hint.content for hint in problem.hints}
    return {
        "problem_id": problem.problem_id,
        "unlocked_stage": progress.unlocked_stage,
        "conceptual": hint_map.get(1) if progress.unlocked_stage >= 1 else None,
        "strategic": hint_map.get(2) if progress.unlocked_stage >= 2 else None,
        "syntactic": hint_map.get(3) if progress.unlocked_stage >= 3 else None,
    }


def generate_fallback_hint(stage: int, failure_category: Optional[str], problem: Problem) -> str:
    if stage == 1:
        return f"Review the core idea behind '{problem.title}' and focus on what the function should return."
    if stage == 2:
        return f"Break the solution into one clear step at a time and verify the return value for {problem.function_name}."
    if failure_category in {"SyntaxError", "DefinitionError"}:
        return f"Check the spelling and definition of '{problem.function_name}' and make sure the code is valid Python."
    return f"Compare your implementation of '{problem.function_name}' against the expected return value for the failing test."
