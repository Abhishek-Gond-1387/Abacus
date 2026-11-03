"""Atomic persistence and deterministic replay for trusted counterexamples."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .harness import CaseEvidence, HarnessStatus, check_case
from .problems import ProblemValidationError, load_problem, validate_problem


SCHEMA_VERSION = 1
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class CounterexampleValidationError(ValueError):
    """A saved counterexample does not match the supported JSON schema."""


class ReplayStatus(str, Enum):
    REPRODUCED = "REPRODUCED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class ReplayEvidence:
    status: ReplayStatus
    code_version_matches: bool
    problem_record_version_matches: bool
    case_evidence: CaseEvidence | None
    explanation: str

    @property
    def reproduced(self) -> bool:
        return self.status is ReplayStatus.REPRODUCED

    def as_dict(self) -> dict[str, Any]:
        evidence = self.case_evidence
        return {
            "status": self.status.value,
            "code_version_matches": self.code_version_matches,
            "problem_record_version_matches": self.problem_record_version_matches,
            "explanation": self.explanation,
            "problem_id": evidence.problem_id if evidence else None,
            "input": list(evidence.input_value) if evidence else None,
            "input_valid": evidence.input_valid if evidence else None,
            "case_status": evidence.status.value if evidence else None,
            "target_result": evidence.target_result if evidence else None,
            "target_exception": _exception_to_dict(evidence.target_exception)
            if evidence
            else None,
            "oracle_status": (
                evidence.oracle_result.status.value
                if evidence and evidence.oracle_result
                else None
            ),
            "expected_output": (
                list(evidence.oracle_result.expected_output or ())
                if evidence and evidence.oracle_result
                else None
            ),
            "case_explanation": evidence.explanation if evidence else None,
        }


def _resolve_problem(problem: Any) -> dict[str, Any]:
    if isinstance(problem, (str, Path)):
        return load_problem(problem)
    if isinstance(problem, Mapping):
        record = dict(problem)
    else:
        record = problem
    validate_problem(record)
    return record


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _versions(record: Mapping[str, Any]) -> dict[str, str]:
    return {
        "target_code_sha256": hashlib.sha256(
            record["code"].encode("utf-8")
        ).hexdigest(),
        "problem_record_sha256": hashlib.sha256(_canonical_json(record)).hexdigest(),
    }


def _exception_to_dict(error: Any) -> dict[str, str] | None:
    if error is None:
        return None
    return {
        "type": error.type_name,
        "message": error.message,
        "phase": error.phase,
    }


def _counterexample_payload(
    record: Mapping[str, Any],
    evidence: CaseEvidence,
    *,
    source: str,
    seed: int | None,
) -> dict[str, Any]:
    if evidence.problem_id != record.get("id"):
        raise ValueError("evidence problem_id does not match the problem record")
    if evidence.status is not HarnessStatus.REFUTED or evidence.oracle_result is None:
        raise ValueError("only an oracle-refuted case can be saved as a counterexample")
    if evidence.input_valid is not True:
        raise ValueError("only contract-valid inputs can be saved as counterexamples")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a non-empty string")
    if seed is not None and type(seed) is not int:
        raise ValueError("seed must be an integer or null")

    oracle = evidence.oracle_result
    if oracle.status.value != "REFUTED":
        raise ValueError("the trusted oracle did not refute this case")
    return {
        "schema_version": SCHEMA_VERSION,
        "problem_id": record["id"],
        "input": list(evidence.input_value),
        "source": source.strip(),
        "seed": seed,
        "contract_validity": {
            "valid": evidence.input_valid,
            "reason": evidence.validity_reason,
        },
        "observed_result": {
            "status": evidence.status.value,
            "target_result": evidence.target_result,
            "target_exception": _exception_to_dict(evidence.target_exception),
            "oracle_status": oracle.status.value,
            "oracle_reason": oracle.reason,
            "explanation": evidence.explanation,
        },
        "expected_property": {
            "oracle_id": record["oracle_id"],
            "description": record["property_description"],
            "expected_output": list(oracle.expected_output or ()),
        },
        "versions": _versions(record),
    }


def save_counterexample(
    problem: Any,
    evidence: CaseEvidence,
    destination: str | os.PathLike[str],
    *,
    source: str,
    seed: int | None = None,
) -> Path:
    """Atomically write a contract-valid oracle refutation as versioned JSON."""

    record = _resolve_problem(problem)
    payload = _counterexample_payload(record, evidence, source=source, seed=seed)
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


def _require_keys(value: Any, expected: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise CounterexampleValidationError(f"{name}: unexpected fields or shape")
    return value


def load_counterexample(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load and validate a saved counterexample JSON file."""

    source_path = Path(path)
    try:
        data = json.loads(source_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise CounterexampleValidationError(
            f"{source_path}: could not read file ({error})"
        ) from None
    except json.JSONDecodeError as error:
        raise CounterexampleValidationError(
            f"{source_path}:{error.lineno}:{error.colno}: invalid JSON ({error.msg})"
        ) from None

    data = _require_keys(
        data,
        {
            "schema_version",
            "problem_id",
            "input",
            "source",
            "seed",
            "contract_validity",
            "observed_result",
            "expected_property",
            "versions",
        },
        "counterexample",
    )
    if type(data["schema_version"]) is not int or data["schema_version"] != SCHEMA_VERSION:
        raise CounterexampleValidationError("schema_version: unsupported version")
    if not isinstance(data["problem_id"], str) or not data["problem_id"].strip():
        raise CounterexampleValidationError("problem_id: expected a non-empty string")
    if (
        not isinstance(data["input"], list)
        or any(type(value) is not int for value in data["input"])
    ):
        raise CounterexampleValidationError("input: expected an integer list")
    if not isinstance(data["source"], str) or not data["source"].strip():
        raise CounterexampleValidationError("source: expected a non-empty string")
    if data["seed"] is not None and type(data["seed"]) is not int:
        raise CounterexampleValidationError("seed: expected an integer or null")

    contract = _require_keys(
        data["contract_validity"], {"valid", "reason"}, "contract_validity"
    )
    if contract["valid"] is not True or (
        contract["reason"] is not None and not isinstance(contract["reason"], str)
    ):
        raise CounterexampleValidationError(
            "contract_validity: saved counterexamples must be contract-valid"
        )

    observed = _require_keys(
        data["observed_result"],
        {
            "status",
            "target_result",
            "target_exception",
            "oracle_status",
            "oracle_reason",
            "explanation",
        },
        "observed_result",
    )
    if observed["status"] != HarnessStatus.REFUTED.value:
        raise CounterexampleValidationError("observed_result.status must be REFUTED")
    if observed["oracle_status"] != "REFUTED":
        raise CounterexampleValidationError("observed_result.oracle_status must be REFUTED")
    if observed["target_exception"] is not None:
        raise CounterexampleValidationError(
            "observed_result.target_exception must be null for a refuted return value"
        )
    for field in ("oracle_reason", "explanation"):
        if observed[field] is not None and not isinstance(observed[field], str):
            raise CounterexampleValidationError(
                f"observed_result.{field}: expected a string or null"
            )

    expected = _require_keys(
        data["expected_property"],
        {"oracle_id", "description", "expected_output"},
        "expected_property",
    )
    for field in ("oracle_id", "description"):
        if not isinstance(expected[field], str) or not expected[field].strip():
            raise CounterexampleValidationError(
                f"expected_property.{field}: expected a non-empty string"
            )
    if (
        not isinstance(expected["expected_output"], list)
        or any(type(value) is not int for value in expected["expected_output"])
    ):
        raise CounterexampleValidationError(
            "expected_property.expected_output: expected an integer list"
        )

    versions = _require_keys(
        data["versions"],
        {"target_code_sha256", "problem_record_sha256"},
        "versions",
    )
    for name, digest in versions.items():
        if not isinstance(digest, str) or not _HASH_PATTERN.fullmatch(digest):
            raise CounterexampleValidationError(f"versions.{name}: invalid SHA-256 hash")
    return data


def _same_json_value(left: Any, right: Any) -> bool:
    try:
        return _canonical_json(left) == _canonical_json(right)
    except (TypeError, ValueError):
        return False


def replay_counterexample(
    counterexample_path: str | os.PathLike[str],
    problem: Any,
) -> ReplayEvidence:
    """Rerun a saved input and oracle, exposing code/record version drift."""

    saved = load_counterexample(counterexample_path)
    record = _resolve_problem(problem)
    current_versions = _versions(record)
    code_matches = (
        current_versions["target_code_sha256"]
        == saved["versions"]["target_code_sha256"]
    )
    record_matches = (
        current_versions["problem_record_sha256"]
        == saved["versions"]["problem_record_sha256"]
    )
    if record["id"] != saved["problem_id"]:
        return ReplayEvidence(
            ReplayStatus.UNRESOLVED,
            code_matches,
            record_matches,
            None,
            "UNRESOLVED: supplied problem ID differs from the saved counterexample",
        )

    evidence = check_case(record, saved["input"])
    reproduced = (
        evidence.status is HarnessStatus.REFUTED
        and evidence.oracle_result is not None
        and record["oracle_id"] == saved["expected_property"]["oracle_id"]
        and _same_json_value(
            evidence.target_result,
            saved["observed_result"]["target_result"],
        )
        and _same_json_value(
            list(evidence.oracle_result.expected_output or ()),
            saved["expected_property"]["expected_output"],
        )
    )
    if reproduced:
        explanation = "REPRODUCED: the saved target result still violates the trusted property"
        if not code_matches or not record_matches:
            explanation += "; version mismatch is visible in the version flags"
        return ReplayEvidence(
            ReplayStatus.REPRODUCED,
            code_matches,
            record_matches,
            evidence,
            explanation,
        )
    return ReplayEvidence(
        ReplayStatus.UNRESOLVED,
        code_matches,
        record_matches,
        evidence,
        "UNRESOLVED: the saved mismatch did not reproduce; do not claim a refutation",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Save and replay counterexamples for trusted Abacus problems."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    record_parser = commands.add_parser("record", help="check and save a refuted input")
    record_parser.add_argument("problem", help="validated problem JSON path")
    record_parser.add_argument("input_json", help="input encoded as JSON")
    record_parser.add_argument("destination", help="counterexample JSON output path")
    record_parser.add_argument("--source", required=True, help="seed/source description")
    record_parser.add_argument("--seed", type=int, help="optional deterministic seed")

    replay_parser = commands.add_parser("replay", help="replay a saved counterexample")
    replay_parser.add_argument("counterexample", help="saved counterexample JSON path")
    replay_parser.add_argument("problem", help="current validated problem JSON path")

    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            record = load_problem(args.problem)
            input_value = json.loads(args.input_json)
            evidence = check_case(record, input_value)
            if evidence.status is not HarnessStatus.REFUTED:
                print(
                    f"not saved: case status is {evidence.status.value} "
                    f"({evidence.explanation})",
                    file=sys.stderr,
                )
                return 1
            saved_path = save_counterexample(
                record,
                evidence,
                args.destination,
                source=args.source,
                seed=args.seed,
            )
            print(f"saved counterexample: {saved_path}")
            return 0

        result = replay_counterexample(args.counterexample, args.problem)
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return 0 if result.reproduced else 1
    except (CounterexampleValidationError, ProblemValidationError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
