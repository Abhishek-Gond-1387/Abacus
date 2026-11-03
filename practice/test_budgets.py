"""Fixtures for bounded run budgets, retries, and partial logs."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from practice.budgets import BudgetConfig, BudgetStopReason, BudgetTracker
from practice.outcomes import FinalOutcome, OutcomeReason


class BudgetTrackerTests(unittest.TestCase):
    def test_normal_completion_records_usage_and_retry(self) -> None:
        now = [0.0]
        tracker = BudgetTracker(
            BudgetConfig(
                max_rounds=1,
                max_wall_time_seconds=10,
                max_model_calls=2,
                max_tokens=100,
                max_cost_usd=1.0,
            ),
            clock=lambda: now[0],
        )

        self.assertTrue(tracker.start_round())
        first = tracker.reserve_call(
            estimated_tokens=20,
            estimated_cost_usd=0.2,
            estimated_duration_seconds=2,
        )
        self.assertIsNotNone(first)
        tracker.fail_call(first, category="TRANSIENT_API")

        now[0] = 2.0
        retry = tracker.reserve_call(
            estimated_tokens=20,
            estimated_cost_usd=0.2,
            estimated_duration_seconds=1,
            retry=True,
        )
        self.assertIsNotNone(retry)
        tracker.settle_call(retry, actual_tokens=10, actual_cost_usd=0.1)
        tracker.finish_round()

        log = tracker.to_dict(evidence_complete=True)
        self.assertIsNone(tracker.stop_reason)
        self.assertEqual(log["usage"]["rounds"], 1)
        self.assertEqual(log["usage"]["model_calls"], 2)
        self.assertEqual(log["usage"]["retry_calls"], 1)
        self.assertEqual(log["usage"]["failed_calls"], 1)
        self.assertEqual(log["usage"]["tokens_committed_or_reserved"], 30)
        self.assertEqual(log["usage"]["tokens_actual"], 10)
        self.assertIsNone(log["run_outcome"])

    def test_tiny_token_budget_blocks_call_and_returns_unresolved(self) -> None:
        tracker = BudgetTracker(
            BudgetConfig(1, 10, 2, 4, 0.02),
            clock=lambda: 0.0,
        )
        self.assertTrue(tracker.start_round())
        reservation = tracker.reserve_call(
            estimated_tokens=8,
            estimated_cost_usd=0.005,
            estimated_duration_seconds=1,
        )

        self.assertIsNone(reservation)
        self.assertIs(tracker.stop_reason, BudgetStopReason.TOKEN_LIMIT)
        self.assertEqual(tracker.model_calls, 0)
        outcome = tracker.outcome_if_incomplete(evidence_complete=False)
        self.assertIs(outcome.outcome, FinalOutcome.UNRESOLVED)
        self.assertIs(outcome.reason, OutcomeReason.BUDGET_EXHAUSTED)
        self.assertIsNone(
            tracker.outcome_if_incomplete(evidence_complete=True)
        )

    def test_wall_time_preflight_denies_overlong_call(self) -> None:
        tracker = BudgetTracker(
            BudgetConfig(1, 4, 2, 20, 1.0),
            clock=lambda: 0.0,
        )
        self.assertTrue(tracker.start_round())

        reservation = tracker.reserve_call(
            estimated_tokens=1,
            estimated_cost_usd=0.001,
            estimated_duration_seconds=5,
        )

        self.assertIsNone(reservation)
        self.assertIs(tracker.stop_reason, BudgetStopReason.WALL_TIME_LIMIT)

    def test_elapsed_time_is_detected_when_a_call_fails(self) -> None:
        now = [0.0]
        tracker = BudgetTracker(
            BudgetConfig(1, 4, 2, 20, 1.0),
            clock=lambda: now[0],
        )
        tracker.start_round()
        reservation = tracker.reserve_call(
            estimated_tokens=1,
            estimated_cost_usd=0.001,
            estimated_duration_seconds=1,
        )
        now[0] = 5.0
        tracker.fail_call(reservation, category="TRANSIENT_API")

        self.assertIs(tracker.stop_reason, BudgetStopReason.WALL_TIME_LIMIT)
        self.assertEqual(
            tracker.outcome_if_incomplete(evidence_complete=False).reason,
            OutcomeReason.BUDGET_EXHAUSTED,
        )

    def test_round_limit_blocks_next_round(self) -> None:
        tracker = BudgetTracker(
            BudgetConfig(0, 10, 2, 20, 1.0),
            clock=lambda: 0.0,
        )

        self.assertFalse(tracker.start_round())
        self.assertIs(tracker.stop_reason, BudgetStopReason.ROUND_LIMIT)
        self.assertEqual(tracker.rounds, 0)

    def test_cost_limit_blocks_call_before_attempt(self) -> None:
        tracker = BudgetTracker(
            BudgetConfig(1, 10, 2, 20, 0.01),
            clock=lambda: 0.0,
        )
        tracker.start_round()

        reservation = tracker.reserve_call(
            estimated_tokens=1,
            estimated_cost_usd=0.02,
            estimated_duration_seconds=1,
        )

        self.assertIsNone(reservation)
        self.assertIs(tracker.stop_reason, BudgetStopReason.COST_LIMIT)
        self.assertEqual(tracker.model_calls, 0)

    def test_retry_is_counted_as_an_attempt_against_call_limit(self) -> None:
        tracker = BudgetTracker(
            BudgetConfig(1, 10, 1, 20, 1.0),
            clock=lambda: 0.0,
        )
        tracker.start_round()
        first = tracker.reserve_call(
            estimated_tokens=1,
            estimated_cost_usd=0.001,
            estimated_duration_seconds=1,
        )
        tracker.settle_call(first, actual_tokens=1, actual_cost_usd=0.001)

        retry = tracker.reserve_call(
            estimated_tokens=1,
            estimated_cost_usd=0.001,
            estimated_duration_seconds=1,
            retry=True,
        )

        self.assertIsNone(retry)
        self.assertIs(tracker.stop_reason, BudgetStopReason.MODEL_CALL_LIMIT)
        self.assertEqual(tracker.model_calls, 1)
        self.assertEqual(tracker.retry_calls, 0)

    def test_failed_attempt_keeps_estimated_usage_for_retry(self) -> None:
        tracker = BudgetTracker(
            BudgetConfig(1, 10, 3, 10, 1.0),
            clock=lambda: 0.0,
        )
        tracker.start_round()
        first = tracker.reserve_call(
            estimated_tokens=8,
            estimated_cost_usd=0.2,
            estimated_duration_seconds=1,
        )
        tracker.fail_call(first, category="TRANSIENT_API")

        retry = tracker.reserve_call(
            estimated_tokens=3,
            estimated_cost_usd=0.1,
            estimated_duration_seconds=1,
            retry=True,
        )

        self.assertIsNone(retry)
        self.assertIs(tracker.stop_reason, BudgetStopReason.TOKEN_LIMIT)
        self.assertEqual(tracker.model_calls, 1)
        self.assertEqual(tracker.to_dict()["usage"]["tokens_committed_or_reserved"], 8)

    def test_reported_usage_overrun_stops_future_calls(self) -> None:
        tracker = BudgetTracker(
            BudgetConfig(1, 10, 3, 10, 1.0),
            clock=lambda: 0.0,
        )
        tracker.start_round()
        reservation = tracker.reserve_call(
            estimated_tokens=5,
            estimated_cost_usd=0.2,
            estimated_duration_seconds=1,
        )
        tracker.settle_call(reservation, actual_tokens=12, actual_cost_usd=0.3)

        self.assertIs(tracker.stop_reason, BudgetStopReason.TOKEN_LIMIT)
        self.assertIsNotNone(tracker.outcome_if_incomplete(evidence_complete=False))

    def test_partial_budget_log_is_valid_json_with_unresolved_outcome(self) -> None:
        tracker = BudgetTracker(
            BudgetConfig(1, 10, 2, 2, 0.1),
            clock=lambda: 0.0,
        )
        tracker.start_round()
        self.assertIsNone(
            tracker.reserve_call(
                estimated_tokens=3,
                estimated_cost_usd=0.01,
                estimated_duration_seconds=1,
            )
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "partial-run.json"
            tracker.save_log(path, evidence_complete=False)
            log = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(log["budget_configured"]["max_tokens"], 2)
        self.assertEqual(log["usage"]["rounds"], 1)
        self.assertEqual(log["usage"]["model_calls"], 0)
        self.assertEqual(log["stop_reason"], "token_limit")
        self.assertEqual(log["run_outcome"]["outcome"], "UNRESOLVED")
        self.assertEqual(log["run_outcome"]["reason"], "budget_exhausted")


if __name__ == "__main__":
    unittest.main()
