"""Atomic stage checkpoints used to preserve evidence before finalization."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .log_safety import sanitize_for_log


CHECKPOINT_VERSION = 1


def save_run_checkpoint(path: str | Path, checkpoint: dict[str, Any]) -> Path:
    """Atomically replace one run's progress snapshot after a completed stage."""
    if type(checkpoint) is not dict or type(checkpoint.get("checkpoint_version")) is not int or checkpoint.get("checkpoint_version") != CHECKPOINT_VERSION:
        raise ValueError("Run checkpoint must use checkpoint_version 1.")
    if not isinstance(checkpoint.get("run_id"), str) or not checkpoint["run_id"]:
        raise ValueError("Run checkpoint must include a run_id.")
    try:
        UUID(checkpoint["run_id"])
    except ValueError as error:
        raise ValueError("Run checkpoint run_id must be a UUID.") from error
    for key in ("problem_id", "stage"):
        if not isinstance(checkpoint.get(key), str) or not checkpoint[key].strip():
            raise ValueError(f"Run checkpoint must include a non-empty {key}.")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    payload = json.dumps(sanitize_for_log(checkpoint), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def load_run_checkpoint(path: str | Path) -> dict[str, Any]:
    """Load a checkpoint and reject malformed or unsupported state snapshots."""
    source = Path(path)
    checkpoint = json.loads(source.read_text(encoding="utf-8"))
    if (
        type(checkpoint) is not dict
        or type(checkpoint.get("checkpoint_version")) is not int
        or checkpoint.get("checkpoint_version") != CHECKPOINT_VERSION
        or not isinstance(checkpoint.get("run_id"), str)
        or not isinstance(checkpoint.get("problem_id"), str)
        or not checkpoint["problem_id"].strip()
        or not isinstance(checkpoint.get("stage"), str)
        or not checkpoint["stage"].strip()
        or type(checkpoint.get("evidence")) is not list
        or type(checkpoint.get("case_log")) is not list
        or type(checkpoint.get("errors")) is not list
    ):
        raise ValueError("Run checkpoint has an unsupported or malformed shape.")
    try:
        UUID(checkpoint["run_id"])
    except ValueError as error:
        raise ValueError("Run checkpoint run_id must be a UUID.") from error
    return checkpoint
