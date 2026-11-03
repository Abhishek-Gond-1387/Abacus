"""Normalize provider usage and summarize resource measurements per run."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any, Mapping
from urllib.parse import urlsplit


def normalize_provider_usage(
    payload: Mapping[str, Any] | None, *, provider_api_called: bool
) -> dict[str, int | str | None]:
    """Normalize common provider token fields without guessing missing values."""
    empty: dict[str, int | str | None] = {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "status": "not_applicable" if not provider_api_called else "unknown",
    }
    if not provider_api_called or not isinstance(payload, Mapping):
        return empty

    raw: Mapping[str, Any] = payload
    nested = payload.get("usage")
    if isinstance(nested, Mapping):
        raw = nested

    def count(*names: str) -> int | None:
        for name in names:
            value = raw.get(name)
            if type(value) is int and value >= 0:
                return value
        return None

    input_tokens = count("input_tokens", "prompt_tokens")
    output_tokens = count("output_tokens", "completion_tokens")
    total_tokens = count("total_tokens", "total")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    status = "known" if input_tokens is not None and output_tokens is not None and total_tokens is not None else "unknown"
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "status": status,
    }


@dataclass(frozen=True)
class PricingConfig:
    """A dated input/output price snapshot for one provider model."""

    provider_id: str
    model_id: str
    input_usd_per_million_tokens: float
    output_usd_per_million_tokens: float
    source_url: str
    checked_at: str

    def __post_init__(self) -> None:
        if (
            type(self.provider_id) is not str or not self.provider_id.strip()
            or type(self.model_id) is not str or not self.model_id.strip()
        ):
            raise ValueError("Pricing needs provider_id and model_id.")
        for name, value in (
            ("input_usd_per_million_tokens", self.input_usd_per_million_tokens),
            ("output_usd_per_million_tokens", self.output_usd_per_million_tokens),
        ):
            if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number.")
        if type(self.source_url) is not str or not self.source_url.strip():
            raise ValueError("Pricing source_url must be an HTTPS URL.")
        parsed_url = urlsplit(self.source_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("Pricing source_url must be an HTTPS URL.")
        if type(self.checked_at) is not str:
            raise ValueError("Pricing checked_at must be an ISO date (YYYY-MM-DD).")
        try:
            date.fromisoformat(self.checked_at)
        except (TypeError, ValueError) as error:
            raise ValueError("Pricing checked_at must be an ISO date (YYYY-MM-DD).") from error

    def calculate(self, *, input_tokens: int, output_tokens: int) -> float:
        """Calculate USD from the configured per-million input/output rates."""
        if type(input_tokens) is not int or input_tokens < 0:
            raise ValueError("input_tokens must be a non-negative integer.")
        if type(output_tokens) is not int or output_tokens < 0:
            raise ValueError("output_tokens must be a non-negative integer.")
        amount = (
            input_tokens * self.input_usd_per_million_tokens
            + output_tokens * self.output_usd_per_million_tokens
        ) / 1_000_000
        return round(amount, 10)

    def to_record(self) -> dict[str, Any]:
        return {
            "status": "configured",
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "input_usd_per_million_tokens": float(self.input_usd_per_million_tokens),
            "output_usd_per_million_tokens": float(self.output_usd_per_million_tokens),
            "source_url": self.source_url,
            "checked_at": self.checked_at,
        }


def calculate_actual_cost_usd(
    usage: Mapping[str, Any], pricing: PricingConfig | None, *, provider_api_called: bool
) -> float | None:
    """Return known actual cost, zero for no calls, or None when unpriced/unknown."""
    if not provider_api_called:
        return 0.0
    if pricing is None or usage.get("status") != "known":
        return None
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if type(input_tokens) is not int or type(output_tokens) is not int:
        return None
    return pricing.calculate(input_tokens=input_tokens, output_tokens=output_tokens)


def _statistics(values: list[int | float]) -> dict[str, int | float | None]:
    if not values:
        return {"count": 0, "median": None, "min": None, "max": None, "range": None}
    low, high = min(values), max(values)
    center = median(values)
    return {
        "count": len(values),
        "median": round(center, 6),
        "min": low,
        "max": high,
        "range": round(high - low, 6),
    }


def summarize_run_usage(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Report totals and median/range across runs without converting unknowns to zero."""
    runs = [record.get("usage", {}) for record in records]

    def metric(name: str) -> dict[str, int | float | None]:
        values = [
            value for run in runs
            if isinstance(run, Mapping)
            and type(value := run.get(name)) in {int, float}
            and math.isfinite(value)
        ]
        return _statistics(values)

    stage_names = ("planning", "proposals", "tests", "total")
    stage_summaries = {}
    for stage in stage_names:
        values = [
            duration
            for run in runs
            if isinstance(run, Mapping)
            and isinstance(run.get("stage_durations_seconds"), Mapping)
            and type(duration := run["stage_durations_seconds"].get(stage)) in {int, float}
            and math.isfinite(duration)
        ]
        stage_summaries[stage] = _statistics(values)

    known_token_runs = [
        run.get("provider_reported_token_usage", {})
        for run in runs
        if isinstance(run, Mapping)
        and isinstance(run.get("provider_reported_token_usage"), Mapping)
        and run["provider_reported_token_usage"].get("status") == "known"
    ]
    token_statuses = [
        run.get("provider_reported_token_usage", {}).get("status")
        for run in runs
        if isinstance(run, Mapping)
    ]
    unknown_tokens = token_statuses.count("unknown")
    not_applicable_tokens = token_statuses.count("not_applicable")
    token_summary_status = (
        "no_runs" if not token_statuses
        else
        "not_applicable" if token_statuses and not_applicable_tokens == len(token_statuses)
        else "unknown" if unknown_tokens
        else "known" if known_token_runs
        else "unknown"
    )
    token_fields = {}
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        values = [
            value for usage in known_token_runs
            if type(value := usage.get(field)) is int and value >= 0
        ]
        token_fields[field] = _statistics(values)

    call_counts = metric("model_call_count")
    successful_counts = metric("successful_model_call_count")
    failed_counts = metric("failed_model_call_count")
    retry_counts = metric("retry_call_count")
    call_runs = [
        run for run in runs
        if isinstance(run, Mapping) and type(run.get("model_call_count")) is int and run["model_call_count"] > 0
    ]
    actual_cost_values = [
        run["actual_cost_usd"] for run in call_runs
        if type(run.get("actual_cost_usd")) in {int, float}
        and math.isfinite(run["actual_cost_usd"])
    ]
    estimated_cost_values = [
        run["estimated_cost_usd"] for run in call_runs
        if type(run.get("estimated_cost_usd")) in {int, float}
        and math.isfinite(run["estimated_cost_usd"])
    ]
    actual_costs = _statistics(actual_cost_values)
    unknown_cost_runs = sum(
        run.get("actual_cost_usd") is None for run in call_runs
    )
    unknown_estimated_cost_runs = sum(
        run.get("estimated_cost_usd") is None for run in call_runs
    )
    any_api_calls = bool(call_runs)
    return {
        "run_count": len(records),
        "model_calls_per_run": call_counts,
        "model_calls_total": sum(
            run["model_call_count"] for run in runs
            if isinstance(run, Mapping) and type(run.get("model_call_count")) is int
        ),
        "successful_calls_per_run": successful_counts,
        "failed_calls_per_run": failed_counts,
        "retry_calls_per_run": retry_counts,
        "duration_seconds": metric("duration_seconds"),
        "stage_durations_seconds": stage_summaries,
        "provider_reported_token_usage": {
            "status": token_summary_status,
            "known_runs": len(known_token_runs),
            "unknown_runs": unknown_tokens,
            "not_applicable_runs": not_applicable_tokens,
            **token_fields,
        },
        "actual_cost_usd": {
            "status": "no_runs" if not records else "unknown" if any_api_calls and unknown_cost_runs else "known" if any_api_calls else "not_applicable",
            "unknown_runs": unknown_cost_runs,
            **actual_costs,
        },
        "estimated_cost_usd": {
            "status": "no_runs" if not records else "unknown" if any_api_calls and unknown_estimated_cost_runs else "known" if any_api_calls else "not_applicable",
            "unknown_runs": unknown_estimated_cost_runs,
            **_statistics(estimated_cost_values),
        },
    }
