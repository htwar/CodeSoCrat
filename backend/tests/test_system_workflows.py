import json
import os
import importlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class SystemWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # System workflow tests still isolate their data, but they exercise the
        # real FastAPI app wiring from request to persistence.
        cls.temp_dir = TemporaryDirectory()
        db_path = Path(cls.temp_dir.name) / "system_test.db"
        os.environ["CODESOCRAT_DATABASE_URL"] = f"sqlite:///{db_path}"

        from app.config import settings

        settings.database_url = os.environ["CODESOCRAT_DATABASE_URL"]
        settings.rate_limit_window_seconds = 60
        settings.rate_limit_ip_public = 60
        settings.rate_limit_ip_authenticated = 120
        settings.rate_limit_user_authenticated = 90
        settings.login_rate_limit_ip = 10
        settings.login_rate_limit_user = 5
        settings.google_client_id = "system-test-google-client-id"

        import app.database as database_module
        import app.main as main_module
        import app.models as models_module
        import app.rate_limit as rate_limit_module

        database_module = importlib.reload(database_module)
        models_module = importlib.reload(models_module)
        rate_limit_module = importlib.reload(rate_limit_module)
        main_module = importlib.reload(main_module)

        from app.database import Base, SessionLocal, engine
        import app.main as main_module
        from app.main import app, evaluation_service, hint_service
        from app.rate_limit import rate_limiter
        from app.services.bootstrap import seed_default_users, seed_starter_problems
        from app.services.evaluation import EvaluationResult

        cls.Base = Base
        cls.SessionLocal = SessionLocal
        cls.engine = engine
        cls.main_module = main_module
        cls.seed_default_users = seed_default_users
        cls.seed_starter_problems = seed_starter_problems
        cls.rate_limiter = rate_limiter

        class FakeExecutor:
            def run(self, *, code: str, function_name: str, test_cases):
                if "return a - b" in code:
                    return EvaluationResult(
                        result="Fail",
                        failure_category="IncorrectOutput",
                        runtime_ms=11,
                        memory_mb=32,
                        feedback="Test case 1 failed: expected 5, got -1.",
                        valid_attempt=True,
                    )
                return EvaluationResult(
                    result="Pass",
                    failure_category=None,
                    runtime_ms=9,
                    memory_mb=32,
                    feedback="All test cases passed.",
                    valid_attempt=True,
                )

        class FakeHintService:
            def generate_hint(self, *, stage, context):
                return f"system-hint-stage-{stage}"

        evaluation_service.executor = FakeExecutor()
        hint_service.generate_hint = FakeHintService().generate_hint
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        cls.temp_dir.cleanup()
        os.environ.pop("CODESOCRAT_DATABASE_URL", None)

    def setUp(self) -> None:
        # Re-seed starter content and demo users before each workflow so the
        # tests reflect a predictable fresh deployment state.
        self.rate_limiter._buckets.clear()
        self.client.cookies.clear()
        self.Base.metadata.drop_all(bind=self.engine)
        self.Base.metadata.create_all(bind=self.engine)
        db = self.SessionLocal()
        try:
            type(self).seed_default_users(db)
            type(self).seed_starter_problems(db)
        finally:
            db.close()

    def _login(self, email: str, password: str) -> dict:
        # Shared login helper keeps the workflow tests focused on system
        # behavior rather than repeated request boilerplate.
        response = self.client.post("/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _csrf_headers(self) -> dict[str, str]:
        csrf = self.client.cookies.get("codesocrat_csrf")
        self.assertTrue(csrf)
        return {"X-CSRF-Token": csrf}

    def test_student_can_complete_problem_end_to_end(self) -> None:
        # Baseline learner journey: authenticate, load problems, and submit a
        # correct solution through the normal grading path.
        session = self._login("student@codesocrat.dev", "studentpass")
        self.assertEqual(session["role"], "Student")

        problems = self.client.get("/problems")
        self.assertEqual(problems.status_code, 200)
        self.assertTrue(problems.json()["problems"])

        submit = self.client.post(
            "/submit",
            headers=self._csrf_headers(),
            json={
                "problem_id": "sum_two_numbers",
                "code": "def add_numbers(a, b):\n    return a + b\n",
                "timed_mode": False,
            },
        )
        self.assertEqual(submit.status_code, 200)
        payload = submit.json()
        self.assertEqual(payload["result"], "Pass")
        self.assertEqual(payload["execution_type"], "Submit")

    def test_run_then_submit_progression_matches_system_rules(self) -> None:
        # This workflow distinguishes practice runs from tracked submits and
        # confirms the hint/answer-key progression rules at system level.
        self._login("student@codesocrat.dev", "studentpass")

        run_response = self.client.post(
            "/run",
            headers=self._csrf_headers(),
            json={
                "problem_id": "sum_two_numbers",
                "code": "def add_numbers(a, b):\n    return a - b\n",
                "timed_mode": False,
            },
        )
        self.assertEqual(run_response.status_code, 200)
        self.assertEqual(run_response.json()["execution_type"], "Run")
        self.assertEqual(run_response.json()["valid_failed_attempts"], 0)

        for _ in range(4):
            submit_response = self.client.post(
                "/submit",
                headers=self._csrf_headers(),
                json={
                    "problem_id": "sum_two_numbers",
                    "code": "def add_numbers(a, b):\n    return a - b\n",
                    "timed_mode": False,
                },
            )
            self.assertEqual(submit_response.status_code, 200)

        hints = self.client.get("/hints", params={"problem_id": "sum_two_numbers", "stage": 1})
        self.assertEqual(hints.status_code, 200)
        self.assertEqual(hints.json()["conceptual"], "system-hint-stage-1")

        answer_key = self.client.get("/answer-key", params={"problem_id": "sum_two_numbers"})
        self.assertEqual(answer_key.status_code, 200)
        self.assertTrue(answer_key.json()["unlocked"])

    def test_timed_submission_uses_same_submission_pipeline(self) -> None:
        # Timed mode should not invent a separate grading path; it should only
        # mark the stored submission as timed when the timer is active.
        self._login("student@codesocrat.dev", "studentpass")

        arm = self.client.post("/progress/sum_two_numbers/timed-mode", headers=self._csrf_headers())
        self.assertEqual(arm.status_code, 200)
        start = self.client.post("/progress/sum_two_numbers/timed-mode/start", headers=self._csrf_headers())
        self.assertEqual(start.status_code, 200)

        timed_submit = self.client.post(
            "/submit",
            headers=self._csrf_headers(),
            json={
                "problem_id": "sum_two_numbers",
                "code": "def add_numbers(a, b):\n    return a + b\n",
                "timed_mode": True,
            },
        )
        self.assertEqual(timed_submit.status_code, 200)
        payload = timed_submit.json()
        self.assertEqual(payload["result"], "Pass")
        self.assertEqual(payload["execution_type"], "Submit")

        db = self.SessionLocal()
        try:
            from app.models import Submission

            stored = db.query(Submission).order_by(Submission.id.desc()).first()
            self.assertIsNotNone(stored)
            self.assertTrue(stored.timed_mode)
        finally:
            db.close()

    def test_author_problem_lifecycle_affects_student_visibility(self) -> None:
        # Author tools are only useful if dashboard actions also change what a
        # student can see in the main problem list.
        self._login("author@codesocrat.dev", "authorpass")

        upload = self.client.post(
            "/author/problems/upload-file",
            headers=self._csrf_headers(),
            files={
                "file": (
                    "system_problem.json",
                    json.dumps(
                        {
                            "problem_id": "system_test_problem",
                            "title": "System Test Problem",
                            "prompt": "Return the number plus one.",
                            "difficulty": "Easy",
                            "function_name": "plus_one",
                            "starter_code": "def plus_one(n):\n    pass\n",
                            "example_cases": [{"input": [1], "expected": 2}],
                            "test_cases": [{"input": [3], "expected": 4}],
                        }
                    ),
                    "application/json",
                )
            },
        )
        self.assertEqual(upload.status_code, 200)

        listing = self.client.get("/author/problems", params={"source": "author"})
        self.assertEqual(listing.status_code, 200)
        self.assertTrue(any(item["problem_id"] == "system_test_problem" for item in listing.json()["problems"]))

        disable = self.client.post(
            "/author/problems/system_test_problem/disable",
            headers=self._csrf_headers(),
        )
        self.assertEqual(disable.status_code, 200)
        self.assertFalse(disable.json()["is_active"])

        student_client = TestClient(type(self).main_module.app)
        login = student_client.post("/auth/login", json={"email": "student@codesocrat.dev", "password": "studentpass"})
        self.assertEqual(login.status_code, 200)
        visible = student_client.get("/problems")
        self.assertFalse(any(item["problem_id"] == "system_test_problem" for item in visible.json()["problems"]))

    def test_google_config_endpoint_reports_enabled_state(self) -> None:
        # The frontend uses this endpoint to decide whether to render the
        # Google sign-in area at all.
        response = self.client.get("/auth/google/config")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["client_id"], "system-test-google-client-id")


if __name__ == "__main__":
    unittest.main()
