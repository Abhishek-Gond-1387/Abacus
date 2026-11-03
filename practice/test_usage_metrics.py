"""Tests for provider usage normalization, pricing, and run summaries."""

from __future__ import annotations

import unittest

from practice.usage_metrics import (
    PricingConfig,
    calculate_actual_cost_usd,
    normalize_provider_usage,
    summarize_run_usage,
)


class UsageMetricsTests(unittest.TestCase):
    def test_no_provider_call_is_not_applicable(self) -> None:
        usage = normalize_provider_usage(None, provider_api_called=False)
        self.assertEqual(usage["status"], "not_applicable")
        self.assertIsNone(usage["input_tokens"])
        self.assertIsNone(usage["total_tokens"])

    def test_missing_provider_usage_is_unknown_not_zero(self) -> None:
        usage = normalize_provider_usage(None, provider_api_called=True)
        self.assertEqual(usage["status"], "unknown")
        self.assertIsNone(usage["input_tokens"])
        self.assertIsNone(usage["output_tokens"])
        self.assertIsNone(usage["total_tokens"])
        self.assertIsNone(calculate_actual_cost_usd(usage, None, provider_api_called=True))

    def test_provider_token_aliases_are_normalized(self) -> None:
        usage = normalize_provider_usage(
            {"usage": {"prompt_tokens": 12, "completion_tokens": 5}},
            provider_api_called=True,
        )
        self.assertEqual(
            usage,
            {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17, "status": "known"},
        )

    def test_cost_uses_configured_dated_rates(self) -> None:
        pricing = PricingConfig(
            provider_id="example-provider",
            model_id="example-model",
            input_usd_per_million_tokens=2.0,
            output_usd_per_million_tokens=8.0,
            source_url="https://example.com/pricing",
            checked_at="2026-11-03",
        )
        usage = normalize_provider_usage(
            {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
            provider_api_called=True,
        )
        self.assertEqual(calculate_actual_cost_usd(usage, pricing, provider_api_called=True), 10.0)
        self.assertEqual(pricing.to_record()["checked_at"], "2026-11-03")
        self.assertEqual(calculate_actual_cost_usd({}, None, provider_api_called=False), 0.0)

    def test_summary_reports_median_range_and_unknown_usage(self) -> None:
        records = [
            {
                "usage": {
                    "model_call_count": 1,
                    "successful_model_call_count": 1,
                    "retry_call_count": 0,
                    "duration_seconds": 1.0,
                    "stage_durations_seconds": {"planning": None, "proposals": None, "tests": 0.8, "total": 1.0},
                    "provider_reported_token_usage": {
                        "input_tokens": None, "output_tokens": None, "total_tokens": None, "status": "unknown",
                    },
                    "estimated_cost_usd": None,
                    "actual_cost_usd": None,
                }
            },
            {
                "usage": {
                    "model_call_count": 3,
                    "successful_model_call_count": 2,
                    "retry_call_count": 1,
                    "duration_seconds": 3.0,
                    "stage_durations_seconds": {"planning": None, "proposals": 0.5, "tests": 2.0, "total": 3.0},
                    "provider_reported_token_usage": {
                        "input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "status": "known",
                    },
                    "estimated_cost_usd": 0.02,
                    "actual_cost_usd": 0.01,
                }
            },
        ]

        summary = summarize_run_usage(records)
        self.assertEqual(summary["model_calls_total"], 4)
        self.assertEqual(summary["model_calls_per_run"]["median"], 2)
        self.assertEqual(summary["duration_seconds"]["range"], 2.0)
        self.assertEqual(summary["provider_reported_token_usage"]["status"], "unknown")
        self.assertEqual(summary["provider_reported_token_usage"]["unknown_runs"], 1)
        self.assertEqual(summary["provider_reported_token_usage"]["input_tokens"]["median"], 100)
        self.assertEqual(summary["actual_cost_usd"]["status"], "unknown")
        self.assertEqual(summary["actual_cost_usd"]["median"], 0.01)
        self.assertEqual(summary["estimated_cost_usd"]["status"], "unknown")
        self.assertEqual(summary["estimated_cost_usd"]["median"], 0.02)


if __name__ == "__main__":
    unittest.main()
