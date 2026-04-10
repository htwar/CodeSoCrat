from __future__ import annotations

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

        if valid_attempt:
            progress.valid_failed_attempts += 1
        # The SRS unlocks the answer key after four valid failed submits for
        # the same user/problem pair.
        if progress.valid_failed_attempts >= 4:
            progress.answer_key_unlocked = True

        progress.unlocked_stage = max(self.get_unlocked_stages(progress), default=0)

        return progress

    def get_unlocked_stages(self, progress: UserProblemProgress) -> set[int]:
        # Hint stages unlock progressively, with syntax issues fast-tracking the
        # syntactic hint so students can get unstuck sooner.
        if progress.completed:
            return set()

        unlocked_stages: set[int] = set()

        if progress.valid_failed_attempts >= 1:
            unlocked_stages.add(1)
        if progress.valid_failed_attempts >= 2:
            unlocked_stages.add(2)
        if progress.valid_failed_attempts >= 3:
            unlocked_stages.add(3)

        if progress.last_failure_category in {"SyntaxError", "DefinitionError"}:
            unlocked_stages.add(3)

        return unlocked_stages

    def clear_timed_mode(self, progress: UserProblemProgress) -> UserProblemProgress:
        progress.timed_mode_enabled = False
        progress.timed_mode_started_at = None
        progress.timed_mode_expires_at = None
        progress.timed_mode_paused_at = None
        return progress
