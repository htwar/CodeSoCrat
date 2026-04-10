import json
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
        # Tests run against an isolated SQLite database so they never touch a
        # developer's local app data.
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
        settings.google_client_id = "test-google-client-id"

        from app.database import Base, SessionLocal, engine
        import app.main as main_module
        from app.main import app, evaluation_service, hint_service
        from app.rate_limit import rate_limiter
        from app.services.evaluation import EvaluationResult
        from app.services.bootstrap import seed_default_users, seed_starter_problems

        cls.Base = Base
        cls.SessionLocal = SessionLocal
        cls.engine = engine
        cls.main_module = main_module
        cls.seed_default_users = seed_default_users
        cls.seed_starter_problems = seed_starter_problems
        cls.rate_limiter = rate_limiter

        class FakeExecutor:
            # Keep the API tests deterministic by replacing real Docker
            # execution with a few recognizable code-pattern outcomes.
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
                if "return n - 2 == 0" in code:
                    return EvaluationResult(
                        result="Fail",
                        failure_category="IncorrectOutput",
                        runtime_ms=9,
                        memory_mb=32,
                        feedback="Test case 2 failed: expected True, got False.",
                        valid_attempt=True,
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
            # Replace model-generated hints with a predictable test string.
            def generate_hint(self, *, stage, context):
                return f"generated-stage-{stage}"

        evaluation_service.executor = FakeExecutor()
        hint_service.generate_hint = FakeHintService().generate_hint
        cls.client = TestClient(app)

    def setUp(self) -> None:
        # Re-seed before each test so cases stay independent.
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

    @classmethod
    def tearDownClass(cls) -> None:
        # Remove the temporary database directory once the suite finishes.
        cls.temp_dir.cleanup()
        os.environ.pop("CODESOCRAT_DATABASE_URL", None)

    def _login(self, email: str, password: str) -> dict:
        # Helper methods keep the tests focused on behavior instead of request
        # plumbing.
        response = self.client.post("/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200)
        self.assertIn("codesocrat_session", response.cookies)
        self.assertIn("codesocrat_csrf", response.cookies)
        return response.json()

    def _csrf_headers(self) -> dict[str, str]:
        # Mirror the frontend's CSRF header format for protected routes.
        csrf = self.client.cookies.get("codesocrat_csrf")
        self.assertTrue(csrf)
        return {"X-CSRF-Token": csrf}

    def _submit(self, problem_id: str, code: str):
        # Convenience wrapper for the full submission endpoint.
        return self.client.post(
            "/submit",
            headers=self._csrf_headers(),
            json={
                "problem_id": problem_id,
                "code": code,
                "timed_mode": False,
            },
        )

    def _run(self, problem_id: str, code: str):
        # Convenience wrapper for practice-mode execution.
        return self.client.post(
            "/run",
            headers=self._csrf_headers(),
            json={
                "problem_id": problem_id,
                "code": code,
                "timed_mode": False,
            },
        )

    def test_register_creates_student_account(self) -> None:
        # Local self-registration should always create the lower-privilege
        # Student role and establish a cookie session immediately.
        response = self.client.post(
            "/auth/register",
            json={
                "email": "new.student@example.com",
                "password": "strongpass123",
                "confirm_password": "strongpass123",
            },
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["role"], "Student")
        self.assertEqual(payload["email"], "new.student@example.com")
        self.assertEqual(payload["auth_provider"], "local")
        self.assertIn("codesocrat_session", response.cookies)
        self.assertIn("codesocrat_csrf", response.cookies)

        login = self.client.post(
            "/auth/login",
            json={"email": "new.student@example.com", "password": "strongpass123"},
        )
        self.assertEqual(login.status_code, 200)

        db = self.SessionLocal()
        try:
            from app.models import User

            user = db.query(User).filter(User.email == "new.student@example.com").first()
            self.assertIsNotNone(user)
            self.assertTrue(user.password_hash.startswith("pbkdf2_sha256:"))
        finally:
            db.close()

    def test_register_rejects_duplicate_email(self) -> None:
        # Duplicate identity creation should be blocked before a second account
        # can be created with the same email.
        response = self.client.post(
            "/auth/register",
            json={
                "email": "student@codesocrat.dev",
                "password": "strongpass123",
                "confirm_password": "strongpass123",
            },
        )
        self.assertEqual(response.status_code, 409)

    def test_login_upgrades_legacy_password_hash(self) -> None:
        # Older unsalted SHA-256 hashes should still verify once, then be
        # replaced with the newer salted format after a successful login.
        legacy_hash = "0c706cd9e9c31663612230ff8d74850ca2efdce103dedc77cdd66bf4cfd192ce"
        db = self.SessionLocal()
        try:
            from app.models import User

            user = db.query(User).filter(User.email == "student@codesocrat.dev").first()
            self.assertIsNotNone(user)
            user.password_hash = legacy_hash
            db.commit()
        finally:
            db.close()

        response = self.client.post(
            "/auth/login",
            json={"email": "student@codesocrat.dev", "password": "studentpass"},
        )
        self.assertEqual(response.status_code, 200)

        db = self.SessionLocal()
        try:
            from app.models import User

            user = db.query(User).filter(User.email == "student@codesocrat.dev").first()
            self.assertIsNotNone(user)
            self.assertNotEqual(user.password_hash, legacy_hash)
            self.assertTrue(user.password_hash.startswith("pbkdf2_sha256:"))
        finally:
            db.close()

    def test_session_endpoint_uses_cookie_auth(self) -> None:
        # Once logged in, the session endpoint should be able to rebuild the
        # user identity from the signed cookie alone.
        self._login("student@codesocrat.dev", "studentpass")
        response = self.client.get("/auth/session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "student@codesocrat.dev")

    def test_logout_clears_cookie_session(self) -> None:
        # Logging out should invalidate the current session so subsequent
        # session lookups return unauthorized.
        self._login("student@codesocrat.dev", "studentpass")
        logout = self.client.post("/auth/logout", headers=self._csrf_headers())
        self.assertEqual(logout.status_code, 204)

        after_logout = self.client.get("/auth/session")
        self.assertEqual(after_logout.status_code, 401)

    def test_logout_resets_active_timed_mode_state(self) -> None:
        self._login("student@codesocrat.dev", "studentpass")

        armed = self.client.post("/progress/sum_two_numbers/timed-mode", headers=self._csrf_headers())
        self.assertEqual(armed.status_code, 200)
        started = self.client.post("/progress/sum_two_numbers/timed-mode/start", headers=self._csrf_headers())
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json()["timed_mode_status"], "running")

        logout = self.client.post("/auth/logout", headers=self._csrf_headers())
        self.assertEqual(logout.status_code, 204)

        self._login("student@codesocrat.dev", "studentpass")
        progress = self.client.get("/progress/sum_two_numbers")
        self.assertEqual(progress.status_code, 200)
        self.assertEqual(progress.json()["timed_mode_status"], "off")
        self.assertFalse(progress.json()["timed_mode_enabled"])

    def test_state_change_without_csrf_is_rejected(self) -> None:
        # Authenticated users still need a matching CSRF token for protected
        # state-changing operations.
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

    def test_student_submission_unlocks_hint(self) -> None:
        # A valid failed submit should create durable progress and unlock the
        # first hint stage, while hidden grading tests stay hidden.
        self._login("student@codesocrat.dev", "studentpass")

        problems = self.client.get("/problems")
        self.assertEqual(problems.status_code, 200)
        self.assertTrue(problems.json()["problems"])
        first_problem = problems.json()["problems"][0]
        self.assertIn("example_cases", first_problem)
        self.assertNotIn("test_cases", first_problem)

        response = self._submit("sum_two_numbers", "def add_numbers(a, b):\n    return a - b\n")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"], "Fail")
        self.assertEqual(payload["execution_type"], "Submit")
        self.assertEqual(payload["hint_stage_unlocked"], 1)

        hints = self.client.get("/hints", params={"problem_id": "sum_two_numbers"})
        self.assertEqual(hints.status_code, 200)
        self.assertEqual(hints.json()["highlight_stage"], 1)
        self.assertEqual(hints.json()["unlocked_stages"], [1])
        self.assertIsNone(hints.json()["conceptual"])

        unlocked = self.client.get("/hints", params={"problem_id": "sum_two_numbers", "stage": 1})
        self.assertEqual(unlocked.status_code, 200)
        self.assertEqual(unlocked.json()["conceptual"], "generated-stage-1")
        self.assertIsNone(unlocked.json()["strategic"])

        answer_key = self.client.get("/answer-key", params={"problem_id": "sum_two_numbers"})
        self.assertEqual(answer_key.status_code, 200)
        self.assertFalse(answer_key.json()["unlocked"])

    def test_run_does_not_unlock_hints_or_increment_attempts(self) -> None:
        # Practice-mode runs should provide feedback without changing long-term
        # progress or unlocking hints.
        self._login("student@codesocrat.dev", "studentpass")

        response = self._run("sum_two_numbers", "def add_numbers(a, b):\n    return a - b\n")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"], "Fail")
        self.assertEqual(payload["execution_type"], "Run")
        self.assertEqual(payload["valid_failed_attempts"], 0)
        self.assertEqual(payload["hint_stage_unlocked"], 0)
        self.assertFalse(payload["counts_toward_progress"])

        hints = self.client.get("/hints", params={"problem_id": "sum_two_numbers"})
        self.assertEqual(hints.status_code, 403)
        self.assertEqual(hints.json()["detail"], "No hints unlocked yet.")

    def test_answer_key_unlocks_after_four_valid_failed_submits(self) -> None:
        # Repeated valid failed submits should escalate support gradually until
        # the answer key becomes available.
        self._login("student@codesocrat.dev", "studentpass")

        for _ in range(4):
            response = self._submit("sum_two_numbers", "def add_numbers(a, b):\n    return a - b\n")
            self.assertEqual(response.status_code, 200)

        answer_key = self.client.get("/answer-key", params={"problem_id": "sum_two_numbers"})
        self.assertEqual(answer_key.status_code, 200)
        payload = answer_key.json()
        self.assertTrue(payload["unlocked"])
        self.assertIn("def add_numbers", payload["solution_code"])
        self.assertTrue(payload["explanation"])

    def test_hints_reset_to_locked_view_after_problem_is_passed(self) -> None:
        # Once the learner passes a problem, the hint panel should go back to
        # its normal locked state for that solved problem.
        self._login("student@codesocrat.dev", "studentpass")

        failed = self._submit("sum_two_numbers", "def add_numbers(a, b):\n    return a - b\n")
        self.assertEqual(failed.status_code, 200)

        unlocked = self.client.get("/hints", params={"problem_id": "sum_two_numbers", "stage": 1})
        self.assertEqual(unlocked.status_code, 200)
        self.assertEqual(unlocked.json()["conceptual"], "generated-stage-1")

        passed = self._submit("sum_two_numbers", "def add_numbers(a, b):\n    return a + b\n")
        self.assertEqual(passed.status_code, 200)
        self.assertEqual(passed.json()["result"], "Pass")

        hints = self.client.get("/hints", params={"problem_id": "sum_two_numbers"})
        self.assertEqual(hints.status_code, 403)
        self.assertEqual(hints.json()["detail"], "No hints unlocked yet.")

    def test_syntax_failure_unlocks_only_syntactic_hint(self) -> None:
        # Syntax mistakes should route students directly toward syntactic help
        # instead of unlocking conceptual and strategic hints first.
        self._login("student@codesocrat.dev", "studentpass")

        response = self._submit("sum_two_numbers", "def add_numbers(a, b)\n    return a + b\n")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"], "Fail")
        self.assertEqual(payload["failure_category"], "SyntaxError")
        self.assertEqual(payload["hint_stage_unlocked"], 3)

        hints = self.client.get("/hints", params={"problem_id": "sum_two_numbers"})
        self.assertEqual(hints.status_code, 200)
        self.assertEqual(hints.json()["highlight_stage"], 3)
        self.assertEqual(hints.json()["unlocked_stages"], [3])
        self.assertIsNone(hints.json()["conceptual"])
        self.assertIsNone(hints.json()["strategic"])
        self.assertIsNone(hints.json()["syntactic"])

        unlocked = self.client.get("/hints", params={"problem_id": "sum_two_numbers", "stage": 3})
        self.assertEqual(unlocked.status_code, 200)
        self.assertEqual(unlocked.json()["syntactic"], "generated-stage-3")

    def test_syntax_failure_prioritizes_syntactic_hint_even_when_all_stages_are_unlocked(self) -> None:
        # Even after broader hint access exists, a fresh syntax error should
        # still highlight the syntactic hint as the most relevant next step.
        self._login("student@codesocrat.dev", "studentpass")

        for _ in range(3):
            response = self._submit("sum_two_numbers", "def add_numbers(a, b):\n    return a - b\n")
            self.assertEqual(response.status_code, 200)

        syntax_response = self._submit("sum_two_numbers", "def add_numbers(a, b):\n    return a + \n")
        self.assertEqual(syntax_response.status_code, 200)
        self.assertEqual(syntax_response.json()["failure_category"], "SyntaxError")

        hints = self.client.get("/hints", params={"problem_id": "sum_two_numbers"})
        self.assertEqual(hints.status_code, 200)
        self.assertEqual(hints.json()["highlight_stage"], 3)

    def test_evaluation_captures_syntax_error_context(self) -> None:
        # This doubles as a route-independent check that evaluation exposes the
        # metadata the hinting/UI layers rely on.
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

    def test_student_submission_passes(self) -> None:
        # Happy-path submit should return a clean passing payload without any
        # failure category attached.
        self._login("student@codesocrat.dev", "studentpass")

        response = self._submit("sum_two_numbers", "def add_numbers(a, b):\n    return a + b\n")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"], "Pass")
        self.assertEqual(payload["execution_type"], "Submit")
        self.assertIsNone(payload["failure_category"])

    def test_is_even_problem_rejects_weak_false_positive_solution(self) -> None:
        # Hidden tests should catch simplistic solutions that only work for one
        # visible sample-like case.
        self._login("student@codesocrat.dev", "studentpass")

        response = self._submit("is_even_number", "def is_even(n):\n    return n - 2 == 0\n")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"], "Fail")
        self.assertEqual(payload["failure_category"], "IncorrectOutput")

    def test_author_uploads_problem(self) -> None:
        # Authors can create custom problems directly from structured JSON in
        # the dashboard editor flow.
        self._login("author@codesocrat.dev", "authorpass")

        response = self.client.post(
            "/author/problems/upload",
            headers=self._csrf_headers(),
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
        self._login("author@codesocrat.dev", "authorpass")

        response = self.client.post(
            "/author/problems/upload",
            headers=self._csrf_headers(),
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

    def test_author_uploads_problem_file(self) -> None:
        self._login("author@codesocrat.dev", "authorpass")

        response = self.client.post(
            "/author/problems/upload-file",
            headers=self._csrf_headers(),
            files={
                "file": (
                    "file_problem.json",
                    json.dumps(
                        {
                            "problem_id": "square_number",
                            "title": "Square Number",
                            "prompt": "Return the square of the number.",
                            "difficulty": "Easy",
                            "function_name": "square_number",
                            "starter_code": "def square_number(n):\n    pass\n",
                            "test_cases": [{"input": [3], "expected": 9}],
                        }
                    ),
                    "application/json",
                )
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["problem_id"], "square_number")

    def test_google_auth_creates_student_account(self) -> None:
        type(self).main_module.verify_google_id_token = lambda _credential: {
            "sub": "google-sub-1",
            "email": "google.student@example.com",
            "email_verified": "true",
            "name": "Google Student",
            "aud": "test-google-client-id",
        }

        response = self.client.post("/auth/google", json={"credential": "signed-token"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["email"], "google.student@example.com")
        self.assertEqual(payload["role"], "Student")
        self.assertEqual(payload["auth_provider"], "google")
        self.assertEqual(payload["display_name"], "Google Student")

    def test_google_auth_links_existing_local_account(self) -> None:
        type(self).main_module.verify_google_id_token = lambda _credential: {
            "sub": "google-sub-2",
            "email": "student@codesocrat.dev",
            "email_verified": "true",
            "name": "Student Demo",
            "aud": "test-google-client-id",
        }

        response = self.client.post("/auth/google", json={"credential": "signed-token"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["email"], "student@codesocrat.dev")
        self.assertEqual(payload["auth_provider"], "local+google")

    def test_author_can_list_update_disable_enable_and_delete_own_problem(self) -> None:
        self._login("author@codesocrat.dev", "authorpass")

        upload = self.client.post(
            "/author/problems/upload",
            headers=self._csrf_headers(),
            json={
                "problem_id": "triple_number",
                "title": "Triple Number",
                "prompt": "Return three times the number.",
                "difficulty": "Easy",
                "function_name": "triple_number",
                "starter_code": "def triple_number(n):\n    pass\n",
                "example_cases": [{"input": [2], "expected": 6}],
                "test_cases": [{"input": [3], "expected": 9}],
            },
        )
        self.assertEqual(upload.status_code, 200)

        listing = self.client.get("/author/problems", params={"source": "author"})
        self.assertEqual(listing.status_code, 200)
        problems = listing.json()["problems"]
        self.assertTrue(any(problem["problem_id"] == "triple_number" for problem in problems))

        detail = self.client.get("/author/problems/triple_number")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["title"], "Triple Number")

        update = self.client.put(
            "/author/problems/triple_number",
            headers=self._csrf_headers(),
            json={
                "problem_id": "triple_number",
                "title": "Triple Any Number",
                "prompt": "Return three times the provided number.",
                "difficulty": "Easy",
                "function_name": "triple_number",
                "starter_code": "def triple_number(n):\n    return n * 3\n",
                "example_cases": [{"input": [2], "expected": 6}],
                "test_cases": [{"input": [3], "expected": 9}],
            },
        )
        self.assertEqual(update.status_code, 200)

        disable = self.client.post("/author/problems/triple_number/disable", headers=self._csrf_headers())
        self.assertEqual(disable.status_code, 200)
        self.assertFalse(disable.json()["is_active"])

        student_session = TestClient(type(self).main_module.app)
        student_login = student_session.post("/auth/login", json={"email": "student@codesocrat.dev", "password": "studentpass"})
        self.assertEqual(student_login.status_code, 200)
        visible = student_session.get("/problems")
        self.assertFalse(any(problem["problem_id"] == "triple_number" for problem in visible.json()["problems"]))

        enable = self.client.post("/author/problems/triple_number/enable", headers=self._csrf_headers())
        self.assertEqual(enable.status_code, 200)
        self.assertTrue(enable.json()["is_active"])

        delete = self.client.delete("/author/problems/triple_number", headers=self._csrf_headers())
        self.assertEqual(delete.status_code, 200)
        self.assertTrue(delete.json()["is_deleted"])

    def test_author_cannot_modify_starter_problem(self) -> None:
        self._login("author@codesocrat.dev", "authorpass")
        response = self.client.post("/author/problems/sum_two_numbers/disable", headers=self._csrf_headers())
        self.assertEqual(response.status_code, 403)

    def test_login_rejects_unexpected_fields(self) -> None:
        response = self.client.post(
            "/auth/login",
            json={"email": "student@codesocrat.dev", "password": "studentpass", "role": "Author"},
        )
        self.assertEqual(response.status_code, 422)

    def test_submission_rejects_invalid_problem_id_shape(self) -> None:
        self._login("student@codesocrat.dev", "studentpass")
        response = self.client.post(
            "/submit",
            headers=self._csrf_headers(),
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

    def test_brand_new_problem_has_no_hint_access_before_any_submission(self) -> None:
        self._login("student@codesocrat.dev", "studentpass")

        response = self.client.get("/hints", params={"problem_id": "sum_two_numbers"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "No hints unlocked yet.")

    def test_reset_progress_clears_problem_state(self) -> None:
        self._login("student@codesocrat.dev", "studentpass")

        failed = self._submit("sum_two_numbers", "def add_numbers(a, b):\n    return a - b\n")
        self.assertEqual(failed.status_code, 200)
        self.assertEqual(failed.json()["hint_stage_unlocked"], 1)

        reset = self.client.delete("/progress/sum_two_numbers", headers=self._csrf_headers())
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.json()["success"], True)

        hints = self.client.get("/hints", params={"problem_id": "sum_two_numbers"})
        self.assertEqual(hints.status_code, 403)
        self.assertEqual(hints.json()["detail"], "No hints unlocked yet.")

    def test_timed_mode_can_be_armed_started_and_reflected_in_progress(self) -> None:
        self._login("student@codesocrat.dev", "studentpass")

        armed = self.client.post("/progress/sum_two_numbers/timed-mode", headers=self._csrf_headers())
        self.assertEqual(armed.status_code, 200)
        self.assertTrue(armed.json()["timed_mode_enabled"])
        self.assertEqual(armed.json()["timed_mode_status"], "ready")

        started = self.client.post("/progress/sum_two_numbers/timed-mode/start", headers=self._csrf_headers())
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json()["timed_mode_status"], "running")
        self.assertGreater(started.json()["timed_mode_remaining_seconds"], 0)

        progress = self.client.get("/progress/sum_two_numbers")
        self.assertEqual(progress.status_code, 200)
        self.assertEqual(progress.json()["timed_mode_status"], "running")

    def test_timed_mode_can_pause_and_resume_around_hint_generation(self) -> None:
        self._login("student@codesocrat.dev", "studentpass")

        self.client.post("/progress/sum_two_numbers/timed-mode", headers=self._csrf_headers())
        started = self.client.post("/progress/sum_two_numbers/timed-mode/start", headers=self._csrf_headers())
        self.assertEqual(started.status_code, 200)
        running_remaining = started.json()["timed_mode_remaining_seconds"]

        paused = self.client.post("/progress/sum_two_numbers/timed-mode/pause", headers=self._csrf_headers())
        self.assertEqual(paused.status_code, 200)
        self.assertEqual(paused.json()["timed_mode_status"], "paused")
        self.assertLessEqual(paused.json()["timed_mode_remaining_seconds"], running_remaining)
        self.assertIsNotNone(paused.json()["timed_mode_paused_at"])

        blocked = self.client.post(
            "/run",
            headers=self._csrf_headers(),
            json={
                "problem_id": "sum_two_numbers",
                "code": "def add_numbers(a, b):\n    return a + b\n",
                "timed_mode": True,
            },
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("paused", blocked.json()["detail"])

        resumed = self.client.post("/progress/sum_two_numbers/timed-mode/resume", headers=self._csrf_headers())
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json()["timed_mode_status"], "running")
        self.assertIsNone(resumed.json()["timed_mode_paused_at"])

    def test_expired_timed_mode_blocks_further_submissions(self) -> None:
        self._login("student@codesocrat.dev", "studentpass")
        self.client.post("/progress/sum_two_numbers/timed-mode", headers=self._csrf_headers())
        self.client.post("/progress/sum_two_numbers/timed-mode/start", headers=self._csrf_headers())

        db = self.SessionLocal()
        try:
            from datetime import datetime, timedelta
            from app.models import Problem, User, UserProblemProgress

            user = db.query(User).filter(User.email == "student@codesocrat.dev").first()
            problem = db.query(Problem).filter(Problem.problem_id == "sum_two_numbers").first()
            progress = db.query(UserProblemProgress).filter(
                UserProblemProgress.user_id == user.id,
                UserProblemProgress.problem_id == problem.id,
            ).first()
            self.assertIsNotNone(progress)
            progress.timed_mode_enabled = True
            progress.timed_mode_started_at = datetime.utcnow() - timedelta(minutes=10)
            progress.timed_mode_expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        finally:
            db.close()

        blocked = self.client.post(
            "/submit",
            headers=self._csrf_headers(),
            json={
                "problem_id": "sum_two_numbers",
                "code": "def add_numbers(a, b):\n    return a + b\n",
                "timed_mode": True,
            },
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("expired", blocked.json()["detail"])

    def test_expired_timed_mode_can_auto_submit_once(self) -> None:
        self._login("student@codesocrat.dev", "studentpass")
        self.client.post("/progress/sum_two_numbers/timed-mode", headers=self._csrf_headers())
        self.client.post("/progress/sum_two_numbers/timed-mode/start", headers=self._csrf_headers())

        db = self.SessionLocal()
        try:
            from datetime import datetime, timedelta
            from app.models import Problem, User, UserProblemProgress

            user = db.query(User).filter(User.email == "student@codesocrat.dev").first()
            problem = db.query(Problem).filter(Problem.problem_id == "sum_two_numbers").first()
            progress = db.query(UserProblemProgress).filter(
                UserProblemProgress.user_id == user.id,
                UserProblemProgress.problem_id == problem.id,
            ).first()
            self.assertIsNotNone(progress)
            progress.timed_mode_enabled = True
            progress.timed_mode_started_at = datetime.utcnow() - timedelta(minutes=10)
            progress.timed_mode_expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        finally:
            db.close()

        auto_submit = self.client.post(
            "/submit/timed-expired",
            headers=self._csrf_headers(),
            json={
                "problem_id": "sum_two_numbers",
                "code": "def add_numbers(a, b):\n    return a - b\n",
                "timed_mode": True,
            },
        )
        self.assertEqual(auto_submit.status_code, 200)
        self.assertEqual(auto_submit.json()["execution_type"], "Submit")
        self.assertFalse(auto_submit.json()["timed_mode_enabled"])

    def test_timed_auto_submit_requires_timed_mode_flag(self) -> None:
        self._login("student@codesocrat.dev", "studentpass")
        response = self.client.post(
            "/submit/timed-expired",
            json={
                "problem_id": "sum_two_numbers",
                "code": "def add_numbers(a, b):\n    return a + b\n",
                "timed_mode": False,
            },
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
