"""Run a validated JSON problem through Abacus's local evidence pipeline."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from hypothesis import __version__ as hypothesis_version

from practice.budgets import BudgetTracker
from practice.outcomes import FinalOutcome
from practice.revisions import ClaimRevision, RevisionTriggerEvidence
from practice.run_checkpoints import save_run_checkpoint
from practice.run_records import (
    RUN_RECORD_SCHEMA_VERSION,
    find_run_record,
    load_run_record,
    list_run_records,
    save_run_record,
    sanitize_for_log,
    sanitize_run_record_for_log,
)
from practice.usage_metrics import calculate_actual_cost_usd, summarize_run_usage
from practice.run_view import render_run_summary
from abacus.experiment import (
    evaluate_case,
    generate_hypothesis_cases,
    methods_for as _methods_for,
    scheduled_count as _scheduled_count,
)
from abacus.llm import (
    LLMNotConfiguredError,
    LLMProviderError,
    collect_offline_proposals,
    complete_structured_output,
    create_llm_client,
    model_proposal_records as _model_proposal_records,
)
from abacus.prompts import (
    HOSTED_PROMPT_TEMPLATE_VERSIONS,
    PROMPT_TEMPLATE_VERSIONS,
    build_model_prompt,
)
from abacus.schemas import ModelOutputError, ProblemSpec, ProblemValidationError, load_problem, parse_problem
from abacus.sandbox import EXECUTION_FLAG, MAX_INPUT_BYTES, MAX_SOURCE_BYTES, SandboxError, SandboxRunner
from abacus.targets import ORACLES, TARGETS
from abacus.verifier import ClaimContract, decide


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = PROJECT_ROOT / "runs"


def _evidence_for_case(
    *, spec: ProblemSpec, method: str, test_id: str, value: list[int]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate one bounded value using only the checked-in target/oracle allowlists."""
    return evaluate_case(
        spec=spec,
        method=method,
        test_id=test_id,
        value=value,
        target=TARGETS[spec.target_id],
        oracle=ORACLES[spec.oracle_id],
    )


def _hosted_request_metadata(
    *, spec: ProblemSpec, kind: str, model_id: str, prompt: str, client: Any
) -> dict[str, Any]:
    """Build a privacy-safe fingerprint and record the effective local request limits."""
    parameters_reader = getattr(client, "audit_metadata", None)
    client_metadata = parameters_reader() if callable(parameters_reader) else {}
    if type(client_metadata) is not dict:
        client_metadata = {}
    prompt_bytes = prompt.encode("utf-8")
    request_parameters = {
        key: value for key, value in client_metadata.items() if key != "provider_id"
    }
    return {
        "request_started_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider_id": client_metadata.get("provider_id"),
        "model_id": model_id.strip(),
        "problem_id": spec.problem_id,
        "dataset_version": spec.dataset_version,
        "problem_spec_sha256": spec.problem_spec_sha256,
        "dataset_sha256": spec.dataset_sha256,
        "prompt_template_version": HOSTED_PROMPT_TEMPLATE_VERSIONS[kind],
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "prompt_bytes": len(prompt_bytes),
        "request_parameters": request_parameters or None,
    }


def _revision_log(spec: ProblemSpec, outcome: Any) -> dict[str, Any]:
    if outcome.outcome is not FinalOutcome.REFUTED:
        return {"status": "skipped", "reason": "Revision requires a confirmed REFUTED result."}
    if spec.revision_proposal is None:
        return {"status": "skipped", "reason": "No offline revision proposal fixture was supplied."}
    try:
        trigger = RevisionTriggerEvidence.from_refuted_outcome(outcome)
        revision = ClaimRevision(spec.claim, outcome.outcome.value)
        prompt = revision.prompt_for_revision(trigger)
        recorded = revision.apply_proposal(spec.revision_proposal, trigger_evidence=trigger)
        return {
            "status": "applied_offline_fixture",
            "provider_api_called": False,
            "prompt": prompt,
            "original_claim": recorded.original_claim,
            "original_label": recorded.original_label,
            "scored_claim": recorded.scored_claim,
            "scored_label": recorded.scored_label,
            "revised_claim": recorded.revised_claim,
            "revision_reason": recorded.revision_reason,
            "revision_relation": recorded.revision_relation.value,
            "trigger": recorded.revision_trigger.value if recorded.revision_trigger else None,
            "evidence_reference": recorded.revision_evidence_reference,
        }
    except Exception as error:
        return {
            "status": "error",
            "error": f"{type(error).__name__}: {error}",
        }


def _git_context() -> tuple[str | None, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True,
            text=True, check=True, timeout=2,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, capture_output=True,
            text=True, check=True, timeout=2,
        ).stdout.strip())
        return revision or None, dirty
    except (OSError, subprocess.SubprocessError):
        return None, False


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _runner_code_sha256() -> str:
    digest = hashlib.sha256()
    for path in (
        Path(__file__),
        Path(__file__).with_name("sandbox.py"),
        Path(__file__).with_name("schemas.py"),
        Path(__file__).with_name("targets.py"),
        Path(__file__).with_name("experiment.py"),
        Path(__file__).with_name("llm.py"),
        Path(__file__).with_name("prompts.py"),
        Path(__file__).with_name("verifier.py"),
        PROJECT_ROOT / "practice" / "run_records.py",
        PROJECT_ROOT / "practice" / "outcomes.py",
        PROJECT_ROOT / "practice" / "budgets.py",
        PROJECT_ROOT / "practice" / "revisions.py",
        PROJECT_ROOT / "practice" / "run_checkpoints.py",
        PROJECT_ROOT / "practice" / "provider_retries.py",
    ):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _append_error(errors: list[dict[str, str]], step: str, message: str) -> str:
    error_id = f"error-{len(errors) + 1}"
    errors.append({"error_id": error_id, "step": step, "error": message})
    return error_id


def _default_run_path(
    problem_id: str,
    run_id: str,
    started_at: datetime,
    runs_dir: str | Path = RUNS_DIR,
) -> Path:
    timestamp = started_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    safe_problem_id = sanitize_for_log(problem_id)
    return Path(runs_dir) / f"{safe_problem_id}_{timestamp}_{run_id}.json"


def run_problem(
    spec: ProblemSpec,
    log_path: str | Path | None = None,
    *,
    runs_dir: str | Path = RUNS_DIR,
    checkpoint_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run fixed, Hypothesis, and proposal evidence and always save the run log."""
    started_at = datetime.now(timezone.utc)
    started_clock = time.perf_counter()
    run_id = str(uuid4())
    destination = (
        Path(log_path)
        if log_path is not None
        else _default_run_path(spec.problem_id, run_id, started_at, runs_dir)
    )
    checkpoint_path = destination.with_name(f"{destination.name}.{run_id}.checkpoint")
    tracker = BudgetTracker(spec.budget_config)
    if not tracker.start_round():
        raise RuntimeError("Could not start the local evaluation round.")

    methods = _methods_for(spec)
    scheduled_count = _scheduled_count(spec)
    contract = ClaimContract(
        contract_id=spec.contract_id,
        oracle_id=spec.oracle_id,
        scheduled_test_count=scheduled_count,
        required_methods=tuple(methods),
    )
    evidence: list[dict[str, Any]] = []
    case_log: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    proposal_evaluation_succeeded = not spec.proposals
    proposal_step: dict[str, Any] = {
        "status": "not_started" if spec.proposals else "not_configured",
        "provider_api_called": False,
        "count": 0,
    }
    proposal_stage_status = "not_started" if spec.proposals else "not_configured"
    revision_snapshot: dict[str, Any] = {"status": "not_started"}

    def save_checkpoint(stage: str, *, stage_durations: dict[str, float | None] | None = None) -> None:
        checkpoint = {
            "checkpoint_version": 1,
            "run_id": run_id,
            "problem_id": spec.problem_id,
            "stage": stage,
            "final_path": str(destination),
            "checkpoint_path": str(checkpoint_path),
            "started_at_utc": started_at.isoformat(),
            "duration_seconds": round(time.perf_counter() - started_clock, 6),
            "scheduled_case_count": scheduled_count,
            "generated_case_count": len(hypothesis_cases),
            "budget": tracker.to_dict(evidence_complete=False),
            "stage_durations_seconds": stage_durations or {},
            "evidence": list(evidence),
            "case_log": list(case_log),
            "errors": list(errors),
            "proposal_step": dict(proposal_step),
            "proposal_evaluation_succeeded": proposal_evaluation_succeeded,
            "revision": dict(revision_snapshot),
        }
        save_run_checkpoint(checkpoint_path, checkpoint)
        if checkpoint_callback is not None:
            checkpoint_callback(checkpoint)

    def record_case(method: str, test_id: str, value: list[int]) -> None:
        record, detail = _evidence_for_case(spec=spec, method=method, test_id=test_id, value=value)
        evidence.append(record)
        case_log.append(detail)
        if record["status"] == "internal_error":
            _append_error(errors, method, detail.get("failure_category", "Evaluation failed."))

    tests_started_clock = time.perf_counter()
    for index, value in enumerate(spec.fixed_cases, start=1):
        record_case("fixed", f"fixed-{index}", value)

    hypothesis_cases, generation_error = generate_hypothesis_cases(spec)
    if generation_error:
        _append_error(errors, "hypothesis_generation", generation_error)
        evidence.append(
            {
                "test_id": "hypothesis-generation",
                "method": "hypothesis",
                "contract_id": spec.contract_id,
                "status": "internal_error",
                "failure_category": "HYPOTHESIS_GENERATION",
            }
        )
    else:
        for index, value in enumerate(hypothesis_cases, start=1):
            record_case("hypothesis", f"hypothesis-{index}", value)
    tests_duration_seconds = round(time.perf_counter() - tests_started_clock, 6)
    save_checkpoint("tests_complete", stage_durations={"tests": tests_duration_seconds})

    proposals_started_clock = time.perf_counter()
    if spec.proposals:
        proposal_stage_status = "completed"
        proposal_step["status"] = "offline_fixtures"
        try:
            proposals = collect_offline_proposals(spec)
            proposal_step["count"] = len(proposals)
            proposal_evaluation_succeeded = True
            for index, proposal in enumerate(proposals, start=1):
                value = proposal["input"]
                record, detail = _evidence_for_case(spec=spec, method="proposals", test_id=f"proposal-{index}", value=value)
                evidence.append(record)
                detail["proposal_source"] = "offline_model_proposal_fixture"
                detail["rationale"] = proposal["rationale"]
                case_log.append(detail)
                if record["status"] == "internal_error":
                    _append_error(errors, "proposals", detail.get("failure_category", "Proposal evaluation failed."))
        except Exception as error:
            proposal_stage_status = "error"
            message = f"{type(error).__name__}: {error}"
            _append_error(errors, "optional_proposal_generation", message)
            proposal_step.update({"status": "error", "error": message})
            for index in range(1, len(spec.proposals) + 1):
                evidence.append(
                    {
                        "test_id": f"proposal-generation-{index}",
                        "method": "proposals",
                        "contract_id": spec.contract_id,
                        "status": "internal_error",
                        "failure_category": "OPTIONAL_PROPOSAL_GENERATION",
                    }
                )
    else:
        proposal_step["status"] = "not_configured"
    proposals_duration_seconds = (
        round(time.perf_counter() - proposals_started_clock, 6)
        if spec.proposals else None
    )
    save_checkpoint(
        "proposals_complete",
        stage_durations={"tests": tests_duration_seconds, "proposals": proposals_duration_seconds},
    )

    outcome = decide(evidence, contract)
    revision = _revision_log(spec, outcome)
    revision_snapshot = dict(revision)
    if revision["status"] == "error":
        _append_error(errors, "optional_revision", revision["error"])
    save_checkpoint(
        "revision_complete",
        stage_durations={"tests": tests_duration_seconds, "proposals": proposals_duration_seconds},
    )

    tracker.finish_round()
    completed_count = sum(record.get("status") == "completed" for record in evidence)
    budget = tracker.to_dict(evidence_complete=outcome.outcome is not FinalOutcome.UNRESOLVED)
    budget["usage"]["evaluated_cases"] = completed_count
    finished_at = datetime.now(timezone.utc)
    duration_seconds = round(time.perf_counter() - started_clock, 6)
    stage_durations_seconds = {
        "planning": None,
        "proposals": proposals_duration_seconds,
        "tests": tests_duration_seconds,
        "total": duration_seconds,
    }
    run_status = "complete"
    if outcome.outcome is FinalOutcome.UNRESOLVED:
        run_status = "partial"
    elif outcome.outcome is FinalOutcome.ERROR:
        run_status = "error"
    elif completed_count < scheduled_count:
        run_status = "partial"
    stage_status = {
        "planning": "not_configured",
        "proposals": proposal_stage_status,
        "tests": "completed" if completed_count >= scheduled_count else "partial",
        "total": "error" if run_status == "error" else "partial" if run_status == "partial" else "completed",
    }

    outcome_dict = outcome.to_dict()
    if outcome.counterexample is not None:
        outcome_refs = [outcome.counterexample["test_id"]]
    elif outcome.outcome is FinalOutcome.TESTS_PASSED:
        outcome_refs = [record["test_id"] for record in evidence]
    else:
        outcome_refs = [record["test_id"] for record in evidence if record["status"] != "completed"]
        if not outcome_refs:
            outcome_refs = [record["test_id"] for record in evidence]
    outcome_dict["evidence_references"] = list(dict.fromkeys(outcome_refs))

    revision_reasons: list[str] = []
    if run_status == "partial":
        revision_reasons.append(outcome.reason.value)
    elif run_status == "error":
        revision_reasons.extend(error["step"] for error in errors)
        if not revision_reasons:
            revision_reasons.append(outcome.failure_category or "evaluation_error")
    case_counts = {
        method: sum(record["method"] == method for record in evidence)
        for method in methods
    }
    validated_candidates = [
        {
            "test_id": record["test_id"],
            "method": record["method"],
            "input": record["input"],
            "contract_valid": record["contract_valid"],
        }
        for record in evidence
        if record.get("status") == "completed"
    ]
    replay_details = [
        {
            "test_id": detail["test_id"],
            "attempted": True,
            "confirmed": detail.get("replay_confirmed"),
            "input": detail["input"],
            "actual": detail.get("replay_actual"),
            "expected": detail.get("replay_expected"),
            "error": detail.get("replay_error"),
        }
        for detail in case_log
        if detail.get("replay_attempted")
    ]
    git_revision, git_dirty = _git_context()
    unknown_values = []
    if git_revision is None:
        unknown_values.append({"field": "provenance.git_revision", "reason": "Git revision could not be read."})
    provider_call_count = budget["usage"]["model_calls"]
    provider_api_called = provider_call_count > 0
    provider_token_usage = budget["usage"]["provider_reported_token_usage"]
    pricing_record = (
        spec.pricing_config.to_record()
        if spec.pricing_config is not None
        else {
            "status": "unknown" if provider_api_called else "not_applicable",
            "provider_id": None,
            "model_id": None,
            "input_usd_per_million_tokens": None,
            "output_usd_per_million_tokens": None,
            "source_url": None,
            "checked_at": None,
        }
    )
    estimated_cost = (
        0.0 if not provider_api_called
        else budget["usage"]["cost_estimated_usd"]
        if spec.pricing_config is not None
        else None
    )
    actual_cost = calculate_actual_cost_usd(
        provider_token_usage, spec.pricing_config, provider_api_called=provider_api_called
    )
    usage_unknown_values = []
    if provider_token_usage["status"] == "unknown":
        usage_unknown_values.append("provider_reported_token_usage")
    if pricing_record["status"] == "unknown":
        usage_unknown_values.append("pricing")
    if estimated_cost is None:
        usage_unknown_values.append("estimated_cost_usd")
    if actual_cost is None:
        usage_unknown_values.append("actual_cost_usd")

    record_schema = {
        "schema_version": RUN_RECORD_SCHEMA_VERSION,
        "run_id": run_id,
        "run_status": run_status,
        "timestamps": {
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at.isoformat(),
            "duration_seconds": duration_seconds,
        },
        "problem": {
            "problem_id": spec.problem_id,
            "dataset_version": spec.dataset_version,
            "dataset_sha256": spec.dataset_sha256,
            "problem_spec_sha256": spec.problem_spec_sha256,
            "dataset": {
                "fixed_cases": list(spec.fixed_cases),
                "proposal_fixtures": list(spec.proposals),
                "hypothesis": spec.hypothesis,
            },
            "original_claim": spec.claim,
            "contract": {
                "id": spec.contract_id,
                "oracle_id": spec.oracle_id,
                "input_type": "integer_list",
                "allow_empty": spec.allow_empty,
            },
        },
        "target": {
            "id": spec.target_id,
            "code_sha256": _sha256_text(inspect.getsource(TARGETS[spec.target_id])),
            "runner_code_sha256": _runner_code_sha256(),
            "execution_origin": "trusted_allowlist",
        },
        "provenance": {
            "git_revision": git_revision,
            "git_dirty": git_dirty,
            "software_versions": {
                "python": sys.version.split()[0],
                "hypothesis": hypothesis_version,
                "platform": platform.platform(),
                "abacus": "0.1.0-pilot",
            },
        },
        "model": {
            "provider_id": None,
            "model_id": None,
            "provider_api_called": False,
            "provider_identity_status": "not_applicable_no_provider_call",
            "proposal_step": proposal_step,
            "prompt_template_versions": dict(PROMPT_TEMPLATE_VERSIONS),
            "plan_suggestions": [
                {"text": text, "source": "offline_model_suggestion_fixture", "applied_as_fact": False}
                for text in spec.suggestions
            ],
        },
        "generation": {
            "methods": methods,
            "random_seeds": {"hypothesis": spec.hypothesis["seed"]},
            "settings": {"hypothesis": spec.hypothesis, "budget": spec.budget_config.to_dict()},
            "scheduled_case_count": scheduled_count,
            "generated_case_count": len(hypothesis_cases),
            "validated_candidate_count": len(validated_candidates),
            "case_counts_by_method": case_counts,
        },
        "model_proposals": _model_proposal_records(spec, evaluated=proposal_evaluation_succeeded),
        "validated_candidates": validated_candidates,
        "evidence": evidence,
        "replay_details": replay_details,
        "outcome": outcome_dict,
        "completion": {
            "status": run_status,
            "scheduled_case_count": scheduled_count,
            "completed_case_count": completed_count,
            "incomplete_reasons": revision_reasons,
        },
        "revision": revision,
        "usage": {
            "resource_usage_version": 1,
            "model_call_count": budget["usage"]["model_calls"],
            "successful_model_call_count": budget["usage"]["successful_calls"],
            "failed_model_call_count": budget["usage"]["failed_calls"],
            "retry_call_count": budget["usage"]["retry_calls"],
            "provider_reported_token_usage": provider_token_usage,
            "duration_seconds": duration_seconds,
            "stage_durations_seconds": stage_durations_seconds,
            "stage_status": stage_status,
            "pricing": pricing_record,
            "estimated_cost_usd": estimated_cost,
            "actual_cost_usd": actual_cost,
            "unknown_values": usage_unknown_values,
        },
        "budget": budget,
        "errors": errors,
        "unknown_values": unknown_values,
    }
    record_schema = sanitize_run_record_for_log(record_schema)
    save_run_record(destination, record_schema)
    try:
        checkpoint_path.unlink(missing_ok=True)
    except OSError:
        # The complete record takes precedence; stale checkpoints are ignored by listing.
        pass
    run_record = record_schema
    run_record["log_path"] = str(destination)
    return run_record


def _emergency_error_record(
    spec: ProblemSpec,
    error: Exception,
    *,
    started_at: datetime,
    duration_seconds: float,
    progress: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a schema-valid failure record if an unexpected stage escapes."""
    finished_at = datetime.now(timezone.utc).isoformat()
    error_id = "pipeline-error"
    methods = _methods_for(spec)
    scheduled_count = _scheduled_count(spec)
    git_revision, git_dirty = _git_context()
    unknown_values = []
    if git_revision is None:
        unknown_values.append({"field": "provenance.git_revision", "reason": "Git revision could not be read."})
    unknown_values.append({"field": "budget.usage.rounds", "reason": "The tracker snapshot was unavailable after the escaped failure."})
    message = f"{type(error).__name__}: {error}"
    record = {
        "schema_version": RUN_RECORD_SCHEMA_VERSION,
        "run_id": str(uuid4()),
        "run_status": "error",
        "timestamps": {
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at,
            "duration_seconds": duration_seconds,
        },
        "problem": {
            "problem_id": spec.problem_id,
            "dataset_version": spec.dataset_version,
            "dataset_sha256": spec.dataset_sha256,
            "problem_spec_sha256": spec.problem_spec_sha256,
            "dataset": {
                "fixed_cases": list(spec.fixed_cases),
                "proposal_fixtures": list(spec.proposals),
                "hypothesis": spec.hypothesis,
            },
            "original_claim": spec.claim,
            "contract": {
                "id": spec.contract_id,
                "oracle_id": spec.oracle_id,
                "input_type": "integer_list",
                "allow_empty": spec.allow_empty,
            },
        },
        "target": {
            "id": spec.target_id,
            "code_sha256": _sha256_text(inspect.getsource(TARGETS[spec.target_id])),
            "runner_code_sha256": _runner_code_sha256(),
            "execution_origin": "trusted_allowlist",
        },
        "provenance": {
            "git_revision": git_revision,
            "git_dirty": git_dirty,
            "software_versions": {
                "python": sys.version.split()[0],
                "hypothesis": hypothesis_version,
                "platform": platform.platform(),
                "abacus": "0.1.0-pilot",
            },
        },
        "model": {
            "provider_id": None,
            "model_id": None,
            "provider_api_called": False,
            "provider_identity_status": "not_applicable_no_provider_call",
            "proposal_step": {"status": "not_started", "provider_api_called": False, "count": 0},
            "prompt_template_versions": dict(PROMPT_TEMPLATE_VERSIONS),
            "plan_suggestions": [
                {"text": text, "source": "offline_model_suggestion_fixture", "applied_as_fact": False}
                for text in spec.suggestions
            ],
        },
        "generation": {
            "methods": methods,
            "random_seeds": {"hypothesis": spec.hypothesis["seed"]},
            "settings": {"hypothesis": spec.hypothesis, "budget": spec.budget_config.to_dict()},
            "scheduled_case_count": scheduled_count,
            "generated_case_count": 0,
            "validated_candidate_count": 0,
            "case_counts_by_method": {method: 0 for method in methods},
        },
        "model_proposals": _model_proposal_records(spec, evaluated=False),
        "validated_candidates": [],
        "evidence": [],
        "replay_details": [],
        "outcome": {
            "outcome": "ERROR",
            "reason": "internal_error",
            "message": "An unexpected pipeline failure prevented a complete run.",
            "test_count": None,
            "methods": ["pipeline"],
            "counterexample": None,
            "failure_category": getattr(error, "category", type(error).__name__),
            "outcome_ambiguous": bool(getattr(error, "outcome_ambiguous", False)),
            "billing_status": getattr(error, "billing_status", "not_applicable"),
            "proof_checker": None,
            "proof_evidence_id": None,
            "evidence_references": [f"error:{error_id}"],
        },
        "completion": {
            "status": "error",
            "scheduled_case_count": scheduled_count,
            "completed_case_count": 0,
            "incomplete_reasons": ["pipeline_failure"],
        },
        "revision": {"status": "not_started", "reason": "Pipeline failed before revision processing."},
        "usage": {
            "resource_usage_version": 1,
            "model_call_count": 0,
            "successful_model_call_count": 0,
            "failed_model_call_count": 0,
            "retry_call_count": 0,
            "provider_reported_token_usage": {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "status": "not_applicable",
            },
            "duration_seconds": duration_seconds,
            "stage_durations_seconds": {
                "planning": None, "proposals": None, "tests": None, "total": duration_seconds,
            },
            "stage_status": {
                "planning": "not_configured", "proposals": "not_started",
                "tests": "not_started", "total": "error",
            },
            "pricing": {
                "status": "not_applicable", "provider_id": None, "model_id": None,
                "input_usd_per_million_tokens": None, "output_usd_per_million_tokens": None,
                "source_url": None, "checked_at": None,
            },
            "estimated_cost_usd": 0.0,
            "actual_cost_usd": 0.0,
            "unknown_values": [],
        },
        "budget": {
            "budget_configured": spec.budget_config.to_dict(),
            "usage": {
                "rounds": None, "model_calls": 0, "successful_calls": 0, "failed_calls": 0,
                "retry_calls": 0,
                "tokens_actual": 0, "tokens_actual_status": "not_applicable",
                "cost_estimated_usd": 0.0, "cost_actual_usd": 0.0,
                "cost_actual_status": "not_applicable",
                "provider_reported_token_usage": {
                    "input_tokens": None, "output_tokens": None, "total_tokens": None,
                    "status": "not_applicable",
                },
            },
            "stop_reason": "pipeline_failure",
            "events": [],
        },
        "errors": [{"error_id": error_id, "step": "pipeline", "error": message}],
        "unknown_values": unknown_values,
    }
    failure_budget = getattr(error, "budget_snapshot", None)
    if not isinstance(progress, Mapping):
        if not isinstance(failure_budget, Mapping):
            return record
        progress = {"budget": failure_budget}

    evidence = progress.get("evidence", [])
    evidence = [dict(item) for item in evidence if isinstance(item, Mapping)] if isinstance(evidence, list) else []
    case_log = progress.get("case_log", [])
    case_log = [dict(item) for item in case_log if isinstance(item, Mapping)] if isinstance(case_log, list) else []
    saved_errors = progress.get("errors", [])
    errors = [dict(item) for item in saved_errors if isinstance(item, Mapping)] if isinstance(saved_errors, list) else []
    existing_error_ids = {item.get("error_id") for item in errors}
    if error_id in existing_error_ids:
        error_id = f"pipeline-error-{len(errors) + 1}"
    message = f"{type(error).__name__}: {error}"
    errors.append({"error_id": error_id, "step": "pipeline", "error": message})

    methods = _methods_for(spec)
    method_counts = {method: sum(item.get("method") == method for item in evidence) for method in methods}
    completed = [item for item in evidence if item.get("status") == "completed"]
    validated_candidates = [
        {
            "test_id": item["test_id"],
            "method": item["method"],
            "input": item["input"],
            "contract_valid": item["contract_valid"],
        }
        for item in completed
        if all(key in item for key in ("test_id", "method", "input", "contract_valid"))
    ]
    replay_details = [
        {
            "test_id": detail["test_id"],
            "attempted": True,
            "confirmed": detail.get("replay_confirmed"),
            "input": detail.get("input"),
            "actual": detail.get("replay_actual"),
            "expected": detail.get("replay_expected"),
            "error": detail.get("replay_error"),
        }
        for detail in case_log
        if detail.get("replay_attempted") and isinstance(detail.get("test_id"), str)
    ]
    proposal_step = progress.get("proposal_step")
    if not isinstance(proposal_step, Mapping):
        proposal_step = record["model"]["proposal_step"]
    revision = progress.get("revision")
    if not isinstance(revision, Mapping):
        revision = {"status": "not_started", "reason": "Pipeline failed before revision processing."}
    stage_durations = progress.get("stage_durations_seconds", {})
    if not isinstance(stage_durations, Mapping):
        stage_durations = {}
    scheduled_count = progress.get("scheduled_case_count")
    if type(scheduled_count) is not int or scheduled_count < len(completed):
        scheduled_count = _scheduled_count(spec)
    generated_count = progress.get("generated_case_count")
    if type(generated_count) is not int or generated_count < 0:
        generated_count = method_counts.get("hypothesis", 0)
    stage = progress.get("stage")
    proposal_status = (
        str(proposal_step.get("status", "completed"))
        if stage in {"proposals_complete", "revision_complete"}
        else "partial" if stage == "tests_complete" and spec.proposals
        else "not_configured" if not spec.proposals
        else "not_started"
    )
    proposal_succeeded = bool(progress.get("proposal_evaluation_succeeded", not spec.proposals))
    progress_budget = failure_budget if isinstance(failure_budget, Mapping) else progress.get("budget")
    if not isinstance(progress_budget, Mapping):
        progress_budget = {}
    progress_budget_usage = progress_budget.get("usage")
    if not isinstance(progress_budget_usage, Mapping):
        progress_budget_usage = {}
    model_calls = progress_budget_usage.get("model_calls", 0)
    successful_calls = progress_budget_usage.get("successful_calls", 0)
    failed_calls = progress_budget_usage.get("failed_calls", 0)
    retry_calls = progress_budget_usage.get("retry_calls", 0)
    provider_usage = progress_budget_usage.get("provider_reported_token_usage")
    if not isinstance(provider_usage, Mapping):
        provider_usage = record["usage"]["provider_reported_token_usage"]
    pricing_record = (
        spec.pricing_config.to_record()
        if model_calls and spec.pricing_config is not None
        else {
            "status": "unknown" if model_calls else "not_applicable",
            "provider_id": None,
            "model_id": None,
            "input_usd_per_million_tokens": None,
            "output_usd_per_million_tokens": None,
            "source_url": None,
            "checked_at": None,
        }
    )
    estimated_cost = (
        progress_budget_usage.get("cost_estimated_usd", 0.0)
        if not model_calls or spec.pricing_config is not None
        else None
    )
    actual_cost = (
        progress_budget_usage.get("cost_actual_usd", 0.0)
        if not model_calls or spec.pricing_config is not None
        else None
    )
    usage_unknown_values = []
    if provider_usage.get("status") == "unknown":
        usage_unknown_values.append("provider_reported_token_usage")
    if pricing_record["status"] == "unknown":
        usage_unknown_values.append("pricing")
    if estimated_cost is None:
        usage_unknown_values.append("estimated_cost_usd")
    if actual_cost is None:
        usage_unknown_values.append("actual_cost_usd")
    model_record = dict(record["model"])
    model_record.update({
        "provider_api_called": bool(model_calls),
        "provider_identity_status": "unknown_after_provider_call" if model_calls else "not_applicable_no_provider_call",
        "proposal_step": dict(proposal_step),
    })
    usage_record = dict(record["usage"])
    usage_record.update({
        "model_call_count": model_calls,
        "successful_model_call_count": successful_calls,
        "failed_model_call_count": failed_calls,
        "retry_call_count": retry_calls,
        "provider_reported_token_usage": dict(provider_usage),
        "pricing": pricing_record,
        "estimated_cost_usd": estimated_cost,
        "actual_cost_usd": actual_cost,
        "unknown_values": usage_unknown_values,
    })
    started_text = progress.get("started_at_utc")
    if isinstance(started_text, str):
        try:
            checkpoint_started_at = datetime.fromisoformat(started_text)
            if checkpoint_started_at.tzinfo is not None:
                started_at = checkpoint_started_at
        except ValueError:
            pass
    revision_reasons = [str(item.get("step", "pipeline_failure")) for item in errors]
    counts = {**method_counts}
    record.update({
        "run_id": progress.get("run_id", record["run_id"]),
        "timestamps": {
            **record["timestamps"],
            "started_at_utc": started_at.isoformat(),
            "duration_seconds": duration_seconds,
        },
        "model": model_record,
        "generation": {
            **record["generation"],
            "scheduled_case_count": scheduled_count,
            "generated_case_count": generated_count,
            "validated_candidate_count": len(validated_candidates),
            "case_counts_by_method": counts,
        },
        "model_proposals": _model_proposal_records(spec, evaluated=proposal_succeeded),
        "validated_candidates": validated_candidates,
        "evidence": evidence,
        "replay_details": replay_details,
        "outcome": {
            **record["outcome"],
            "test_count": len(completed),
            "evidence_references": [f"error:{error_id}"],
        },
        "completion": {
            "status": "error",
            "scheduled_case_count": scheduled_count,
            "completed_case_count": len(completed),
            "incomplete_reasons": revision_reasons or ["pipeline_failure"],
        },
        "revision": dict(revision),
        "errors": errors,
        "usage": {
            **usage_record,
            "duration_seconds": duration_seconds,
            "stage_durations_seconds": {
                "planning": None,
                "proposals": stage_durations.get("proposals"),
                "tests": stage_durations.get("tests"),
                "total": duration_seconds,
            },
            "stage_status": {
                "planning": "not_configured",
                "proposals": proposal_status,
                "tests": "completed" if stage in {"tests_complete", "proposals_complete", "revision_complete"} else "partial",
                "total": "error",
            },
        },
        "budget": {
            **record["budget"],
            **dict(progress_budget),
            "budget_configured": spec.budget_config.to_dict(),
            "usage": {
                **record["budget"]["usage"],
                **dict(progress_budget_usage),
                "rounds": progress_budget_usage.get("rounds", 1 if stage else None),
                "model_calls": model_calls,
                "successful_calls": successful_calls,
                "failed_calls": failed_calls,
                "retry_calls": retry_calls,
                "evaluated_cases": len(completed),
            },
            "stop_reason": progress_budget.get("stop_reason") or "pipeline_failure",
            "events": list(progress_budget.get("events", [])) if isinstance(progress_budget.get("events", []), list) else [],
        },
        "unknown_values": [
            item for item in unknown_values
            if item.get("field") != "budget.usage.rounds"
        ],
    })
    return record


def _sandbox_error_record(
    execution_id: str,
    started_at: datetime,
    reason: str,
    *,
    source_sha256: str | None = None,
    input_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "execution_id": execution_id,
        "started_at_utc": started_at.isoformat(),
        "execution_origin": "untrusted_sandbox",
        "outcome": "ERROR",
        "reason": reason,
        "source_sha256": source_sha256,
        "input_sha256": input_sha256,
    }


def _read_bounded_file(path: str, limit: int, reason: str) -> bytes:
    try:
        with Path(path).open("rb") as handle:
            contents = handle.read(limit + 1)
    except OSError as error:
        raise SandboxError(reason) from error
    if len(contents) > limit:
        raise SandboxError(reason)
    return contents


def _reject_nonstandard_json(constant: str) -> None:
    raise ValueError(f"Non-standard JSON number: {constant}")


def _execute_untrusted_cli(args: argparse.Namespace) -> int:
    execution_id = str(uuid4())
    started_at = datetime.now(timezone.utc)

    source_sha256 = None
    input_sha256 = None

    def fail(reason: str) -> int:
        error_record = _sandbox_error_record(
            execution_id,
            started_at,
            reason,
            source_sha256=source_sha256,
            input_sha256=input_sha256,
        )
        print(json.dumps(error_record, ensure_ascii=False))
        return 1

    if not args.allow_untrusted_code:
        return fail("explicit_opt_in_required")
    if os.environ.get(EXECUTION_FLAG) != "1":
        return fail("execution_flag_disabled")

    runner = SandboxRunner()
    try:
        # Check Day 37's verification receipt before opening candidate files.
        runner.preflight(explicit_opt_in=True)
        source_bytes = _read_bounded_file(args.source_file, MAX_SOURCE_BYTES, "source_file_unavailable_or_too_large")
        input_bytes = _read_bounded_file(args.input_file, MAX_INPUT_BYTES, "input_file_unavailable_or_too_large")
        source = source_bytes.decode("utf-8")
        value = json.loads(input_bytes.decode("utf-8"), parse_constant=_reject_nonstandard_json)
        canonical_input = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        input_sha256 = hashlib.sha256(canonical_input.encode("utf-8")).hexdigest()
        sandbox_result = runner.execute(source, value, explicit_opt_in=True)
    except SandboxError as error:
        return fail(error.reason)
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        return fail("source_or_input_invalid")
    except Exception:
        return fail("sandbox_internal_error")

    result_record = {
        "execution_id": execution_id,
        "started_at_utc": started_at.isoformat(),
        "execution_origin": "untrusted_sandbox",
        "outcome": "COMPLETED",
        "reason": "candidate_returned_json",
        "source_sha256": source_sha256,
        "input_sha256": input_sha256,
        "runtime_version": sandbox_result["runtime_version"],
        "image_id": sandbox_result["image_id"],
        "result": sandbox_result["result"],
    }
    print(json.dumps(result_record, ensure_ascii=False, allow_nan=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m abacus")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run one JSON problem through the local evidence pipeline")
    run_parser.add_argument("problem", help="path to a validated problem JSON file")
    run_parser.add_argument(
        "--output",
        help="exact run-log path (default: unique timestamp+UUID under runs/); existing files are never overwritten",
    )
    prompt_parser = subparsers.add_parser(
        "prompt-preview",
        help="preview a bounded hosted-model prompt without calling a provider",
    )
    prompt_parser.add_argument("problem", help="path to a validated problem JSON file")
    prompt_parser.add_argument(
        "--kind",
        required=True,
        choices=tuple(HOSTED_PROMPT_TEMPLATE_VERSIONS),
        help="structured model output kind to preview",
    )
    suggest_parser = subparsers.add_parser(
        "model-suggest",
        help="make one explicitly authorized hosted request and return parsed suggestions",
    )
    suggest_parser.add_argument("problem", help="path to a validated problem JSON file")
    suggest_parser.add_argument(
        "--kind",
        required=True,
        choices=tuple(HOSTED_PROMPT_TEMPLATE_VERSIONS),
        help="structured model output kind to request",
    )
    suggest_parser.add_argument("--model", required=True, help="provider model ID for this request")
    suggest_parser.add_argument(
        "--send-to-provider",
        action="store_true",
        required=True,
        help="required confirmation; sends the claim and test context to the configured provider",
    )
    suggest_parser.add_argument(
        "--evaluate-proposals",
        action="store_true",
        help="evaluate parsed candidate inputs with the registered local target and oracle",
    )
    untrusted_parser = subparsers.add_parser(
        "execute-untrusted",
        help="run a candidate(value) function only through the verified container sandbox",
    )
    untrusted_parser.add_argument("source_file", help="UTF-8 Python source defining candidate(value)")
    untrusted_parser.add_argument("--input", dest="input_file", required=True, help="UTF-8 JSON input file")
    untrusted_parser.add_argument(
        "--allow-untrusted-code",
        action="store_true",
        help="explicitly opt in; ABACUS_UNTRUSTED_EXECUTION=1 is also required",
    )
    list_parser = subparsers.add_parser("list-runs", help="list saved runs and interrupted-save markers")
    list_parser.add_argument("problem_id", nargs="?", help="optionally filter by problem ID")
    list_parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    show_parser = subparsers.add_parser("show-run", help="open one saved run record by run ID")
    show_parser.add_argument("run_id", help="UUID from list-runs")
    show_parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    view_parser = subparsers.add_parser("view-run", help="show a readable summary for one run ID")
    view_parser.add_argument("run_id", help="UUID from list-runs")
    view_parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    summary_parser = subparsers.add_parser("summarize-runs", help="summarize resource usage across saved runs")
    summary_parser.add_argument("problem_id", nargs="?", help="optionally summarize one problem")
    summary_parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    args = parser.parse_args(argv)

    if args.command == "list-runs":
        print(json.dumps(list_run_records(args.runs_dir, problem_id=args.problem_id), indent=2, ensure_ascii=False))
        return 0
    if args.command == "show-run":
        record = find_run_record(args.runs_dir, args.run_id)
        if record is None:
            print(f"Run ID not found: {args.run_id}", file=sys.stderr)
            return 2
        if "incomplete_marker" in record:
            print(json.dumps(record, indent=2, ensure_ascii=False))
            return 1
        print(json.dumps(record, indent=2, ensure_ascii=False))
        return 0
    if args.command == "view-run":
        record = find_run_record(args.runs_dir, args.run_id)
        if record is None:
            print(f"Run ID not found: {args.run_id}", file=sys.stderr)
            return 2
        entries = list_run_records(args.runs_dir)
        record_path = next(
            (item["path"] for item in entries["runs"] if item["run_id"] == args.run_id),
            None,
        )
        if "incomplete_marker" in record:
            marker = record["incomplete_marker"]
            record_path = marker.get("marker_path", record_path)
        elif "progress_checkpoint" in record:
            checkpoint = record["progress_checkpoint"]
            record_path = checkpoint.get("path", record_path)
        print(render_run_summary(record, record_path=record_path))
        return 1 if "incomplete_marker" in record or "progress_checkpoint" in record else 0
    if args.command == "summarize-runs":
        entries = list_run_records(args.runs_dir, problem_id=args.problem_id)
        records = [load_run_record(item["path"]) for item in entries["runs"]]
        summary = summarize_run_usage(records)
        summary["problem_id"] = args.problem_id
        summary["incomplete_run_count"] = len(entries["incomplete"])
        summary["checkpoint_count"] = len(entries["checkpoints"])
        summary["invalid_file_count"] = len(entries["invalid_files"])
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    if args.command == "execute-untrusted":
        return _execute_untrusted_cli(args)

    try:
        spec = load_problem(args.problem)
    except ProblemValidationError as error:
        print(f"Problem validation failed: {error}", file=sys.stderr)
        return 2

    if args.command == "prompt-preview":
        try:
            prompt = build_model_prompt(args.kind, spec)
        except (TypeError, ValueError) as error:
            print(f"Prompt could not be built: {error}", file=sys.stderr)
            return 2
        print(json.dumps({
            "output_kind": args.kind,
            "template_version": HOSTED_PROMPT_TEMPLATE_VERSIONS[args.kind],
            "prompt_bytes": len(prompt.encode("utf-8")),
            "target_source_included": False,
            "provider_api_called": False,
            "prompt": prompt,
        }, indent=2, ensure_ascii=False))
        return 0

    if args.command == "model-suggest":
        if args.evaluate_proposals and args.kind != "candidate_proposals":
            print(json.dumps({
                "status": "invalid_request",
                "provider_api_called": False,
                "error": "--evaluate-proposals requires --kind candidate_proposals.",
            }, ensure_ascii=False))
            return 2
        if not args.model.strip():
            print(json.dumps({
                "status": "invalid_request",
                "provider_api_called": False,
                "error": "--model must be a non-empty model ID.",
            }, ensure_ascii=False))
            return 2
        try:
            prompt = build_model_prompt(args.kind, spec)
        except (TypeError, ValueError) as error:
            print(json.dumps({
                "status": "invalid_prompt",
                "provider_api_called": False,
                "error": str(error),
            }, ensure_ascii=False))
            return 2

        try:
            client = create_llm_client()
        except LLMNotConfiguredError as error:
            print(json.dumps({
                "status": "not_configured",
                "provider_api_called": False,
                "error": str(error),
            }, ensure_ascii=False))
            return 2

        request_metadata = _hosted_request_metadata(
            spec=spec,
            kind=args.kind,
            model_id=args.model,
            prompt=prompt,
            client=client,
        )
        try:
            result = complete_structured_output(
                client,
                args.kind,
                prompt,
                model_id=args.model,
            )
        except LLMNotConfiguredError as error:
            print(json.dumps({
                "status": "not_configured",
                "provider_api_called": False,
                "request_metadata": request_metadata,
                "error": str(error),
            }, ensure_ascii=False))
            return 2
        except (LLMProviderError, ModelOutputError) as error:
            print(json.dumps({
                "status": "error",
                "output_kind": args.kind,
                "model_id": args.model,
                "provider_api_called": True,
                "usage_recorded": False,
                "request_metadata": request_metadata,
                "error_category": error.category,
            }, ensure_ascii=False))
            return 1
        except ValueError as error:
            print(json.dumps({
                "status": "invalid_request",
                "provider_api_called": False,
                "request_metadata": request_metadata,
                "error": str(error),
            }, ensure_ascii=False))
            return 2
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        output = {
            "status": "suggestions_ready",
            "output_kind": args.kind,
            "template_version": HOSTED_PROMPT_TEMPLATE_VERSIONS[args.kind],
            "model_id": args.model,
            "provider_api_called": True,
            "usage_recorded": False,
            "request_metadata": request_metadata,
            "suggestions_are_evidence": False,
            "result": asdict(result),
        }
        if args.evaluate_proposals:
            evaluated: list[dict[str, Any]] = []
            for index, proposal in enumerate(result.proposals, start=1):
                candidate = list(proposal.input)
                item: dict[str, Any] = {
                    "proposal_index": index,
                    "input": candidate,
                    "rationale": proposal.rationale,
                    "contract_status": "valid",
                    "evaluation_status": "not_run",
                    "evidence": None,
                }
                if not spec.allow_empty and not candidate:
                    item.update({
                        "contract_status": "rejected",
                        "evaluation_status": "not_run",
                        "failure_category": "empty_input_not_allowed",
                    })
                else:
                    evidence, _detail = _evidence_for_case(
                        spec=spec,
                        method="hosted_model_proposal",
                        test_id=f"hosted-proposal-{index}",
                        value=candidate,
                    )
                    item["evaluation_status"] = evidence.get("category", evidence.get("status"))
                    item["evidence"] = evidence
                evaluated.append(item)
            output["proposal_evaluation"] = {
                "status": "completed",
                "evaluator": "registered_local_target_and_oracle",
                "results_saved": False,
                "results": evaluated,
            }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0

    requested_log_path = Path(args.output) if args.output else None
    pipeline_started_at = datetime.now(timezone.utc)
    pipeline_started_clock = time.perf_counter()
    latest_checkpoint: dict[str, Any] = {}

    def remember_checkpoint(checkpoint: dict[str, Any]) -> None:
        latest_checkpoint.clear()
        latest_checkpoint.update(checkpoint)

    try:
        record = run_problem(spec, requested_log_path, checkpoint_callback=remember_checkpoint)
    except Exception as error:
        failure = _emergency_error_record(
            spec,
            error,
            started_at=pipeline_started_at,
            duration_seconds=round(time.perf_counter() - pipeline_started_clock, 6),
            progress=latest_checkpoint or None,
        )
        failure = sanitize_run_record_for_log(failure)
        progress_path = latest_checkpoint.get("final_path")
        log_path = Path(progress_path) if isinstance(progress_path, str) else requested_log_path
        if log_path is None:
            log_path = _default_run_path(
                spec.problem_id,
                failure["run_id"],
                pipeline_started_at,
            )
        if log_path.exists() or log_path.with_name(log_path.name + ".incomplete").exists():
            log_path = log_path.with_name(f"{log_path.stem}.error-{failure['run_id']}{log_path.suffix}")
        save_run_record(log_path, failure)
        checkpoint_path = latest_checkpoint.get("checkpoint_path")
        if isinstance(checkpoint_path, str):
            try:
                Path(checkpoint_path).unlink(missing_ok=True)
            except OSError:
                pass
        print(json.dumps(failure, indent=2, ensure_ascii=False))
        print(f"Saved error log: {log_path}", file=sys.stderr)
        return 1

    print(json.dumps({
        "problem_id": record["problem"]["problem_id"],
        "outcome": record["outcome"]["outcome"],
        "reason": record["outcome"]["reason"],
        "test_count": record["outcome"]["test_count"],
        "counterexample": record["outcome"]["counterexample"],
        "log_path": record["log_path"],
        "provider_api_called": record["model"]["provider_api_called"],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
