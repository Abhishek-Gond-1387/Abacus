"""Day 34 provider retry classification and budget accounting fixtures."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from abacus.cli import _emergency_error_record, load_problem
from practice.budgets import BudgetConfig, BudgetTracker
from practice.provider_retries import (
    AmbiguousProviderError,
    PermanentProviderError,
    ProviderCallFailure,
    TransientProviderError,
    call_with_retries,
    classify_provider_error,
)
from practice.run_records import validate_run_record


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def tracker_for(*, max_model_calls: int = 3) -> BudgetTracker:
    tracker = BudgetTracker(BudgetConfig(
        max_rounds=1,
        max_wall_time_seconds=30,
        max_model_calls=max_model_calls,
        max_tokens=100,
        max_cost_usd=1.0,
    ))
    assert tracker.start_round()
    return tracker


class ProviderRetryTests(unittest.TestCase):
    def test_transient_failure_retries_with_backoff_and_budgets_each_attempt(self) -> None:
        tracker = tracker_for()
        calls = 0
        delays: list[float] = []

        def operation() -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TransientProviderError("temporary rate limit")
            return {"usage": {"input_tokens": 3, "output_tokens": 2}}

        response = call_with_retries(
            operation,
            tracker,
            estimated_tokens=10,
            estimated_cost_usd=0.1,
            estimated_duration_seconds=1,
            max_retries=2,
            backoff_seconds=0.05,
            sleep=delays.append,
        )

        snapshot = tracker.to_dict()
        self.assertEqual(calls, 2)
        self.assertEqual(delays, [0.05])
        self.assertEqual(response["usage"]["input_tokens"], 3)
        self.assertEqual(snapshot["usage"]["model_calls"], 2)
        self.assertEqual(snapshot["usage"]["failed_calls"], 1)
        self.assertEqual(snapshot["usage"]["successful_calls"], 1)
        self.assertEqual(snapshot["usage"]["retry_calls"], 1)
        self.assertEqual(snapshot["usage"]["provider_reported_token_usage"]["status"], "unknown")
        self.assertIsNone(snapshot["usage"]["provider_reported_token_usage"]["total_tokens"])
        self.assertEqual(snapshot["events"][2]["category"], "rate_limited")

    def test_auth_error_stops_without_repeating_request(self) -> None:
        tracker = tracker_for()
        calls = 0

        def operation() -> None:
            nonlocal calls
            calls += 1
            raise PermanentProviderError("invalid credentials", category="authentication_error")

        with self.assertRaises(ProviderCallFailure) as raised:
            call_with_retries(
                operation,
                tracker,
                estimated_tokens=10,
                estimated_cost_usd=0.1,
                estimated_duration_seconds=1,
                sleep=lambda _: self.fail("permanent errors must not back off"),
            )

        snapshot = tracker.to_dict()
        self.assertEqual(calls, 1)
        self.assertEqual(raised.exception.category, "authentication_error")
        self.assertFalse(raised.exception.outcome_ambiguous)
        self.assertEqual(snapshot["usage"]["model_calls"], 1)
        self.assertEqual(snapshot["usage"]["retry_calls"], 0)
        self.assertEqual(snapshot["events"][2]["category"], "authentication_error")

        spec = load_problem(PROJECT_ROOT / "problems" / "p01_true_sort.json")
        record = _emergency_error_record(
            spec,
            raised.exception,
            started_at=datetime.now(timezone.utc),
            duration_seconds=0.01,
        )
        self.assertTrue(record["model"]["provider_api_called"])
        self.assertEqual(record["usage"]["model_call_count"], 1)
        self.assertEqual(record["usage"]["failed_model_call_count"], 1)
        self.assertEqual(record["outcome"]["failure_category"], "authentication_error")
        self.assertIs(validate_run_record(record), record)

    def test_ambiguous_lost_response_is_not_retried_and_marks_billing_ambiguous(self) -> None:
        tracker = tracker_for()
        calls = 0

        def operation() -> None:
            nonlocal calls
            calls += 1
            raise AmbiguousProviderError("response lost after request")

        with self.assertRaises(ProviderCallFailure) as raised:
            call_with_retries(
                operation,
                tracker,
                estimated_tokens=10,
                estimated_cost_usd=0.1,
                estimated_duration_seconds=1,
            )

        self.assertEqual(calls, 1)
        self.assertTrue(raised.exception.outcome_ambiguous)
        self.assertEqual(raised.exception.billing_status, "ambiguous")
        self.assertEqual(tracker.to_dict()["usage"]["retry_calls"], 0)

    def test_retry_attempts_stop_at_model_call_budget_and_keep_error_categories(self) -> None:
        tracker = tracker_for(max_model_calls=2)
        calls = 0

        def operation() -> None:
            nonlocal calls
            calls += 1
            raise TransientProviderError("still rate limited")

        with self.assertRaises(ProviderCallFailure) as raised:
            call_with_retries(
                operation,
                tracker,
                estimated_tokens=10,
                estimated_cost_usd=0.1,
                estimated_duration_seconds=1,
                max_retries=4,
                backoff_seconds=0,
                sleep=lambda _: None,
            )

        snapshot = tracker.to_dict()
        self.assertEqual(raised.exception.category, "budget_exhausted")
        self.assertEqual(calls, 2)
        self.assertEqual(snapshot["usage"]["model_calls"], 2)
        self.assertEqual(snapshot["usage"]["retry_calls"], 1)
        self.assertEqual(
            [event["category"] for event in snapshot["events"] if event["event"] == "call_failed"],
            ["rate_limited", "rate_limited"],
        )

    def test_http_statuses_separate_auth_model_schema_transient_and_ambiguous_errors(self) -> None:
        class HttpError(Exception):
            def __init__(self, status_code: int) -> None:
                self.status_code = status_code

        cases = {
            401: ("authentication_error", False, False),
            404: ("model_not_found", False, False),
            422: ("invalid_request_or_schema", False, False),
            429: ("rate_limited", True, False),
            503: ("provider_response_ambiguous", False, True),
        }
        for status_code, expected in cases.items():
            with self.subTest(status_code=status_code):
                result = classify_provider_error(HttpError(status_code))
                self.assertEqual(
                    (result.category, result.retryable, result.outcome_ambiguous),
                    expected,
                )
        programming = classify_provider_error(RuntimeError("bug"))
        self.assertEqual(programming.category, "programming_error")
        self.assertFalse(programming.retryable)


if __name__ == "__main__":
    unittest.main()
