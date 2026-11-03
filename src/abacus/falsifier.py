"""Adversarial input proposals checked and replayed by trusted Abacus code."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .counterexamples import (
    CounterexampleValidationError,
    replay_counterexample,
    save_counterexample,
)
from .errors import LLMError
from .failure_categories import FailureCategory
from .harness import CaseEvidence, HarnessStatus
from .llm import LLMResult, ask
from .problems import ProblemValidationError, load_problem, validate_problem
from .proposals import ProposalStatus, evaluate_proposal_response


logger = logging.getLogger(__name__)
REPORT_SCHEMA_VERSION = 1

FALSIFIER_SYSTEM_PROMPT = (
    "You are an adversarial test-input proposer. Search for concrete inputs that "
    "could falsify the stated property. Return candidate inputs and short rationales "
    "only. Do not judge the claim, provide a verdict, write code, or execute code. "
    "The independent checker decides every outcome."
)


def _resolve_problem(problem: Any) -> dict[str, Any]:
    if isinstance(problem, (str, Path)):
        return load_problem(problem)
    if isinstance(problem, Mapping):
        record = dict(problem)
    else:
        record = problem
    validate_problem(record)
    return record


def build_falsifier_prompt(problem: Any) -> tuple[str, str]:
    """Build a dedicated counterexample-search prompt from the full contract."""

    record = _resolve_problem(problem)
    context = {
        "claim": record["claim"],
        "candidate_code": record["code"],
        "domain": record["domain"],
        "preconditions": record["preconditions"],
        "property_description": record["property_description"],
        "oracle_id": record["oracle_id"],
    }
    prompt = (
        "Actively try to find inputs that make the candidate violate the exact "
        "contract below. Prioritize boundary cases and interactions between the "
        "preconditions. Stay within the stated input domain. Return up to five "
        "candidate input values and a short rationale for each, in exactly this "
        "JSON shape, with no Markdown or extra fields:\n"
        '{"candidate_inputs":[{"input":<JSON value>,"rationale":"short reason"}]}\n'
        "Do not include a pass/fail label, verdict, expected output, or code. "
        "The trusted harness will validate the inputs and decide whether any "
        "candidate is a counterexample.\n\n"
        "Exact problem contract:\n"
        f"{json.dumps(context, ensure_ascii=True, indent=2)}"
    )
    return FALSIFIER_SYSTEM_PROMPT, prompt


def _serialize_case_evidence(evidence: CaseEvidence | None) -> dict[str, Any] | None:
    if evidence is None:
        return None
    oracle = evidence.oracle_result
    target_exception = evidence.target_exception
    execution = evidence.execution
    return {
        "problem_id": evidence.problem_id,
        "input": list(evidence.input_value)
        if isinstance(evidence.input_value, (list, tuple))
        else evidence.input_value,
        "input_valid": evidence.input_valid,
        "validity_reason": evidence.validity_reason,
        "status": evidence.status.value,
        "failure_category": (
            evidence.failure_category.value if evidence.failure_category else None
        ),
        "explanation": evidence.explanation,
        "target_result": evidence.target_result,
        "target_exception": (
            {
                "type": target_exception.type_name,
                "message": target_exception.message,
                "phase": target_exception.phase,
            }
            if target_exception
            else None
        ),
        "oracle": (
            {
                "status": oracle.status.value,
                "expected_output": list(oracle.expected_output)
                if oracle.expected_output is not None
                else None,
                "input_unchanged": oracle.input_unchanged,
                "reason": oracle.reason,
            }
            if oracle
            else None
        ),
        "execution": (
            {
                "category": execution.category.value,
                "exit_code": execution.exit_code,
                "duration_seconds": execution.duration_seconds,
                "timed_out": execution.timed_out,
                "output_limit_exceeded": execution.output_limit_exceeded,
                "stdout_truncated": execution.stdout_truncated,
                "stderr_truncated": execution.stderr_truncated,
            }
            if execution
            else None
        ),
    }


def _atomic_json_write(destination: str | os.PathLike[str], payload: Any) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
    return path


def _check_candidate(
    problem: Mapping[str, Any],
    idea: Any,
    counterexample_directory: Path,
    *,
    provider: str | None,
) -> dict[str, Any]:
    evidence = idea.harness_evidence
    result: dict[str, Any] = {
        "source": "model_proposed",
        "input": idea.input_value,
        "rationale": idea.rationale,
        "contract_status": idea.contract_status.value,
        "contract_reason": idea.contract_reason,
        "failure_category": (
            idea.failure_category.value if idea.failure_category else None
        ),
        "harness_evidence": _serialize_case_evidence(evidence),
        "falsifier_status": "INVALID_EVIDENCE",
        "falsifier_explanation": "input was not checked by the trusted oracle",
        "counterexample_path": None,
        "counterexample_replay": None,
    }

    if idea.status is ProposalStatus.REJECTED_OUT_OF_CONTRACT:
        result["falsifier_explanation"] = (
            "rejected: proposed input is outside the problem contract"
        )
        return result

    if evidence is None:
        return result
    if evidence.status is HarnessStatus.PASSED:
        result["falsifier_status"] = "REJECTED"
        result["falsifier_explanation"] = (
            "candidate did not reproduce a property violation"
        )
        return result
    if evidence.status is not HarnessStatus.REFUTED:
        result["falsifier_status"] = "UNRESOLVED"
        result["falsifier_explanation"] = (
            "invalid evidence: the harness did not confirm a property violation "
            f"(status {evidence.status.value})"
        )
        return result

    counterexample_path = counterexample_directory / (
        f"{problem['id']}-{uuid.uuid4().hex}.json"
    )
    try:
        save_counterexample(
            problem,
            evidence,
            counterexample_path,
            source=f"model_falsifier:{provider or 'unknown'}",
        )
        replay = replay_counterexample(counterexample_path, problem)
    except (CounterexampleValidationError, OSError, ValueError) as error:
        result["falsifier_status"] = "UNRESOLVED"
        result["failure_category"] = FailureCategory.SANDBOX_FAILURE.value
        result["falsifier_explanation"] = (
            f"invalid evidence: counterexample could not be saved and replayed ({error})"
        )
        return result

    result["counterexample_path"] = str(counterexample_path)
    result["counterexample_replay"] = replay.as_dict()
    if replay.reproduced:
        result["falsifier_status"] = "REFUTED"
        result["falsifier_explanation"] = (
            "trusted oracle refuted the candidate and the saved counterexample replayed"
        )
        logger.info("Falsifier found replayable counterexample for %s", problem["id"])
    else:
        result["falsifier_status"] = "UNRESOLVED"
        result["failure_category"] = FailureCategory.INTERNAL_ERROR.value
        result["falsifier_explanation"] = (
            "invalid evidence: the saved candidate did not reproduce on replay"
        )
        logger.warning("Falsifier counterexample did not replay for %s", problem["id"])
    return result


def run_falsifier(
    problem: Any,
    destination: str | os.PathLike[str],
    *,
    counterexample_directory: str | os.PathLike[str] | None = None,
    max_tokens: int = 512,
    settings: Any | None = None,
    ask_function: Callable[..., LLMResult] | None = None,
) -> dict[str, Any]:
    """Ask for adversarial inputs, check them, replay refutations, and save a report."""

    record = _resolve_problem(problem)
    system, prompt = build_falsifier_prompt(record)
    report_path = Path(destination)
    cex_directory = (
        Path(counterexample_directory)
        if counterexample_directory is not None
        else report_path.parent / "counterexamples"
    )
    request = ask_function or ask
    request_kwargs: dict[str, Any] = {}
    if settings is not None:
        request_kwargs["settings"] = settings

    result: LLMResult | None = None
    request_error: str | None = None
    try:
        result = request(
            prompt,
            system=system,
            max_tokens=max_tokens,
            **request_kwargs,
        )
    except LLMError as error:
        request_error = f"{error.category}: {error}"
        logger.warning("Falsifier request failed for %s: %s", record["id"], error)

    batch = (
        evaluate_proposal_response(
            record,
            result.text,
            ignore_labels=True,
        )
        if result is not None
        else None
    )
    candidates = (
        [
            _check_candidate(
                record,
                idea,
                cex_directory,
                provider=result.provider,
            )
            for idea in batch.ideas
        ]
        if batch is not None
        else []
    )
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_type": "falsifier",
        "problem_id": record["id"],
        "source": "model_proposed",
        "provider": result.provider if result else None,
        "model": result.model if result else None,
        "usage": result.usage if result else None,
        "request_error": request_error,
        "parse_error": batch.parse_error if batch else None,
        "run_failure_category": (
            FailureCategory.API_ERROR.value
            if request_error
            else batch.failure_category.value
            if batch and batch.failure_category
            else None
        ),
        "run_status": (
            "UNRESOLVED"
            if request_error
            else "INVALID_EVIDENCE"
            if batch and batch.parse_error
            else "COMPLETED"
        ),
        "candidate_inputs": candidates,
        "report_path": str(report_path),
    }
    _atomic_json_write(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Search for counterexamples with a model and check them independently."
    )
    parser.add_argument("problem", help="validated problem JSON path")
    parser.add_argument("report", help="JSON path for the full falsifier run report")
    parser.add_argument(
        "--counterexample-directory",
        help="where replayable oracle refutations are saved (defaults beside report)",
    )
    parser.add_argument("--max-tokens", type=int, default=512)
    args = parser.parse_args(argv)
    try:
        report = run_falsifier(
            args.problem,
            args.report,
            counterexample_directory=args.counterexample_directory,
            max_tokens=args.max_tokens,
        )
    except (ProblemValidationError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["request_error"] or report["parse_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
