"""Deterministic case generation and trusted target/oracle evidence collection."""

from __future__ import annotations

from typing import Any, Callable

from hypothesis import HealthCheck, given, seed, settings, strategies as st

from .schemas import ProblemSpec


def generate_hypothesis_cases(spec: ProblemSpec) -> tuple[list[list[int]], str | None]:
    """Generate bounded, repeatable integer-list examples from validated limits."""
    config = spec.hypothesis
    cases: list[list[int]] = []

    @seed(config["seed"])
    @given(
        st.lists(
            st.integers(min_value=config["min_value"], max_value=config["max_value"]),
            min_size=config["min_size"],
            max_size=config["max_size"],
        )
    )
    @settings(
        max_examples=config["max_examples"],
        deadline=None,
        database=None,
        suppress_health_check=(HealthCheck.too_slow,),
    )
    def collect(value: list[int]) -> None:
        cases.append(value)

    try:
        collect()
    except Exception as error:
        return cases, f"{type(error).__name__}: {error}"
    return cases, None


def evaluate_case(
    *,
    spec: ProblemSpec,
    method: str,
    test_id: str,
    value: list[int],
    target: Callable[[list[int]], list[int]],
    oracle: Callable[[list[int]], list[int]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    detail: dict[str, Any] = {
        "test_id": test_id,
        "method": method,
        "input": value,
        "replay_attempted": False,
        "replay_confirmed": None,
    }
    try:
        actual = target(value.copy())
    except Exception as error:
        category = f"target_exception:{type(error).__name__}"
        return (
            {
                "test_id": test_id,
                "method": method,
                "contract_id": spec.contract_id,
                "status": "internal_error",
                "failure_category": category,
            },
            {**detail, "status": "INTERNAL_ERROR", "error": str(error), "failure_category": category},
        )
    try:
        expected = oracle(value.copy())
    except Exception as error:
        category = f"oracle_exception:{type(error).__name__}"
        return (
            {
                "test_id": test_id,
                "method": method,
                "contract_id": spec.contract_id,
                "status": "internal_error",
                "failure_category": category,
            },
            {**detail, "status": "INTERNAL_ERROR", "actual": actual, "error": str(error), "failure_category": category},
        )

    mismatch = actual != expected
    replay_confirmed = False
    if mismatch:
        detail["replay_attempted"] = True
        try:
            replay_actual = target(value.copy())
            replay_expected = oracle(value.copy())
            replay_confirmed = replay_actual == actual and replay_expected == expected and replay_actual != replay_expected
            detail["replay_actual"] = replay_actual
            detail["replay_expected"] = replay_expected
        except Exception:
            replay_confirmed = False
            detail["replay_error"] = "Replay target or oracle raised an exception."

    category = "PROPERTY_VIOLATION" if mismatch else "CASE_PASSED"
    evidence = {
        "test_id": test_id,
        "method": method,
        "contract_id": spec.contract_id,
        "status": "completed",
        "contract_valid": True,
        "oracle_id": spec.oracle_id,
        "input": value,
        "actual": actual,
        "expected": expected,
        "replay_confirmed": replay_confirmed if mismatch else None,
        "replay_attempted": mismatch,
        "replay_actual": detail.get("replay_actual"),
        "replay_expected": detail.get("replay_expected"),
        "category": category,
    }
    detail.update(
        {
            "status": category,
            "actual": actual,
            "expected": expected,
            "replay_confirmed": replay_confirmed if mismatch else None,
        }
    )
    return evidence, detail


def methods_for(spec: ProblemSpec) -> list[str]:
    methods = ["fixed", "hypothesis"]
    if spec.proposals:
        methods.append("proposals")
    return methods


def scheduled_count(spec: ProblemSpec) -> int:
    return len(spec.fixed_cases) + spec.hypothesis["max_examples"] + len(spec.proposals)
