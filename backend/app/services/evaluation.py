from __future__ import annotations

import ast
import json
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import settings


FAILURE_SYNTAX = "SyntaxError"
FAILURE_DEFINITION = "DefinitionError"
FAILURE_RUNTIME = "RuntimeError"
FAILURE_INCORRECT = "IncorrectOutput"
FAILURE_TIMEOUT = "TimeLimitExceeded"


@dataclass
class EvaluationResult:
    result: str
    failure_category: Optional[str]
    runtime_ms: int
    memory_mb: int
    feedback: str
    valid_attempt: bool


class DockerSandboxExecutor:
    def run(self, *, code: str, function_name: str, test_cases: list[tuple[list, object]]) -> EvaluationResult:
        availability_error = self._check_docker_availability()
        if availability_error is not None:
            return availability_error

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runner_path = temp_path / "runner.py"
            runner_path.write_text(self._build_runner_script(code=code, function_name=function_name, test_cases=test_cases))

            start = time.perf_counter()
            command = self._build_docker_command(temp_path)
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=settings.docker_startup_timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                runtime_ms = int((time.perf_counter() - start) * 1000)
                return EvaluationResult(
                    result="Fail",
                    failure_category=FAILURE_RUNTIME,
                    runtime_ms=runtime_ms,
                    memory_mb=self._memory_limit_mb(),
                    feedback="Docker sandbox startup timed out before execution completed.",
                    valid_attempt=False,
                )
            except FileNotFoundError:
                return EvaluationResult(
                    result="Fail",
                    failure_category=FAILURE_RUNTIME,
                    runtime_ms=0,
                    memory_mb=self._memory_limit_mb(),
                    feedback="Docker is not installed on the server.",
                    valid_attempt=False,
                )

        runtime_ms = int((time.perf_counter() - start) * 1000)
        return self._classify_container_result(completed=completed, runtime_ms=runtime_ms)

    def _build_docker_command(self, sandbox_dir: Path) -> list[str]:
        memory_mb = f"{self._memory_limit_mb()}m"
        return [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--cpus",
            settings.docker_cpus,
            "--memory",
            memory_mb,
            "--pids-limit",
            str(settings.docker_pids_limit),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
            "-v",
            f"{sandbox_dir}:/workspace:ro",
            "-w",
            "/workspace",
            settings.docker_image,
            "python",
            "-B",
            "/workspace/runner.py",
        ]

    def _check_docker_availability(self) -> Optional[EvaluationResult]:
        try:
            info = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except subprocess.TimeoutExpired:
            return EvaluationResult(
                result="Fail",
                failure_category=FAILURE_RUNTIME,
                runtime_ms=0,
                memory_mb=self._memory_limit_mb(),
                feedback="Docker daemon did not respond in time.",
                valid_attempt=False,
            )
        except FileNotFoundError:
            return EvaluationResult(
                result="Fail",
                failure_category=FAILURE_RUNTIME,
                runtime_ms=0,
                memory_mb=self._memory_limit_mb(),
                feedback="Docker is not installed on the server.",
                valid_attempt=False,
            )

        if info.returncode != 0:
            combined = "\n".join(part for part in [(info.stdout or "").strip(), (info.stderr or "").strip()] if part)
            return EvaluationResult(
                result="Fail",
                failure_category=FAILURE_RUNTIME,
                runtime_ms=0,
                memory_mb=self._memory_limit_mb(),
                feedback=combined or "Docker daemon is not available.",
                valid_attempt=False,
            )

        image_check = subprocess.run(
            ["docker", "image", "inspect", settings.docker_image],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if image_check.returncode != 0:
            return EvaluationResult(
                result="Fail",
                failure_category=FAILURE_RUNTIME,
                runtime_ms=0,
                memory_mb=self._memory_limit_mb(),
                feedback=f"Docker image '{settings.docker_image}' is not available locally. Run: docker pull {settings.docker_image}",
                valid_attempt=False,
            )

        return None

    def _classify_container_result(self, *, completed: subprocess.CompletedProcess[str], runtime_ms: int) -> EvaluationResult:
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()

        if completed.returncode != 0:
            combined_output = "\n".join(part for part in [stdout, stderr] if part).strip()
            if "Cannot connect to the Docker daemon" in combined_output:
                return EvaluationResult(
                    result="Fail",
                    failure_category=FAILURE_RUNTIME,
                    runtime_ms=runtime_ms,
                    memory_mb=self._memory_limit_mb(),
                    feedback="Docker daemon is not available. Start Docker and try again.",
                    valid_attempt=False,
                )
            if "MemoryError" in combined_output or "OOMKilled" in combined_output:
                return EvaluationResult(
                    result="Fail",
                    failure_category=FAILURE_TIMEOUT,
                    runtime_ms=runtime_ms,
                    memory_mb=self._memory_limit_mb(),
                    feedback="Execution exceeded the allowed memory limit in the Docker sandbox.",
                    valid_attempt=False,
                )
            return EvaluationResult(
                result="Fail",
                failure_category=FAILURE_RUNTIME,
                runtime_ms=runtime_ms,
                memory_mb=self._memory_limit_mb(),
                feedback=combined_output or "Runtime error occurred inside the Docker sandbox.",
                valid_attempt=False,
            )

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return EvaluationResult(
                result="Fail",
                failure_category=FAILURE_RUNTIME,
                runtime_ms=runtime_ms,
                memory_mb=self._memory_limit_mb(),
                feedback="Sandbox returned an unreadable response.",
                valid_attempt=False,
            )

        if payload["status"] == "pass":
            return EvaluationResult(
                result="Pass",
                failure_category=None,
                runtime_ms=runtime_ms,
                memory_mb=self._memory_limit_mb(),
                feedback="All test cases passed.",
                valid_attempt=True,
            )

        if payload["status"] == "fail":
            return EvaluationResult(
                result="Fail",
                failure_category=FAILURE_INCORRECT,
                runtime_ms=runtime_ms,
                memory_mb=self._memory_limit_mb(),
                feedback=payload["message"],
                valid_attempt=True,
            )

        return EvaluationResult(
            result="Fail",
            failure_category=FAILURE_RUNTIME,
            runtime_ms=runtime_ms,
            memory_mb=self._memory_limit_mb(),
            feedback=payload.get("message", "Unexpected sandbox response."),
            valid_attempt=False,
        )

    def _build_runner_script(self, *, code: str, function_name: str, test_cases: list[tuple[list, object]]) -> str:
        serialized_cases = json.dumps(test_cases)
        return "\n".join(
            [
                "import json",
                "",
                code.rstrip(),
                "",
                f"TEST_CASES = json.loads({serialized_cases!r})",
                f"FUNCTION_NAME = {function_name!r}",
                "",
                "try:",
                "    fn = globals()[FUNCTION_NAME]",
                "    for idx, case in enumerate(TEST_CASES, start=1):",
                "        args, expected = case",
                "        actual = fn(*args)",
                "        if actual != expected:",
                "            print(json.dumps({",
                '                "status": "fail",',
                '                "message": f"Test case {idx} failed: expected {expected!r}, got {actual!r}."',
                "            }))",
                "            raise SystemExit(0)",
                '    print(json.dumps({"status": "pass"}))',
                "except Exception as exc:",
                '    print(json.dumps({"status": "error", "message": str(exc)}))',
                "    raise",
                "",
            ]
        )

    def _memory_limit_mb(self) -> int:
        return int(settings.evaluation_memory_bytes / (1024 * 1024))


class EvaluationService:
    def __init__(self, executor: Optional[DockerSandboxExecutor] = None):
        self.executor = executor or DockerSandboxExecutor()

    def evaluate(self, *, code: str, function_name: str, test_cases: list[tuple[list, object]]) -> EvaluationResult:
        syntax_error = self._check_syntax(code)
        if syntax_error:
            return EvaluationResult(
                result="Fail",
                failure_category=FAILURE_SYNTAX,
                runtime_ms=0,
                memory_mb=0,
                feedback=syntax_error,
                valid_attempt=False,
            )

        definition_error = self._check_required_function(code, function_name)
        if definition_error:
            return EvaluationResult(
                result="Fail",
                failure_category=FAILURE_DEFINITION,
                runtime_ms=0,
                memory_mb=0,
                feedback=definition_error,
                valid_attempt=False,
            )

        return self.executor.run(code=code, function_name=function_name, test_cases=test_cases)

    def _check_syntax(self, code: str) -> Optional[str]:
        try:
            ast.parse(code)
        except SyntaxError as exc:
            return f"Syntax error on line {exc.lineno}: {exc.msg}"
        return None

    def _check_required_function(self, code: str, function_name: str) -> Optional[str]:
        tree = ast.parse(code)
        functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        if function_name not in functions:
            return f"Required function '{function_name}' is missing or misnamed."
        return None
