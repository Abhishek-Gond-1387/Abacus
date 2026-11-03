"""Deterministic case and batch checks using trusted problem records."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .contracts import InputStatus, validate_input
from .failure_categories import FailureCategory
from .problems import load_problem, validate_problem
from .runner import ExecutionResult, RunCategory, run_trusted_program
from .sorting_oracle import CheckStatus, PropertyCheck, check_sorted_integer_list


logger = logging.getLogger(__name__)


class HarnessStatus(str, Enum):
    """Case outcomes exposed by the independent harness."""

    PASSED = "PASSED"
    REFUTED = "REFUTED"
    OUT_OF_CONTRACT = "OUT_OF_CONTRACT"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    OUTPUT_LIMIT = "OUTPUT_LIMIT"


@dataclass(frozen=True)
class TargetException:
    type_name: str
    message: str
    phase: str


@dataclass(frozen=True)
class CaseEvidence:
    """Evidence and outcome for one input and one problem record."""

    problem_id: str | None
    input_value: Any
    input_valid: bool | None
    validity_reason: str | None
    target_result: Any
    target_exception: TargetException | None
    oracle_result: PropertyCheck | None
    status: HarnessStatus
    explanation: str
    execution: ExecutionResult | None = None
    failure_category: FailureCategory | None = None

    @property
    def passed(self) -> bool:
        return self.status == HarnessStatus.PASSED


@dataclass(frozen=True)
class BatchEvidence:
    """Results accumulated by ``check_cases`` without losing earlier cases."""

    results: tuple[CaseEvidence, ...]
    batch_error: str | None = None
    failure_category: FailureCategory | None = None

    @property
    def passed_count(self) -> int:
        return sum(result.passed for result in self.results)

    @property
    def summary(self) -> str:
        if not self.results:
            return "tests completed: no cases were checked"
        if self.batch_error is None and self.passed_count == len(self.results):
            return (
                f"tests passed: {self.passed_count}/{len(self.results)} cases "
                "(finite checks, not a proof)"
            )
        summary = (
            f"tests completed: {self.passed_count}/{len(self.results)} cases passed"
        )
        if self.batch_error:
            summary += f"; batch stopped: {self.batch_error}"
        return summary


def _resolve_problem(problem: Any) -> dict[str, Any]:
    if isinstance(problem, (str, Path)):
        return load_problem(problem)
    if isinstance(problem, Mapping):
        record = dict(problem)
    else:
        record = problem
    validate_problem(record)
    return record


def _exception_message(error: BaseException) -> str:
    try:
        return str(error)[:500]
    except BaseException:
        return "<exception message unavailable>"


def _worker_exception_message(error: BaseException) -> str:
    try:
        return str(error)[:500]
    except BaseException:
        return "<exception message unavailable>"


def _worker_source(code: str, input_value: list[int], marker: str) -> str:
    """Create a protocol wrapper; only hand-authored trusted record code belongs here."""

    template = r'''import contextlib
import json
import math
import sys

_candidate_source = __SOURCE__
_input_value = __INPUT__
_marker = __MARKER__

def _describe(value):
    try:
        rendered = repr(value)[:300]
    except BaseException:
        rendered = "<repr unavailable>"
    return {"type": type(value).__name__, "repr": rendered}

def _worker_exception_message(error):
    try:
        return str(error)[:500]
    except BaseException:
        return "<exception message unavailable>"

def _encode_item(value):
    value_type = type(value)
    if value is None or value_type in (bool, int, str):
        return {"type": value_type.__name__, "value": value}
    if value_type is float and math.isfinite(value):
        return {"type": "float", "value": value}
    return _describe(value)

def _encode_value(value):
    value_type = type(value)
    if value_type in (list, tuple):
        return {
            "type": value_type.__name__,
            "items": [_encode_item(item) for item in value],
        }
    return _encode_item(value)

def _exception_payload(error, phase):
    return {
        "kind": "exception",
        "phase": phase,
        "type": type(error).__name__,
        "message": _worker_exception_message(error),
    }

try:
    with contextlib.redirect_stdout(sys.stderr):
        namespace = {}
        try:
            exec(_candidate_source, namespace, namespace)
        except BaseException as error:
            payload = _exception_payload(error, "module")
        else:
            candidate = namespace.get("candidate")
            if not callable(candidate):
                payload = {
                    "kind": "exception",
                    "phase": "module",
                    "type": "TypeError",
                    "message": "problem code must define callable candidate(values)",
                }
            else:
                values = _input_value
                try:
                    target_result = candidate(values)
                except BaseException as error:
                    payload = _exception_payload(error, "target")
                else:
                    try:
                        payload = {
                            "kind": "returned",
                            "result": _encode_value(target_result),
                            "input_after": _encode_value(values),
                        }
                    except BaseException as error:
                        payload = _exception_payload(error, "result encoding")
except BaseException as error:
    payload = _exception_payload(error, "harness worker")

sys.__stdout__.write(
    _marker + json.dumps(payload, ensure_ascii=True, allow_nan=False) + "\n"
)
'''
    return (
        template.replace("__MARKER__", json.dumps(marker))
        .replace("__INPUT__", json.dumps(input_value))
        .replace("__SOURCE__", json.dumps(code))
    )


def _decode_item(encoded: Any) -> Any:
    if not isinstance(encoded, dict) or "type" not in encoded:
        raise ValueError("target result did not match the harness protocol")
    type_name = encoded["type"]
    if "value" in encoded:
        return encoded["value"]
    return {"type": type_name, "repr": encoded.get("repr", "")}


def _decode_value(encoded: Any) -> Any:
    if not isinstance(encoded, dict) or "type" not in encoded:
        raise ValueError("target result did not match the harness protocol")
    type_name = encoded["type"]
    if type_name in ("list", "tuple"):
        items = encoded.get("items")
        if not isinstance(items, list):
            raise ValueError("target sequence did not match the harness protocol")
        decoded = [_decode_item(item) for item in items]
        return tuple(decoded) if type_name == "tuple" else decoded
    return _decode_item(encoded)


def _evidence_error(
    problem_id: str | None,
    input_value: Any,
    error: BaseException,
    *,
    execution: ExecutionResult | None = None,
    input_valid: bool | None = None,
    validity_reason: str | None = None,
    phase: str = "harness",
    failure_category: FailureCategory | None = None,
) -> CaseEvidence:
    target_exception = (
        TargetException(type(error).__name__, _exception_message(error), phase)
        if phase in ("target", "module")
        else None
    )
    return CaseEvidence(
        problem_id=problem_id,
        input_value=input_value,
        input_valid=input_valid,
        validity_reason=validity_reason,
        target_result=None,
        target_exception=target_exception,
        oracle_result=None,
        status=HarnessStatus.ERROR,
        explanation=f"{phase} error: {type(error).__name__}: {_exception_message(error)}",
        execution=execution,
        failure_category=failure_category
        or (
            FailureCategory.TARGET_EXCEPTION
            if phase in ("target", "module")
            else FailureCategory.SANDBOX_FAILURE
            if phase in ("runner", "runner protocol")
            else FailureCategory.INTERNAL_ERROR
        ),
    )


def check_case(problem: Any, input_value: Any) -> CaseEvidence:
    """Run one input through its contract, trusted target, and registered oracle.

    ``problem`` may be a validated record mapping or a path accepted by
    ``load_problem``. The record's code must be hand-authored and trusted.
    """

    record: dict[str, Any] | None = None
    problem_id: str | None = None
    evidence_input = tuple(input_value) if isinstance(input_value, list) else input_value
    try:
        record = _resolve_problem(problem)
        problem_id = record.get("id")
        validation = validate_input(record, input_value)
        if validation.status is InputStatus.OUTSIDE_CONTRACT:
            return CaseEvidence(
                problem_id=problem_id,
                input_value=evidence_input,
                input_valid=False,
                validity_reason=validation.reason,
                target_result=None,
                target_exception=None,
                oracle_result=None,
                status=HarnessStatus.OUT_OF_CONTRACT,
                explanation=f"target was not run: {validation.reason}",
                failure_category=FailureCategory.OUT_OF_CONTRACT,
            )

        target_input = list(input_value)
        marker = f"ABACUS_RESULT_{uuid.uuid4().hex}:"
        source = _worker_source(record["code"], target_input, marker)
        try:
            execution = run_trusted_program(source)
        except Exception as error:
            return _evidence_error(
                problem_id,
                evidence_input,
                error,
                input_valid=True,
                phase="runner",
                failure_category=FailureCategory.SANDBOX_FAILURE,
            )

        if execution.category is RunCategory.TIMEOUT:
            return CaseEvidence(
                problem_id,
                evidence_input,
                True,
                None,
                None,
                None,
                None,
                HarnessStatus.TIMEOUT,
                "target exceeded the subprocess timeout",
                execution,
                FailureCategory.TIMEOUT,
            )
        if execution.category is RunCategory.OUTPUT_LIMIT:
            return CaseEvidence(
                problem_id,
                evidence_input,
                True,
                None,
                None,
                None,
                None,
                HarnessStatus.OUTPUT_LIMIT,
                "target output exceeded the configured capture limit",
                execution,
                FailureCategory.SANDBOX_FAILURE,
            )
        if execution.category is not RunCategory.SUCCESS:
            return CaseEvidence(
                problem_id,
                evidence_input,
                True,
                None,
                None,
                None,
                None,
                HarnessStatus.ERROR,
                f"runner failed: {execution.category.value}",
                execution,
                FailureCategory.SANDBOX_FAILURE,
            )

        result_lines = [
            line[len(marker) :]
            for line in execution.stdout.splitlines()
            if line.startswith(marker)
        ]
        if not result_lines:
            return CaseEvidence(
                problem_id,
                evidence_input,
                True,
                None,
                None,
                None,
                None,
                HarnessStatus.ERROR,
                "target subprocess returned no harness result",
                execution,
                FailureCategory.SANDBOX_FAILURE,
            )
        try:
            payload = json.loads(result_lines[-1])
            if not isinstance(payload, dict):
                raise ValueError("target result did not match the harness protocol")
        except (json.JSONDecodeError, ValueError, TypeError) as error:
            return _evidence_error(
                problem_id,
                evidence_input,
                error,
                execution=execution,
                input_valid=True,
                phase="runner protocol",
                failure_category=FailureCategory.SANDBOX_FAILURE,
            )
        if payload.get("kind") == "exception":
            target_exception = TargetException(
                type_name=str(payload.get("type", "Exception")),
                message=str(payload.get("message", "")),
                phase=str(payload.get("phase", "target")),
            )
            return CaseEvidence(
                problem_id,
                evidence_input,
                True,
                None,
                None,
                target_exception,
                None,
                HarnessStatus.ERROR,
                f"target {target_exception.phase} raised {target_exception.type_name}: "
                f"{target_exception.message}",
                execution,
                FailureCategory.TARGET_EXCEPTION
                if target_exception.phase in ("target", "module")
                else FailureCategory.SANDBOX_FAILURE,
            )
        if payload.get("kind") != "returned":
            return _evidence_error(
                problem_id,
                evidence_input,
                ValueError("target result did not match the harness protocol"),
                execution=execution,
                input_valid=True,
                phase="runner protocol",
                failure_category=FailureCategory.SANDBOX_FAILURE,
            )

        try:
            target_result = _decode_value(payload.get("result"))
            input_after = _decode_value(payload.get("input_after"))
            if not isinstance(input_after, list):
                raise ValueError(
                    "target input snapshot did not match the harness protocol"
                )
        except (ValueError, TypeError, KeyError) as error:
            return _evidence_error(
                problem_id,
                evidence_input,
                error,
                execution=execution,
                input_valid=True,
                phase="runner protocol",
                failure_category=FailureCategory.SANDBOX_FAILURE,
            )

        oracle_input = list(target_input)

        def use_recorded_result(values: list[int]) -> Any:
            values[:] = input_after
            return target_result

        try:
            oracle_result = check_sorted_integer_list(
                use_recorded_result,
                oracle_input,
                record,
            )
        except Exception as error:
            return _evidence_error(
                problem_id,
                evidence_input,
                error,
                execution=execution,
                input_valid=True,
                phase="oracle",
                failure_category=FailureCategory.TEST_ORACLE_DEFECT,
            )
        status = (
            HarnessStatus.PASSED
            if oracle_result.status is CheckStatus.PASSED
            else HarnessStatus.REFUTED
            if oracle_result.status is CheckStatus.REFUTED
            else HarnessStatus.ERROR
        )
        explanation = (
            "returned value satisfies the registered sorting property"
            if oracle_result.passed
            else oracle_result.reason or f"oracle returned {oracle_result.status.value}"
        )
        failure_category = (
            None
            if status is HarnessStatus.PASSED
            else FailureCategory.PROPERTY_VIOLATION
            if status is HarnessStatus.REFUTED
            else FailureCategory.TEST_ORACLE_DEFECT
        )
        return CaseEvidence(
            problem_id,
            evidence_input,
            True,
            None,
            target_result,
            None,
            oracle_result,
            status,
            explanation,
            execution,
            failure_category,
        )
    except Exception as error:
        return _evidence_error(
            problem_id,
            evidence_input,
            error,
            input_valid=None,
            phase="harness",
            failure_category=FailureCategory.INTERNAL_ERROR,
        )


def check_cases(problem: Any, cases: Iterable[Any]) -> BatchEvidence:
    """Check each case, preserving completed evidence if a later case fails."""

    results: list[CaseEvidence] = []
    batch_error: str | None = None
    try:
        for input_value in cases:
            try:
                result = check_case(problem, input_value)
            except Exception as error:
                result = _evidence_error(
                    None,
                    input_value,
                    error,
                    phase="batch case",
                    failure_category=FailureCategory.INTERNAL_ERROR,
                )
            results.append(result)
    except Exception as error:
        batch_error = f"{type(error).__name__}: {_exception_message(error)}"

    batch = BatchEvidence(
        tuple(results),
        batch_error,
        FailureCategory.INTERNAL_ERROR if batch_error else None,
    )
    if batch_error is None and batch.passed_count == len(batch.results):
        logger.info(batch.summary)
    else:
        logger.warning(batch.summary)
    return batch
