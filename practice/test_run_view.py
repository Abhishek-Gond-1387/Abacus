"""Run-viewer fixtures for passed, refuted, incomplete, and error records."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from abacus.cli import load_problem, run_problem
from practice.day29_record_examples import partial_sample
from practice.run_view import TESTS_PASSED_NOTE, render_run_summary


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBLEMS = PROJECT_ROOT / "problems"


class RunViewTests(unittest.TestCase):
    def test_true_run_view_limits_finite_pass_and_separates_suggestions(self) -> None:
        spec = load_problem(PROBLEMS / "p01_true_sort.json")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "true.json"
            record = run_problem(spec, path)
            view = render_run_summary(record, record_path=path)

        self.assertIn("Outcome: TESTS_PASSED", view)
        self.assertIn(TESTS_PASSED_NOTE, view)
        self.assertIn("MODEL INPUT (unverified; not harness evidence)", view)
        self.assertIn("HARNESS EVIDENCE (executed by code)", view)
        self.assertIn("Full evidence record:", view)
        self.assertLess(view.index("HARNESS EVIDENCE"), view.index("MODEL INPUT"))

    def test_false_run_view_shows_counterexample_and_replay(self) -> None:
        spec = load_problem(PROBLEMS / "p02_false_sort.json")
        with tempfile.TemporaryDirectory() as directory:
            record = run_problem(spec, Path(directory) / "false.json")
            view = render_run_summary(record)

        self.assertIn("Outcome: REFUTED", view)
        self.assertIn("replay confirmed", view)
        self.assertIn("input=[3,-1,3,0]", view)
        self.assertIn("actual=[-1,0,3]", view)
        self.assertIn("expected=[-1,0,3,3]", view)

    def test_unresolved_run_view_keeps_completed_evidence_and_reason(self) -> None:
        view = render_run_summary(partial_sample())
        self.assertIn("Outcome: UNRESOLVED", view)
        self.assertIn("1 completed / 2 scheduled", view)
        self.assertIn("Incomplete reasons: round_limit", view)

    def test_error_run_view_shows_error_without_hiding_checks(self) -> None:
        spec = load_problem(PROBLEMS / "p01_true_sort.json")
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch(
                "abacus.cli.collect_offline_proposals",
                side_effect=RuntimeError("synthetic stage failure"),
            ):
                record = run_problem(spec, Path(directory) / "error.json")
            view = render_run_summary(record)

        self.assertIn("Outcome: ERROR", view)
        self.assertIn("Errors:", view)
        self.assertIn("synthetic stage failure", view)
        self.assertIn("HARNESS EVIDENCE (executed by code)", view)
        self.assertIn("29 completed / 31 scheduled", view)
        self.assertIn("Incomplete reasons: optional_proposal_generation", view)
        self.assertIn("Errors: none recorded", render_run_summary(partial_sample()))


if __name__ == "__main__":
    unittest.main()
