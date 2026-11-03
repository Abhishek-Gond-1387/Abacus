from __future__ import annotations

import unittest
from datetime import timedelta
from pathlib import Path

from hypothesis import find, given, settings, strategies as st

from abacus.harness import HarnessStatus, check_case
from abacus.problems import load_problem
from abacus.sorting_oracle import CheckStatus


PROBLEMS_DIRECTORY = Path(__file__).resolve().parents[1] / "problems"
SORTING_LISTS = st.lists(
    st.integers(min_value=-20, max_value=20),
    min_size=0,
    max_size=12,
)
BOUNDED_SETTINGS = settings(
    max_examples=20,
    derandomize=True,
    database=None,
    deadline=timedelta(seconds=5),
)
FIND_SETTINGS = settings(
    max_examples=40,
    derandomize=True,
    database=None,
    deadline=timedelta(seconds=5),
)


class HypothesisSortingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.true_problem = load_problem(
            PROBLEMS_DIRECTORY / "sort-ascending-true.json"
        )
        cls.false_problem = load_problem(
            PROBLEMS_DIRECTORY / "sort-ascending-false.json"
        )

    @BOUNDED_SETTINGS
    @given(values=SORTING_LISTS)
    def test_true_problem_passes_generated_contract_inputs(
        self, values: list[int]
    ) -> None:
        evidence = check_case(self.true_problem, values)

        self.assertTrue(evidence.input_valid)
        self.assertEqual(evidence.status, HarnessStatus.PASSED, evidence.explanation)
        self.assertEqual(evidence.oracle_result.status, CheckStatus.PASSED)

    def test_faulty_problem_gets_oracle_confirmed_shrunk_counterexample(self) -> None:
        # Hypothesis proposes and shrinks inputs; only the harness decides a refutation.
        def is_refuted(values: list[int]) -> bool:
            evidence = check_case(self.false_problem, values)
            return evidence.status is HarnessStatus.REFUTED

        witness = find(SORTING_LISTS, is_refuted, settings=FIND_SETTINGS)
        evidence = check_case(self.false_problem, witness)

        self.assertTrue(evidence.input_valid)
        self.assertEqual(evidence.status, HarnessStatus.REFUTED)
        self.assertEqual(evidence.oracle_result.status, CheckStatus.REFUTED)
        self.assertNotEqual(evidence.target_result, list(evidence.oracle_result.expected_output))


if __name__ == "__main__":
    unittest.main()
