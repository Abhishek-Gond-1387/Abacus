"""Fail-closed tests for the explicit untrusted-code sandbox path."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from abacus import sandbox
from abacus.cli import main


IMAGE_ID = "sha256:" + "a" * 64
BASE_DIGEST = "python@sha256:" + "b" * 64


def passing_report() -> str:
    probes = "\n".join(f"| {probe} | PASS | verified |" for probe in sandbox.REQUIRED_PROBES)
    return (
        "# Day 37 — Isolated runner verification\n\n"
        "**Status: PASS.**\n\n"
        "- Docker engine: `linux|29.0.0`\n"
        f"- Image: `{sandbox.IMAGE}; image ID `{IMAGE_ID}`; base `{BASE_DIGEST}``\n\n"
        "| Probe | Result | Notes |\n|---|---|---|\n"
        f"{probes}\n"
    )


class SandboxRoutingTests(unittest.TestCase):
    def runner(self, report: Path, *, process_runner=None, executable_resolver=None) -> sandbox.SandboxRunner:
        return sandbox.SandboxRunner(
            report_path=report,
            environment={sandbox.EXECUTION_FLAG: "1"},
            process_runner=process_runner or mock.Mock(),
            executable_resolver=executable_resolver or (lambda _name: "docker.exe"),
        )

    def test_missing_explicit_opt_in_refuses_before_runtime_or_source(self) -> None:
        process_runner = mock.Mock()
        runner = sandbox.SandboxRunner(
            report_path=Path("missing-report.md"),
            environment={sandbox.EXECUTION_FLAG: "1"},
            process_runner=process_runner,
        )
        with self.assertRaises(sandbox.SandboxError) as raised:
            runner.execute("def candidate(value): return value", [1], explicit_opt_in=False)
        self.assertEqual(raised.exception.reason, "explicit_opt_in_required")
        process_runner.assert_not_called()

    def test_missing_runtime_fails_closed_without_host_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "verified.md"
            report.write_text(passing_report(), encoding="utf-8")
            process_runner = mock.Mock()
            runner = self.runner(
                report,
                process_runner=process_runner,
                executable_resolver=lambda _name: None,
            )
            with self.assertRaises(sandbox.SandboxError) as raised:
                runner.execute("def candidate(value): return value", [1], explicit_opt_in=True)

        self.assertEqual(raised.exception.reason, "docker_runtime_unavailable")
        process_runner.assert_not_called()
        self.assertNotIn("candidate", str(raised.exception))

    def test_day37_blocked_report_prevents_runtime_lookup(self) -> None:
        process_runner = mock.Mock()
        runner = sandbox.SandboxRunner(
            environment={sandbox.EXECUTION_FLAG: "1"},
            process_runner=process_runner,
        )
        with self.assertRaises(sandbox.SandboxError) as raised:
            runner.preflight(explicit_opt_in=True)
        self.assertEqual(raised.exception.reason, "day37_verification_not_passed")
        process_runner.assert_not_called()

    def test_nonzero_container_start_returns_error_and_never_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "verified.md"
            report.write_text(passing_report(), encoding="utf-8")
            calls: list[tuple[list[str], dict[str, object]]] = []

            def fake_process(argv, **kwargs):
                calls.append((argv, kwargs))
                if argv[1:3] == ["version", "--format"]:
                    return {"returncode": 0, "reason": None, "stdout": b"linux|29.0.0", "stderr": b"", "output_bytes": 14}
                if argv[1:4] == ["image", "inspect", "--format"]:
                    metadata = f"{IMAGE_ID}|linux|fixed-purpose-sandbox-probes|python-json-v2".encode()
                    return {"returncode": 0, "reason": None, "stdout": metadata, "stderr": b"", "output_bytes": len(metadata)}
                if argv[1] == "create":
                    return {"returncode": 1, "reason": None, "stdout": b"", "stderr": b"runtime rejected create", "output_bytes": 23}
                if argv[1:3] == ["rm", "--force"]:
                    return {"returncode": 1, "reason": None, "stdout": b"", "stderr": b"No such container", "output_bytes": 18}
                if argv[1] == "inspect":
                    return {"returncode": 1, "reason": None, "stdout": b"", "stderr": b"No such container", "output_bytes": 18}
                self.fail(f"Unexpected host command: {argv!r}")

            runner = self.runner(report, process_runner=fake_process)
            code = "def candidate(value): return value * 2"
            with self.assertRaises(sandbox.SandboxError) as raised:
                runner.execute(code, [3], explicit_opt_in=True)

        self.assertEqual(raised.exception.reason, "sandbox_start_failed")
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(argv[0] == "docker" for argv, _ in calls))
        self.assertFalse(any(argv[1] == "start" for argv, _ in calls))
        self.assertFalse(any(code in " ".join(argv) for argv, _ in calls))

    def test_cli_requires_flag_before_opening_candidate_files(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(
                [
                    "execute-untrusted",
                    "missing-candidate.py",
                    "--input",
                    "missing-input.json",
                ]
            )
        self.assertEqual(result, 1)
        record = json.loads(output.getvalue())
        self.assertEqual(record["outcome"], "ERROR")
        self.assertEqual(record["reason"], "explicit_opt_in_required")
        self.assertNotIn("missing-candidate.py", output.getvalue())
        self.assertNotIn("missing-input.json", output.getvalue())

    def test_cli_requires_environment_flag_before_opening_candidate_files(self) -> None:
        output = io.StringIO()
        with mock.patch.dict("os.environ", {}, clear=True), redirect_stdout(output):
            result = main(
                [
                    "execute-untrusted",
                    "missing-candidate.py",
                    "--input",
                    "missing-input.json",
                    "--allow-untrusted-code",
                ]
            )
        self.assertEqual(result, 1)
        record = json.loads(output.getvalue())
        self.assertEqual(record["reason"], "execution_flag_disabled")
        self.assertNotIn("missing-candidate.py", output.getvalue())


if __name__ == "__main__":
    unittest.main()
