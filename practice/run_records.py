"""Versioned, validated run records for reproducible Abacus evaluations."""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4
from typing import Any

from .log_safety import sanitize_for_log


RUN_RECORD_SCHEMA_VERSION = 2
RUN_STATUSES = {"complete", "partial", "error"}
OUTCOMES = {"REFUTED", "TESTS_PASSED", "PROVEN", "UNRESOLVED", "ERROR"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RunRecordValidationError(ValueError):
    """A run record does not satisfy its declared versioned schema."""


def _object(value: Any, label: str, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict:
        raise RunRecordValidationError(f"{label} must be an object.")
    missing = keys - value.keys()
    if missing:
        raise RunRecordValidationError(f"{label} is missing: {', '.join(sorted(missing))}.")
    return value


def _text(value: Any, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise RunRecordValidationError(f"{label} must be a non-empty string.")


def _nonnegative_int(value: Any, label: str) -> None:
    if type(value) is not int or value < 0:
        raise RunRecordValidationError(f"{label} must be a non-negative integer.")


def _finite_number(value: Any, label: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise RunRecordValidationError(f"{label} must be a finite non-negative number.")


def _aware_timestamp(value: Any, label: str) -> None:
    _text(value, label)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise RunRecordValidationError(f"{label} must be an ISO-8601 timestamp.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RunRecordValidationError(f"{label} must include a UTC offset.")


def _canonical_sha256(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_run_record(record: Any) -> dict[str, Any]:
    """Validate a complete or explicitly partial/error schema-v2 record.

    Extra properties are allowed for forward-compatible annotations, while all
    fields needed to identify, reproduce, and interpret a run are required.
    """
    required = {
        "schema_version", "run_id", "run_status", "timestamps", "problem", "target",
        "provenance", "model", "generation", "model_proposals", "validated_candidates",
        "evidence", "replay_details", "outcome", "completion", "revision", "usage",
        "budget", "errors", "unknown_values",
    }
    result = _object(record, "run_record", required)
    if type(result["schema_version"]) is not int or result["schema_version"] != RUN_RECORD_SCHEMA_VERSION:
        raise RunRecordValidationError(f"schema_version must be {RUN_RECORD_SCHEMA_VERSION}.")
    try:
        UUID(result["run_id"])
    except (ValueError, TypeError, AttributeError) as error:
        raise RunRecordValidationError("run_id must be a UUID.") from error
    if type(result["run_status"]) is not str or result["run_status"] not in RUN_STATUSES:
        raise RunRecordValidationError("run_status must be complete, partial, or error.")

    timestamps = _object(result["timestamps"], "timestamps", {"started_at_utc", "finished_at_utc", "duration_seconds"})
    _aware_timestamp(timestamps["started_at_utc"], "timestamps.started_at_utc")
    _aware_timestamp(timestamps["finished_at_utc"], "timestamps.finished_at_utc")
    _finite_number(timestamps["duration_seconds"], "timestamps.duration_seconds")

    problem = _object(
        result["problem"], "problem",
        {"problem_id", "dataset_version", "dataset_sha256", "problem_spec_sha256", "dataset", "original_claim", "contract"},
    )
    for key in ("problem_id", "dataset_version", "original_claim"):
        _text(problem[key], f"problem.{key}")
    for key in ("dataset_sha256", "problem_spec_sha256"):
        if type(problem[key]) is not str or not SHA256_PATTERN.fullmatch(problem[key]):
            raise RunRecordValidationError(f"problem.{key} must be a lowercase SHA-256 hex digest.")
    dataset = _object(problem["dataset"], "problem.dataset", {"fixed_cases", "proposal_fixtures", "hypothesis"})
    if _canonical_sha256({"dataset_version": problem["dataset_version"], **dataset}) != problem["dataset_sha256"]:
        raise RunRecordValidationError("problem.dataset_sha256 does not match the stored dataset and settings.")
    contract = _object(problem["contract"], "problem.contract", {"id", "oracle_id", "input_type", "allow_empty"})
    _text(contract["id"], "problem.contract.id")
    _text(contract["input_type"], "problem.contract.input_type")
    if contract["oracle_id"] is not None:
        _text(contract["oracle_id"], "problem.contract.oracle_id")
    if type(contract["allow_empty"]) is not bool:
        raise RunRecordValidationError("problem.contract.allow_empty must be boolean.")

    target = _object(result["target"], "target", {"id", "code_sha256"})
    _text(target["id"], "target.id")
    if type(target["code_sha256"]) is not str or not SHA256_PATTERN.fullmatch(target["code_sha256"]):
        raise RunRecordValidationError("target.code_sha256 must be a lowercase SHA-256 hex digest.")

    provenance = _object(result["provenance"], "provenance", {"git_revision", "git_dirty", "software_versions"})
    if provenance["git_revision"] is not None:
        _text(provenance["git_revision"], "provenance.git_revision")
    if type(provenance["git_dirty"]) is not bool:
        raise RunRecordValidationError("provenance.git_dirty must be boolean.")
    versions = _object(provenance["software_versions"], "provenance.software_versions", {"python", "hypothesis", "platform", "abacus"})
    for key, value in versions.items():
        _text(value, f"provenance.software_versions.{key}")

    model = _object(
        result["model"], "model",
        {"provider_id", "model_id", "provider_api_called", "prompt_template_versions", "provider_identity_status"},
    )
    if type(model["provider_api_called"]) is not bool:
        raise RunRecordValidationError("model.provider_api_called must be boolean.")
    for key in ("provider_id", "model_id"):
        if model[key] is not None:
            _text(model[key], f"model.{key}")
    _text(model["provider_identity_status"], "model.provider_identity_status")
    templates = _object(model["prompt_template_versions"], "model.prompt_template_versions", set())
    for key, value in templates.items():
        _text(key, "model.prompt_template_versions key")
        _text(value, f"model.prompt_template_versions.{key}")

    generation = _object(
        result["generation"], "generation",
        {"methods", "random_seeds", "settings", "scheduled_case_count", "generated_case_count", "validated_candidate_count", "case_counts_by_method"},
    )
    if type(generation["methods"]) is not list or not generation["methods"]:
        raise RunRecordValidationError("generation.methods must be a non-empty array.")
    for method in generation["methods"]:
        _text(method, "generation.methods entry")
    if len(set(generation["methods"])) != len(generation["methods"]):
        raise RunRecordValidationError("generation.methods cannot contain duplicates.")
    if type(generation["random_seeds"]) is not dict:
        raise RunRecordValidationError("generation.random_seeds must be an object.")
    for key, value in generation["random_seeds"].items():
        _text(key, "generation.random_seeds key")
        if type(value) is not int:
            raise RunRecordValidationError(f"generation.random_seeds.{key} must be an integer.")
    if type(generation["settings"]) is not dict or type(generation["case_counts_by_method"]) is not dict:
        raise RunRecordValidationError("generation.settings and case_counts_by_method must be objects.")
    for key in ("scheduled_case_count", "generated_case_count", "validated_candidate_count"):
        _nonnegative_int(generation[key], f"generation.{key}")
    for key, value in generation["case_counts_by_method"].items():
        _text(key, "generation.case_counts_by_method key")
        _nonnegative_int(value, f"generation.case_counts_by_method.{key}")

    for name in ("model_proposals", "validated_candidates", "evidence", "replay_details", "errors", "unknown_values"):
        if type(result[name]) is not list:
            raise RunRecordValidationError(f"{name} must be an array.")
    for index, proposal in enumerate(result["model_proposals"]):
        item = _object(proposal, f"model_proposals[{index}]", {"proposal_id", "source", "input", "rationale", "validated", "evaluation_status"})
        for key in ("proposal_id", "source", "rationale", "evaluation_status"):
            _text(item[key], f"model_proposals[{index}].{key}")
        if type(item["validated"]) is not bool:
            raise RunRecordValidationError(f"model_proposals[{index}].validated must be boolean.")
    evidence_ids: set[str] = set()
    completed_count = 0
    for index, item in enumerate(result["evidence"]):
        evidence = _object(item, f"evidence[{index}]", {"test_id", "method", "status", "contract_id"})
        for key in ("test_id", "method", "status", "contract_id"):
            _text(evidence[key], f"evidence[{index}].{key}")
        if evidence["test_id"] in evidence_ids:
            raise RunRecordValidationError(f"Duplicate evidence test_id {evidence['test_id']!r}.")
        evidence_ids.add(evidence["test_id"])
        if evidence["status"] == "completed":
            completed_count += 1
            for key in ("contract_valid", "oracle_id", "input", "actual", "expected"):
                if key not in evidence:
                    raise RunRecordValidationError(f"evidence[{index}] is missing {key}.")
            if type(evidence["contract_valid"]) is not bool:
                raise RunRecordValidationError(f"evidence[{index}].contract_valid must be boolean.")
            if evidence["contract_id"] != problem["contract"]["id"]:
                raise RunRecordValidationError(f"evidence[{index}] uses a different contract.")
            if evidence["oracle_id"] != problem["contract"]["oracle_id"]:
                raise RunRecordValidationError(f"evidence[{index}] uses a different oracle.")

    for index, candidate in enumerate(result["validated_candidates"]):
        item = _object(candidate, f"validated_candidates[{index}]", {"test_id", "method", "input", "contract_valid"})
        if item["test_id"] not in evidence_ids:
            raise RunRecordValidationError(f"validated_candidates[{index}] references unknown evidence.")
        _text(item["method"], f"validated_candidates[{index}].method")
        if type(item["contract_valid"]) is not bool:
            raise RunRecordValidationError(f"validated_candidates[{index}].contract_valid must be boolean.")
    if generation["validated_candidate_count"] != len(result["validated_candidates"]):
        raise RunRecordValidationError("generation.validated_candidate_count does not match validated_candidates.")
    if sum(generation["case_counts_by_method"].values()) != len(result["evidence"]):
        raise RunRecordValidationError("generation.case_counts_by_method does not match evidence.")

    for index, replay in enumerate(result["replay_details"]):
        item = _object(replay, f"replay_details[{index}]", {"test_id", "attempted", "confirmed"})
        if item["test_id"] not in evidence_ids:
            raise RunRecordValidationError(f"replay_details[{index}] references unknown evidence.")
        if type(item["attempted"]) is not bool or (item["confirmed"] is not None and type(item["confirmed"]) is not bool):
            raise RunRecordValidationError(f"replay_details[{index}] has invalid replay flags.")

    error_ids: set[str] = set()
    for index, error in enumerate(result["errors"]):
        item = _object(error, f"errors[{index}]", {"error_id", "step", "error"})
        for key in ("error_id", "step", "error"):
            _text(item[key], f"errors[{index}].{key}")
        error_ids.add(item["error_id"])

    outcome = _object(
        result["outcome"], "outcome",
        {"outcome", "reason", "message", "test_count", "methods", "counterexample", "failure_category", "proof_checker", "proof_evidence_id", "evidence_references"},
    )
    if type(outcome["outcome"]) is not str or outcome["outcome"] not in OUTCOMES:
        raise RunRecordValidationError("outcome.outcome is not a recognized run label.")
    for key in ("reason", "message"):
        _text(outcome[key], f"outcome.{key}")
    if type(outcome["methods"]) is not list or any(type(value) is not str or not value.strip() for value in outcome["methods"]):
        raise RunRecordValidationError("outcome.methods must be an array of non-empty strings.")
    if outcome["test_count"] is not None:
        _nonnegative_int(outcome["test_count"], "outcome.test_count")
    references = outcome["evidence_references"]
    if type(references) is not list or not references or any(type(value) is not str or not value.strip() for value in references):
        raise RunRecordValidationError("outcome.evidence_references must name at least one evidence or error item.")
    resolvable = evidence_ids | {f"error:{value}" for value in error_ids}
    if any(reference not in resolvable for reference in references):
        raise RunRecordValidationError("outcome.evidence_references contains an unknown reference.")

    completion = _object(
        result["completion"], "completion",
        {"status", "scheduled_case_count", "completed_case_count", "incomplete_reasons"},
    )
    if type(completion["status"]) is not str or completion["status"] not in RUN_STATUSES or completion["status"] != result["run_status"]:
        raise RunRecordValidationError("completion.status must match run_status.")
    _nonnegative_int(completion["scheduled_case_count"], "completion.scheduled_case_count")
    _nonnegative_int(completion["completed_case_count"], "completion.completed_case_count")
    if completion["scheduled_case_count"] != generation["scheduled_case_count"]:
        raise RunRecordValidationError("completion and generation scheduled counts disagree.")
    if completion["completed_case_count"] != completed_count or completed_count > completion["scheduled_case_count"]:
        raise RunRecordValidationError("completion count does not match recorded evidence.")
    reasons = completion["incomplete_reasons"]
    if type(reasons) is not list or any(type(value) is not str or not value.strip() for value in reasons):
        raise RunRecordValidationError("completion.incomplete_reasons must be an array of strings.")
    if completion["status"] == "complete" and (completed_count != completion["scheduled_case_count"] or reasons):
        raise RunRecordValidationError("A complete run must finish every scheduled case without incomplete reasons.")
    if completion["status"] == "partial" and not reasons:
        raise RunRecordValidationError("A partial run must state why it is incomplete.")
    if completion["status"] == "error" and not reasons:
        raise RunRecordValidationError("An error run must identify the stage that stopped it.")

    expected_status = {
        "TESTS_PASSED": "complete",
        "UNRESOLVED": "partial",
        "ERROR": "error",
    }.get(outcome["outcome"])
    if expected_status is not None and result["run_status"] != expected_status:
        raise RunRecordValidationError(f"{outcome['outcome']} requires run_status={expected_status!r}.")
    if outcome["outcome"] == "TESTS_PASSED":
        if outcome["reason"] != "no_counterexample_found" or completed_count == 0 or outcome["test_count"] != completed_count:
            raise RunRecordValidationError("TESTS_PASSED requires completed evidence and no_counterexample_found.")
        if outcome["counterexample"] is not None or not outcome["methods"]:
            raise RunRecordValidationError("TESTS_PASSED cannot include a counterexample and must name its methods.")
    elif outcome["outcome"] == "REFUTED":
        counterexample = _object(outcome["counterexample"], "outcome.counterexample", {"input", "actual", "expected", "test_id", "replay_confirmed"})
        if outcome["reason"] != "confirmed_counterexample" or counterexample["replay_confirmed"] is not True:
            raise RunRecordValidationError("REFUTED requires a replay-confirmed counterexample.")
        if counterexample["test_id"] not in evidence_ids:
            raise RunRecordValidationError("REFUTED counterexample must reference recorded evidence.")
        if counterexample["actual"] == counterexample["expected"]:
            raise RunRecordValidationError("REFUTED requires differing actual and expected outputs.")
        matching = next(item for item in result["evidence"] if item["test_id"] == counterexample["test_id"])
        if matching.get("status") != "completed" or matching.get("replay_confirmed") is not True:
            raise RunRecordValidationError("REFUTED must cite completed, replay-confirmed evidence.")
    elif outcome["outcome"] == "UNRESOLVED":
        if not (result["run_status"] == "partial" and outcome["reason"] in {
            "budget_exhausted", "conflicting_evidence", "invalid_evidence", "incomplete_evidence", "no_usable_oracle", "timeout"
        }):
            raise RunRecordValidationError("UNRESOLVED requires a partial run and an evidence/budget reason.")
    elif outcome["outcome"] == "ERROR":
        if result["run_status"] != "error" or outcome["reason"] not in {"external_error", "internal_error"}:
            raise RunRecordValidationError("ERROR requires an error run status and external/internal error reason.")
        _text(outcome["failure_category"], "outcome.failure_category")
        if not error_ids and not any(item.get("status") == "internal_error" for item in result["evidence"]):
            raise RunRecordValidationError("ERROR requires a recorded error or internal-error evidence item.")
    elif outcome["outcome"] == "PROVEN":
        if outcome["reason"] != "formal_proof_confirmed":
            raise RunRecordValidationError("PROVEN requires formal_proof_confirmed.")
        _text(outcome["proof_checker"], "outcome.proof_checker")
        _text(outcome["proof_evidence_id"], "outcome.proof_evidence_id")

    usage = _object(
        result["usage"], "usage",
        {"model_call_count", "provider_reported_token_usage", "duration_seconds", "estimated_cost_usd", "actual_cost_usd", "unknown_values"},
    )
    _nonnegative_int(usage["model_call_count"], "usage.model_call_count")
    _finite_number(usage["duration_seconds"], "usage.duration_seconds")
    _finite_number(usage["estimated_cost_usd"], "usage.estimated_cost_usd", nullable=True)
    _finite_number(usage["actual_cost_usd"], "usage.actual_cost_usd", nullable=True)
    if type(usage["unknown_values"]) is not list or any(type(value) is not str or not value.strip() for value in usage["unknown_values"]):
        raise RunRecordValidationError("usage.unknown_values must explicitly list any unavailable usage values.")
    token_usage = _object(usage["provider_reported_token_usage"], "usage.provider_reported_token_usage", {"input_tokens", "output_tokens", "total_tokens", "status"})
    if type(token_usage["status"]) is not str or token_usage["status"] not in {"known", "unknown", "not_applicable"}:
        raise RunRecordValidationError("Token usage status must be known, unknown, or not_applicable.")
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        _nonnegative_int(token_usage[key], f"usage.provider_reported_token_usage.{key}") if token_usage[key] is not None else None
    if token_usage["status"] == "unknown" and "provider_reported_token_usage" not in usage["unknown_values"]:
        raise RunRecordValidationError("Unknown provider token usage must be listed in usage.unknown_values.")
    if token_usage["status"] == "known" and any(token_usage[key] is None for key in ("input_tokens", "output_tokens", "total_tokens")):
        raise RunRecordValidationError("Known token usage requires input, output, and total counts.")
    if token_usage["status"] == "not_applicable" and model["provider_api_called"]:
        raise RunRecordValidationError("Provider token usage cannot be not_applicable when an API call occurred.")
    if usage["estimated_cost_usd"] is None and "estimated_cost_usd" not in usage["unknown_values"]:
        raise RunRecordValidationError("Unknown estimated cost must be listed in usage.unknown_values.")
    if usage["actual_cost_usd"] is None and "actual_cost_usd" not in usage["unknown_values"]:
        raise RunRecordValidationError("Unknown actual cost must be listed in usage.unknown_values.")

    if type(result["budget"]) is not dict:
        raise RunRecordValidationError("budget must be an object.")
    for index, unknown in enumerate(result["unknown_values"]):
        item = _object(unknown, f"unknown_values[{index}]", {"field", "reason"})
        _text(item["field"], f"unknown_values[{index}].field")
        _text(item["reason"], f"unknown_values[{index}].reason")
    if provenance["git_revision"] is None and not any(item["field"] == "provenance.git_revision" for item in result["unknown_values"]):
        raise RunRecordValidationError("Missing Git revision must be identified in unknown_values.")

    try:
        json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise RunRecordValidationError(f"Run record must contain JSON-safe finite values: {error}") from error
    return result


def sanitize_run_record_for_log(record: Any) -> dict[str, Any]:
    """Redact secrets and keep the stored dataset digest consistent."""
    sanitized = sanitize_for_log(record)
    if type(sanitized) is not dict:
        raise RunRecordValidationError("Run record must be an object before redaction.")
    problem = sanitized.get("problem")
    if type(problem) is dict and type(problem.get("dataset")) is dict:
        problem["dataset_sha256"] = _canonical_sha256(
            {"dataset_version": problem.get("dataset_version"), **problem["dataset"]}
        )
    return sanitized


def save_run_record(path: str | Path, record: dict[str, Any]) -> Path:
    """Validate and atomically save without replacing an earlier run.

    The incomplete marker is installed before the temporary record is created.
    If the process stops mid-write, the marker and any temporary bytes remain
    beside the destination and describe how far the save got.
    """
    validated = validate_run_record(sanitize_run_record_for_log(record))
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    marker = destination.with_name(destination.name + ".incomplete")
    run_id = validated["run_id"]
    nonce = uuid4().hex
    temporary = destination.with_name(f".{destination.name}.{run_id}.{nonce}.tmp")
    if destination.exists():
        raise FileExistsError(f"Run record already exists; refusing to overwrite it: {destination}")
    if marker.exists():
        raise FileExistsError(f"An incomplete marker already exists for this path: {marker}")

    marker_payload = {
        "marker_version": 1,
        "run_id": run_id,
        "problem_id": validated["problem"]["problem_id"],
        "state": "writing",
        "final_path": destination.name,
        "temporary_path": temporary.name,
        "started_at_utc": validated["timestamps"]["started_at_utc"],
    }
    safe_marker_payload = sanitize_for_log(marker_payload)
    _write_fsynced_exclusive(
        marker, json.dumps(safe_marker_payload, separators=(",", ":")) + "\n"
    )
    _fsync_directory(destination.parent)

    try:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
    except Exception:
        marker.unlink(missing_ok=True)
        raise

    content = json.dumps(validated, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    _write_fsynced_exclusive(temporary, content)
    os.replace(temporary, destination)
    _fsync_directory(destination.parent)
    marker.unlink()
    _fsync_directory(destination.parent)
    return destination


def _write_fsynced_exclusive(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        # Some filesystems do not support directory fsync; the file itself was synced.
        return


def load_run_record(path: str | Path) -> dict[str, Any]:
    """Read and validate one versioned record from disk."""
    source = Path(path)
    try:
        record = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunRecordValidationError(f"Cannot load run record {source}: {error}") from error
    return validate_run_record(record)


def list_run_records(
    runs_dir: str | Path, *, problem_id: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    """List valid records, interrupted-save markers, and unreadable files."""
    root = Path(runs_dir)
    records: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    complete_ids: set[str] = set()

    if not root.exists():
        return {"runs": records, "incomplete": incomplete, "invalid_files": invalid}

    for path in sorted(root.glob("*.json")):
        try:
            record = load_run_record(path)
        except RunRecordValidationError as error:
            invalid.append({"path": str(path), "error": str(error)})
            continue
        if problem_id is not None and record["problem"]["problem_id"] != problem_id:
            continue
        complete_ids.add(record["run_id"])
        records.append(
            {
                "run_id": record["run_id"],
                "problem_id": record["problem"]["problem_id"],
                "schema_version": record["schema_version"],
                "run_status": record["run_status"],
                "outcome": record["outcome"]["outcome"],
                "reason": record["outcome"]["reason"],
                "path": str(path),
            }
        )

    for marker_path in sorted(root.glob("*.json.incomplete")):
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            if type(marker) is not dict or not isinstance(marker.get("run_id"), str):
                raise ValueError("Incomplete marker is missing a run_id.")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            invalid.append({"path": str(marker_path), "error": str(error)})
            continue
        if marker["run_id"] in complete_ids:
            continue
        if problem_id is not None and marker.get("problem_id") != problem_id:
            continue
        incomplete.append({**marker, "marker_path": str(marker_path)})

    return {"runs": records, "incomplete": incomplete, "invalid_files": invalid}


def find_run_record(runs_dir: str | Path, run_id: str) -> dict[str, Any] | None:
    """Load one complete run by ID, or return its interruption marker."""
    entries = list_run_records(runs_dir)
    for item in entries["runs"]:
        if item["run_id"] == run_id:
            return load_run_record(item["path"])
    for marker in entries["incomplete"]:
        if marker["run_id"] == run_id:
            return {"incomplete_marker": marker}
    return None
