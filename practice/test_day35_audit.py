"""Day 35 audit checks for checked-in outcome examples."""

from __future__ import annotations

import unittest
from pathlib import Path

from abacus.cli import ORACLES, TARGETS
from practice.log_safety import sanitize_for_log
from practice.run_records import load_run_record


SAMPLE_DIR = Path(__file__).resolve().parent / "samples"
SAMPLES = {
    "day35_refuted.v2.json": "REFUTED",
    "day35_tests_passed.v2.json": "TESTS_PASSED",
    "day35_unresolved.v2.json": "UNRESOLVED",
    "day35_error.v2.json": "ERROR",
}


class Day35RunAuditTests(unittest.TestCase):
    def test_four_saved_outcomes_validate_and_have_consistent_completion(self) -> None:
        for name, expected_outcome in SAMPLES.items():
            with self.subTest(name=name):
                record = load_run_record(SAMPLE_DIR / name)
                self.assertEqual(record["outcome"]["outcome"], expected_outcome)
                self.assertEqual(record["run_status"], record["completion"]["status"])
                self.assertEqual(
                    record["completion"]["completed_case_count"],
                    sum(item["status"] == "completed" for item in record["evidence"]),
                )
                self.assertFalse(record["model"]["provider_api_called"])
                self.assertIsNone(record["model"]["provider_id"])
                self.assertIsNone(record["model"]["model_id"])
                self.assertEqual(record["provenance"]["git_dirty"], False)
                self.assertTrue(record["provenance"]["git_revision"])
                self.assertIn("hypothesis", record["generation"]["settings"])
                self.assertTrue(record["model"]["prompt_template_versions"])

    def test_saved_refuted_counterexample_replays_to_the_same_mismatch(self) -> None:
        record = load_run_record(SAMPLE_DIR / "day35_refuted.v2.json")
        counterexample = record["outcome"]["counterexample"]
        target = TARGETS[record["target"]["id"]]
        oracle = ORACLES[record["problem"]["contract"]["oracle_id"]]
        actual = target(counterexample["input"].copy())
        expected = oracle(counterexample["input"].copy())
        evidence = next(item for item in record["evidence"] if item["test_id"] == counterexample["test_id"])

        self.assertTrue(evidence["replay_confirmed"])
        self.assertEqual(actual, counterexample["actual"])
        self.assertEqual(expected, counterexample["expected"])
        self.assertNotEqual(actual, expected)

    def test_saved_examples_are_already_secret_sanitized(self) -> None:
        for name in SAMPLES:
            with self.subTest(name=name):
                record = load_run_record(SAMPLE_DIR / name)
                self.assertEqual(sanitize_for_log(record), record)

    def test_error_and_incomplete_examples_explain_their_state(self) -> None:
        unresolved = load_run_record(SAMPLE_DIR / "day35_unresolved.v2.json")
        error = load_run_record(SAMPLE_DIR / "day35_error.v2.json")

        self.assertLess(unresolved["completion"]["completed_case_count"], unresolved["completion"]["scheduled_case_count"])
        self.assertEqual(unresolved["completion"]["incomplete_reasons"], ["incomplete_evidence"])
        self.assertEqual(error["errors"][0]["step"], "optional_proposal_generation")
        self.assertIn("offline proposal fixture unavailable", error["errors"][0]["error"])


if __name__ == "__main__":
    unittest.main()
