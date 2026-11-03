"""Compare fixed, Hypothesis, and offline LLM-proposed cases on shared oracles.

The targets below are intentionally faulty examples. This review script only
runs code maintained in this repository; it never executes generated code.
"""

from __future__ import annotations

import json
import platform
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from hypothesis import HealthCheck, given, seed, settings, strategies as st
from hypothesis import __version__ as hypothesis_version

if __package__:
    from .outcomes import FinalOutcome, OutcomeReason
else:
    from outcomes import FinalOutcome, OutcomeReason


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "practice" / "day21_report.md"
MAX_EXAMPLES = 100
MAX_LIST_SIZE = 8
INTEGER_BOUND = 20
HYPOTHESIS_SEED = 2103


@dataclass(frozen=True)
class Proposal:
    value: Any
    rationale: str


@dataclass(frozen=True)
class SeedProblem:
    problem_id: str
    claim: str
    target: Callable[[list[int]], Any]
    oracle: Callable[[list[int]], Any]
    is_in_contract: Callable[[Any], bool]
    fixed_cases: tuple[Proposal, ...]
    llm_cases: tuple[Proposal, ...]
    hypothesis_strategy: Callable[[], Any]
    contract_description: str


def sort_with_duplicate_bug(values: list[int]) -> list[int]:
    """Intentionally faulty target: sorting works, but duplicates disappear."""
    return sorted(set(values))


def largest_with_negative_bug(values: list[int]) -> int:
    """Intentionally faulty target: negative-only lists incorrectly return 0."""
    largest = 0
    for value in values:
        if value > largest:
            largest = value
    return largest


def integer_list(value: Any) -> bool:
    """Accept lists of integers, excluding bool even though bool subclasses int."""
    return isinstance(value, list) and all(type(item) is int for item in value)


PROBLEMS = (
    SeedProblem(
        problem_id="sort-preserves-duplicates",
        claim="Return the input integers in ascending order, preserving duplicates.",
        target=sort_with_duplicate_bug,
        oracle=lambda values: sorted(values),
        is_in_contract=integer_list,
        fixed_cases=(
            Proposal([], "Empty list boundary."),
            Proposal([7], "Single value."),
            Proposal([3, 1, 2], "Unsorted values without duplicates."),
            Proposal([4, 4], "Repeated values must remain repeated."),
            Proposal([-2, 0, 5], "Negative, zero, and positive values."),
        ),
        llm_cases=(
            Proposal([3, 1, 2], "Try a short unsorted list."),
            Proposal("not a list", "Malformed proposal used to check validation."),
        ),
        hypothesis_strategy=lambda: st.lists(
            st.integers(min_value=-INTEGER_BOUND, max_value=INTEGER_BOUND),
            min_size=0,
            max_size=MAX_LIST_SIZE,
        ),
        contract_description="A list containing only integers; empty lists are allowed.",
    ),
    SeedProblem(
        problem_id="largest-negative-values",
        claim="For a non-empty integer list, return its largest value.",
        target=largest_with_negative_bug,
        oracle=lambda values: max(values),
        is_in_contract=lambda value: integer_list(value) and bool(value),
        fixed_cases=(
            Proposal([-7], "Single negative value."),
            Proposal([3, 1, 2], "Positive values in mixed order."),
            Proposal([-4, -1, -9], "All values are negative."),
            Proposal([0], "Zero boundary."),
        ),
        llm_cases=(
            Proposal([2, 1, 3], "Try a small positive list."),
            Proposal([], "Empty list is outside the non-empty contract."),
        ),
        hypothesis_strategy=lambda: st.lists(
            st.integers(min_value=-INTEGER_BOUND, max_value=INTEGER_BOUND),
            min_size=1,
            max_size=MAX_LIST_SIZE,
        ),
        contract_description="A non-empty list containing only integers.",
    ),
)


def check_case(problem: SeedProblem, value: Any) -> dict[str, Any]:
    """Apply the same contract and trusted oracle to every source."""
    if not problem.is_in_contract(value):
        return {
            "category": "OUT_OF_CONTRACT",
            "valid": False,
            "actual": None,
            "expected": None,
            "message": "Input did not satisfy the seed problem contract.",
        }

    try:
        actual = problem.target(value)
    except Exception as error:  # The target is local, trusted demonstration code.
        return {
            "category": "TARGET_EXCEPTION",
            "valid": True,
            "actual": None,
            "expected": None,
            "message": f"{type(error).__name__}: {error}",
        }

    try:
        expected = problem.oracle(value)
    except Exception as error:
        return {
            "category": "TEST_ORACLE_DEFECT",
            "valid": True,
            "actual": actual,
            "expected": None,
            "message": f"{type(error).__name__}: {error}",
        }

    if actual != expected:
        return {
            "category": "PROPERTY_VIOLATION",
            "valid": True,
            "actual": actual,
            "expected": expected,
            "message": "The target disagreed with the trusted reference.",
        }
    return {
        "category": "CASE_PASSED",
        "valid": True,
        "actual": actual,
        "expected": expected,
        "message": "The trusted property held for this input.",
    }


def run_fixed_cases(problem: SeedProblem) -> tuple[list[Any], str | None]:
    return [case.value for case in problem.fixed_cases], None


def run_llm_proposals(problem: SeedProblem) -> tuple[list[Any], str | None]:
    return [case.value for case in problem.llm_cases], None


def run_hypothesis(problem: SeedProblem) -> tuple[list[Any], str | None]:
    """Explore with bounded deterministic Hypothesis settings and retain cases."""
    generated: list[Any] = []

    @seed(HYPOTHESIS_SEED)
    @given(problem.hypothesis_strategy())
    @settings(
        max_examples=MAX_EXAMPLES,
        deadline=None,
        database=None,
        suppress_health_check=(HealthCheck.too_slow,),
    )
    def explore(value: Any) -> None:
        generated.append(value)
        result = check_case(problem, value)
        if result["category"] == "PROPERTY_VIOLATION":
            raise AssertionError("Trusted property violation found.")
        if result["category"] not in {"CASE_PASSED", "PROPERTY_VIOLATION"}:
            raise RuntimeError(f"Hypothesis generated an unusable input: {result['category']}")

    try:
        explore()
    except AssertionError as error:
        # A failing assertion is expected when the trusted oracle confirms a bug.
        if not any(
            check_case(problem, value)["category"] == "PROPERTY_VIOLATION"
            for value in generated
        ):
            return generated, f"Unexpected assertion: {error}"
    except Exception as error:
        return generated, f"{type(error).__name__}: {error}"
    return generated, None


def case_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def evaluate_source(
    problem: SeedProblem, source: str, proposals: list[Any], generation_error: str | None
) -> dict[str, Any]:
    started = time.perf_counter()
    outcomes = [check_case(problem, value) for value in proposals]
    elapsed_ms = (time.perf_counter() - started) * 1000

    confirmed = {
        case_key(value)
        for value, outcome in zip(proposals, outcomes)
        if outcome["category"] == "PROPERTY_VIOLATION"
    }
    failure_categories = Counter(
        outcome["category"]
        for outcome in outcomes
        if outcome["category"] not in {"CASE_PASSED", "PROPERTY_VIOLATION"}
    )
    if generation_error:
        failure_categories["INTERNAL_ERROR"] += 1

    findings_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for value, outcome in zip(proposals, outcomes):
        if outcome["category"] == "CASE_PASSED":
            continue
        key = (case_key(value), outcome["category"])
        findings_by_key.setdefault(key, {"input": value, **outcome})
    findings = list(findings_by_key.values())
    return {
        "problem_id": problem.problem_id,
        "source": source,
        "generated": len(proposals),
        "valid": sum(outcome["valid"] for outcome in outcomes),
        "confirmed_counterexamples": len(confirmed),
        "runtime_ms": round(elapsed_ms, 3),
        "failures": dict(sorted(failure_categories.items())),
        "generation_error": generation_error,
        "findings": findings,
    }


def render_report(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Day 21 — Input source comparison",
        "",
        "This is a bounded review of two intentionally faulty, hand-written targets. "
        "Each source uses the same input contract and trusted reference for a given problem. "
        "A confirmed counterexample is an in-contract input whose target output differs "
        "from that reference. This report records case-level evidence, not final run verdicts.",
        "",
        f"- Python: {platform.python_version()}",
        f"- Hypothesis: {hypothesis_version}",
        f"- Hypothesis setting: seed {HYPOTHESIS_SEED}; up to {MAX_EXAMPLES} examples; "
        f"integer values from -{INTEGER_BOUND} through {INTEGER_BOUND}; "
        f"lists up to {MAX_LIST_SIZE} items.",
        "- LLM proposals: offline proposal fixtures drafted for this review; no provider API "
        "was called.",
        "",
        "## Seed contracts",
        "",
    ]
    for problem in PROBLEMS:
        lines.extend(
            [
                f"### {problem.problem_id}",
                "",
                f"- Claim: {problem.claim}",
                f"- Contract: {problem.contract_description}",
                "",
            ]
        )
    lines.extend(
        [
            "## Offline LLM proposal inspection",
            "",
        ]
    )
    for problem in PROBLEMS:
        lines.append(f"### {problem.problem_id}")
        lines.append("")
        for proposal in problem.llm_cases:
            lines.append(
                f"- `{json.dumps(proposal.value, ensure_ascii=False)}` — "
                f"{proposal.rationale}"
            )
        lines.append("")
    lines.extend(
        [
            "## Final outcome vocabulary",
            "",
            "A case-level CASE_PASSED result means only that one input satisfied the property. "
            "It is not the run-level TESTS_PASSED verdict.",
            "",
        ]
    )
    for outcome in FinalOutcome:
        lines.append("- " + outcome.value)
    lines.extend(
        [
            "",
            "Outcome reasons include "
            + OutcomeReason.CONFIRMED_COUNTEREXAMPLE.value
            + ", "
            + OutcomeReason.NO_COUNTEREXAMPLE_FOUND.value
            + ", "
            + OutcomeReason.BUDGET_EXHAUSTED.value
            + ", "
            + OutcomeReason.CONFLICTING_EVIDENCE.value
            + ", and "
            + OutcomeReason.EXTERNAL_ERROR.value
            + ".",
            "",
        ]
    )
    lines.extend(
        [
            "| Seed problem | Source | Cases generated | Valid | Confirmed counterexamples | Runtime (ms) | Failures |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        failures = ", ".join(
            f"{category}: {count}" for category, count in row["failures"].items()
        ) or "None"
        lines.append(
            f"| {row['problem_id']} | {row['source']} | {row['generated']} | "
            f"{row['valid']} | {row['confirmed_counterexamples']} | "
            f"{row['runtime_ms']:.3f} | {failures} |"
        )

    lines.extend(["", "## Findings", ""])
    for row in rows:
        lines.append(f"### {row['problem_id']} — {row['source']}")
        lines.append("")
        if row["generation_error"]:
            lines.append(f"Source execution issue: {row['generation_error']}")
            lines.append("")
        if not row["findings"]:
            lines.append(
                "No invalid proposals, target exceptions, oracle defects, or "
                "confirmed counterexamples were observed."
            )
            lines.append("")
            continue
        for finding in row["findings"]:
            details = (
                f"input `{json.dumps(finding['input'], ensure_ascii=False)}` → "
                f"{finding['category']}"
            )
            if finding["category"] == "PROPERTY_VIOLATION":
                details += (
                    f" (target returned `{json.dumps(finding['actual'])}`, "
                    f"reference expected `{json.dumps(finding['expected'])}`)"
                )
            else:
                details += f" ({finding['message']})"
            lines.append(f"- {details}")
        lines.append("")

    lines.extend(
        [
            "## Interpretation",
            "",
            "The fixed and Hypothesis sources find the seeded defects. The offline LLM-style "
            "proposals miss both defects because they do not include duplicate values or an "
            "all-negative list. The malformed sort proposal and empty largest proposal are "
            "rejected as OUT_OF_CONTRACT before the target or oracle is called.",
            "",
            "This small, intentionally seeded comparison demonstrates the evidence flow; it "
            "does not measure general LLM or property-based-testing performance. Hypothesis "
            "stops a problem's run after its first confirmed mismatch and may evaluate extra "
            "examples while shrinking it. Hypothesis's generated count includes property "
            "function invocations during shrinking. Runtime is local wall-clock time for "
            "source generation and harness checks; it does not include any model latency.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    rows: list[dict[str, Any]] = []
    for problem in PROBLEMS:
        source_runs = (
            ("Fixed edge cases", run_fixed_cases),
            ("Hypothesis", run_hypothesis),
            ("Offline LLM proposals", run_llm_proposals),
        )
        for source, run_source in source_runs:
            started = time.perf_counter()
            proposals, generation_error = run_source(problem)
            row = evaluate_source(problem, source, proposals, generation_error)
            row["runtime_ms"] = round((time.perf_counter() - started) * 1000, 3)
            rows.append(row)

    report = render_report(rows)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
