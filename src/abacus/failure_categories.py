"""Shared failure categories and short definitions for Abacus evidence."""

from __future__ import annotations

from enum import Enum


class FailureCategory(str, Enum):
    OUT_OF_CONTRACT = "OUT_OF_CONTRACT"
    TARGET_EXCEPTION = "TARGET_EXCEPTION"
    PROPERTY_VIOLATION = "PROPERTY_VIOLATION"
    TEST_ORACLE_DEFECT = "TEST_ORACLE_DEFECT"
    TIMEOUT = "TIMEOUT"
    SANDBOX_FAILURE = "SANDBOX_FAILURE"
    API_ERROR = "API_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


FAILURE_CATEGORY_GUIDE: dict[FailureCategory, tuple[str, str]] = {
    FailureCategory.OUT_OF_CONTRACT: (
        "The proposed input violates the declared input domain or preconditions.",
        "A boolean appears where the contract requires exact integers.",
    ),
    FailureCategory.TARGET_EXCEPTION: (
        "The candidate raised while loading or processing a valid input.",
        "candidate([1, 2]) raises ValueError.",
    ),
    FailureCategory.PROPERTY_VIOLATION: (
        "The trusted oracle confirmed that the returned result violates the property.",
        "Reverse sorting returns [2, 1] when [1, 2] is expected.",
    ),
    FailureCategory.TEST_ORACLE_DEFECT: (
        "The independent oracle could not produce a valid property check.",
        "The oracle returns its ERROR status for a contract-valid result.",
    ),
    FailureCategory.TIMEOUT: (
        "The candidate exceeded the configured execution time limit.",
        "A valid candidate input enters an infinite loop.",
    ),
    FailureCategory.SANDBOX_FAILURE: (
        "The bounded runner or its result protocol failed; this does not imply a security sandbox.",
        "The child process cannot start or exceeds the captured-output limit.",
    ),
    FailureCategory.API_ERROR: (
        "The model request failed before a usable response was received.",
        "The provider key is missing or the provider rejects the request.",
    ),
    FailureCategory.PARSE_ERROR: (
        "The model response is not valid JSON matching the proposal schema.",
        "candidate_inputs is a string instead of an array.",
    ),
    FailureCategory.INTERNAL_ERROR: (
        "Abacus encountered an unexpected error outside the target or runner boundary.",
        "An unexpected exception occurs while assembling harness evidence.",
    ),
}
