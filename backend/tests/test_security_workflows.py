import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class SecurityWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Security tests use the same app stack but focus only on rejection of
        # unsafe or unauthorized requests.
        cls.temp_dir = TemporaryDirectory()
        db_path = Path(cls.temp_dir.name) / "security_test.db"
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
        from app.main import app
        from app.rate_limit import rate_limiter
        from app.services.bootstrap import seed_default_users, seed_starter_problems

        cls.Base = Base
        cls.SessionLocal = SessionLocal
        cls.engine = engine
        cls.rate_limiter = rate_limiter
        cls.seed_default_users = seed_default_users
        cls.seed_starter_problems = seed_starter_problems
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()
        os.environ.pop("CODESOCRAT_DATABASE_URL", None)

    def setUp(self) -> None:
        # Reset rate-limiter state and database contents so security tests do
        # not interfere with one another.
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

    def _login(self, email: str, password: str) -> None:
        response = self.client.post("/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200)

    def _csrf_headers(self) -> dict[str, str]:
        csrf = self.client.cookies.get("codesocrat_csrf")
        self.assertTrue(csrf)
        return {"X-CSRF-Token": csrf}

    def test_missing_csrf_header_is_rejected(self) -> None:
        # Protected write routes should fail even for authenticated users when
        # the CSRF token is missing.
        self._login("student@codesocrat.dev", "studentpass")
        response = self.client.post(
            "/submit",
            json={
                "problem_id": "sum_two_numbers",
                "code": "def add_numbers(a, b):\n    return a + b\n",
                "timed_mode": False,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "CSRF validation failed.")

    def test_login_rate_limit_blocks_repeated_bad_attempts(self) -> None:
        # Brute-force style login retries should eventually trigger the public
        # login rate limiter.
        for _ in range(5):
            response = self.client.post("/auth/login", json={"email": "student@codesocrat.dev", "password": "wrongpass"})
            self.assertEqual(response.status_code, 401)

        limited = self.client.post("/auth/login", json={"email": "student@codesocrat.dev", "password": "wrongpass"})
        self.assertEqual(limited.status_code, 429)
        self.assertIn("Retry-After", limited.headers)

    def test_login_rejects_unexpected_fields(self) -> None:
        # Strict request schemas help prevent clients from smuggling extra
        # fields into auth requests.
        response = self.client.post(
            "/auth/login",
            json={"email": "student@codesocrat.dev", "password": "studentpass", "role": "Author"},
        )
        self.assertEqual(response.status_code, 422)

    def test_submission_rejects_invalid_problem_id_shape(self) -> None:
        # Path-like or malformed problem identifiers should never be accepted
        # into the submission pipeline.
        self._login("student@codesocrat.dev", "studentpass")
        response = self.client.post(
            "/submit",
            headers=self._csrf_headers(),
            json={"problem_id": "../bad", "code": "print(1)", "timed_mode": False},
        )
        self.assertEqual(response.status_code, 422)

    def test_author_cannot_modify_starter_problem(self) -> None:
        # Starter problems are intentionally immutable even for authors so the
        # bundled curriculum stays protected.
        self._login("author@codesocrat.dev", "authorpass")
        response = self.client.post(
            "/author/problems/sum_two_numbers/disable",
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
