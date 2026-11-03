"""Machine-checkable input contracts shared by problem generators and oracles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator


SORTED_INTEGER_LIST_ORACLE_ID = "sorted-integer-list-v1"
SORTED_INTEGER_LIST_INPUT_TYPE = "list[int]"
SORTED_INTEGER_LIST_PRECONDITIONS = (
    "input_is_list",
    "elements_are_exact_ints",
)


class InputStatus(str, Enum):
    VALID = "VALID"
    OUTSIDE_CONTRACT = "OUTSIDE_CONTRACT"


@dataclass(frozen=True)
class InputValidation:
    """Contract-check result, separate from any target-function result."""

    status: InputStatus
    reason: str | None = None

    @property
    def valid(self) -> bool:
        return self.status is InputStatus.VALID


def _outside(reason: str) -> InputValidation:
    return InputValidation(status=InputStatus.OUTSIDE_CONTRACT, reason=reason)


def validate_input(problem: Any, input_value: Any) -> InputValidation:
    """Check input and record metadata against a registered problem contract."""

    if not isinstance(problem, Mapping):
        return _outside("problem must be a mapping with an oracle_id")

    oracle_id = problem.get("oracle_id")
    if oracle_id != SORTED_INTEGER_LIST_ORACLE_ID:
        return _outside(f"no input contract is registered for oracle_id {oracle_id!r}")

    domain = problem.get("domain")
    if (
        not isinstance(domain, Mapping)
        or domain.get("input_type") != SORTED_INTEGER_LIST_INPUT_TYPE
    ):
        return _outside(
            f"domain.input_type must be '{SORTED_INTEGER_LIST_INPUT_TYPE}' "
            f"for oracle_id {SORTED_INTEGER_LIST_ORACLE_ID}"
        )

    preconditions = problem.get("preconditions")
    if (
        not isinstance(preconditions, list)
        or any(not isinstance(item, str) for item in preconditions)
        or len(preconditions) != len(SORTED_INTEGER_LIST_PRECONDITIONS)
        or frozenset(preconditions) != frozenset(SORTED_INTEGER_LIST_PRECONDITIONS)
    ):
        expected = ", ".join(SORTED_INTEGER_LIST_PRECONDITIONS)
        return _outside(f"preconditions must declare exactly: {expected}")

    if not isinstance(input_value, list):
        return _outside("input_value must be a list")
    for index, value in enumerate(input_value):
        if type(value) is not int:
            return _outside(
                f"input_value[{index}] must be an exact int; booleans are excluded"
            )

    return InputValidation(status=InputStatus.VALID)


def generate_sorted_integer_examples(problem: Any) -> Iterator[list[int]]:
    """Yield fixed edge-case inputs only when they satisfy the shared contract."""

    cases = (
        (),
        (7,),
        (3, 1, 3),
        (0, -3, 2, -1),
        (-2, 0, 4, 8),
    )
    for case in cases:
        input_value = list(case)
        validation = validate_input(problem, input_value)
        if not validation.valid:
            raise ValueError(
                f"configured example violates its problem contract: {validation.reason}"
            )
        yield input_value
