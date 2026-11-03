from __future__ import annotations

import unittest
from pathlib import Path

from abacus.contracts import (
    InputStatus,
    generate_sorted_integer_examples,
    validate_input,
)
from abacus.problems import load_problem
from abacus.sorting_oracle import (
    SORTED_INTEGER_LIST_ORACLE_ID,
    CheckStatus,
    check_sorted_integer_list,
)

PROBLEMS_DIRECTORY = Path(__file__).resolve().parents[1] / "problems"


def correct_sort(values: list[int]) -> list[int]:
    return sorted(values)


def faulty_reverse_sort(values: list[int]) -> list[int]:
    return sorted(values, reverse=True)


def faulty_in_place_sort(values: list[int]) -> list[int]:
    values.sort()
    return values


class SortedIntegerListOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.true_problem = load_problem(
            PROBLEMS_DIRECTORY / "sort-ascending-true.json"
        )
        cls.false_problem = load_problem(
            PROBLEMS_DIRECTORY / "sort-ascending-false.json"
        )

    def test_oracle_id_matches_problem_records(self) -> None:
        self.assertEqual(
            self.true_problem["oracle_id"], SORTED_INTEGER_LIST_ORACLE_ID
        )
        self.assertEqual(
            self.false_problem["oracle_id"], SORTED_INTEGER_LIST_ORACLE_ID
        )

    def test_correct_sort_passes_required_edge_cases(self) -> None:
        cases = list(generate_sorted_integer_examples(self.true_problem))
        self.assertEqual(len(cases), 5)
        for values in cases:
            with self.subTest(values=values):
                original = list(values)
                validation = validate_input(self.true_problem, values)
                result = check_sorted_integer_list(
                    correct_sort, values, self.true_problem
                )
                self.assertEqual(validation.status, InputStatus.VALID)
                self.assertTrue(result.passed, result.reason)
                self.assertEqual(result.status, CheckStatus.PASSED)
                self.assertEqual(result.expected_output, tuple(sorted(original)))
                self.assertEqual(values, original)
                self.assertTrue(result.input_unchanged)

    def test_known_false_record_witness_fails_reverse_sort(self) -> None:
        witness = self.false_problem["known_counterexample"]

        result = check_sorted_integer_list(
            faulty_reverse_sort, witness["input"], self.false_problem
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.status, CheckStatus.REFUTED)
        self.assertEqual(list(result.expected_output), witness["expected_output"])
        self.assertEqual(result.actual_output, witness["actual_output"])
        self.assertIn("sorted reference", result.reason or "")

    def test_in_place_sort_fails_the_no_mutation_requirement(self) -> None:
        values = [3, 1, 2]

        result = check_sorted_integer_list(
            faulty_in_place_sort, values, self.true_problem
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.status, CheckStatus.REFUTED)
        self.assertFalse(result.input_unchanged)
        self.assertEqual(values, [1, 2, 3])
        self.assertEqual(result.reason, "candidate mutated the input list")

    def test_non_list_or_non_integer_outputs_fail(self) -> None:
        tuple_result = check_sorted_integer_list(
            lambda values: tuple(sorted(values)), [1], self.true_problem
        )
        boolean_result = check_sorted_integer_list(
            lambda values: [True], [1], self.true_problem
        )

        self.assertFalse(tuple_result.passed)
        self.assertEqual(tuple_result.status, CheckStatus.REFUTED)
        self.assertEqual(tuple_result.reason, "candidate output must be a list")
        self.assertFalse(boolean_result.passed)
        self.assertEqual(boolean_result.status, CheckStatus.REFUTED)
        self.assertEqual(
            boolean_result.reason,
            "candidate output must contain only integers",
        )

    def test_invalid_inputs_are_outside_contract_and_skip_target(self) -> None:
        invalid_values = [None, "12", (1, 2), [True, 1], [1, "2"]]
        for values in invalid_values:
            calls: list[object] = []

            def candidate(input_value: list[int]) -> list[int]:
                calls.append(input_value)
                return sorted(input_value)

            with self.subTest(values=values):
                validation = validate_input(self.true_problem, values)
                result = check_sorted_integer_list(
                    candidate, values, self.true_problem
                )
                self.assertEqual(validation.status, InputStatus.OUTSIDE_CONTRACT)
                self.assertEqual(result.status, CheckStatus.OUTSIDE_CONTRACT)
                self.assertNotEqual(result.status, CheckStatus.REFUTED)
                self.assertIsNone(result.expected_output)
                self.assertIsNone(result.input_unchanged)
                self.assertTrue(result.reason)
                self.assertEqual(calls, [])

    def test_record_preconditions_must_match_registered_contract(self) -> None:
        inconsistent_problem = dict(self.true_problem)
        inconsistent_problem["preconditions"] = []

        result = validate_input(inconsistent_problem, [1, 2])

        self.assertEqual(result.status, InputStatus.OUTSIDE_CONTRACT)
        self.assertIn("preconditions must declare exactly", result.reason or "")

    def test_candidate_exception_is_error_not_refutation(self) -> None:
        def raises(_values: list[int]) -> list[int]:
            raise RuntimeError("deliberate target failure")

        result = check_sorted_integer_list(raises, [1], self.true_problem)

        self.assertEqual(result.status, CheckStatus.ERROR)
        self.assertNotEqual(result.status, CheckStatus.REFUTED)
        self.assertEqual(result.reason, "candidate raised RuntimeError")


if __name__ == "__main__":
    unittest.main()
