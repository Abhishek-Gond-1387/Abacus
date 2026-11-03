"""Per-run round, wall-time, model-call, token, and cost budgets."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

if __package__:
    from .log_safety import sanitize_for_log
    from .outcomes import FinalOutcome, OutcomeReason, RunOutcome
    from .usage_metrics import normalize_provider_usage
else:
    from log_safety import sanitize_for_log
    from outcomes import FinalOutcome, OutcomeReason, RunOutcome
    from usage_metrics import normalize_provider_usage


class BudgetStopReason(str, Enum):
    ROUND_LIMIT = "round_limit"
    WALL_TIME_LIMIT = "wall_time_limit"
    MODEL_CALL_LIMIT = "model_call_limit"
    TOKEN_LIMIT = "token_limit"
    COST_LIMIT = "cost_limit"


@dataclass(frozen=True)
class BudgetConfig:
    max_rounds: int
    max_wall_time_seconds: float
    max_model_calls: int
    max_tokens: int
    max_cost_usd: float

    def __post_init__(self) -> None:
        integer_limits = (self.max_rounds, self.max_model_calls, self.max_tokens)
        if any(type(value) is not int or value < 0 for value in integer_limits):
            raise ValueError("Round, model-call, and token limits must be non-negative integers.")
        numeric_limits = (self.max_wall_time_seconds, self.max_cost_usd)
        if any(
            type(value) not in {int, float}
            or not math.isfinite(value)
            or value < 0
            for value in numeric_limits
        ):
            raise ValueError("Wall-time and cost limits must be finite and non-negative.")

    def to_dict(self) -> dict[str, int | float]:
        return {
            "max_rounds": self.max_rounds,
            "max_wall_time_seconds": float(self.max_wall_time_seconds),
            "max_model_calls": self.max_model_calls,
            "max_tokens": self.max_tokens,
            "max_cost_usd": float(self.max_cost_usd),
        }


@dataclass(frozen=True)
class CallReservation:
    call_id: int
    round_number: int
    estimated_tokens: int
    estimated_cost_usd: float
    is_retry: bool


class BudgetTracker:
    """Reserve budgets before calls and log actual or conservatively reserved use.

    Every retry is a separate model-call attempt. Failed calls keep their
    pre-call token and cost estimates because usage may be unknown.
    """

    def __init__(
        self,
        config: BudgetConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(config, BudgetConfig):
            raise TypeError("config must be a BudgetConfig.")
        self.config = config
        self._clock = clock
        self._started_at = self._clock()
        self._rounds = 0
        self._model_calls = 0
        self._successful_calls = 0
        self._retry_calls = 0
        self._failed_calls = 0
        self._tokens_committed = 0
        self._tokens_actual = 0
        self._actual_tokens_unknown = False
        self._cost_committed = 0.0
        self._cost_estimated = 0.0
        self._cost_actual = 0.0
        self._actual_cost_unknown = False
        self._provider_usage_unknown = False
        self._provider_usage_seen = 0
        self._provider_input_tokens = 0
        self._provider_output_tokens = 0
        self._provider_total_tokens = 0
        self._current_round: int | None = None
        self._round_call_count = 0
        self._next_call_id = 1
        self._pending: dict[int, CallReservation] = {}
        self._events: list[dict[str, Any]] = []
        self._stop_reason: BudgetStopReason | None = None

    @property
    def stop_reason(self) -> BudgetStopReason | None:
        return self._stop_reason

    @property
    def rounds(self) -> int:
        return self._rounds

    @property
    def model_calls(self) -> int:
        return self._model_calls

    @property
    def retry_calls(self) -> int:
        return self._retry_calls

    @property
    def successful_calls(self) -> int:
        return self._successful_calls

    def _elapsed(self) -> float:
        return max(0.0, self._clock() - self._started_at)

    def _check_elapsed(self) -> None:
        if self._elapsed() >= self.config.max_wall_time_seconds:
            self._stop(BudgetStopReason.WALL_TIME_LIMIT)

    def _stop(self, reason: BudgetStopReason) -> None:
        if self._stop_reason is None:
            self._stop_reason = reason
            self._events.append(
                {
                    "event": "budget_exhausted",
                    "reason": reason.value,
                    "elapsed_seconds": round(self._elapsed(), 6),
                }
            )

    def start_round(self) -> bool:
        """Start one logical round if round and time budgets permit it."""
        if self._stop_reason is not None:
            return False
        if self._current_round is not None:
            raise RuntimeError("Finish the active round before starting another.")
        self._check_elapsed()
        if self._stop_reason is not None:
            return False
        if self._rounds + 1 > self.config.max_rounds:
            self._stop(BudgetStopReason.ROUND_LIMIT)
            return False

        self._rounds += 1
        self._current_round = self._rounds
        self._round_call_count = 0
        self._events.append(
            {
                "event": "round_started",
                "round": self._current_round,
                "elapsed_seconds": round(self._elapsed(), 6),
            }
        )
        return True

    def reserve_call(
        self,
        *,
        estimated_tokens: int,
        estimated_cost_usd: float,
        estimated_duration_seconds: float,
        retry: bool = False,
    ) -> CallReservation | None:
        """Check remaining budgets and reserve one model-call attempt.

        The caller must not make the API call if this method returns None.
        Estimates should include prompt and maximum response usage.
        """
        self._validate_estimate(
            estimated_tokens, estimated_cost_usd, estimated_duration_seconds
        )
        if self._stop_reason is not None:
            return None
        if self._current_round is None:
            raise RuntimeError("Start a round before reserving a model call.")
        if retry and self._round_call_count == 0:
            raise ValueError("A retry requires an earlier call attempt in this round.")
        if self._pending:
            raise RuntimeError("Settle or fail the previous call before starting another.")

        if self._elapsed() + estimated_duration_seconds > self.config.max_wall_time_seconds:
            self._stop(BudgetStopReason.WALL_TIME_LIMIT)
            return None
        if self._model_calls + 1 > self.config.max_model_calls:
            self._stop(BudgetStopReason.MODEL_CALL_LIMIT)
            return None
        if self._tokens_committed + estimated_tokens > self.config.max_tokens:
            self._stop(BudgetStopReason.TOKEN_LIMIT)
            return None
        if self._cost_committed + estimated_cost_usd > self.config.max_cost_usd:
            self._stop(BudgetStopReason.COST_LIMIT)
            return None

        reservation = CallReservation(
            call_id=self._next_call_id,
            round_number=self._current_round,
            estimated_tokens=estimated_tokens,
            estimated_cost_usd=float(estimated_cost_usd),
            is_retry=retry,
        )
        self._next_call_id += 1
        self._model_calls += 1
        self._round_call_count += 1
        if retry:
            self._retry_calls += 1
        self._tokens_committed += estimated_tokens
        self._cost_committed += float(estimated_cost_usd)
        self._cost_estimated += float(estimated_cost_usd)
        self._pending[reservation.call_id] = reservation
        self._events.append(
            {
                "event": "call_reserved",
                "call_id": reservation.call_id,
                "round": reservation.round_number,
                "retry": retry,
                "estimated_tokens": estimated_tokens,
                "estimated_cost_usd": round(float(estimated_cost_usd), 8),
                "estimated_duration_seconds": round(estimated_duration_seconds, 6),
            }
        )
        return reservation

    @staticmethod
    def _validate_estimate(
        estimated_tokens: int,
        estimated_cost_usd: float,
        estimated_duration_seconds: float,
    ) -> None:
        if type(estimated_tokens) is not int or estimated_tokens < 0:
            raise ValueError("estimated_tokens must be a non-negative integer.")
        for label, value in (
            ("estimated_cost_usd", estimated_cost_usd),
            ("estimated_duration_seconds", estimated_duration_seconds),
        ):
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{label} must be finite and non-negative.")

    def settle_call(
        self,
        reservation: CallReservation,
        *,
        actual_tokens: int | None,
        actual_cost_usd: float | None,
        provider_usage: Mapping[str, Any] | None = None,
    ) -> None:
        """Replace estimates with reported usage after a completed call."""
        self._require_pending(reservation)
        if actual_tokens is not None:
            self._validate_estimate(actual_tokens, 0.0, 0.0)
        if actual_cost_usd is not None:
            self._validate_estimate(0, actual_cost_usd, 0.0)
        reported_usage = normalize_provider_usage(provider_usage, provider_api_called=True)
        del self._pending[reservation.call_id]
        self._successful_calls += 1
        self._provider_usage_seen += 1
        if reported_usage["status"] == "known":
            self._provider_input_tokens += int(reported_usage["input_tokens"])
            self._provider_output_tokens += int(reported_usage["output_tokens"])
            self._provider_total_tokens += int(reported_usage["total_tokens"])
        else:
            self._provider_usage_unknown = True
        if actual_tokens is None and reported_usage["status"] == "known":
            actual_tokens = int(reported_usage["total_tokens"])
        if actual_tokens is None:
            self._actual_tokens_unknown = True
        else:
            self._tokens_committed += actual_tokens - reservation.estimated_tokens
            self._tokens_actual += actual_tokens
        if actual_cost_usd is None:
            self._actual_cost_unknown = True
        else:
            self._cost_committed += float(actual_cost_usd) - reservation.estimated_cost_usd
            self._cost_actual += float(actual_cost_usd)
        self._events.append(
            {
                "event": "call_settled",
                "call_id": reservation.call_id,
                "actual_tokens": actual_tokens,
                "actual_cost_usd": round(float(actual_cost_usd), 8) if actual_cost_usd is not None else None,
                "provider_reported_token_usage": reported_usage,
            }
        )
        if self._tokens_committed > self.config.max_tokens:
            self._stop(BudgetStopReason.TOKEN_LIMIT)
        elif self._cost_committed > self.config.max_cost_usd:
            self._stop(BudgetStopReason.COST_LIMIT)
        self._check_elapsed()

    def fail_call(self, reservation: CallReservation, *, category: str) -> None:
        """Record a failed attempt; keep its estimates charged conservatively."""
        self._require_pending(reservation)
        if type(category) is not str or not category.strip():
            raise ValueError("A failure category is required.")
        del self._pending[reservation.call_id]
        self._failed_calls += 1
        self._provider_usage_unknown = True
        self._provider_usage_seen += 1
        self._actual_tokens_unknown = True
        self._actual_cost_unknown = True
        self._events.append(
            {
                "event": "call_failed",
                "call_id": reservation.call_id,
                "category": category,
                "estimated_usage_kept": True,
            }
        )
        self._check_elapsed()

    def _require_pending(self, reservation: CallReservation) -> None:
        if (
            not isinstance(reservation, CallReservation)
            or self._pending.get(reservation.call_id) != reservation
        ):
            raise ValueError("Reservation is unknown, already settled, or belongs elsewhere.")

    def finish_round(self) -> None:
        if self._current_round is None:
            raise RuntimeError("There is no active round.")
        if any(
            reservation.round_number == self._current_round
            for reservation in self._pending.values()
        ):
            raise RuntimeError("Settle or fail the active call before finishing the round.")
        self._events.append(
            {"event": "round_finished", "round": self._current_round}
        )
        self._current_round = None
        self._round_call_count = 0
        self._check_elapsed()

    def outcome_if_incomplete(self, *, evidence_complete: bool) -> RunOutcome | None:
        """Return UNRESOLVED on exhaustion only while evidence is incomplete."""
        self._check_elapsed()
        if self._stop_reason is None or evidence_complete:
            return None
        return RunOutcome(
            outcome=FinalOutcome.UNRESOLVED,
            reason=OutcomeReason.BUDGET_EXHAUSTED,
            message=f"Evidence is incomplete because {self._stop_reason.value} was reached.",
        )

    def to_dict(self, *, evidence_complete: bool = False) -> dict[str, Any]:
        self._check_elapsed()
        outcome = self.outcome_if_incomplete(evidence_complete=evidence_complete)
        provider_usage_status = (
            "not_applicable" if self._model_calls == 0
            else "unknown" if self._provider_usage_unknown or self._provider_usage_seen < self._model_calls
            else "known"
        )
        provider_usage = {
            "input_tokens": self._provider_input_tokens if provider_usage_status == "known" else None,
            "output_tokens": self._provider_output_tokens if provider_usage_status == "known" else None,
            "total_tokens": self._provider_total_tokens if provider_usage_status == "known" else None,
            "status": provider_usage_status,
        }
        actual_tokens_unknown = self._actual_tokens_unknown or self._provider_usage_seen < self._model_calls
        actual_cost_unknown = self._actual_cost_unknown or self._provider_usage_seen < self._model_calls
        return {
            "budget_configured": self.config.to_dict(),
            "usage": {
                "rounds": self._rounds,
                "model_calls": self._model_calls,
                "successful_calls": self._successful_calls,
                "retry_calls": self._retry_calls,
                "failed_calls": self._failed_calls,
                "tokens_committed_or_reserved": self._tokens_committed,
                "tokens_actual": None if actual_tokens_unknown else self._tokens_actual,
                "tokens_actual_status": (
                    "not_applicable" if self._model_calls == 0
                    else "unknown" if actual_tokens_unknown
                    else "known"
                ),
                "tokens_open_reserved": sum(
                    reservation.estimated_tokens
                    for reservation in self._pending.values()
                ),
                "cost_committed_or_reserved_usd": round(self._cost_committed, 8),
                "cost_estimated_usd": round(self._cost_estimated, 8),
                "cost_actual_usd": None if actual_cost_unknown else round(self._cost_actual, 8),
                "cost_actual_status": (
                    "not_applicable" if self._model_calls == 0
                    else "unknown" if actual_cost_unknown
                    else "known"
                ),
                "cost_open_reserved_usd": round(
                    sum(
                        reservation.estimated_cost_usd
                        for reservation in self._pending.values()
                    ),
                    8,
                ),
                "elapsed_seconds": round(self._elapsed(), 6),
                "provider_reported_token_usage": provider_usage,
            },
            "stop_reason": (
                self._stop_reason.value if self._stop_reason is not None else None
            ),
            "run_outcome": outcome.to_dict() if outcome is not None else None,
            "events": list(self._events),
        }

    def save_log(
        self, path: str | Path, *, evidence_complete: bool = False
    ) -> Path:
        """Atomically save configured limits, usage, partial events, and stop reason."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        payload = json.dumps(
            sanitize_for_log(self.to_dict(evidence_complete=evidence_complete)),
            indent=2,
            ensure_ascii=False,
        )
        temporary.write_text(payload + "\n", encoding="utf-8")
        temporary.replace(destination)
        return destination
