from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from abacus.contracts import InputStatus, validate_input
from abacus.counterexamples import ReplayStatus, load_counterexample, replay_counterexample
from abacus.harness import HarnessStatus
from abacus.hypothesis_capture import find_and_save_sorting_failure
from abacus.problems import load_problem
from abacus.sorting_oracle import CheckStatus


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
COUNTEREXAMPLE_PATH = (
    PROJECT_DIRECTORY
    / "counterexamples"
    / "sort-ascending-false-hypothesis-day17.json"
)
PROBLEM_PATH = PROJECT_DIRECTORY / "problems" / "sort-ascending-false.json"


class HypothesisShrunkRegressionTests(unittest.TestCase):
    def test_capture_hook_saves_seed_settings_and_minimized_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "shrunk.json"
            captured = find_and_save_sorting_failure(
                PROBLEM_PATH,
                destination,
                seed=17017,
                max_examples=40,
                deadline_ms=5000,
            )
            saved = load_counterexample(destination)

        self.assertEqual(captured.input_value, [0, 1])
        self.assertEqual(saved["input"], [0, 1])
        self.assertEqual(saved["seed"], 17017)
        self.assertIn("version=6.170.14", saved["source"])
        self.assertIn("max_examples=40", saved["source"])
        self.assertIn("database=None", saved["source"])
        self.assertIn("deadline_ms=5000", saved["source"])
        self.assertIn("random_seed=17017", saved["source"])

    def test_saved_shrunk_failure_replays_through_ordinary_harness(self) -> None:
        saved = load_counterexample(COUNTEREXAMPLE_PATH)
        problem = load_problem(PROBLEM_PATH)
        validation = validate_input(problem, saved["input"])

        self.assertEqual(saved["input"], [0, 1])
        self.assertEqual(saved["seed"], 17017)
        self.assertIn("hypothesis.find", saved["source"])
        self.assertIn("max_examples=40", saved["source"])
        self.assertEqual(validation.status, InputStatus.VALID)

        replay = replay_counterexample(COUNTEREXAMPLE_PATH, problem)

        self.assertEqual(replay.status, ReplayStatus.REPRODUCED)
        self.assertTrue(replay.code_version_matches)
        self.assertTrue(replay.problem_record_version_matches)
        self.assertEqual(replay.case_evidence.status, HarnessStatus.REFUTED)
        self.assertEqual(replay.case_evidence.target_result, [1, 0])
        self.assertEqual(
            replay.case_evidence.oracle_result.status,
            CheckStatus.REFUTED,
        )
        self.assertEqual(
            list(replay.case_evidence.oracle_result.expected_output), [0, 1]
        )


if __name__ == "__main__":
    unittest.main()
