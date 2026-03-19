import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class BackendFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = TemporaryDirectory()
        db_path = Path(cls.temp_dir.name) / "test.db"
        os.environ["CODESOCRAT_DATABASE_URL"] = f"sqlite:///{db_path}"

        from app.config import settings

        settings.database_url = os.environ["CODESOCRAT_DATABASE_URL"]
        settings.rate_limit_window_seconds = 60
        settings.rate_limit_ip_public = 60
        settings.rate_limit_ip_authenticated = 120
        settings.rate_limit_user_authenticated = 90
        settings.login_rate_limit_ip = 10
        settings.login_rate_limit_user = 5

        from app.database import Base, SessionLocal, engine
        from app.main import app, evaluation_service, hint_service
        from app.rate_limit import rate_limiter
        from app.services.evaluation import EvaluationResult
        from app.services.bootstrap import seed_default_users, seed_starter_problems

        cls.Base = Base
        cls.SessionLocal = SessionLocal
        cls.engine = engine
        cls.seed_default_users = seed_default_users
        cls.seed_starter_problems = seed_starter_problems
        cls.rate_limiter = rate_limiter

        class FakeExecutor:
            def run(self, *, code: str, function_name: str, test_cases):
                if "return a - b" in code:
                    return EvaluationResult(
                        result="Fail",
                        failure_category="IncorrectOutput",
                        runtime_ms=12,
                        memory_mb=32,
                        feedback="Test case 1 failed: expected 5, got -1.",
                        valid_attempt=True,
                    )
                if "raise ValueError" in code:
                    return EvaluationResult(
                        result="Fail",
                        failure_category="RuntimeError",
                        runtime_ms=8,
                        memory_mb=32,
                        feedback="Runtime error occurred inside the Docker sandbox.",
                        valid_attempt=False,
                    )
                return EvaluationResult(
                    result="Pass",
                    failure_category=None,
                    runtime_ms=10,
                    memory_mb=32,
                    feedback="All test cases passed.",
                    valid_attempt=True,
                )

        class FakeHintService:
            def generate_hint(self, *, stage, context):
                return f"generated-stage-{stage}"

        evaluation_service.executor = FakeExecutor()
        hint_service.generate_hint = FakeHintService().generate_hint
        cls.client = TestClient(app)

    def setUp(self) -> None:
        self.rate_limiter._buckets.clear()
        self.Base.metadata.drop_all(bind=self.engine)
        self.Base.metadata.create_all(bind=self.engine)
        db = self.SessionLocal()
        try:
            type(self).seed_default_users(db)
            type(self).seed_starter_problems(db)
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()
        os.environ.pop("CODESOCRAT_DATABASE_URL", None)

    def _login(self, email: str, password: str) -> str:
        response = self.client.post("/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200)
        return response.json()["token"]

    def test_student_submission_unlocks_hint(self) -> None:
        token = self._login("student@codesocrat.dev", "studentpass")
        headers = {"Authorization": f"Bearer {token}"}

        problems = self.client.get("/problems", headers=headers)
        self.assertEqual(problems.status_code, 200)
        self.assertTrue(problems.json()["problems"])

        response = self.client.post(
            "/submissions",
            headers=headers,
            json={
                "problem_id": "sum_two_numbers",
                "code": "def add_numbers(a, b):\n    return a - b\n",
                "timed_mode": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"], "Fail")
        self.assertEqual(payload["hint_stage_unlocked"], 1)

        hints = self.client.get("/hints", headers=headers, params={"problem_id": "sum_two_numbers"})
        self.assertEqual(hints.status_code, 200)
        self.assertEqual(hints.json()["conceptual"], "generated-stage-1")

    def test_syntax_failure_unlocks_only_syntactic_hint(self) -> None:
        token = self._login("student@codesocrat.dev", "studentpass")
        headers = {"Authorization": f"Bearer {token}"}

        response = self.client.post(
            "/submissions",
            headers=headers,
            json={
                "problem_id": "sum_two_numbers",
                "code": "def add_numbers(a, b)\n    return a + b\n",
                "timed_mode": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"], "Fail")
        self.assertEqual(payload["failure_category"], "SyntaxError")
        self.assertEqual(payload["hint_stage_unlocked"], 3)

        hints = self.client.get("/hints", headers=headers, params={"problem_id": "sum_two_numbers"})
        self.assertEqual(hints.status_code, 200)
        self.assertIsNone(hints.json()["conceptual"])
        self.assertIsNone(hints.json()["strategic"])
        self.assertEqual(hints.json()["syntactic"], "generated-stage-3")

    def test_student_submission_passes(self) -> None:
        token = self._login("student@codesocrat.dev", "studentpass")
        headers = {"Authorization": f"Bearer {token}"}

        response = self.client.post(
            "/submissions",
            headers=headers,
            json={
                "problem_id": "sum_two_numbers",
                "code": "def add_numbers(a, b):\n    return a + b\n",
                "timed_mode": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"], "Pass")
        self.assertIsNone(payload["failure_category"])

    def test_author_uploads_problem(self) -> None:
        token = self._login("author@codesocrat.dev", "authorpass")
        headers = {"Authorization": f"Bearer {token}"}

        response = self.client.post(
            "/author/problems/upload",
            headers=headers,
            json={
                "problem_id": "double_number",
                "title": "Double Number",
                "prompt": "Return twice the input number.",
                "difficulty": "Easy",
                "function_name": "double_number",
                "starter_code": "def double_number(n):\n    pass\n",
                "test_cases": [{"input": [2], "expected": 4}],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["success"], True)

    def test_author_upload_validation_rejects_invalid_difficulty(self) -> None:
        token = self._login("author@codesocrat.dev", "authorpass")
        headers = {"Authorization": f"Bearer {token}"}

        response = self.client.post(
            "/author/problems/upload",
            headers=headers,
            json={
                "problem_id": "bad-problem",
                "title": "Bad Problem",
                "prompt": "Invalid difficulty.",
                "difficulty": "Beginner",
                "function_name": "bad_problem",
                "test_cases": [{"input": [1], "expected": 1}],
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_login_rejects_unexpected_fields(self) -> None:
        response = self.client.post(
            "/auth/login",
            json={"email": "student@codesocrat.dev", "password": "studentpass", "role": "Author"},
        )
        self.assertEqual(response.status_code, 422)

    def test_submission_rejects_invalid_problem_id_shape(self) -> None:
        token = self._login("student@codesocrat.dev", "studentpass")
        headers = {"Authorization": f"Bearer {token}"}
        response = self.client.post(
            "/submissions",
            headers=headers,
            json={"problem_id": "../bad", "code": "print(1)", "timed_mode": False},
        )
        self.assertEqual(response.status_code, 422)

    def test_login_rate_limit_returns_429(self) -> None:
        for _ in range(5):
            response = self.client.post("/auth/login", json={"email": "student@codesocrat.dev", "password": "wrongpass"})
            self.assertEqual(response.status_code, 401)

        limited = self.client.post("/auth/login", json={"email": "student@codesocrat.dev", "password": "wrongpass"})
        self.assertEqual(limited.status_code, 429)
        self.assertIn("Retry-After", limited.headers)


if __name__ == "__main__":
    unittest.main()
