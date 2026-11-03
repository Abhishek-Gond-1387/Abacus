"""Ensure a named sentinel secret does not escape into run artifacts."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from abacus import cli


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBLEM = PROJECT_ROOT / "problems" / "p01_true_sort.json"


class LogSafetyTests(unittest.TestCase):
    def test_sentinel_secret_is_absent_from_saved_log_and_cli_output(self) -> None:
        sentinel = "TEST_SECRET_" + "DO_NOT_LOG_123"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "secret-check.json"
            with mock.patch.dict(os.environ, {"ABACUS_TEST_SECRET": sentinel}):
                with mock.patch(
                    "abacus.cli.collect_offline_proposals",
                    side_effect=RuntimeError(f"provider error included {sentinel}"),
                ):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        result = cli.main(["run", str(PROBLEM), "--output", str(log_path)])
            saved_log = log_path.read_text(encoding="utf-8")

        self.assertEqual(result, 0)
        self.assertNotIn(sentinel, saved_log)
        self.assertNotIn(sentinel, stdout.getvalue())
        self.assertNotIn(sentinel, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
