from __future__ import annotations

import ast
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Problem, User, UserProblemProgress


class ProgressService:
    def get_or_create(self, db: Session, *, user: User, problem: Problem) -> UserProblemProgress:
        # Every user/problem pair keeps a compact snapshot of attempts and
        # unlocks so the UI can rebuild progress quickly.
        progress = (
            db.query(UserProblemProgress)
            .filter(UserProblemProgress.user_id == user.id, UserProblemProgress.problem_id == problem.id)
            .first()
        )
        if progress is None:
            progress = UserProblemProgress(user_id=user.id, problem_id=problem.id)
            db.add(progress)
            db.flush()
        return progress

    def apply_submission_outcome(
        self,
        *,
        progress: UserProblemProgress,
        execution_type: str,
        result: str,
        failure_category: Optional[str],
        valid_attempt: bool,
        code: Optional[str] = None,
        needed_stage: Optional[int] = None,
    ) -> UserProblemProgress:
        # "Run" is practice mode; only full submits change durable progress.
        if execution_type != "Submit":
            return progress

        if result == "Pass":
            # Passing submissions stop further hint escalation and mark the
            # problem complete.
            progress.completed = True
            progress.last_failure_category = None
            progress.unlocked_stage = max(self.get_unlocked_stages(progress), default=0)
            return progress

        progress.last_failure_category = failure_category
        effective_stage = needed_stage or self.infer_needed_stage(
            failure_category=failure_category,
            code=code,
        )

        progress.unlocked_stage = effective_stage

        if valid_attempt:
            progress.valid_failed_attempts += 1

        if progress.valid_failed_attempts >= 3:
            progress.answer_key_unlocked = True

        return progress

    def infer_needed_stage(self, *, failure_category: Optional[str], code: Optional[str]) -> int:
        if failure_category in {"SyntaxError", "DefinitionError"}:
            return 3
        if failure_category in {"RuntimeError", "TimeLimitExceeded"}:
            return 2
        if failure_category == "IncorrectOutput":
            return 1
        if not code:
            return 1

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return 1

        strategic_nodes = (ast.Compare, ast.BoolOp, ast.If, ast.IfExp)
        uses_strategy_structure = any(isinstance(node, strategic_nodes) for node in ast.walk(tree))
        if uses_strategy_structure:
            return 2
        return 1

    def get_unlocked_stages(self, progress: UserProblemProgress) -> set[int]:
        # The current submission only unlocks the one hint type that best
        # matches the learner's active blocker. Previously revealed hints are
        # surfaced separately by the hint cache, not by widening this set.
        if progress.completed:
            return set()

        unlocked_stages: set[int] = set()

        if progress.unlocked_stage:
            unlocked_stages.add(progress.unlocked_stage)

        return unlocked_stages

    def clear_timed_mode(self, progress: UserProblemProgress) -> UserProblemProgress:
        progress.timed_mode_enabled = False
        progress.timed_mode_started_at = None
        progress.timed_mode_expires_at = None
        progress.timed_mode_paused_at = None
        return progress