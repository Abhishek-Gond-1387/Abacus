from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from abacus.failure_categories import FailureCategory
from abacus.harness import HarnessStatus, check_case, check_cases
from abacus.problems import load_problem
from abacus.runner import ExecutionResult, RunCategory
from abacus.sorting_oracle import CheckStatus


PROBLEMS_DIRECTORY = Path(__file__).resolve().parents[1] / "problems"


class IndependentHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.true_problem = load_problem(
            PROBLEMS_DIRECTORY / "sort-ascending-true.json"
        )
        cls.false_problem = load_problem(
            PROBLEMS_DIRECTORY / "sort-ascending-false.json"
        )

    def test_true_problem_passes_known_cases_and_logs_tests_passed(self) -> None:
        cases = [[], [7], [3, 1, 3], [0, -3, 2, -1], [-2, 0, 4, 8]]

        with self.assertLogs("abacus.harness", level="INFO") as captured:
            batch = check_cases(self.true_problem, cases)

        self.assertEqual(len(batch.results), len(cases))
        self.assertEqual(batch.passed_count, len(cases))
        self.assertTrue(all(item.status == HarnessStatus.PASSED for item in batch.results))
        self.assertTrue(all(item.oracle_result is not None for item in batch.results))
        self.assertIn("tests passed", batch.summary)
        self.assertNotIn("proven", batch.summary.lower())
        self.assertIn("tests passed", captured.output[0])
        self.assertEqual(batch.results[2].target_result, [1, 3, 3])
        self.assertEqual(batch.results[2].input_value, (3, 1, 3))

    def test_false_problem_known_witness_is_independently_refuted(self) -> None:
        witness = self.false_problem["known_counterexample"]

        evidence = check_case(self.false_problem, witness["input"])

        self.assertEqual(evidence.status, HarnessStatus.REFUTED)
        self.assertEqual(
            evidence.failure_category,
            FailureCategory.PROPERTY_VIOLATION,
        )
        self.assertEqual(evidence.target_result, witness["actual_output"])
        self.assertEqual(
            list(evidence.oracle_result.expected_output), witness["expected_output"]
        )
        self.assertEqual(evidence.oracle_result.status, CheckStatus.REFUTED)
        self.assertIn("sorted reference", evidence.explanation)

    def test_out_of_contract_input_does_not_run_target(self) -> None:
        problem = dict(self.true_problem)
        problem["code"] = "raise AssertionError('target must not run')"

        evidence = check_case(problem, [True, 1])

        self.assertEqual(evidence.status, HarnessStatus.OUT_OF_CONTRACT)
        self.assertEqual(
            evidence.failure_category,
            FailureCategory.OUT_OF_CONTRACT,
        )
        self.assertFalse(evidence.input_valid)
        self.assertIsNone(evidence.execution)
        self.assertIsNone(evidence.target_exception)
        self.assertIsNone(evidence.oracle_result)
        self.assertIn("target was not run", evidence.explanation)

    def test_target_exception_is_separate_from_returned_value(self) -> None:
        problem = dict(self.true_problem)
        problem["code"] = (
            "def candidate(values):\n"
            "    raise ValueError('deliberate target failure')"
        )

        evidence = check_case(problem, [1, 2])

        self.assertEqual(evidence.status, HarnessStatus.ERROR)
        self.assertEqual(
            evidence.failure_category,
            FailureCategory.TARGET_EXCEPTION,
        )
        self.assertIsNone(evidence.target_result)
        self.assertEqual(evidence.target_exception.type_name, "ValueError")
        self.assertEqual(evidence.target_exception.phase, "target")
        self.assertIn("deliberate target failure", evidence.target_exception.message)
        self.assertIsNone(evidence.oracle_result)

    def test_target_mutation_is_refuted_by_the_oracle(self) -> None:
        problem = dict(self.true_problem)
        problem["code"] = (
            "def candidate(values):\n"
            "    values.sort()\n"
            "    return values"
        )

        evidence = check_case(problem, [3, 1, 2])

        self.assertEqual(evidence.status, HarnessStatus.REFUTED)
        self.assertEqual(
            evidence.failure_category,
            FailureCategory.PROPERTY_VIOLATION,
        )
        self.assertEqual(evidence.target_result, [1, 2, 3])
        self.assertFalse(evidence.oracle_result.input_unchanged)
        self.assertIn("mutated", evidence.explanation)

    def test_problem_path_is_loaded_and_validated(self) -> None:
        evidence = check_case(
            PROBLEMS_DIRECTORY / "sort-ascending-true.json",
            [2, 1],
        )

        self.assertEqual(evidence.status, HarnessStatus.PASSED)
        self.assertEqual(evidence.problem_id, "sort-ascending-true")

    def test_target_source_may_contain_protocol_placeholder_text(self) -> None:
        problem = dict(self.true_problem)
        problem["code"] = (
            "def candidate(values):\n"
            "    note = '__INPUT__ and __MARKER__'\n"
            "    return sorted(values)"
        )

        evidence = check_case(problem, [2, 1])

        self.assertEqual(evidence.status, HarnessStatus.PASSED)
        self.assertEqual(evidence.target_result, [1, 2])

    def test_batch_keeps_completed_results_if_iterator_later_fails(self) -> None:
        def incomplete_cases():
            yield [2, 1]
            raise RuntimeError("case source stopped")

        batch = check_cases(self.true_problem, incomplete_cases())

        self.assertEqual(len(batch.results), 1)
        self.assertTrue(batch.results[0].passed)
        self.assertIn("RuntimeError", batch.batch_error)
        self.assertIn("tests completed", batch.summary)
        self.assertNotIn("proven", batch.summary.lower())
        self.assertEqual(batch.failure_category, FailureCategory.INTERNAL_ERROR)

    @patch("abacus.harness.run_trusted_program")
    def test_timeout_is_categorized_without_refuting_the_claim(self, run_program) -> None:
        run_program.return_value = ExecutionResult(
            RunCategory.TIMEOUT,
            None,
            "",
            "",
            2.0,
            timed_out=True,
        )

        evidence = check_case(self.false_problem, [1, 2])

        self.assertEqual(evidence.status, HarnessStatus.TIMEOUT)
        self.assertEqual(evidence.failure_category, FailureCategory.TIMEOUT)
        self.assertIsNone(evidence.oracle_result)

    @patch("abacus.harness.run_trusted_program")
    def test_output_limit_is_a_runner_failure_not_a_property_violation(
        self, run_program
    ) -> None:
        run_program.return_value = ExecutionResult(
            RunCategory.OUTPUT_LIMIT,
            -1,
            "",
            "",
            0.1,
            output_limit_exceeded=True,
        )

        evidence = check_case(self.true_problem, [1, 2])

        self.assertEqual(evidence.status, HarnessStatus.OUTPUT_LIMIT)
        self.assertEqual(evidence.failure_category, FailureCategory.SANDBOX_FAILURE)
        self.assertIsNone(evidence.oracle_result)

    @patch("abacus.harness.check_sorted_integer_list")
    def test_oracle_exception_is_classified_as_oracle_defect(self, oracle):
        oracle.side_effect = RuntimeError("deliberate oracle failure")

        evidence = check_case(self.true_problem, [1, 2])

        self.assertEqual(evidence.status, HarnessStatus.ERROR)
        self.assertEqual(
            evidence.failure_category,
            FailureCategory.TEST_ORACLE_DEFECT,
        )
        self.assertIn("deliberate oracle failure", evidence.explanation)

    @patch("abacus.harness.run_trusted_program")
    def test_missing_worker_result_is_a_runner_protocol_failure(self, run_program):
        run_program.return_value = ExecutionResult(
            RunCategory.SUCCESS,
            0,
            "ordinary output only",
            "",
            0.1,
        )

        evidence = check_case(self.true_problem, [1, 2])

        self.assertEqual(evidence.status, HarnessStatus.ERROR)
        self.assertEqual(evidence.failure_category, FailureCategory.SANDBOX_FAILURE)
        self.assertIn("no harness result", evidence.explanation)

    @patch("abacus.harness._worker_source")
    def test_unexpected_harness_error_is_internal_error(self, make_source):
        make_source.side_effect = RuntimeError("deliberate harness assembly failure")

        evidence = check_case(self.true_problem, [1, 2])

        self.assertEqual(evidence.status, HarnessStatus.ERROR)
        self.assertEqual(evidence.failure_category, FailureCategory.INTERNAL_ERROR)
        self.assertIn("deliberate harness assembly failure", evidence.explanation)


if __name__ == "__main__":
    unittest.main()
