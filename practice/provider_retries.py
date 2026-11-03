"""Bounded, classification-based retries for future provider adapters."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, TypeVar

from .budgets import BudgetTracker
from .usage_metrics import PricingConfig, calculate_actual_cost_usd, normalize_provider_usage


ResponseT = TypeVar("ResponseT")


@dataclass(frozen=True)
class FailureClassification:
    category: str
    retryable: bool
    outcome_ambiguous: bool


class ProviderError(Exception):
    """Base error for provider adapters to classify explicitly."""

    def __init__(self, message: str, *, category: str) -> None:
        super().__init__(message)
        self.category = category


class TransientProviderError(ProviderError):
    """A temporary error known to occur before the provider completes work."""

    def __init__(self, message: str, *, category: str = "rate_limited") -> None:
        super().__init__(message, category=category)


class PermanentProviderError(ProviderError):
    """A permanent authentication, model, request, or schema error."""

    def __init__(self, message: str, *, category: str = "provider_configuration_error") -> None:
        super().__init__(message, category=category)


class AmbiguousProviderError(ProviderError):
    """The request may have completed even though its response was lost."""

    def __init__(self, message: str, *, category: str = "response_lost") -> None:
        super().__init__(message, category=category)


class ProviderCallFailure(RuntimeError):
    """A failed provider operation with attempt and ambiguity metadata."""

    def __init__(
        self,
        message: str,
        *,
        category: str,
        attempts: int,
        outcome_ambiguous: bool,
        budget_snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.attempts = attempts
        self.retry_attempts = max(0, attempts - 1)
        self.outcome_ambiguous = outcome_ambiguous
        self.billing_status = "ambiguous" if outcome_ambiguous else "unknown"
        self.budget_snapshot = dict(budget_snapshot) if budget_snapshot is not None else None


def classify_provider_error(error: Exception) -> FailureClassification:
    """Classify known errors; unknown exceptions are programming failures."""
    if isinstance(error, TransientProviderError):
        return FailureClassification(error.category, retryable=True, outcome_ambiguous=False)
    if isinstance(error, PermanentProviderError):
        return FailureClassification(error.category, retryable=False, outcome_ambiguous=False)
    if isinstance(error, AmbiguousProviderError):
        return FailureClassification(error.category, retryable=False, outcome_ambiguous=True)
    if isinstance(error, ProviderError):
        return FailureClassification(error.category, retryable=False, outcome_ambiguous=False)

    status_code = getattr(error, "status_code", None)
    if status_code is None:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
    if status_code in {401, 403}:
        return FailureClassification("authentication_error", retryable=False, outcome_ambiguous=False)
    if status_code == 404:
        return FailureClassification("model_not_found", retryable=False, outcome_ambiguous=False)
    if status_code in {400, 422}:
        return FailureClassification("invalid_request_or_schema", retryable=False, outcome_ambiguous=False)
    if status_code == 429:
        return FailureClassification("rate_limited", retryable=True, outcome_ambiguous=False)
    if status_code == 408 or (isinstance(status_code, int) and 500 <= status_code <= 599):
        return FailureClassification("provider_response_ambiguous", retryable=False, outcome_ambiguous=True)
    if isinstance(error, (TimeoutError, ConnectionError)):
        return FailureClassification("transport_outcome_ambiguous", retryable=False, outcome_ambiguous=True)
    return FailureClassification("programming_error", retryable=False, outcome_ambiguous=False)


def _default_usage_getter(response: Any) -> Mapping[str, Any] | None:
    if isinstance(response, Mapping):
        usage = response.get("usage")
        if isinstance(usage, Mapping):
            return usage
        return response
    usage = getattr(response, "usage", None)
    return usage if isinstance(usage, Mapping) else None


def call_with_retries(
    operation: Callable[[], ResponseT],
    tracker: BudgetTracker,
    *,
    estimated_tokens: int,
    estimated_cost_usd: float,
    estimated_duration_seconds: float,
    pricing: PricingConfig | None = None,
    max_retries: int = 2,
    backoff_seconds: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
    usage_getter: Callable[[ResponseT], Mapping[str, Any] | None] = _default_usage_getter,
) -> ResponseT:
    """Run one provider operation, retrying only explicitly safe transient errors.

    Every attempt is reserved and counted by ``BudgetTracker`` before calling
    the provider. A denied retry never reaches ``operation``. Timeouts,
    connection loss, and 5xx responses are treated as ambiguous and are not
    retried automatically because the service may already have completed work.
    """
    if type(max_retries) is not int or max_retries < 0:
        raise ValueError("max_retries must be a non-negative integer.")
    if type(backoff_seconds) not in {int, float} or not math.isfinite(backoff_seconds) or backoff_seconds < 0:
        raise ValueError("backoff_seconds must be finite and non-negative.")

    for attempt_index in range(max_retries + 1):
        reservation = tracker.reserve_call(
            estimated_tokens=estimated_tokens,
            estimated_cost_usd=estimated_cost_usd,
            estimated_duration_seconds=estimated_duration_seconds,
            retry=attempt_index > 0,
        )
        if reservation is None:
            raise ProviderCallFailure(
                f"Provider call stopped by budget: {tracker.stop_reason.value if tracker.stop_reason else 'unknown'}.",
                category="budget_exhausted",
                attempts=attempt_index,
                outcome_ambiguous=False,
                budget_snapshot=tracker.to_dict(evidence_complete=False),
            )
        try:
            response = operation()
        except Exception as error:
            classification = classify_provider_error(error)
            tracker.fail_call(reservation, category=classification.category)
            if classification.retryable and attempt_index < max_retries:
                sleep(backoff_seconds * (2**attempt_index))
                continue
            raise ProviderCallFailure(
                f"Provider call failed ({classification.category}): {error}",
                category=classification.category,
                attempts=attempt_index + 1,
                outcome_ambiguous=classification.outcome_ambiguous,
                budget_snapshot=tracker.to_dict(evidence_complete=False),
            ) from error

        try:
            reported_payload = usage_getter(response)
        except Exception as error:
            tracker.settle_call(reservation, actual_tokens=None, actual_cost_usd=None)
            raise ProviderCallFailure(
                f"Provider response was received but its usage metadata could not be read: {error}",
                category="usage_metadata_error",
                attempts=attempt_index + 1,
                outcome_ambiguous=False,
                budget_snapshot=tracker.to_dict(evidence_complete=False),
            ) from error
        normalized_usage = normalize_provider_usage(reported_payload, provider_api_called=True)
        actual_tokens = normalized_usage["total_tokens"] if normalized_usage["status"] == "known" else None
        actual_cost = calculate_actual_cost_usd(
            normalized_usage, pricing, provider_api_called=True
        )
        tracker.settle_call(
            reservation,
            actual_tokens=actual_tokens,
            actual_cost_usd=actual_cost,
            provider_usage=reported_payload,
        )
        return response

    raise AssertionError("bounded retry loop ended without a response or failure")
