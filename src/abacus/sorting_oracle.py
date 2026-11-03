"""Independent reference check for the sorted-integer-list problem."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


SORTED_INTEGER_LIST_ORACLE_ID = "sorted-integer-list-v1"


@dataclass(frozen=True)
class PropertyCheck:
    """Result of checking one input against the sorting property."""

    passed: bool
    expected_output: tuple[int, ...]
    actual_output: Any
    input_unchanged: bool
    reason: str | None = None


def check_sorted_integer_list(
    candidate: Callable[[list[int]], Any], values: list[int]
) -> PropertyCheck:
    """Check one candidate result against Python's trusted ``sorted`` reference.

    Inputs must be lists of exact built-in integers; booleans are excluded even
    though ``bool`` is a subclass of ``int``. The candidate must return a list
    of exact integers in ascending order and leave the input list unchanged.
    """

    if not callable(candidate):
        raise TypeError("candidate must be callable")
    if not isinstance(values, list) or any(
        type(value) is not int for value in values
    ):
        raise TypeError("values must be a list of integers; booleans are excluded")

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
            passed=False,
            expected_output=expected,
            actual_output=None,
            input_unchanged=unchanged,
            reason=reason,
        )

    unchanged = tuple(values) == original
    if not unchanged:
        return PropertyCheck(
            passed=False,
            expected_output=expected,
            actual_output=actual,
            input_unchanged=False,
            reason="candidate mutated the input list",
        )
    if not isinstance(actual, list):
        return PropertyCheck(
            passed=False,
            expected_output=expected,
            actual_output=actual,
            input_unchanged=True,
            reason="candidate output must be a list",
        )
    if any(type(value) is not int for value in actual):
        return PropertyCheck(
            passed=False,
            expected_output=expected,
            actual_output=actual,
            input_unchanged=True,
            reason="candidate output must contain only integers",
        )
    if tuple(actual) != expected:
        return PropertyCheck(
            passed=False,
            expected_output=expected,
            actual_output=actual,
            input_unchanged=True,
            reason="candidate output differs from the sorted reference",
        )

    return PropertyCheck(
        passed=True,
        expected_output=expected,
        actual_output=actual,
        input_unchanged=True,
    )
