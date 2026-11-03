from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from abacus.contracts import InputStatus
from abacus.edge_cases import (
    DEFAULT_RANDOM_SEED,
    GENERATOR_VERSION,
    generate_edge_cases,
    run_edge_case_suite,
)
from abacus.harness import HarnessStatus
from abacus.problems import load_problem


PROBLEMS_DIRECTORY = Path(__file__).resolve().parents[1] / "problems"


class DeterministicEdgeCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.true_problem = load_problem(
            PROBLEMS_DIRECTORY / "sort-ascending-true.json"
        )

    def test_generator_has_explained_contract_valid_boundaries(self) -> None:
        case_set = generate_edge_cases(self.true_problem)
        by_name = {case.name: case for case in case_set.cases}

        expected_names = {
            "empty",
            "single_item",
            "duplicates",
            "negative_and_zero",
            "already_sorted",
            "reverse_sorted",
            "all_equal",
            "large_magnitude",
            "seeded_random_1",
            "seeded_random_2",
            "seeded_random_3",
            "boolean_is_out_of_contract",
        }
        self.assertEqual(set(by_name), expected_names)
        self.assertEqual(case_set.generator_version, GENERATOR_VERSION)
        self.assertEqual(case_set.seed, DEFAULT_RANDOM_SEED)
        self.assertTrue(all(case.explanation for case in case_set.cases))
        self.assertTrue(
            all(
                case.contract_status is InputStatus.VALID
                for case in case_set.cases[:-1]
            )
        )
        self.assertEqual(
            by_name["boolean_is_out_of_contract"].contract_status,
            InputStatus.OUTSIDE_CONTRACT,
        )
        self.assertEqual(by_name["large_magnitude"].input_value, [-(10**30), 0, 10**30])

    def test_two_harness_runs_have_identical_cases_and_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = run_edge_case_suite(
                self.true_problem,
                Path(directory) / "first.json",
                seed=DEFAULT_RANDOM_SEED,
            )
            second = run_edge_case_suite(
                self.true_problem,
                Path(directory) / "second.json",
                seed=DEFAULT_RANDOM_SEED,
            )

        self.assertEqual(first.case_set.as_dict(), second.case_set.as_dict())
        self.assertEqual(first.case_set.inputs, second.case_set.inputs)
        self.assertEqual(
            [item.status for item in first.evidence],
            [item.status for item in second.evidence],
        )
        self.assertEqual(
            [item.target_result for item in first.evidence],
            [item.target_result for item in second.evidence],
        )
        self.assertEqual(first.passed_count, 11)
        self.assertEqual(first.out_of_contract_count, 1)
        self.assertEqual(
            first.evidence[-1].status,
            HarnessStatus.OUT_OF_CONTRACT,
        )
        self.assertIsNone(first.evidence[-1].execution)

    def test_saved_run_record_contains_generator_seed_cases_and_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = run_edge_case_suite(
                self.true_problem,
                Path(directory) / "day15-run.json",
                seed=2468,
            )
            record = json.loads(run.saved_path.read_text(encoding="utf-8"))

        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["problem_id"], "sort-ascending-true")
        self.assertEqual(record["generator_version"], GENERATOR_VERSION)
        self.assertEqual(record["seed"], 2468)
        self.assertEqual(record["python_version"], run.case_set.python_version)
        self.assertEqual(record["cases"], [case.as_dict() for case in run.case_set.cases])
        self.assertEqual(len(record["outcomes"]), len(record["cases"]))
        self.assertEqual(record["outcomes"][-1]["status"], "OUT_OF_CONTRACT")


if __name__ == "__main__":
    unittest.main()