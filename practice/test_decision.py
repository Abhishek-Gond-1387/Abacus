"""Fixtures for the evidence-based final outcome policy."""

from __future__ import annotations

import copy
import unittest

from practice.decision import decide
from practice.outcomes import FinalOutcome, OutcomeReason


CONTRACT = {
    "contract_id": "sort-integers-v1",
    "oracle_id": "python-sorted-v1",
    "scheduled_test_count": 2,
    "required_methods": ["fixed", "hypothesis"],
    "oracle_usable": True,
}


def passing_record(test_id: str, method: str) -> dict:
    return {
        "test_id": test_id,
        "method": method,
        "contract_id": CONTRACT["contract_id"],
        "status": "completed",
        "contract_valid": True,
        "oracle_id": CONTRACT["oracle_id"],
        "input": [1, 2],
        "actual": [1, 2],
        "expected": [1, 2],
        "category": "CASE_PASSED",
    }


def passing_suite() -> list[dict]:
    return [
        passing_record("fixed-1", "fixed"),
        passing_record("hypothesis-1", "hypothesis"),
    ]


class DecisionPolicyTests(unittest.TestCase):
    def test_replayed_contract_valid_counterexample_refutes(self) -> None:
        counterexample = passing_record("fixed-1", "fixed")
        counterexample.update(
            {
                "input": [2, 1],
                "actual": [2, 1],
                "expected": [1, 2],
                "category": "PROPERTY_VIOLATION",
                "replay_confirmed": True,
            }
        )

        outcome = decide([counterexample], CONTRACT)

        self.assertIs(outcome.outcome, FinalOutcome.REFUTED)
        self.assertIs(outcome.reason, OutcomeReason.CONFIRMED_COUNTEREXAMPLE)
        self.assertEqual(outcome.counterexample["input"], [2, 1])

    def test_complete_finite_suite_returns_tests_passed(self) -> None:
        outcome = decide(passing_suite(), CONTRACT)

        self.assertIs(outcome.outcome, FinalOutcome.TESTS_PASSED)
        self.assertIs(outcome.reason, OutcomeReason.NO_COUNTEREXAMPLE_FOUND)
        self.assertEqual(outcome.test_count, 2)
        self.assertEqual(outcome.methods, ("fixed", "hypothesis"))

    def test_timeout_is_unresolved(self) -> None:
        timeout = {
            "test_id": "hypothesis-1",
            "method": "hypothesis",
            "contract_id": CONTRACT["contract_id"],
            "status": "timeout",
            "category": "TIMEOUT",
        }

        outcome = decide([passing_record("fixed-1", "fixed"), timeout], CONTRACT)

        self.assertIs(outcome.outcome, FinalOutcome.UNRESOLVED)
        self.assertIs(outcome.reason, OutcomeReason.TIMEOUT)

    def test_budget_exhaustion_is_unresolved(self) -> None:
        exhausted = {
            "test_id": "hypothesis-1",
            "method": "hypothesis",
            "contract_id": CONTRACT["contract_id"],
            "status": "budget_exhausted",
            "category": "BUDGET_EXHAUSTED",
        }

        outcome = decide([passing_record("fixed-1", "fixed"), exhausted], CONTRACT)

        self.assertIs(outcome.outcome, FinalOutcome.UNRESOLVED)
        self.assertIs(outcome.reason, OutcomeReason.BUDGET_EXHAUSTED)

    def test_invalid_or_out_of_contract_record_is_unresolved(self) -> None:
        invalid = {
            "test_id": "proposal-1",
            "method": "fixed",
            "contract_id": CONTRACT["contract_id"],
            "status": "invalid",
            "category": "OUT_OF_CONTRACT",
        }

        outcome = decide([invalid], CONTRACT)

        self.assertIs(outcome.outcome, FinalOutcome.UNRESOLVED)
        self.assertIs(outcome.reason, OutcomeReason.INVALID_EVIDENCE)

    def test_contract_invalid_record_cannot_refute(self) -> None:
        invalid = passing_record("fixed-1", "fixed")
        invalid.update(
            {
                "contract_valid": False,
                "actual": [2, 1],
                "expected": [1, 2],
                "category": "PROPERTY_VIOLATION",
                "replay_confirmed": True,
            }
        )

        outcome = decide([invalid], CONTRACT)

        self.assertIs(outcome.outcome, FinalOutcome.UNRESOLVED)
        self.assertIs(outcome.reason, OutcomeReason.INVALID_EVIDENCE)

    def test_conflicting_duplicate_test_ids_are_unresolved(self) -> None:
        first = passing_record("fixed-1", "fixed")
        second = copy.deepcopy(first)
        second.update({"actual": [2, 1], "category": "PROPERTY_VIOLATION"})

        outcome = decide([first, second], CONTRACT)

        self.assertIs(outcome.outcome, FinalOutcome.UNRESOLVED)
        self.assertIs(outcome.reason, OutcomeReason.CONFLICTING_EVIDENCE)

    def test_contradictory_case_label_is_unresolved(self) -> None:
        contradictory = passing_record("fixed-1", "fixed")
        contradictory["actual"] = [2, 1]

        outcome = decide([contradictory], CONTRACT)

        self.assertIs(outcome.outcome, FinalOutcome.UNRESOLVED)
        self.assertIs(outcome.reason, OutcomeReason.CONFLICTING_EVIDENCE)

    def test_same_input_with_conflicting_outputs_is_unresolved(self) -> None:
        first = passing_record("fixed-1", "fixed")
        second = passing_record("hypothesis-1", "hypothesis")
        second.update(
            {
                "actual": [2, 1],
                "category": "PROPERTY_VIOLATION",
                "replay_confirmed": True,
            }
        )

        outcome = decide([first, second], CONTRACT)

        self.assertIs(outcome.outcome, FinalOutcome.UNRESOLVED)
        self.assertIs(outcome.reason, OutcomeReason.CONFLICTING_EVIDENCE)

    def test_mismatch_without_successful_replay_is_unresolved(self) -> None:
        unreplayed = passing_record("fixed-1", "fixed")
        unreplayed.update(
            {"actual": [2, 1], "expected": [1, 2], "category": None}
        )

        outcome = decide([unreplayed], CONTRACT)

        self.assertIs(outcome.outcome, FinalOutcome.UNRESOLVED)
        self.assertIs(outcome.reason, OutcomeReason.INVALID_EVIDENCE)

    def test_api_error_returns_error_with_category(self) -> None:
        error = {
            "test_id": "model-1",
            "method": "llm",
            "contract_id": CONTRACT["contract_id"],
            "status": "api_error",
            "failure_category": "RATE_LIMIT",
        }
        contract = {**CONTRACT, "required_methods": ["llm"], "scheduled_test_count": 1}

        outcome = decide([error], contract)

        self.assertIs(outcome.outcome, FinalOutcome.ERROR)
        self.assertIs(outcome.reason, OutcomeReason.EXTERNAL_ERROR)
        self.assertEqual(outcome.failure_category, "RATE_LIMIT")

    def test_internal_error_returns_error_with_category(self) -> None:
        error = {
            "test_id": "runner-1",
            "method": "fixed",
            "contract_id": CONTRACT["contract_id"],
            "status": "internal_error",
            "failure_category": "HARNESS_BUG",
        }
        contract = {**CONTRACT, "required_methods": ["fixed"], "scheduled_test_count": 1}

        outcome = decide([error], contract)

        self.assertIs(outcome.outcome, FinalOutcome.ERROR)
        self.assertIs(outcome.reason, OutcomeReason.INTERNAL_ERROR)
        self.assertEqual(outcome.failure_category, "HARNESS_BUG")

    def test_missing_oracle_is_unresolved(self) -> None:
        contract = {**CONTRACT, "oracle_id": None, "oracle_usable": False}

        outcome = decide(passing_suite(), contract)

        self.assertIs(outcome.outcome, FinalOutcome.UNRESOLVED)
        self.assertIs(outcome.reason, OutcomeReason.NO_USABLE_ORACLE)

        mismatch_without_oracle = passing_record("fixed-1", "fixed")
        mismatch_without_oracle.update(
            {
                "actual": [2, 1],
                "expected": [1, 2],
                "category": "PROPERTY_VIOLATION",
                "replay_confirmed": True,
            }
        )
        untrusted_result = decide([mismatch_without_oracle], contract)
        self.assertIs(untrusted_result.outcome, FinalOutcome.UNRESOLVED)
        self.assertIs(untrusted_result.reason, OutcomeReason.NO_USABLE_ORACLE)

    def test_incomplete_suite_is_unresolved(self) -> None:
        outcome = decide([passing_record("fixed-1", "fixed")], CONTRACT)

        self.assertIs(outcome.outcome, FinalOutcome.UNRESOLVED)
        self.assertIs(outcome.reason, OutcomeReason.INCOMPLETE_EVIDENCE)

    def test_missing_required_method_is_unresolved(self) -> None:
        records = [
            passing_record("fixed-1", "fixed"),
            passing_record("fixed-2", "fixed"),
        ]

        outcome = decide(records, CONTRACT)

        self.assertIs(outcome.outcome, FinalOutcome.UNRESOLVED)
        self.assertIs(outcome.reason, OutcomeReason.INCOMPLETE_EVIDENCE)

    def test_llm_wording_does_not_change_the_outcome(self) -> None:
        baseline = passing_suite()
        annotated = copy.deepcopy(baseline)
        for record in annotated:
            record["llm_verdict"] = "PROVEN"
            record["llm_explanation"] = "The implementation is certainly correct."

        self.assertEqual(decide(baseline, CONTRACT), decide(annotated, CONTRACT))


if __name__ == "__main__":
    unittest.main()
