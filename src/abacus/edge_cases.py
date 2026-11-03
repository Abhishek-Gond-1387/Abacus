"""Deterministic, explained edge cases for the integer-sorting pilot."""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import InputStatus, validate_input
from .harness import CaseEvidence, HarnessStatus, check_case
from .problems import ProblemValidationError, load_problem, validate_problem


GENERATOR_VERSION = "sorted-integer-edge-cases-v1"
RUN_RECORD_SCHEMA_VERSION = 1
DEFAULT_RANDOM_SEED = 1501
RANDOM_CASE_COUNT = 3


@dataclass(frozen=True)
class EdgeCase:
    name: str
    input_value: Any
    explanation: str
    contract_status: InputStatus

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "input": self.input_value,
            "contract_status": self.contract_status.value,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class EdgeCaseSet:
    problem_id: str
    generator_version: str
    seed: int
    python_version: str
    cases: tuple[EdgeCase, ...]

    @property
    def inputs(self) -> tuple[Any, ...]:
        return tuple(case.input_value for case in self.cases)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUN_RECORD_SCHEMA_VERSION,
            "problem_id": self.problem_id,
            "generator_version": self.generator_version,
            "seed": self.seed,
            "python_version": self.python_version,
            "cases": [case.as_dict() for case in self.cases],
        }


@dataclass(frozen=True)
class EdgeCaseRun:
    case_set: EdgeCaseSet
    evidence: tuple[CaseEvidence, ...]
    saved_path: Path

    @property
    def passed_count(self) -> int:
        return sum(item.status is HarnessStatus.PASSED for item in self.evidence)

    @property
    def out_of_contract_count(self) -> int:
        return sum(
            item.status is HarnessStatus.OUT_OF_CONTRACT for item in self.evidence
        )

    @property
    def other_count(self) -> int:
        return len(self.evidence) - self.passed_count - self.out_of_contract_count


def _resolve_problem(problem: Any) -> dict[str, Any]:
    if isinstance(problem, (str, Path)):
        return load_problem(problem)
    if isinstance(problem, Mapping):
        record = dict(problem)
    else:
        record = problem
    validate_problem(record)
    return record


def generate_edge_cases(
    problem: Any,
    *,
    seed: int = DEFAULT_RANDOM_SEED,
) -> EdgeCaseSet:
    """Build named boundary fixtures and a small repeatable random sample."""

    if type(seed) is not int:
        raise ValueError("seed must be an integer (booleans are not seeds)")
    record = _resolve_problem(problem)
    fixed_cases: tuple[tuple[str, Any, str], ...] = (
        ("empty", [], "Checks the valid empty-list boundary."),
        ("single_item", [7], "Checks the smallest non-empty list."),
        ("duplicates", [3, 1, 3], "Checks duplicate preservation and ordering."),
        (
            "negative_and_zero",
            [0, -3, 2, -1],
            "Checks ordering across negative values, zero, and positives.",
        ),
        (
            "already_sorted",
            [-2, 0, 4, 8],
            "Checks an input that already satisfies nondecreasing order.",
        ),
        (
            "reverse_sorted",
            [8, 4, 0, -2],
            "Checks an input in descending order.",
        ),
        ("all_equal", [5, 5, 5, 5], "Checks repeated equal values."),
        (
            "large_magnitude",
            [-(10**30), 0, 10**30],
            "Checks arbitrary-precision integers beyond common 64-bit bounds.",
        ),
    )
    cases: list[EdgeCase] = []
    for name, input_value, explanation in fixed_cases:
        validation = validate_input(record, input_value)
        if not validation.valid:
            raise ValueError(
                f"configured edge case {name!r} violates its contract: "
                f"{validation.reason}"
            )
        cases.append(EdgeCase(name, input_value, explanation, InputStatus.VALID))

    randomizer = random.Random(seed)
    for index in range(RANDOM_CASE_COUNT):
        length = randomizer.randint(1, 8)
        input_value = [randomizer.randint(-100, 100) for _ in range(length)]
        validation = validate_input(record, input_value)
        if not validation.valid:
            raise ValueError(
                "seeded random generator produced an out-of-contract input: "
                f"{validation.reason}"
            )
        cases.append(
            EdgeCase(
                f"seeded_random_{index + 1}",
                input_value,
                f"Seeded sample {index + 1}; exercises a repeatable combination "
                "of values in [-100, 100].",
                InputStatus.VALID,
            )
        )

    invalid_input = [True, 1]
    invalid_validation = validate_input(record, invalid_input)
    if invalid_validation.status is not InputStatus.OUTSIDE_CONTRACT:
        raise ValueError("the configured invalid fixture unexpectedly satisfies its contract")
    cases.append(
        EdgeCase(
            "boolean_is_out_of_contract",
            invalid_input,
            "Confirms booleans are rejected even though bool is a subclass of int.",
            InputStatus.OUTSIDE_CONTRACT,
        )
    )

    return EdgeCaseSet(
        problem_id=record["id"],
        generator_version=GENERATOR_VERSION,
        seed=seed,
        python_version=platform.python_version(),
        cases=tuple(cases),
    )


def save_edge_case_run(
    case_set: EdgeCaseSet,
    evidence: tuple[CaseEvidence, ...],
    destination: str | os.PathLike[str],
) -> Path:
    """Atomically save the exact generated inputs and their harness outcomes."""

    if len(evidence) != len(case_set.cases):
        raise ValueError("evidence count must match the generated case count")
    outcomes = []
    for case, result in zip(case_set.cases, evidence, strict=True):
        outcomes.append(
            {
                "case_name": case.name,
                "status": result.status.value,
                "target_result": result.target_result,
                "target_exception": (
                    {
                        "type": result.target_exception.type_name,
                        "message": result.target_exception.message,
                        "phase": result.target_exception.phase,
                    }
                    if result.target_exception
                    else None
                ),
                "oracle_status": (
                    result.oracle_result.status.value if result.oracle_result else None
                ),
                "explanation": result.explanation,
            }
        )
    payload = case_set.as_dict()
    payload["outcomes"] = outcomes

    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".tmp",
        dir=destination_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination_path)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
    return destination_path


def run_edge_case_suite(
    problem: Any,
    destination: str | os.PathLike[str],
    *,
    seed: int = DEFAULT_RANDOM_SEED,
) -> EdgeCaseRun:
    record = _resolve_problem(problem)
    case_set = generate_edge_cases(record, seed=seed)
    evidence = tuple(check_case(record, item.input_value) for item in case_set.cases)
    saved_path = save_edge_case_run(case_set, evidence, destination)
    return EdgeCaseRun(case_set, evidence, saved_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate, run, and save deterministic Abacus edge cases."
    )
    parser.add_argument("problem", help="validated problem JSON path")
    parser.add_argument("destination", help="run record JSON output path")
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    args = parser.parse_args(argv)

    try:
        run = run_edge_case_suite(args.problem, args.destination, seed=args.seed)
    except (OSError, ProblemValidationError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"saved run record: {run.saved_path} "
        f"({run.passed_count} passed, "
        f"{run.out_of_contract_count} out of contract, "
        f"{run.other_count} other outcomes, "
        f"{len(run.evidence)} cases; seed={run.case_set.seed})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())