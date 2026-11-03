from __future__ import annotations

import unittest
from pathlib import Path

from abacus.problems import load_problem
from abacus.sorting_oracle import (
    SORTED_INTEGER_LIST_ORACLE_ID,
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
    def test_oracle_id_matches_problem_records(self) -> None:
        for filename in (
            "sort-ascending-true.json",
            "sort-ascending-false.json",
        ):
            with self.subTest(filename=filename):
                record = load_problem(PROBLEMS_DIRECTORY / filename)
                self.assertEqual(record["oracle_id"], SORTED_INTEGER_LIST_ORACLE_ID)

    def test_correct_sort_passes_required_edge_cases(self) -> None:
        cases = [
            [],
            [7],
            [3, 1, 3],
            [0, -3, 2, -1],
            [-2, 0, 4, 8],
        ]
        for values in cases:
            with self.subTest(values=values):
                original = list(values)
                result = check_sorted_integer_list(correct_sort, values)
                self.assertTrue(result.passed, result.reason)
                self.assertEqual(result.expected_output, tuple(sorted(original)))
                self.assertEqual(values, original)
                self.assertTrue(result.input_unchanged)

    def test_known_false_record_witness_fails_reverse_sort(self) -> None:
        record = load_problem(PROBLEMS_DIRECTORY / "sort-ascending-false.json")
        witness = record["known_counterexample"]

        result = check_sorted_integer_list(faulty_reverse_sort, witness["input"])

        self.assertFalse(result.passed)
        self.assertEqual(list(result.expected_output), witness["expected_output"])
        self.assertEqual(result.actual_output, witness["actual_output"])
        self.assertIn("sorted reference", result.reason or "")

    def test_in_place_sort_fails_the_no_mutation_requirement(self) -> None:
        values = [3, 1, 2]

        result = check_sorted_integer_list(faulty_in_place_sort, values)

        self.assertFalse(result.passed)
        self.assertFalse(result.input_unchanged)
        self.assertEqual(values, [1, 2, 3])
        self.assertEqual(result.reason, "candidate mutated the input list")

    def test_non_list_or_non_integer_outputs_fail(self) -> None:
        tuple_result = check_sorted_integer_list(
            lambda values: tuple(sorted(values)), [1]
        )
        boolean_result = check_sorted_integer_list(lambda values: [True], [1])

        self.assertFalse(tuple_result.passed)
        self.assertEqual(tuple_result.reason, "candidate output must be a list")
        self.assertFalse(boolean_result.passed)
        self.assertEqual(
            boolean_result.reason,
            "candidate output must contain only integers",
        )

    def test_boolean_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(TypeError, "booleans are excluded"):
            check_sorted_integer_list(correct_sort, [True])


if __name__ == "__main__":
    unittest.main()
