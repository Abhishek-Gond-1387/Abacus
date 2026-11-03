"""Check the test oracle with manual fixtures, mutants, and saved failures."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

if __package__:
    from .day21_review import PROBLEMS, check_case
else:
    from day21_review import PROBLEMS, check_case


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DAY21_REPORT = PROJECT_ROOT / "practice" / "day21_report.md"
REPORT_PATH = PROJECT_ROOT / "practice" / "day26_checker_report.md"


@dataclass(frozen=True)
class KnownCase:
    input_value: list[int]
    expected: Any


def sort_correct(values: list[int]) -> list[int]:
    return sorted(values)


def sort_drops_duplicates(values: list[int]) -> list[int]:
    return sorted(set(values))


def largest_correct(values: list[int]) -> int:
    if not values:
        raise ValueError("largest expects a non-empty list")
    return max(values)


def largest_returns_zero_for_negative_lists(values: list[int]) -> int:
    largest = 0
    for value in values:
        if value > largest:
            largest = value
    return largest


def sort_oracle(values: list[int]) -> list[int]:
    return sorted(values)


def largest_oracle(values: list[int]) -> int:
    return max(values)


def flawed_sort_oracle(values: list[int]) -> list[int]:
    return sorted(set(values))


SORT_CASES = (
    KnownCase([], []),
    KnownCase([7], [7]),
    KnownCase([3, -1, 3, 0], [-1, 0, 3, 3]),
    KnownCase([4, 4], [4, 4]),
)

LARGEST_CASES = (
    KnownCase([4], 4),
    KnownCase([-4, -1, -9], -1),
    KnownCase([3, 3], 3),
)


def evaluate_known_cases(
    target: Callable[[list[int]], Any],
    oracle: Callable[[list[int]], Any],
    cases: tuple[KnownCase, ...],
) -> list[dict[str, Any]]:
    """Compare target and oracle separately against hand-written answers."""
    records = []
    for case in cases:
        actual = target(case.input_value)
        oracle_value = oracle(case.input_value)
        records.append(
            {
                "input": case.input_value,
                "manual_expected": case.expected,
                "oracle": oracle_value,
                "actual": actual,
                "oracle_matches_fixture": oracle_value == case.expected,
                "target_matches_fixture": actual == case.expected,
                "category": "CASE_PASSED" if actual == oracle_value else "PROPERTY_VIOLATION",
            }
        )
    return records


def audit_oracle(
    oracle: Callable[[list[int]], Any], cases: tuple[KnownCase, ...]
) -> list[dict[str, Any]]:
    """Check the oracle itself against independently written expected values."""
    records = []
    for case in cases:
        actual = oracle(case.input_value)
        records.append(
            {
                "input": case.input_value,
                "manual_expected": case.expected,
                "oracle": actual,
                "category": "CASE_PASSED" if actual == case.expected else "TEST_ORACLE_DEFECT",
            }
        )
    return records


def sort_idempotence(function: Callable[[list[int]], list[int]], values: list[int]) -> bool:
    once = function(values)
    return function(once) == once


def replay_saved_counterexamples(
    report_path: Path = DAY21_REPORT,
) -> list[dict[str, Any]]:
    """Re-run every Day 21 finding marked PROPERTY_VIOLATION."""
    section = re.compile(r"^### ([^ ]+) — ")
    finding = re.compile(r"^- input `(.+?)` → PROPERTY_VIOLATION")
    known_problems = {problem.problem_id: problem for problem in PROBLEMS}
    current_problem: str | None = None
    results = []

    for line in report_path.read_text(encoding="utf-8").splitlines():
        heading = section.match(line)
        if heading:
            current_problem = heading.group(1) if heading.group(1) in known_problems else None
            continue
        match = finding.match(line)
        if not match or current_problem is None:
            continue
        value = json.loads(match.group(1))
        outcome = check_case(known_problems[current_problem], value)
        results.append(
            {
                "problem_id": current_problem,
                "input": value,
                "category": outcome["category"],
                "still_counterexample": outcome["category"] == "PROPERTY_VIOLATION",
            }
        )

    if not results:
        raise ValueError(f"No saved counterexamples found in {report_path}")
    return results


def build_report() -> tuple[str, dict[str, Any]]:
    correct_sort = evaluate_known_cases(sort_correct, sort_oracle, SORT_CASES)
    faulty_sort = evaluate_known_cases(sort_drops_duplicates, sort_oracle, SORT_CASES)
    correct_largest = evaluate_known_cases(largest_correct, largest_oracle, LARGEST_CASES)
    faulty_largest = evaluate_known_cases(
        largest_returns_zero_for_negative_lists, largest_oracle, LARGEST_CASES
    )
    bad_oracle = audit_oracle(flawed_sort_oracle, SORT_CASES)
    false_accusation = evaluate_known_cases(sort_correct, flawed_sort_oracle, SORT_CASES)
    replay = replay_saved_counterexamples()
    mutant_passes_metamorphic = sort_idempotence(sort_drops_duplicates, [4, 4])

    summary = {
        "correct_fixtures_pass": all(
            row["category"] == "CASE_PASSED"
            and row["oracle_matches_fixture"]
            and row["target_matches_fixture"]
            for row in (*correct_sort, *correct_largest)
        ),
        "sort_mutant_caught": any(row["category"] == "PROPERTY_VIOLATION" for row in faulty_sort),
        "largest_mutant_caught": any(
            row["category"] == "PROPERTY_VIOLATION" for row in faulty_largest
        ),
        "bad_oracle_detected": any(row["category"] == "TEST_ORACLE_DEFECT" for row in bad_oracle),
        "correct_target_falsely_accused_by_bad_oracle": any(
            row["category"] == "PROPERTY_VIOLATION" for row in false_accusation
        ),
        "saved_counterexamples_replayed": len(replay),
        "saved_counterexamples_still_fail": sum(row["still_counterexample"] for row in replay),
        "duplicate_mutant_passes_sort_idempotence": mutant_passes_metamorphic,
    }

    lines = [
        "# Day 26 — Check the checker",
        "",
        "The fixtures use manually written expected outputs to inspect both target functions and the oracle. They cover duplicate preservation and negative-only maximum inputs. These finite fixtures catch the included defects but do not prove either implementation correct for every integer list.",
        "",
        "## Validation results",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Correct target fixtures and reference agree with manual answers | {'PASS' if summary['correct_fixtures_pass'] else 'FAIL'} |",
        f"| Duplicate-removing sort mutant is caught | {'CAUGHT' if summary['sort_mutant_caught'] else 'MISSED'} |",
        f"| Zero-initialized maximum mutant is caught | {'CAUGHT' if summary['largest_mutant_caught'] else 'MISSED'} |",
        f"| Duplicate-removing oracle disagrees with manual fixtures | {'DETECTED' if summary['bad_oracle_detected'] else 'MISSED'} |",
        f"| Bad oracle would falsely accuse correct sort | {'YES' if summary['correct_target_falsely_accused_by_bad_oracle'] else 'NO'} |",
        f"| Saved Day 21 counterexamples replayed | {summary['saved_counterexamples_replayed']} |",
        f"| Saved Day 21 counterexamples still reproduce | {summary['saved_counterexamples_still_fail']} |",
        f"| Duplicate-removal mutant passes sort idempotence | {'YES' if mutant_passes_metamorphic else 'NO'} |",
        "",
        "The intentionally faulty oracle returns sorted unique values. The manual duplicate fixtures flag it as TEST_ORACLE_DEFECT; using it anyway makes the correct sorter appear to violate the contract. This demonstrates that an oracle defect can reverse a verdict.",
        "",
        "Sort idempotence (`sort(sort(xs)) == sort(xs)`) is useful but incomplete: duplicate removal is idempotent and still violates duplicate preservation. The manual contract fixtures are needed to catch that defect.",
        "",
        "## Day 21 replay",
        "",
        "| Problem | Saved input | Replay |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {row['problem_id']} | `{json.dumps(row['input'])}` | {row['category']} |"
        for row in replay
    )
    lines.extend(
        [
            "",
            "## Remaining uncertainty",
            "",
            "The expected outputs were reviewed directly against the stated contracts, and no independent human reviewer was available for this run. Handwritten fixtures reduce shared-oracle risk on these examples, but they cannot establish full oracle soundness or cover all inputs. A broader independent review is still useful before treating an oracle as trusted.",
            "",
        ]
    )
    return "\n".join(lines), summary


def main() -> None:
    report, summary = build_report()
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print("\nSummary:")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
