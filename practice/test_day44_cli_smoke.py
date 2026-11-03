"""Day 44 smoke checks for the installed command-line workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBLEMS = PROJECT_ROOT / "problems"


class Day44CliSmokeTests(unittest.TestCase):
    def run_seed(self, problem_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
        environment = os.environ.copy()
        for variable in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ABACUS_LLM_PROVIDER"):
            environment.pop(variable, None)

        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / f"{problem_name}.run.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "abacus",
                    "run",
                    str(PROBLEMS / f"{problem_name}.json"),
                    "--output",
                    str(log_path),
                ],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=f"CLI failed. stdout={result.stdout!r}; stderr={result.stderr!r}",
            )
            summary = json.loads(result.stdout)
            self.assertTrue(log_path.is_file(), "CLI did not save the run record")
            saved_record = json.loads(log_path.read_text(encoding="utf-8"))

        self.assertFalse(summary["provider_api_called"])
        self.assertFalse(saved_record["model"]["provider_api_called"])
        return summary, saved_record

    def test_true_seed_cli_run_saves_offline_finite_result(self) -> None:
        summary, saved_record = self.run_seed("p01_true_sort")

        self.assertEqual(summary["outcome"], "TESTS_PASSED")
        self.assertEqual(summary["test_count"], 31)
        self.assertEqual(saved_record["outcome"]["outcome"], "TESTS_PASSED")

    def test_false_seed_cli_run_saves_replay_confirmed_counterexample(self) -> None:
        summary, saved_record = self.run_seed("p02_false_sort")

        self.assertEqual(summary["outcome"], "REFUTED")
        self.assertEqual(summary["test_count"], 31)
        self.assertTrue(summary["counterexample"]["replay_confirmed"])
        self.assertEqual(saved_record["outcome"]["outcome"], "REFUTED")


if __name__ == "__main__":
    unittest.main()
