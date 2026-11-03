"""Load and validate hand-authored Abacus problem records."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = (
    "id",
    "title",
    "claim",
    "code",
    "domain",
    "preconditions",
    "property_description",
    "oracle_id",
    "expected_label",
    "label_rationale",
    "family",
)
ALLOWED_FIELDS = frozenset((*REQUIRED_FIELDS, "known_counterexample"))
DOMAIN_FIELDS = frozenset(("input_type", "output_type", "description"))
COUNTEREXAMPLE_FIELDS = frozenset(
    ("input", "expected_output", "actual_output", "reason")
)
COUNTEREXAMPLE_REQUIRED_FIELDS = frozenset(
    ("input", "expected_output", "actual_output")
)
VALID_LABELS = frozenset(("TRUE", "FALSE"))
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


class ProblemValidationError(ValueError):
    """A problem record contains one or more structural contract violations."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        details = "\n".join(f"- {error}" for error in errors)
        super().__init__(f"Invalid problem record:\n{details}")


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_problem(record: Any) -> None:
    """Validate one JSON-compatible problem record without executing its code."""

    if not isinstance(record, dict):
        raise ProblemValidationError(["record: expected a JSON object"])

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in record:
            errors.append(f"{field}: required field is missing")

    unknown_fields = sorted(set(record) - ALLOWED_FIELDS)
    for field in unknown_fields:
        errors.append(f"{field}: unknown top-level field")

    for field in (
        "id",
        "title",
        "claim",
        "code",
        "property_description",
        "oracle_id",
        "label_rationale",
        "family",
    ):
        if field in record and not _is_nonempty_string(record[field]):
            errors.append(f"{field}: expected a non-empty string")

    if "id" in record and _is_nonempty_string(record["id"]):
        if not _ID_PATTERN.fullmatch(record["id"]):
            errors.append(
                "id: use lowercase letters and digits with single hyphens between words"
            )

    if "domain" in record:
        domain = record["domain"]
        if not isinstance(domain, dict):
            errors.append("domain: expected an object")
        else:
            for field in sorted(DOMAIN_FIELDS):
                if field not in domain:
                    errors.append(f"domain.{field}: required field is missing")
                elif not _is_nonempty_string(domain[field]):
                    errors.append(f"domain.{field}: expected a non-empty string")
            for field in sorted(set(domain) - DOMAIN_FIELDS):
                errors.append(f"domain.{field}: unknown field")

    if "preconditions" in record:
        preconditions = record["preconditions"]
        if not isinstance(preconditions, list):
            errors.append("preconditions: expected an array of non-empty strings")
        else:
            for index, precondition in enumerate(preconditions):
                if not _is_nonempty_string(precondition):
                    errors.append(
                        f"preconditions[{index}]: expected a non-empty string"
                    )

    expected_label = record.get("expected_label")
    if "expected_label" in record and (
        not isinstance(expected_label, str) or expected_label not in VALID_LABELS
    ):
        errors.append("expected_label: must be exactly 'TRUE' or 'FALSE'")

    if expected_label == "FALSE":
        if "known_counterexample" not in record:
            errors.append(
                "known_counterexample: required when expected_label is 'FALSE'"
            )
        else:
            counterexample = record["known_counterexample"]
            if not isinstance(counterexample, dict):
                errors.append(
                    "known_counterexample: expected an object for a false claim"
                )
            else:
                missing_fields = COUNTEREXAMPLE_REQUIRED_FIELDS - counterexample.keys()
                for field in sorted(missing_fields):
                    errors.append(f"known_counterexample.{field}: required field is missing")
                for field in sorted(set(counterexample) - COUNTEREXAMPLE_FIELDS):
                    errors.append(f"known_counterexample.{field}: unknown field")
                if "reason" in counterexample and not _is_nonempty_string(
                    counterexample["reason"]
                ):
                    errors.append(
                        "known_counterexample.reason: expected a non-empty string"
                    )
    elif (
        expected_label == "TRUE"
        and "known_counterexample" in record
        and record["known_counterexample"] is not None
    ):
        errors.append(
            "known_counterexample: omit this field or set it to null for a true claim"
        )

    if errors:
        raise ProblemValidationError(errors)


def load_problem(path: str | Path) -> dict[str, Any]:
    """Load a UTF-8 JSON problem file and validate its record contract."""

    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as error:
        raise ProblemValidationError(
            [f"{source}: could not read file ({error})"]
        ) from None

    try:
        record = json.loads(text)
    except json.JSONDecodeError as error:
        raise ProblemValidationError(
            [f"{source}:{error.lineno}:{error.colno}: invalid JSON ({error.msg})"]
        ) from None

    try:
        validate_problem(record)
    except ProblemValidationError as error:
        raise ProblemValidationError(
            [f"{source}: {item}" for item in error.errors]
        ) from None

    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Abacus problem JSON files.")
    parser.add_argument("paths", nargs="+", help="one or more problem JSON files")
    args = parser.parse_args(argv)

    invalid = False
    for path in args.paths:
        try:
            record = load_problem(path)
        except ProblemValidationError as error:
            invalid = True
            print(error, file=sys.stderr)
        else:
            print(f"valid: {path} ({record['id']})")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
