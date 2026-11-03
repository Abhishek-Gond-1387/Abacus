"""Find, shrink, and save oracle-confirmed failures from trusted records."""

from __future__ import annotations

import argparse
import random
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import hypothesis
from hypothesis import find, settings, strategies as st
from hypothesis.errors import NoSuchExample

from .counterexamples import save_counterexample
from .harness import CaseEvidence, HarnessStatus, check_case
from .problems import ProblemValidationError, load_problem, validate_problem


DEFAULT_HYPOTHESIS_SEED = 17017
DEFAULT_MAX_EXAMPLES = 40
DEFAULT_DEADLINE_MS = 5_000
SORTING_INPUTS = st.lists(
    st.integers(min_value=-20, max_value=20),
    min_size=0,
    max_size=12,
)


@dataclass(frozen=True)
class SavedHypothesisFailure:
    input_value: list[int]
    evidence: CaseEvidence
    seed: int
    source: str
    saved_path: Path


def _resolve_problem(problem: Any) -> dict[str, Any]:
    if isinstance(problem, (str, Path)):
        return load_problem(problem)
    if isinstance(problem, Mapping):
        record = dict(problem)
    else:
        record = problem
    validate_problem(record)
    return record


def find_and_save_sorting_failure(
    problem: Any,
    destination: str | Path,
    *,
    seed: int = DEFAULT_HYPOTHESIS_SEED,
    max_examples: int = DEFAULT_MAX_EXAMPLES,
    deadline_ms: int = DEFAULT_DEADLINE_MS,
) -> SavedHypothesisFailure:
    """Shrink an oracle refutation, recheck it, then save it in Day 13 format."""

    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if type(max_examples) is not int or max_examples <= 0:
        raise ValueError("max_examples must be a positive integer")
    if type(deadline_ms) is not int or deadline_ms <= 0:
        raise ValueError("deadline_ms must be a positive integer")

    record = _resolve_problem(problem)

    def is_oracle_refuted(values: list[int]) -> bool:
        evidence = check_case(record, values)
        return evidence.status is HarnessStatus.REFUTED

    search_settings = settings(
        max_examples=max_examples,
        database=None,
        deadline=timedelta(milliseconds=deadline_ms),
    )
    shrunk_input = find(
        SORTING_INPUTS,
        is_oracle_refuted,
        settings=search_settings,
        random=random.Random(seed),
    )
    evidence = check_case(record, shrunk_input)
    if evidence.status is not HarnessStatus.REFUTED or not evidence.input_valid:
        raise RuntimeError("the minimized input did not reproduce a valid oracle refutation")

    source = (
        f"hypothesis.find; version={hypothesis.__version__}; "
        "strategy=lists(integers(-20..20), min_size=0, max_size=12); "
        f"max_examples={max_examples}; database=None; deadline_ms={deadline_ms}; "
        f"random_seed={seed}"
    )
    saved_path = save_counterexample(
        record,
        evidence,
        destination,
        source=source,
        seed=seed,
    )
    return SavedHypothesisFailure(
        input_value=list(shrunk_input),
        evidence=evidence,
        seed=seed,
        source=source,
        saved_path=saved_path,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Shrink and save a sorting failure found by Hypothesis."
    )
    parser.add_argument("problem", help="validated problem JSON path")
    parser.add_argument("destination", help="counterexample JSON output path")
    parser.add_argument("--seed", type=int, default=DEFAULT_HYPOTHESIS_SEED)
    parser.add_argument("--max-examples", type=int, default=DEFAULT_MAX_EXAMPLES)
    parser.add_argument("--deadline-ms", type=int, default=DEFAULT_DEADLINE_MS)
    args = parser.parse_args(argv)

    try:
        saved = find_and_save_sorting_failure(
            args.problem,
            args.destination,
            seed=args.seed,
            max_examples=args.max_examples,
            deadline_ms=args.deadline_ms,
        )
    except (NoSuchExample, OSError, ProblemValidationError, ValueError, RuntimeError) as error:
        print(f"error: no replayable counterexample saved ({error})", file=sys.stderr)
        return 1

    expected = list(saved.evidence.oracle_result.expected_output)
    print(
        f"saved shrunk input {saved.input_value}: "
        f"target={saved.evidence.target_result}, expected={expected}; "
        f"seed={saved.seed}; path={saved.saved_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
