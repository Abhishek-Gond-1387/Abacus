"""Independent reference check for the sorted-integer-list problem."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .contracts import (
    SORTED_INTEGER_LIST_ORACLE_ID,
    validate_input,
)


class CheckStatus(str, Enum):
    PASSED = "PASSED"
    REFUTED = "REFUTED"
    OUTSIDE_CONTRACT = "OUTSIDE_CONTRACT"
    ERROR = "ERROR"


@dataclass(frozen=True)
class PropertyCheck:
    """Result of checking one input against the sorting property."""

    status: CheckStatus
    expected_output: tuple[int, ...] | None
    actual_output: Any
    input_unchanged: bool | None
    reason: str | None = None

    @property
    def passed(self) -> bool:
        return self.status is CheckStatus.PASSED


def check_sorted_integer_list(
    candidate: Callable[[list[int]], Any], values: Any, problem: Any
) -> PropertyCheck:
    """Validate input, then check one candidate against Python's ``sorted``.

    Contract violations return ``OUTSIDE_CONTRACT`` without calling the
    candidate. Valid inputs require a list of exact built-in integers; the
    candidate must return such a list in ascending order and leave input intact.
    """

    validation = validate_input(problem, values)
    if not validation.valid:
        return PropertyCheck(
            status=CheckStatus.OUTSIDE_CONTRACT,
            expected_output=None,
            actual_output=None,
            input_unchanged=None,
            reason=validation.reason,
        )

    if not callable(candidate):
        raise TypeError("candidate must be callable")

    original = tuple(values)
    expected = tuple(sorted(values))

    try:
        actual = candidate(values)
    except Exception as error:
        unchanged = tuple(values) == original
        reason = f"candidate raised {type(error).__name__}"
        if not unchanged:
            reason += " and mutated the input list"
        return PropertyCheck(
            status=CheckStatus.ERROR,
            expected_output=expected,
            actual_output=None,
            input_unchanged=unchanged,
            reason=reason,
        )

    unchanged = tuple(values) == original
    if not unchanged:
        return PropertyCheck(
            status=CheckStatus.REFUTED,
            expected_output=expected,
            actual_output=actual,
            input_unchanged=False,
            reason="candidate mutated the input list",
        )
    if not isinstance(actual, list):
        return PropertyCheck(
            status=CheckStatus.REFUTED,
            expected_output=expected,
            actual_output=actual,
            input_unchanged=True,
            reason="candidate output must be a list",
        )
    if any(type(value) is not int for value in actual):
        return PropertyCheck(
            status=CheckStatus.REFUTED,
            expected_output=expected,
            actual_output=actual,
            input_unchanged=True,
            reason="candidate output must contain only integers",
        )
    if tuple(actual) != expected:
        return PropertyCheck(
            status=CheckStatus.REFUTED,
            expected_output=expected,
            actual_output=actual,
            input_unchanged=True,
            reason="candidate output differs from the sorted reference",
        )

    return PropertyCheck(
        status=CheckStatus.PASSED,
        expected_output=expected,
        actual_output=actual,
        input_unchanged=True,
    )
