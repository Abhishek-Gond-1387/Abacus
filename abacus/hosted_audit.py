"""Strict, no-overwrite persistence for explicitly requested hosted suggestion audits."""

from __future__ import annotations

import json
import math
import os
import re
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
        or not math.isfinite(parameters["timeout_seconds"])
        or not 0 < parameters["timeout_seconds"] <= 120
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
        parse_model_output(kind, parsed_output)
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
        if type(evaluation["results"]) is not list or len(evaluation["results"]) > 20:
            raise HostedAuditValidationError("proposal_evaluation.results exceeds its limit.")


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
