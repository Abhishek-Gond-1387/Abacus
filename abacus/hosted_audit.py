"""Strict, no-overwrite persistence for explicitly requested hosted suggestion audits."""

from __future__ import annotations

import json
import math
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from .prompts import HOSTED_PROMPT_TEMPLATE_VERSIONS
from .schemas import parse_model_output


HOSTED_AUDIT_SCHEMA_VERSION = 1
MAX_HOSTED_AUDIT_BYTES = 512 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HostedAuditValidationError(ValueError):
    """A hosted suggestion audit record is malformed or exceeds its limit."""


def _valid_timestamp(value: Any, label: str) -> None:
    if type(value) is not str:
        raise HostedAuditValidationError(f"{label} must be an ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise HostedAuditValidationError(f"{label} must be an ISO-8601 timestamp.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HostedAuditValidationError(f"{label} must include a UTC offset.")


def _validate_suggestion_output(value: Any) -> None:
    required = {
        "status", "output_kind", "template_version", "model_id", "provider_api_called",
        "usage_recorded", "request_metadata", "suggestions_are_evidence", "result",
    }
    optional = {"proposal_evaluation"}
    if type(value) is not dict or not required.issubset(value) or value.keys() - required - optional:
        raise HostedAuditValidationError("suggestion_output has missing or unknown fields.")
    kind = value["output_kind"]
    if type(kind) is not str or kind not in HOSTED_PROMPT_TEMPLATE_VERSIONS:
        raise HostedAuditValidationError("suggestion_output.output_kind is unsupported.")
    if value["status"] != "suggestions_ready":
        raise HostedAuditValidationError("Only successfully parsed suggestions can be saved.")
    if value["template_version"] != HOSTED_PROMPT_TEMPLATE_VERSIONS[kind]:
        raise HostedAuditValidationError("suggestion_output.template_version does not match its kind.")
    if type(value["model_id"]) is not str or not value["model_id"].strip():
        raise HostedAuditValidationError("suggestion_output.model_id must be non-empty.")
    if value["provider_api_called"] is not True or value["usage_recorded"] is not False:
        raise HostedAuditValidationError("suggestion_output provider and usage flags are invalid.")
    if value["suggestions_are_evidence"] is not False:
        raise HostedAuditValidationError("Hosted suggestions cannot be labeled as evidence.")

    metadata = value["request_metadata"]
    metadata_fields = {
        "request_started_at_utc", "provider_id", "model_id", "problem_id", "dataset_version",
        "problem_spec_sha256", "dataset_sha256", "prompt_template_version", "prompt_sha256",
        "prompt_bytes", "request_parameters",
    }
    if type(metadata) is not dict or metadata.keys() != metadata_fields:
        raise HostedAuditValidationError("request_metadata has missing or unknown fields.")
    _valid_timestamp(metadata["request_started_at_utc"], "request_metadata.request_started_at_utc")
    if type(metadata["provider_id"]) is not str or metadata["provider_id"] not in {"gemini", "openai"}:
        raise HostedAuditValidationError("request_metadata.provider_id is unsupported.")
    for key in ("model_id", "problem_id", "dataset_version"):
        if type(metadata[key]) is not str or not metadata[key].strip():
            raise HostedAuditValidationError(f"request_metadata.{key} must be non-empty.")
    if metadata["model_id"] != value["model_id"]:
        raise HostedAuditValidationError("request_metadata.model_id does not match the output.")
    if metadata["prompt_template_version"] != value["template_version"]:
        raise HostedAuditValidationError("request_metadata prompt template does not match the output.")
    for key in ("problem_spec_sha256", "dataset_sha256", "prompt_sha256"):
        if type(metadata[key]) is not str or not _SHA256.fullmatch(metadata[key]):
            raise HostedAuditValidationError(f"request_metadata.{key} must be a SHA-256 digest.")
    if type(metadata["prompt_bytes"]) is not int or not 1 <= metadata["prompt_bytes"] <= 32 * 1024:
        raise HostedAuditValidationError("request_metadata.prompt_bytes is outside the prompt limit.")

    parameters = metadata["request_parameters"]
    parameter_fields = {
        "timeout_seconds", "automatic_retries", "max_output_tokens", "sampling_parameters",
    }
    if type(parameters) is not dict or parameters.keys() != parameter_fields:
        raise HostedAuditValidationError("request_metadata.request_parameters is incomplete.")
    if (
        type(parameters["timeout_seconds"]) not in {int, float}
        or not 0 < parameters["timeout_seconds"] <= 120
        or not math.isfinite(parameters["timeout_seconds"])
    ):
        raise HostedAuditValidationError("request timeout must be positive.")
    if (
        type(parameters["automatic_retries"]) is not int
        or parameters["automatic_retries"] != 0
        or type(parameters["max_output_tokens"]) is not int
        or parameters["max_output_tokens"] != 1_024
    ):
        raise HostedAuditValidationError("request retry or token limits are unsupported.")
    if parameters["sampling_parameters"] != "provider_defaults":
        raise HostedAuditValidationError("request sampling marker is unsupported.")

    try:
        parsed_output = json.dumps(value["result"], ensure_ascii=False, allow_nan=False)
        parsed_result = parse_model_output(kind, parsed_output)
    except (TypeError, ValueError) as error:
        raise HostedAuditValidationError("suggestion_output.result failed strict schema validation.") from error

    evaluation = value.get("proposal_evaluation")
    if evaluation is not None:
        if kind != "candidate_proposals" or type(evaluation) is not dict:
            raise HostedAuditValidationError("proposal_evaluation is allowed only for candidate proposals.")
        if evaluation.keys() != {"status", "evaluator", "normal_run_record_saved", "results"}:
            raise HostedAuditValidationError("proposal_evaluation has missing or unknown fields.")
        if evaluation["status"] != "completed" or evaluation["evaluator"] != "registered_local_target_and_oracle":
            raise HostedAuditValidationError("proposal_evaluation status or evaluator is unsupported.")
        if evaluation["normal_run_record_saved"] is not False:
            raise HostedAuditValidationError("Hosted evaluation cannot be saved as a normal run record.")
        if (
            type(evaluation["results"]) is not list
            or len(evaluation["results"]) > 20
            or len(evaluation["results"]) != len(parsed_result.proposals)
        ):
            raise HostedAuditValidationError("proposal_evaluation.results exceeds its limit.")
        for index, (item, proposal) in enumerate(
            zip(evaluation["results"], parsed_result.proposals, strict=True),
            start=1,
        ):
            _validate_evaluated_proposal(item, index, proposal)


def _validate_evaluated_proposal(item: Any, index: int, proposal: Any) -> None:
    required = {
        "proposal_index", "input", "rationale", "contract_status", "evaluation_status", "evidence",
    }
    optional = {"failure_category"}
    if type(item) is not dict or not required.issubset(item) or item.keys() - required - optional:
        raise HostedAuditValidationError("proposal_evaluation result has missing or unknown fields.")
    if type(item["proposal_index"]) is not int or item["proposal_index"] != index:
        raise HostedAuditValidationError("proposal_evaluation indices must be consecutive integers.")
    candidate = item["input"]
    if (
        type(candidate) is not list
        or len(candidate) > 100
        or any(type(value) is not int or abs(value) > (2**63) - 1 for value in candidate)
    ):
        raise HostedAuditValidationError("proposal_evaluation input is invalid.")
    if tuple(candidate) != proposal.input or item["rationale"] != proposal.rationale:
        raise HostedAuditValidationError("proposal_evaluation does not match its parsed suggestion.")

    if item["contract_status"] == "rejected":
        if (
            candidate
            or item.get("failure_category") != "empty_input_not_allowed"
            or item["evaluation_status"] != "not_run"
            or item["evidence"] is not None
        ):
            raise HostedAuditValidationError("Rejected proposal evaluation is inconsistent.")
        return
    if item["contract_status"] != "valid" or "failure_category" in item:
        raise HostedAuditValidationError("proposal_evaluation contract status is unsupported.")

    evidence = item["evidence"]
    if type(evidence) is not dict:
        raise HostedAuditValidationError("Evaluated proposal must include trusted evidence.")
    if evidence.get("test_id") != f"hosted-proposal-{index}" or evidence.get("method") != "hosted_model_proposal":
        raise HostedAuditValidationError("proposal_evaluation evidence identifiers are invalid.")
    if evidence.get("status") == "internal_error":
        expected_fields = {"test_id", "method", "contract_id", "status", "failure_category"}
        if evidence.keys() != expected_fields or item["evaluation_status"] != "internal_error":
            raise HostedAuditValidationError("Internal proposal evaluation evidence is malformed.")
        if any(type(evidence[key]) is not str or not evidence[key] for key in ("contract_id", "failure_category")):
            raise HostedAuditValidationError("Internal proposal evaluation evidence is incomplete.")
        return

    completed_fields = {
        "test_id", "method", "contract_id", "status", "contract_valid", "oracle_id", "input",
        "actual", "expected", "replay_confirmed", "replay_attempted", "replay_actual",
        "replay_expected", "category",
    }
    if evidence.keys() != completed_fields:
        raise HostedAuditValidationError("Completed proposal evaluation evidence is malformed.")
    if (
        evidence["status"] != "completed"
        or evidence["contract_valid"] is not True
        or evidence["input"] != candidate
        or type(evidence["contract_id"]) is not str
        or type(evidence["oracle_id"]) is not str
        or type(evidence["category"]) is not str
        or evidence["category"] not in {"CASE_PASSED", "PROPERTY_VIOLATION"}
        or item["evaluation_status"] != evidence["category"]
    ):
        raise HostedAuditValidationError("Completed proposal evaluation evidence is inconsistent.")
    for key in ("actual", "expected"):
        if (
            type(evidence[key]) is not list
            or len(evidence[key]) > 100
            or any(type(value) is not int or abs(value) > (2**63) - 1 for value in evidence[key])
        ):
            raise HostedAuditValidationError(f"proposal_evaluation evidence {key} must be an integer array.")
    if evidence["expected"] != sorted(candidate):
        raise HostedAuditValidationError("proposal_evaluation oracle output does not match the registered sort oracle.")
    for key in ("replay_actual", "replay_expected"):
        replay_value = evidence[key]
        if replay_value is not None and (
            type(replay_value) is not list
            or len(replay_value) > 100
            or any(type(value) is not int or abs(value) > (2**63) - 1 for value in replay_value)
        ):
            raise HostedAuditValidationError(f"proposal_evaluation evidence {key} is invalid.")
    if evidence["replay_expected"] is not None and evidence["replay_expected"] != evidence["expected"]:
        raise HostedAuditValidationError("Replayed oracle output does not match the initial oracle output.")
    if type(evidence["replay_attempted"]) is not bool:
        raise HostedAuditValidationError("proposal_evaluation replay_attempted must be boolean.")
    if evidence["replay_confirmed"] is not None and type(evidence["replay_confirmed"]) is not bool:
        raise HostedAuditValidationError("proposal_evaluation replay_confirmed must be boolean or null.")
    if evidence["category"] == "CASE_PASSED":
        if (
            evidence["actual"] != evidence["expected"]
            or evidence["replay_attempted"]
            or evidence["replay_confirmed"] is not None
            or evidence["replay_actual"] is not None
            or evidence["replay_expected"] is not None
        ):
            raise HostedAuditValidationError("Passing proposal evidence cannot claim a replay.")
    elif evidence["actual"] == evidence["expected"] or not evidence["replay_attempted"]:
        raise HostedAuditValidationError("Mismatched proposal evidence must have attempted a replay.")


def _write_exclusive(path: Path, content: str) -> None:
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
        pass


def save_hosted_audit_record(path: str | Path, record: dict[str, Any]) -> Path:
    """Validate and atomically save one audit artifact without replacing existing data."""
    fields = {"audit_schema_version", "audit_record_id", "saved_at_utc", "suggestion_output"}
    if type(record) is not dict or record.keys() != fields:
        raise HostedAuditValidationError("Hosted audit record has missing or unknown fields.")
    if (
        type(record["audit_schema_version"]) is not int
        or record["audit_schema_version"] != HOSTED_AUDIT_SCHEMA_VERSION
    ):
        raise HostedAuditValidationError("Unsupported hosted audit schema version.")
    try:
        UUID(record["audit_record_id"])
    except (ValueError, TypeError, AttributeError) as error:
        raise HostedAuditValidationError("audit_record_id must be a UUID.") from error
    _valid_timestamp(record["saved_at_utc"], "saved_at_utc")
    _validate_suggestion_output(record["suggestion_output"])
    try:
        content = json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    except (TypeError, ValueError) as error:
        raise HostedAuditValidationError("Hosted audit record must contain JSON-safe values.") from error
    if len(content.encode("utf-8")) > MAX_HOSTED_AUDIT_BYTES:
        raise HostedAuditValidationError(f"Hosted audit record exceeds {MAX_HOSTED_AUDIT_BYTES} bytes.")

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    marker = destination.with_name(destination.name + ".incomplete")
    temporary = destination.with_name(f".{destination.name}.{record['audit_record_id']}.tmp")
    if destination.exists():
        raise FileExistsError(f"Audit record already exists; refusing to overwrite it: {destination}")
    if marker.exists():
        raise FileExistsError(f"An incomplete marker already exists for this path: {marker}")

    marker_content = json.dumps({
        "audit_schema_version": HOSTED_AUDIT_SCHEMA_VERSION,
        "audit_record_id": record["audit_record_id"],
        "state": "writing",
        "final_path": destination.name,
        "temporary_path": temporary.name,
        "saved_at_utc": record["saved_at_utc"],
    }, separators=(",", ":")) + "\n"
    _write_exclusive(marker, marker_content)
    _fsync_directory(destination.parent)
    try:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
    except Exception:
        marker.unlink(missing_ok=True)
        raise

    _write_exclusive(temporary, content)
    os.replace(temporary, destination)
    _fsync_directory(destination.parent)
    marker.unlink()
    _fsync_directory(destination.parent)
    return destination


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HostedAuditValidationError("Audit JSON contains a duplicate object key.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise HostedAuditValidationError(f"Audit JSON contains a non-standard constant: {value}.")


def _decode_json(payload: bytes) -> Any:
    if len(payload) > MAX_HOSTED_AUDIT_BYTES:
        raise HostedAuditValidationError(f"Hosted audit file exceeds {MAX_HOSTED_AUDIT_BYTES} bytes.")
    try:
        text = payload.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as error:
        raise HostedAuditValidationError("Hosted audit file is not UTF-8.") from error
    except (json.JSONDecodeError, RecursionError) as error:
        raise HostedAuditValidationError("Hosted audit file contains invalid JSON.") from error


def _read_bounded(path: Path, maximum_bytes: int) -> bytes:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise HostedAuditValidationError("Audit input must be a regular file.")
    with path.open("rb") as handle:
        return handle.read(maximum_bytes + 1)


def load_hosted_audit_record(path: str | Path) -> dict[str, Any]:
    """Load one bounded audit file and revalidate its envelope, metadata, and typed output."""
    source = Path(path)
    record = _decode_json(_read_bounded(source, MAX_HOSTED_AUDIT_BYTES))
    fields = {"audit_schema_version", "audit_record_id", "saved_at_utc", "suggestion_output"}
    if type(record) is not dict or record.keys() != fields:
        raise HostedAuditValidationError("Hosted audit record has missing or unknown fields.")
    if (
        type(record["audit_schema_version"]) is not int
        or record["audit_schema_version"] != HOSTED_AUDIT_SCHEMA_VERSION
    ):
        raise HostedAuditValidationError("Unsupported hosted audit schema version.")
    try:
        UUID(record["audit_record_id"])
    except (ValueError, TypeError, AttributeError) as error:
        raise HostedAuditValidationError("audit_record_id must be a UUID.") from error
    _valid_timestamp(record["saved_at_utc"], "saved_at_utc")
    _validate_suggestion_output(record["suggestion_output"])
    return record


def _load_incomplete_marker(path: Path) -> dict[str, Any]:
    payload = _read_bounded(path, 8 * 1024)
    if len(payload) > 8 * 1024:
        raise HostedAuditValidationError("Incomplete audit marker exceeds its size limit.")
    marker = _decode_json(payload)
    fields = {
        "audit_schema_version", "audit_record_id", "state", "final_path",
        "temporary_path", "saved_at_utc",
    }
    if type(marker) is not dict or marker.keys() != fields:
        raise HostedAuditValidationError("Incomplete audit marker has missing or unknown fields.")
    if type(marker["audit_schema_version"]) is not int or marker["audit_schema_version"] != HOSTED_AUDIT_SCHEMA_VERSION:
        raise HostedAuditValidationError("Unsupported incomplete audit marker version.")
    try:
        UUID(marker["audit_record_id"])
    except (ValueError, TypeError, AttributeError) as error:
        raise HostedAuditValidationError("Incomplete marker audit_record_id must be a UUID.") from error
    if marker["state"] != "writing":
        raise HostedAuditValidationError("Incomplete audit marker state is unsupported.")
    for key in ("final_path", "temporary_path"):
        value = marker[key]
        if type(value) is not str or not value or Path(value).name != value:
            raise HostedAuditValidationError(f"Incomplete marker {key} must be a filename.")
    _valid_timestamp(marker["saved_at_utc"], "incomplete marker saved_at_utc")
    return marker


def list_hosted_audit_records(directory: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Summarize saved artifacts and interrupted saves without exposing their prompt data."""
    root = Path(directory)
    records: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    invalid_files: list[dict[str, str]] = []
    if not root.exists():
        return {"records": records, "incomplete": incomplete, "invalid_files": invalid_files}

    for path in sorted(root.glob("*.json")):
        try:
            record = load_hosted_audit_record(path)
        except HostedAuditValidationError as error:
            invalid_files.append({"path": str(path), "error": str(error)})
            continue
        except OSError:
            invalid_files.append({"path": str(path), "error": "audit_file_unreadable"})
            continue
        output = record["suggestion_output"]
        proposals = output["result"].get("proposals", [])
        records.append({
            "audit_record_id": record["audit_record_id"],
            "saved_at_utc": record["saved_at_utc"],
            "problem_id": output["request_metadata"]["problem_id"],
            "output_kind": output["output_kind"],
            "model_id": output["model_id"],
            "proposal_count": len(proposals),
            "path": str(path),
        })

    for path in sorted(root.glob("*.json.incomplete")):
        try:
            marker = _load_incomplete_marker(path)
        except HostedAuditValidationError as error:
            invalid_files.append({"path": str(path), "error": str(error)})
            continue
        except OSError:
            invalid_files.append({"path": str(path), "error": "incomplete_marker_unreadable"})
            continue
        incomplete.append({**marker, "marker_path": str(path)})

    return {"records": records, "incomplete": incomplete, "invalid_files": invalid_files}


def find_hosted_audit_record(directory: str | Path, audit_record_id: str) -> dict[str, Any] | None:
    """Find one fully validated audit record by UUID, skipping invalid files."""
    for path in sorted(Path(directory).glob("*.json")):
        try:
            record = load_hosted_audit_record(path)
        except (HostedAuditValidationError, OSError):
            continue
        if record["audit_record_id"] == audit_record_id:
            return record
    return None
