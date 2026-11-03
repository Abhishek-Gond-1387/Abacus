from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from abacus.runner import RunCategory, run_trusted_program


class TrustedProgramRunnerTests(unittest.TestCase):
    def test_normal_output_succeeds(self) -> None:
        result = run_trusted_program('print("hello")')

        self.assertEqual(result.category, RunCategory.SUCCESS)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout, f"hello{os.linesep}")
        self.assertEqual(result.stderr, "")
        self.assertFalse(result.timed_out)
        self.assertGreaterEqual(result.duration_seconds, 0)

    def test_assertion_failure_is_classified(self) -> None:
        result = run_trusted_program("assert 1 == 2")

        self.assertEqual(result.category, RunCategory.ASSERTION_FAILURE)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("AssertionError", result.stderr)

    def test_syntax_error_is_classified(self) -> None:
        result = run_trusted_program("def broken(:\n    pass")

        self.assertEqual(result.category, RunCategory.SYNTAX_ERROR)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("SyntaxError", result.stderr)

    def test_runtime_exception_is_classified(self) -> None:
        result = run_trusted_program("raise RuntimeError('expected failure')")

        self.assertEqual(result.category, RunCategory.EXCEPTION)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("RuntimeError: expected failure", result.stderr)

    def test_timeout_is_classified_and_temp_files_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = run_trusted_program(
                "import time; time.sleep(5)",
                timeout_seconds=0.5,
                temp_root=root,
            )
            remaining = list(Path(root).iterdir())

        self.assertEqual(result.category, RunCategory.TIMEOUT)
        self.assertTrue(result.timed_out)
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(remaining, [])
        self.assertLess(result.duration_seconds, 3)

    def test_noisy_output_is_bounded_and_classified(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = run_trusted_program(
                "import sys; print('o' * 20000); print('e' * 20000, file=sys.stderr)",
                max_output_bytes=256,
                temp_root=root,
            )
            remaining = list(Path(root).iterdir())

        self.assertEqual(result.category, RunCategory.OUTPUT_LIMIT)
        self.assertTrue(result.output_limit_exceeded)
        self.assertLessEqual(
            len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8")),
            256,
        )
        self.assertTrue(result.stdout_truncated or result.stderr_truncated)
        self.assertEqual(remaining, [])

    def test_nonzero_exit_without_traceback_is_distinct(self) -> None:
        result = run_trusted_program("raise SystemExit(7)")

        self.assertEqual(result.category, RunCategory.NONZERO_EXIT)
        self.assertEqual(result.exit_code, 7)


if __name__ == "__main__":
    unittest.main()
