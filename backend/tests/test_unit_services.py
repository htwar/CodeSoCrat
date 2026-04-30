import os
import importlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class UnitServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Point the service-level tests at a disposable SQLite database so
        # persistence helpers can be exercised safely.
        cls.temp_dir = TemporaryDirectory()
        db_path = Path(cls.temp_dir.name) / "unit_test.db"
        os.environ["CODESOCRAT_DATABASE_URL"] = f"sqlite:///{db_path}"

        from app.config import settings

        settings.database_url = os.environ["CODESOCRAT_DATABASE_URL"]

        import app.database as database_module
        import app.models as models_module

        database_module = importlib.reload(database_module)
        models_module = importlib.reload(models_module)

        Base = database_module.Base
        SessionLocal = database_module.SessionLocal
        engine = database_module.engine

        cls.Base = Base
        cls.SessionLocal = SessionLocal
        cls.engine = engine

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        cls.temp_dir.cleanup()
        os.environ.pop("CODESOCRAT_DATABASE_URL", None)

    def setUp(self) -> None:
        # Recreate schema per test so each unit case starts from a clean slate.
        self.Base.metadata.drop_all(bind=self.engine)
        self.Base.metadata.create_all(bind=self.engine)

    def test_evaluation_service_reports_syntax_error_context(self) -> None:
        # The evaluator should surface syntax mistakes before any sandbox
        # execution and include enough context for hinting/UI feedback.
        from app.services.evaluation import EvaluationService

        service = EvaluationService(executor=None)
        result = service.evaluate(
            code="def add_numbers(a, b):\n    return a + \n",
            function_name="add_numbers",
            test_cases=[([1, 2], 3)],
        )

        self.assertEqual(result.failure_category, "SyntaxError")
        self.assertEqual(result.error_line, 2)
        self.assertEqual(result.error_excerpt, "    return a +")

    def test_progress_service_unlocks_answer_key_after_threshold(self) -> None:
        # Repeated valid failed submits should advance durable progress and
        # eventually unlock the answer key.
        from app.models import UserProblemProgress
        from app.services.progress import ProgressService

        service = ProgressService()
        progress = UserProblemProgress(
            user_id=1,
            problem_id=1,
            valid_failed_attempts=0,
            answer_key_unlocked=False,
            unlocked_stage=0,
            completed=False,
        )

        for _ in range(3):
            service.apply_submission_outcome(
                progress=progress,
                execution_type="Submit",
                result="Fail",
                failure_category="IncorrectOutput",
                valid_attempt=True,
            )

        self.assertEqual(progress.valid_failed_attempts, 3)
        self.assertTrue(progress.answer_key_unlocked)
        self.assertEqual(progress.unlocked_stage, 1)
        self.assertEqual(service.get_unlocked_stages(progress), {1})

    def test_get_unlocked_stages_fast_tracks_syntax_failures(self) -> None:
        # Syntax mistakes skip directly to the syntactic hint even before the
        # student accumulates normal failed-attempt thresholds.
        from app.models import UserProblemProgress
        from app.services.progress import ProgressService

        service = ProgressService()
        progress = UserProblemProgress(
            user_id=1,
            problem_id=1,
            valid_failed_attempts=0,
            answer_key_unlocked=False,
            unlocked_stage=3,
            completed=False,
            last_failure_category="SyntaxError",
        )

        unlocked = service.get_unlocked_stages(progress)
        self.assertEqual(unlocked, {3})

    def test_infer_needed_stage_defaults_incorrect_output_to_conceptual(self) -> None:
        from app.services.progress import ProgressService

        service = ProgressService()
        stage = service.infer_needed_stage(
            failure_category="IncorrectOutput",
            code="def is_even(n):\n    return n % 2 == 3\n",
        )
        self.assertEqual(stage, 1)

    def test_infer_needed_stage_marks_simple_wrong_return_as_conceptual(self) -> None:
        from app.services.progress import ProgressService

        service = ProgressService()
        stage = service.infer_needed_stage(
            failure_category="IncorrectOutput",
            code="def is_even(n):\n    return n + 2\n",
        )
        self.assertEqual(stage, 1)

    def test_hint_sanitizer_rewrites_meta_fallback_into_plain_hint(self) -> None:
        from app.models import Problem, UserProblemProgress
        from app.services.hints import BaseHintService, HintContext

        class StubHintService(BaseHintService):
            def generate_hint(self, *, stage: int, context: HintContext) -> str:
                return ""

        service = StubHintService()
        context = HintContext(
            problem=Problem(title="Is Even Number", prompt="Write is_even.", function_name="is_even"),
            progress=UserProblemProgress(),
            latest_submission=None,
        )

        hint = service._sanitize_generated_hint(
            stage=2,
            hint="Use return n % 2 == 0.",
            context=context,
        )

        self.assertNotIn("This strategic hint should", hint)
        self.assertIn("wrong relationship", hint)

    def test_completed_problem_hides_previously_unlocked_hints(self) -> None:
        # Passing a problem should return the hint panel to its normal locked
        # state even if the learner had unlocked hints earlier.
        from app.models import UserProblemProgress
        from app.services.progress import ProgressService

        service = ProgressService()
        progress = UserProblemProgress(
            user_id=1,
            problem_id=1,
            valid_failed_attempts=3,
            answer_key_unlocked=False,
            unlocked_stage=3,
            completed=True,
            last_failure_category="IncorrectOutput",
        )

        unlocked = service.get_unlocked_stages(progress)
        self.assertEqual(unlocked, set())

    def test_problem_payload_validation_rejects_invalid_difficulty(self) -> None:
        # Upload payload validation is a unit concern too because bad author
        # data should fail before it ever reaches persistence.
        from pydantic import ValidationError

        from app.schemas import ProblemUploadPayload

        with self.assertRaises(ValidationError):
            ProblemUploadPayload.model_validate(
                {
                    "problem_id": "bad_problem",
                    "title": "Bad Problem",
                    "prompt": "This should fail validation.",
                    "difficulty": "Beginner",
                    "function_name": "bad_problem",
                    "test_cases": [{"input": [1], "expected": 1}],
                }
            )

    def test_persist_problem_stores_custom_problem(self) -> None:
        # Persisting a valid author problem should write the core metadata in a
        # shape the rest of the app can query later.
        from app.models import Problem
        from app.schemas import ProblemUploadPayload
        from app.services.bootstrap import persist_problem

        db = self.SessionLocal()
        try:
            payload = ProblemUploadPayload.model_validate(
                {
                    "problem_id": "unit_problem",
                    "title": "Unit Problem",
                    "prompt": "Return n plus one.",
                    "difficulty": "Easy",
                    "function_name": "plus_one",
                    "starter_code": "def plus_one(n):\n    pass\n",
                    "example_cases": [{"input": [1], "expected": 2}],
                    "test_cases": [{"input": [4], "expected": 5}],
                }
            )
            persist_problem(db=db, payload=payload, source="author", author_id=2)
            db.commit()

            stored = db.query(Problem).filter(Problem.problem_id == "unit_problem").first()
            self.assertIsNotNone(stored)
            self.assertEqual(stored.source, "author")
            self.assertEqual(stored.difficulty, "Easy")
            self.assertEqual(stored.function_name, "plus_one")
        finally:
            db.close()

    def test_replace_problem_contents_overwrites_existing_problem_data(self) -> None:
        # Updating an authored problem should replace child records so the
        # stored JSON-backed content matches the latest upload exactly.
        from app.models import ExampleCase, Problem, TestCase
        from app.schemas import ProblemUploadPayload
        from app.services.bootstrap import persist_problem, replace_problem_contents

        db = self.SessionLocal()
        try:
            original_payload = ProblemUploadPayload.model_validate(
                {
                    "problem_id": "replace_problem",
                    "title": "Original Problem",
                    "prompt": "Return n plus one.",
                    "difficulty": "Easy",
                    "function_name": "plus_one",
                    "starter_code": "def plus_one(n):\n    pass\n",
                    "example_cases": [{"input": [1], "expected": 2}],
                    "test_cases": [{"input": [4], "expected": 5}],
                }
            )
            persist_problem(db=db, payload=original_payload, source="author", author_id=2)
            db.commit()

            stored = db.query(Problem).filter(Problem.problem_id == "replace_problem").first()
            self.assertIsNotNone(stored)

            updated_payload = ProblemUploadPayload.model_validate(
                {
                    "problem_id": "replace_problem",
                    "title": "Updated Problem",
                    "prompt": "Return n plus two.",
                    "difficulty": "Medium",
                    "function_name": "plus_two",
                    "starter_code": "def plus_two(n):\n    pass\n",
                    "example_cases": [{"input": [2], "expected": 4}],
                    "test_cases": [{"input": [5], "expected": 7}],
                }
            )
            replace_problem_contents(db=db, problem=stored, payload=updated_payload)
            db.commit()

            refreshed = db.query(Problem).filter(Problem.problem_id == "replace_problem").first()
            self.assertIsNotNone(refreshed)
            self.assertEqual(refreshed.title, "Updated Problem")
            self.assertEqual(refreshed.prompt, "Return n plus two.")
            self.assertEqual(refreshed.difficulty, "Medium")
            self.assertEqual(refreshed.function_name, "plus_two")

            example_cases = db.query(ExampleCase).filter(ExampleCase.problem_id == refreshed.id).all()
            test_cases = db.query(TestCase).filter(TestCase.problem_id == refreshed.id).all()
            self.assertEqual(len(example_cases), 1)
            self.assertEqual(len(test_cases), 1)
            self.assertIn("4", example_cases[0].expected_json)
            self.assertIn("7", test_cases[0].expected_json)
        finally:
            db.close()

    def test_hint_cache_keeps_revealed_hints_visible_across_submissions(self) -> None:
        # Once a learner reveals a hint for a problem, it should remain
        # visible even after later submissions until the problem is reset.
        from datetime import datetime, timedelta

        from app.models import GeneratedHint, Submission
        from app.services.hints import OllamaHintService

        service = OllamaHintService()
        older_submission = Submission(id=10, user_id=1, problem_id=1, execution_type="Submit", code="x", timed_mode=False, result="Fail", failure_category="IncorrectOutput", feedback="older")
        latest_submission = Submission(id=11, user_id=1, problem_id=1, execution_type="Submit", code="y", timed_mode=False, result="Fail", failure_category="IncorrectOutput", feedback="latest")

        cached_hints = [
            GeneratedHint(
                id=1,
                user_id=1,
                problem_id=1,
                submission_id=older_submission.id,
                stage=1,
                content="Older conceptual hint",
                created_at=datetime.utcnow() - timedelta(minutes=2),
            ),
            GeneratedHint(
                id=2,
                user_id=1,
                problem_id=1,
                submission_id=latest_submission.id,
                stage=2,
                content="Latest strategic hint",
                created_at=datetime.utcnow() - timedelta(minutes=1),
            ),
        ]

        generated = service.get_cached_hints(
            cached_hints=cached_hints,
            unlocked_stages={1, 2},
            latest_submission=latest_submission,
        )

        self.assertEqual(generated[1], "Older conceptual hint")
        self.assertEqual(generated[2], "Latest strategic hint")

    def test_conceptual_hint_sanitizer_removes_exact_solution_rule(self) -> None:
        # Conceptual hints should not leak the solved condition for a simple
        # beginner problem.
        from app.models import Problem, UserProblemProgress
        from app.services.hints import HintContext, OllamaHintService

        service = OllamaHintService()
        context = HintContext(
            problem=Problem(
                id=1,
                problem_id="is_even_number",
                title="Is Even Number",
                prompt="Write a function named is_even(n) that returns True when n is even and False otherwise.",
                difficulty="Easy",
                function_name="is_even",
                source="starter",
                is_active=True,
                is_deleted=False,
            ),
            progress=UserProblemProgress(
                user_id=1,
                problem_id=1,
                valid_failed_attempts=1,
                answer_key_unlocked=False,
                unlocked_stage=1,
                completed=False,
            ),
            latest_submission=None,
        )

        sanitized = service._sanitize_generated_hint(
            stage=1,
            hint="Ensure that the expression n % 2 == 0 is used to check if n is even, and include a return statement.",
            context=context,
        )

        self.assertNotIn("% 2", sanitized)
        self.assertNotIn("== 0", sanitized)
        self.assertNotIn("return statement", sanitized.lower())


if __name__ == "__main__":
    unittest.main()
