"""Trusted outcome policy over normalized evidence; performs no code execution or I/O.

This policy consumes normalized records from trusted harness components. It
does not execute the target, call an oracle, call a model, or perform I/O.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from practice.outcomes import FinalOutcome, OutcomeReason, RunOutcome


class EvidenceStatus(str, Enum):
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    BUDGET_EXHAUSTED = "budget_exhausted"
    API_ERROR = "api_error"
    INTERNAL_ERROR = "internal_error"
    INVALID = "invalid"


@dataclass(frozen=True)
class ClaimContract:
    contract_id: str
    oracle_id: str | None
    scheduled_test_count: int
    required_methods: tuple[str, ...]
    oracle_usable: bool = True


@dataclass(frozen=True)
class EvidenceRecord:
    test_id: str
    method: str
    contract_id: str
    status: EvidenceStatus
    contract_valid: bool | None = None
    oracle_id: str | None = None
    input_value: Any = None
    actual: Any = None
    expected: Any = None
    replay_confirmed: bool | None = None
    category: str | None = None
    failure_category: str | None = None


def _json_value(value: Any, *, depth: int = 0) -> bool:
    """Accept inert JSON values so comparison cannot invoke custom equality code."""
    if depth > 100:
        return False
    if value is None or type(value) in {str, bool, int}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_json_value(item, depth=depth + 1) for item in value)
    if type(value) is dict:
        return all(
            type(key) is str and _json_value(item, depth=depth + 1)
            for key, item in value.items()
        )
    return False


def _contract_from(value: Any) -> ClaimContract | None:
    if isinstance(value, ClaimContract):
        contract = value
    elif type(value) is dict:
        methods = value.get("required_methods")
        if not isinstance(methods, (list, tuple)):
            return None
        contract = ClaimContract(
            contract_id=value.get("contract_id"),
            oracle_id=value.get("oracle_id"),
            scheduled_test_count=value.get("scheduled_test_count"),
            required_methods=tuple(methods),
            oracle_usable=value.get("oracle_usable", True),
        )
    else:
        return None

    if (
        type(contract.contract_id) is not str
        or not contract.contract_id.strip()
        or type(contract.scheduled_test_count) is not int
        or contract.scheduled_test_count <= 0
        or not isinstance(contract.required_methods, (list, tuple))
        or not contract.required_methods
        or any(
            type(method) is not str or not method.strip()
            for method in contract.required_methods
        )
        or len(set(contract.required_methods)) != len(contract.required_methods)
        or type(contract.oracle_usable) is not bool
        or (
            contract.oracle_id is not None
            and (type(contract.oracle_id) is not str or not contract.oracle_id.strip())
        )
    ):
        return None
    return ClaimContract(
        contract_id=contract.contract_id,
        oracle_id=contract.oracle_id,
        scheduled_test_count=contract.scheduled_test_count,
        required_methods=tuple(contract.required_methods),
        oracle_usable=contract.oracle_usable,
    )


def _record_from(value: Any) -> EvidenceRecord | None:
    if isinstance(value, EvidenceRecord):
        record = value
    elif type(value) is dict:
        try:
            status = EvidenceStatus(value.get("status"))
        except (ValueError, TypeError):
            return None

        common = ("test_id", "method", "contract_id")
        if any(
            type(value.get(key)) is not str or not value.get(key).strip()
            for key in common
        ):
            return None

        if status is EvidenceStatus.COMPLETED:
            required = ("contract_valid", "oracle_id", "input", "actual", "expected")
            if any(key not in value for key in required):
                return None
            contract_valid = value.get("contract_valid")
            replay_confirmed = value.get("replay_confirmed")
            if type(contract_valid) is not bool:
                return None
            if replay_confirmed is not None and type(replay_confirmed) is not bool:
                return None
            payload = (value.get("input"), value.get("actual"), value.get("expected"))
            if not all(_json_value(item) for item in payload):
                return None
        else:
            contract_valid = value.get("contract_valid")
            replay_confirmed = value.get("replay_confirmed")

        record = EvidenceRecord(
            test_id=value["test_id"],
            method=value["method"],
            contract_id=value["contract_id"],
            status=status,
            contract_valid=contract_valid,
            oracle_id=value.get("oracle_id"),
            input_value=value.get("input"),
            actual=value.get("actual"),
            expected=value.get("expected"),
            replay_confirmed=replay_confirmed,
            category=value.get("category"),
            failure_category=value.get("failure_category"),
        )
    else:
        return None

    if (
        type(record.test_id) is not str
        or not record.test_id.strip()
        or type(record.method) is not str
        or not record.method.strip()
        or type(record.contract_id) is not str
        or not record.contract_id.strip()
        or not isinstance(record.status, EvidenceStatus)
        or (
            record.oracle_id is not None
            and (
                type(record.oracle_id) is not str
                or not record.oracle_id.strip()
            )
        )
        or (record.category is not None and type(record.category) is not str)
        or (
            record.failure_category is not None
            and type(record.failure_category) is not str
        )
    ):
        return None

    if record.status is EvidenceStatus.COMPLETED:
        if type(record.contract_valid) is not bool:
            return None
        if record.replay_confirmed is not None and type(record.replay_confirmed) is not bool:
            return None
        if record.category not in {None, "CASE_PASSED", "PROPERTY_VIOLATION"}:
            return None
        if not all(_json_value(item) for item in (record.input_value, record.actual, record.expected)):
            return None
    return record


def _unresolved(
    reason: OutcomeReason,
    message: str,
    *,
    test_count: int = 0,
    methods: tuple[str, ...] = (),
) -> RunOutcome:
    return RunOutcome(
        outcome=FinalOutcome.UNRESOLVED,
        reason=reason,
        message=message,
        test_count=test_count or None,
        methods=methods,
    )


def decide(
    evidence_records: list[EvidenceRecord | dict[str, Any]]
    | tuple[EvidenceRecord | dict[str, Any], ...],
    claim_contract: ClaimContract | dict[str, Any],
) -> RunOutcome:
    """Choose a final outcome from evidence fields only; ignore model wording.

    Dict records may contain extra model annotations, but only the declared
    contract, status, oracle, replay, and output fields affect the decision.
    """
    contract = _contract_from(claim_contract)
    if contract is None:
        return _unresolved(
            OutcomeReason.INVALID_EVIDENCE,
            "The claim contract is missing required decision-policy fields.",
        )

    if type(evidence_records) not in {list, tuple}:
        return _unresolved(
            OutcomeReason.INVALID_EVIDENCE,
            "Evidence records must be a finite sequence.",
        )

    records: list[EvidenceRecord] = []
    for raw_record in evidence_records:
        record = _record_from(raw_record)
        if record is None:
            return _unresolved(
                OutcomeReason.INVALID_EVIDENCE,
                "At least one evidence record is malformed or contains non-JSON data.",
            )
        records.append(record)

    if not records:
        return _unresolved(
            OutcomeReason.INCOMPLETE_EVIDENCE,
            "No evidence records were supplied.",
        )

    test_ids: set[str] = set()
    for record in records:
        if record.test_id in test_ids:
            return _unresolved(
                OutcomeReason.CONFLICTING_EVIDENCE,
                f"Duplicate test id {record.test_id!r} makes the evidence ambiguous.",
            )
        test_ids.add(record.test_id)
        if record.contract_id != contract.contract_id:
            return _unresolved(
                OutcomeReason.INVALID_EVIDENCE,
                f"Evidence {record.test_id!r} belongs to a different contract.",
            )
        if record.method not in contract.required_methods:
            return _unresolved(
                OutcomeReason.INVALID_EVIDENCE,
                f"Evidence {record.test_id!r} names an unconfigured method.",
            )

    if any(record.status is EvidenceStatus.INVALID for record in records):
        return _unresolved(
            OutcomeReason.INVALID_EVIDENCE,
            "The run contains invalid or out-of-contract evidence.",
        )

    completed = [record for record in records if record.status is EvidenceStatus.COMPLETED]
    trusted_oracle_available = contract.oracle_usable and contract.oracle_id is not None
    for record in completed:
        if record.contract_valid is not True:
            return _unresolved(
                OutcomeReason.INVALID_EVIDENCE,
                f"Evidence {record.test_id!r} is not contract-valid.",
                test_count=len(completed),
            )
        if trusted_oracle_available and record.oracle_id != contract.oracle_id:
            return _unresolved(
                OutcomeReason.INVALID_EVIDENCE,
                f"Evidence {record.test_id!r} does not use the contract's trusted oracle.",
                test_count=len(completed),
            )

    if len(records) > contract.scheduled_test_count:
        return _unresolved(
            OutcomeReason.CONFLICTING_EVIDENCE,
            "More evidence records were supplied than tests were scheduled.",
            test_count=len(completed),
        )

    observations: dict[str, tuple[str, str]] = {}
    for record in completed:
        input_key = json.dumps(record.input_value, sort_keys=True, separators=(",", ":"))
        output_pair = (
            json.dumps(record.actual, sort_keys=True, separators=(",", ":")),
            json.dumps(record.expected, sort_keys=True, separators=(",", ":")),
        )
        previous = observations.setdefault(input_key, output_pair)
        if previous != output_pair:
            return _unresolved(
                OutcomeReason.CONFLICTING_EVIDENCE,
                "Repeated evaluation of the same input produced conflicting outputs.",
                test_count=len(completed),
            )

    counterexamples: list[EvidenceRecord] = []
    if trusted_oracle_available:
        for record in completed:
            mismatch = record.actual != record.expected
            if record.category == "PROPERTY_VIOLATION" and not mismatch:
                return _unresolved(
                    OutcomeReason.CONFLICTING_EVIDENCE,
                    f"Evidence {record.test_id!r} labels equal outputs as a violation.",
                    test_count=len(completed),
                )
            if record.category == "CASE_PASSED" and mismatch:
                return _unresolved(
                    OutcomeReason.CONFLICTING_EVIDENCE,
                    f"Evidence {record.test_id!r} labels mismatched outputs as passing.",
                    test_count=len(completed),
                )
            if record.replay_confirmed is True and not mismatch:
                return _unresolved(
                    OutcomeReason.CONFLICTING_EVIDENCE,
                    f"Evidence {record.test_id!r} claims a replayed mismatch for equal outputs.",
                    test_count=len(completed),
                )
            if mismatch:
                if record.replay_confirmed is not True:
                    return _unresolved(
                        OutcomeReason.INVALID_EVIDENCE,
                        f"Evidence {record.test_id!r} has a mismatch that replay did not confirm.",
                        test_count=len(completed),
                    )
                counterexamples.append(record)

    if counterexamples:
        record = counterexamples[0]
        return RunOutcome(
            outcome=FinalOutcome.REFUTED,
            reason=OutcomeReason.CONFIRMED_COUNTEREXAMPLE,
            message="A contract-valid counterexample was confirmed by replay.",
            test_count=len(completed),
            methods=(record.method,),
            counterexample={
                "input": record.input_value,
                "actual": record.actual,
                "expected": record.expected,
                "test_id": record.test_id,
                "replay_confirmed": True,
            },
        )

    api_failure = next(
        (record for record in records if record.status is EvidenceStatus.API_ERROR),
        None,
    )
    if api_failure is not None:
        return RunOutcome(
            outcome=FinalOutcome.ERROR,
            reason=OutcomeReason.EXTERNAL_ERROR,
            message=f"External evaluation failed for test {api_failure.test_id!r}.",
            test_count=len(completed) or None,
            methods=(api_failure.method,),
            failure_category=api_failure.failure_category or "API_ERROR",
        )

    internal_failure = next(
        (record for record in records if record.status is EvidenceStatus.INTERNAL_ERROR),
        None,
    )
    if internal_failure is not None:
        return RunOutcome(
            outcome=FinalOutcome.ERROR,
            reason=OutcomeReason.INTERNAL_ERROR,
            message=f"Internal evaluation failed for test {internal_failure.test_id!r}.",
            test_count=len(completed) or None,
            methods=(internal_failure.method,),
            failure_category=internal_failure.failure_category or "INTERNAL_ERROR",
        )

    if not trusted_oracle_available:
        return _unresolved(
            OutcomeReason.NO_USABLE_ORACLE,
            "The claim contract has no usable trusted oracle.",
            test_count=len(completed),
        )

    if any(record.status is EvidenceStatus.TIMEOUT for record in records):
        return _unresolved(
            OutcomeReason.TIMEOUT,
            "At least one scheduled evaluation timed out.",
            test_count=len(completed),
            methods=tuple(dict.fromkeys(record.method for record in records)),
        )

    if any(record.status is EvidenceStatus.BUDGET_EXHAUSTED for record in records):
        return _unresolved(
            OutcomeReason.BUDGET_EXHAUSTED,
            "The evaluation budget ended before all scheduled tests completed.",
            test_count=len(completed),
            methods=tuple(dict.fromkeys(record.method for record in records)),
        )

    completed_methods = {record.method for record in completed}
    if (
        len(completed) != contract.scheduled_test_count
        or not set(contract.required_methods).issubset(completed_methods)
    ):
        return _unresolved(
            OutcomeReason.INCOMPLETE_EVIDENCE,
            "Not all scheduled tests and required methods completed.",
            test_count=len(completed),
            methods=tuple(dict.fromkeys(record.method for record in completed)),
        )

    return RunOutcome.from_finite_tests(
        test_count=len(completed),
        methods=contract.required_methods,
    )
