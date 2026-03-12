from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models import Problem, User, UserProblemProgress


class ProgressService:
    def get_or_create(self, db: Session, *, user: User, problem: Problem) -> UserProblemProgress:
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
        result: str,
        failure_category: Optional[str],
        valid_attempt: bool,
    ) -> UserProblemProgress:
        if result == "Pass":
            progress.completed = True
            progress.last_failure_category = None
            return progress

        progress.last_failure_category = failure_category

        if failure_category in {"SyntaxError", "DefinitionError"}:
            progress.unlocked_stage = max(progress.unlocked_stage, 3)
            return progress

        if valid_attempt:
            progress.valid_failed_attempts += 1
            if progress.valid_failed_attempts >= 1:
                progress.unlocked_stage = max(progress.unlocked_stage, 1)
            if progress.valid_failed_attempts >= 2:
                progress.unlocked_stage = max(progress.unlocked_stage, 2)
            if progress.valid_failed_attempts >= 3:
                progress.unlocked_stage = max(progress.unlocked_stage, 3)
                progress.answer_key_unlocked = True

        return progress
