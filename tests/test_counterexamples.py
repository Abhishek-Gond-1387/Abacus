from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from abacus.counterexamples import (
    CounterexampleValidationError,
    ReplayStatus,
    load_counterexample,
    replay_counterexample,
    save_counterexample,
)
from abacus.harness import HarnessStatus, check_case
from abacus.problems import load_problem


PROBLEMS_DIRECTORY = Path(__file__).resolve().parents[1] / "problems"


class CounterexamplePersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.false_problem = load_problem(
            PROBLEMS_DIRECTORY / "sort-ascending-false.json"
        )

    def _save_known_witness(self, destination: Path) -> Path:
        evidence = check_case(self.false_problem, [1, 2])
        self.assertEqual(evidence.status, HarnessStatus.REFUTED)
        return save_counterexample(
            self.false_problem,
            evidence,
            destination,
            source="problem.known_counterexample",
            seed=13,
        )

    def test_save_and_replay_known_false_witness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._save_known_witness(Path(directory) / "counterexample.json")
            saved = load_counterexample(path)
            replay = replay_counterexample(path, self.false_problem)

        self.assertEqual(saved["problem_id"], "sort-ascending-false")
        self.assertEqual(saved["input"], [1, 2])
        self.assertEqual(saved["source"], "problem.known_counterexample")
        self.assertEqual(saved["seed"], 13)
        self.assertTrue(saved["contract_validity"]["valid"])
        self.assertEqual(saved["observed_result"]["target_result"], [2, 1])
        self.assertEqual(saved["expected_property"]["expected_output"], [1, 2])
        self.assertEqual(len(saved["versions"]["target_code_sha256"]), 64)
        self.assertEqual(len(saved["versions"]["problem_record_sha256"]), 64)
        self.assertEqual(replay.status, ReplayStatus.REPRODUCED)
        self.assertTrue(replay.code_version_matches)
        self.assertTrue(replay.problem_record_version_matches)
        self.assertEqual(replay.case_evidence.status, HarnessStatus.REFUTED)

    def test_changed_target_version_is_visible_and_unresolved_if_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._save_known_witness(Path(directory) / "counterexample.json")
            changed_problem = dict(self.false_problem)
            changed_problem["code"] = (
                "def candidate(values):\n"
                "    return sorted(values)"
            )

            replay = replay_counterexample(path, changed_problem)

        self.assertEqual(replay.status, ReplayStatus.UNRESOLVED)
        self.assertFalse(replay.code_version_matches)
        self.assertFalse(replay.problem_record_version_matches)
        self.assertEqual(replay.case_evidence.status, HarnessStatus.PASSED)
        self.assertIn("do not claim a refutation", replay.explanation)

    def test_atomic_replace_failure_keeps_old_file_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "counterexample.json"
            destination.write_text("old saved evidence\n", encoding="utf-8")
            evidence = check_case(self.false_problem, [1, 2])

            with patch(
                "abacus.counterexamples.os.replace",
                side_effect=OSError("simulated replace failure"),
            ):
                with self.assertRaises(OSError):
                    save_counterexample(
                        self.false_problem,
                        evidence,
                        destination,
                        source="test",
                    )

            self.assertEqual(
                destination.read_text(encoding="utf-8"), "old saved evidence\n"
            )
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])
            self.assertEqual(list(Path(directory).glob(".*.tmp")), [])

    def test_only_oracle_refutations_can_be_saved(self) -> None:
        true_problem = load_problem(
            PROBLEMS_DIRECTORY / "sort-ascending-true.json"
        )
        evidence = check_case(true_problem, [1, 2])

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "only an oracle-refuted case"):
                save_counterexample(
                    true_problem,
                    evidence,
                    Path(directory) / "not-a-counterexample.json",
                    source="test",
                )

    def test_invalid_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")

            with self.assertRaises(CounterexampleValidationError):
                load_counterexample(path)


if __name__ == "__main__":
    unittest.main()
