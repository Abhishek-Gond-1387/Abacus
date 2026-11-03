"""Shared vocabulary and records for final Abacus run outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FinalOutcome(str, Enum):
    """Allowed run-level outcomes; finite tests cannot establish PROVEN."""

    REFUTED = "REFUTED"
    TESTS_PASSED = "TESTS_PASSED"
    PROVEN = "PROVEN"
    UNRESOLVED = "UNRESOLVED"
    ERROR = "ERROR"


class OutcomeReason(str, Enum):
    """Machine-readable explanation attached to a final outcome."""

    CONFIRMED_COUNTEREXAMPLE = "confirmed_counterexample"
    NO_COUNTEREXAMPLE_FOUND = "no_counterexample_found"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    INVALID_EVIDENCE = "invalid_evidence"
    NO_USABLE_ORACLE = "no_usable_oracle"
    TIMEOUT = "timeout"
    EXTERNAL_ERROR = "external_error"
    INTERNAL_ERROR = "internal_error"
    FORMAL_PROOF_CONFIRMED = "formal_proof_confirmed"


@dataclass(frozen=True)
class RunOutcome:
    """Serializable run-level outcome with its reason and supporting evidence."""

    outcome: FinalOutcome
    reason: OutcomeReason
    message: str
    test_count: int | None = None
    methods: tuple[str, ...] = ()
    counterexample: Any | None = None
    failure_category: str | None = None
    proof_checker: str | None = None
    proof_evidence_id: str | None = None

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("An outcome message is required.")

        if self.outcome is FinalOutcome.TESTS_PASSED:
            if self.reason is not OutcomeReason.NO_COUNTEREXAMPLE_FOUND:
                raise ValueError("TESTS_PASSED requires no_counterexample_found.")
            if self.test_count is None or self.test_count <= 0:
                raise ValueError("TESTS_PASSED requires at least one completed test.")
            if not self.methods or any(not method.strip() for method in self.methods):
                raise ValueError("TESTS_PASSED requires at least one named test method.")
            if self.counterexample is not None:
                raise ValueError("TESTS_PASSED cannot include a counterexample.")

        elif self.outcome is FinalOutcome.REFUTED:
            if self.reason is not OutcomeReason.CONFIRMED_COUNTEREXAMPLE:
                raise ValueError("REFUTED requires confirmed_counterexample.")
            if self.counterexample is None:
                raise ValueError("REFUTED requires the confirmed counterexample.")

        elif self.outcome is FinalOutcome.UNRESOLVED:
            unresolved_reasons = {
                OutcomeReason.BUDGET_EXHAUSTED,
                OutcomeReason.CONFLICTING_EVIDENCE,
                OutcomeReason.INVALID_EVIDENCE,
                OutcomeReason.NO_USABLE_ORACLE,
                OutcomeReason.TIMEOUT,
            }
            if self.reason not in unresolved_reasons:
                raise ValueError("UNRESOLVED requires an evidence or budget reason.")

        elif self.outcome is FinalOutcome.ERROR:
            error_reasons = {
                OutcomeReason.EXTERNAL_ERROR,
                OutcomeReason.INTERNAL_ERROR,
            }
            if self.reason not in error_reasons or not self.failure_category:
                raise ValueError("ERROR requires an error reason and category.")

        elif self.outcome is FinalOutcome.PROVEN:
            if self.reason is not OutcomeReason.FORMAL_PROOF_CONFIRMED:
                raise ValueError("PROVEN requires formal_proof_confirmed.")
            if not self.proof_checker or not self.proof_evidence_id:
                raise ValueError("PROVEN requires a checker and proof evidence reference.")

    @classmethod
    def from_finite_tests(
        cls, *, test_count: int, methods: tuple[str, ...] | list[str]
    ) -> RunOutcome:
        """Record a completed finite suite as TESTS_PASSED, never as PROVEN."""
        return cls(
            outcome=FinalOutcome.TESTS_PASSED,
            reason=OutcomeReason.NO_COUNTEREXAMPLE_FOUND,
            message="All scheduled finite tests passed; this is not a proof.",
            test_count=test_count,
            methods=tuple(methods),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return stable string values suitable for JSON logs and reports."""
        return {
            "outcome": self.outcome.value,
            "reason": self.reason.value,
            "message": self.message,
            "test_count": self.test_count,
            "methods": list(self.methods),
            "counterexample": self.counterexample,
            "failure_category": self.failure_category,
            "proof_checker": self.proof_checker,
            "proof_evidence_id": self.proof_evidence_id,
        }
