"""Run a validated JSON problem through Abacus's local evidence pipeline."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from hypothesis import HealthCheck, __version__ as hypothesis_version, given, seed, settings, strategies as st

from practice.budgets import BudgetConfig, BudgetTracker
from practice.decision import ClaimContract, decide
from practice.outcomes import FinalOutcome
from practice.revisions import ClaimRevision, RevisionTriggerEvidence
from practice.run_records import (
    RUN_RECORD_SCHEMA_VERSION,
    find_run_record,
    load_run_record,
    list_run_records,
    save_run_record,
    sanitize_for_log,
    sanitize_run_record_for_log,
)
from practice.usage_metrics import PricingConfig, calculate_actual_cost_usd, summarize_run_usage
from practice.run_view import render_run_summary


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = PROJECT_ROOT / "runs"


class ProblemValidationError(ValueError):
    """A problem file is malformed or asks for an unsupported operation."""


@dataclass(frozen=True)
class ProblemSpec:
    problem_id: str
    dataset_version: str
    dataset_sha256: str
    problem_spec_sha256: str
    claim: str
    target_id: str
    contract_id: str
    oracle_id: str
    allow_empty: bool
    fixed_cases: tuple[list[int], ...]
    proposals: tuple[dict[str, Any], ...]
    suggestions: tuple[str, ...]
    hypothesis: dict[str, int]
    budget_config: BudgetConfig
    revision_proposal: dict[str, str] | None
    pricing_config: PricingConfig | None


def sort_correct(values: list[int]) -> list[int]:
    return sorted(values)


def sort_drops_duplicates(values: list[int]) -> list[int]:
    return sorted(set(values))


TARGETS: dict[str, Callable[[list[int]], list[int]]] = {
    "sort_correct": sort_correct,
    "sort_drops_duplicates": sort_drops_duplicates,
}
ORACLES: dict[str, Callable[[list[int]], list[int]]] = {
    "sorted_integer_list_v1": sorted,
}


def _nonempty_text(value: Any, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ProblemValidationError(f"{label} must be a non-empty string.")
    return value.strip()


def _require_keys(value: Any, required: set[str], optional: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProblemValidationError(f"{label} must be a JSON object.")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing or extra:
        parts = []
        if missing:
            parts.append("missing " + ", ".join(sorted(missing)))
        if extra:
            parts.append("unknown " + ", ".join(sorted(extra)))
        raise ProblemValidationError(f"{label}: " + "; ".join(parts) + ".")
    return value


def _validate_integer_list(value: Any, *, allow_empty: bool, label: str) -> list[int]:
    if type(value) is not list or any(type(item) is not int for item in value):
        raise ProblemValidationError(f"{label} must be a JSON list of integers (booleans excluded).")
    if not allow_empty and not value:
        raise ProblemValidationError(f"{label} cannot be empty for this contract.")
    return value


def parse_problem(payload: Any) -> ProblemSpec:
    """Validate the complete inert JSON record before target or oracle execution."""
    root = _require_keys(
        payload,
        {"schema_version", "problem_id", "dataset_version", "claim", "target", "contract", "plan_suggestions", "fixed_cases", "hypothesis", "budget"},
        {"proposal_fixtures", "revision_proposal_fixture", "pricing"},
        "problem",
    )
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise ProblemValidationError("schema_version must be the integer 1.")
    problem_id = _nonempty_text(root["problem_id"], "problem_id")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", problem_id):
        raise ProblemValidationError("problem_id may contain lowercase letters, digits, _ and - only.")
    dataset_version = _nonempty_text(root["dataset_version"], "dataset_version")
    claim = _nonempty_text(root["claim"], "claim")

    target_obj = _require_keys(root["target"], {"id"}, set(), "target")
    target_id = _nonempty_text(target_obj["id"], "target.id")
    if target_id not in TARGETS:
        raise ProblemValidationError(f"Unsupported target id {target_id!r}.")

    contract = _require_keys(
        root["contract"], {"id", "oracle_id", "input_type", "allow_empty"}, set(), "contract"
    )
    contract_id = _nonempty_text(contract["id"], "contract.id")
    oracle_id = _nonempty_text(contract["oracle_id"], "contract.oracle_id")
    if oracle_id not in ORACLES:
        raise ProblemValidationError(f"Unsupported oracle id {oracle_id!r}.")
    if contract["input_type"] != "integer_list":
        raise ProblemValidationError("contract.input_type must be 'integer_list'.")
    if type(contract["allow_empty"]) is not bool:
        raise ProblemValidationError("contract.allow_empty must be a boolean.")
    allow_empty = contract["allow_empty"]

    raw_fixed = root["fixed_cases"]
    if type(raw_fixed) is not list or not raw_fixed:
        raise ProblemValidationError("fixed_cases must be a non-empty JSON array.")
    fixed_cases = tuple(
        _validate_integer_list(case, allow_empty=allow_empty, label=f"fixed_cases[{index}]")
        for index, case in enumerate(raw_fixed)
    )

    raw_proposals = root.get("proposal_fixtures", [])
    if type(raw_proposals) is not list:
        raise ProblemValidationError("proposal_fixtures must be a JSON array.")
    proposals: list[dict[str, Any]] = []
    for index, proposal in enumerate(raw_proposals):
        item = _require_keys(proposal, {"input", "rationale"}, set(), f"proposal_fixtures[{index}]")
        proposals.append(
            {
                "input": _validate_integer_list(
                    item["input"], allow_empty=allow_empty, label=f"proposal_fixtures[{index}].input"
                ),
                "rationale": _nonempty_text(item["rationale"], f"proposal_fixtures[{index}].rationale"),
            }
        )

    raw_suggestions = root["plan_suggestions"]
    if type(raw_suggestions) is not list or any(type(item) is not str or not item.strip() for item in raw_suggestions):
        raise ProblemValidationError("plan_suggestions must be an array of non-empty strings.")
    suggestions = tuple(item.strip() for item in raw_suggestions)

    raw_hypothesis = _require_keys(
        root["hypothesis"],
        {"seed", "max_examples", "min_size", "max_size", "min_value", "max_value"},
        set(),
        "hypothesis",
    )
    hypothesis: dict[str, int] = {}
    for key, value in raw_hypothesis.items():
        if type(value) is not int:
            raise ProblemValidationError(f"hypothesis.{key} must be an integer.")
        hypothesis[key] = value
    if hypothesis["seed"] < 0:
        raise ProblemValidationError("hypothesis.seed must be non-negative.")
    if not 1 <= hypothesis["max_examples"] <= 500:
        raise ProblemValidationError("hypothesis.max_examples must be between 1 and 500.")
    if not 0 <= hypothesis["min_size"] <= hypothesis["max_size"] <= 100:
        raise ProblemValidationError("Hypothesis list sizes must satisfy 0 <= min_size <= max_size <= 100.")
    if hypothesis["min_value"] > hypothesis["max_value"]:
        raise ProblemValidationError("hypothesis.min_value cannot exceed max_value.")
    if not allow_empty and hypothesis["min_size"] < 1:
        raise ProblemValidationError("A non-empty-list contract needs hypothesis.min_size >= 1.")

    raw_budget = _require_keys(
        root["budget"],
        {"max_rounds", "max_wall_time_seconds", "max_model_calls", "max_tokens", "max_cost_usd"},
        set(),
        "budget",
    )
    try:
        budget = BudgetConfig(**raw_budget)
    except (TypeError, ValueError) as error:
        raise ProblemValidationError(f"Invalid budget configuration: {error}") from error
    if budget.max_rounds < 1 or budget.max_wall_time_seconds <= 0:
        raise ProblemValidationError("The local evaluation needs at least one round and positive wall time.")

    raw_pricing = root.get("pricing")
    pricing_config = None
    if raw_pricing is not None:
        pricing = _require_keys(
            raw_pricing,
            {
                "provider_id", "model_id", "input_usd_per_million_tokens",
                "output_usd_per_million_tokens", "source_url", "checked_at",
            },
            set(),
            "pricing",
        )
        try:
            pricing_config = PricingConfig(
                provider_id=_nonempty_text(pricing["provider_id"], "pricing.provider_id"),
                model_id=_nonempty_text(pricing["model_id"], "pricing.model_id"),
                input_usd_per_million_tokens=pricing["input_usd_per_million_tokens"],
                output_usd_per_million_tokens=pricing["output_usd_per_million_tokens"],
                source_url=_nonempty_text(pricing["source_url"], "pricing.source_url"),
                checked_at=_nonempty_text(pricing["checked_at"], "pricing.checked_at"),
            )
        except (TypeError, ValueError) as error:
            raise ProblemValidationError(f"Invalid pricing configuration: {error}") from error

    revision_fixture = root.get("revision_proposal_fixture")
    revision_proposal = None
    if revision_fixture is not None:
        item = _require_keys(
            revision_fixture,
            {"revised_claim", "revision_reason", "revision_relation"},
            set(),
            "revision_proposal_fixture",
        )
        relation = _nonempty_text(item["revision_relation"], "revision_proposal_fixture.revision_relation")
        if relation not in {"clarifies", "narrows", "changes_meaning"}:
            raise ProblemValidationError("revision_proposal_fixture.revision_relation is unsupported.")
        revision_proposal = {
            "revised_claim": _nonempty_text(item["revised_claim"], "revision_proposal_fixture.revised_claim"),
            "revision_reason": _nonempty_text(item["revision_reason"], "revision_proposal_fixture.revision_reason"),
            "revision_relation": relation,
        }

    canonical_payload = json.dumps(root, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    dataset_payload = json.dumps(
        {
            "dataset_version": dataset_version,
            "fixed_cases": fixed_cases,
            "proposal_fixtures": proposals,
            "hypothesis": hypothesis,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return ProblemSpec(
        problem_id=problem_id,
        dataset_version=dataset_version,
        dataset_sha256=hashlib.sha256(dataset_payload).hexdigest(),
        problem_spec_sha256=hashlib.sha256(canonical_payload).hexdigest(),
        claim=claim,
        target_id=target_id,
        contract_id=contract_id,
        oracle_id=oracle_id,
        allow_empty=allow_empty,
        fixed_cases=fixed_cases,
        proposals=tuple(proposals),
        suggestions=suggestions,
        hypothesis=hypothesis,
        budget_config=budget,
        revision_proposal=revision_proposal,
        pricing_config=pricing_config,
    )


def load_problem(path: str | Path) -> ProblemSpec:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProblemValidationError(f"Cannot load problem file {source}: {error}") from error
    return parse_problem(payload)


def generate_hypothesis_cases(spec: ProblemSpec) -> tuple[list[list[int]], str | None]:
    """Generate bounded, repeatable integer-list examples from validated limits."""
    config = spec.hypothesis
    cases: list[list[int]] = []

    @seed(config["seed"])
    @given(
        st.lists(
            st.integers(min_value=config["min_value"], max_value=config["max_value"]),
            min_size=config["min_size"],
            max_size=config["max_size"],
        )
    )
    @settings(
        max_examples=config["max_examples"],
        deadline=None,
        database=None,
        suppress_health_check=(HealthCheck.too_slow,),
    )
    def collect(value: list[int]) -> None:
        cases.append(value)

    try:
        collect()
    except Exception as error:
        return cases, f"{type(error).__name__}: {error}"
    return cases, None


def collect_offline_proposals(spec: ProblemSpec) -> list[dict[str, Any]]:
    """Return inert proposal fixtures; this pilot never calls a model provider."""
    return list(spec.proposals)


def _evidence_for_case(
    *, spec: ProblemSpec, method: str, test_id: str, value: list[int]
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = TARGETS[spec.target_id]
    oracle = ORACLES[spec.oracle_id]
    detail: dict[str, Any] = {
        "test_id": test_id,
        "method": method,
        "input": value,
        "replay_attempted": False,
        "replay_confirmed": None,
    }
    try:
        actual = target(value.copy())
    except Exception as error:
        category = f"target_exception:{type(error).__name__}"
        return (
            {
                "test_id": test_id,
                "method": method,
                "contract_id": spec.contract_id,
                "status": "internal_error",
                "failure_category": category,
            },
            {**detail, "status": "INTERNAL_ERROR", "error": str(error), "failure_category": category},
        )
    try:
        expected = oracle(value.copy())
    except Exception as error:
        category = f"oracle_exception:{type(error).__name__}"
        return (
            {
                "test_id": test_id,
                "method": method,
                "contract_id": spec.contract_id,
                "status": "internal_error",
                "failure_category": category,
            },
            {**detail, "status": "INTERNAL_ERROR", "actual": actual, "error": str(error), "failure_category": category},
        )

    mismatch = actual != expected
    replay_confirmed = False
    if mismatch:
        detail["replay_attempted"] = True
        try:
            replay_actual = target(value.copy())
            replay_expected = oracle(value.copy())
            replay_confirmed = replay_actual == actual and replay_expected == expected and replay_actual != replay_expected
            detail["replay_actual"] = replay_actual
            detail["replay_expected"] = replay_expected
        except Exception:
            replay_confirmed = False
            detail["replay_error"] = "Replay target or oracle raised an exception."

    category = "PROPERTY_VIOLATION" if mismatch else "CASE_PASSED"
    evidence = {
        "test_id": test_id,
        "method": method,
        "contract_id": spec.contract_id,
        "status": "completed",
        "contract_valid": True,
        "oracle_id": spec.oracle_id,
        "input": value,
        "actual": actual,
        "expected": expected,
        "replay_confirmed": replay_confirmed if mismatch else None,
            "replay_attempted": mismatch,
            "replay_actual": detail.get("replay_actual"),
            "replay_expected": detail.get("replay_expected"),
        "category": category,
    }
    detail.update(
        {
            "status": category,
            "actual": actual,
            "expected": expected,
            "replay_confirmed": replay_confirmed if mismatch else None,
        }
    )
    return evidence, detail


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
        PROJECT_ROOT / "practice" / "run_records.py",
        PROJECT_ROOT / "practice" / "decision.py",
        PROJECT_ROOT / "practice" / "outcomes.py",
        PROJECT_ROOT / "practice" / "budgets.py",
        PROJECT_ROOT / "practice" / "revisions.py",
    ):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _append_error(errors: list[dict[str, str]], step: str, message: str) -> str:
    error_id = f"error-{len(errors) + 1}"
    errors.append({"error_id": error_id, "step": step, "error": message})
    return error_id


def _methods_for(spec: ProblemSpec) -> list[str]:
    methods = ["fixed", "hypothesis"]
    if spec.proposals:
        methods.append("proposals")
    return methods


def _scheduled_count(spec: ProblemSpec) -> int:
    return len(spec.fixed_cases) + spec.hypothesis["max_examples"] + len(spec.proposals)


def _default_run_path(
    problem_id: str,
    run_id: str,
    started_at: datetime,
    runs_dir: str | Path = RUNS_DIR,
) -> Path:
    timestamp = started_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    safe_problem_id = sanitize_for_log(problem_id)
    return Path(runs_dir) / f"{safe_problem_id}_{timestamp}_{run_id}.json"


def _model_proposal_records(spec: ProblemSpec, *, evaluated: bool) -> list[dict[str, Any]]:
    return [
        {
            "proposal_id": f"proposal-{index}",
            "source": "offline_model_proposal_fixture",
            "input": item["input"],
            "rationale": item["rationale"],
            "validated": True,
            "evaluation_status": "evaluated" if evaluated else "not_evaluated",
        }
        for index, item in enumerate(spec.proposals, start=1)
    ]


def run_problem(
    spec: ProblemSpec,
    log_path: str | Path | None = None,
    *,
    runs_dir: str | Path = RUNS_DIR,
) -> dict[str, Any]:
    """Run fixed, Hypothesis, and proposal evidence and always save the run log."""
    started_at = datetime.now(timezone.utc)
    started_clock = time.perf_counter()
    run_id = str(uuid4())
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

    proposal_step: dict[str, Any] = {
        "status": "not_configured" if not spec.proposals else "offline_fixtures",
        "provider_api_called": False,
        "count": 0,
    }
    proposals_started_clock = time.perf_counter()
    proposal_stage_status = "not_configured" if not spec.proposals else "completed"
    if spec.proposals:
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
    proposals_duration_seconds = (
        round(time.perf_counter() - proposals_started_clock, 6)
        if spec.proposals else None
    )

    outcome = decide(evidence, contract)
    revision = _revision_log(spec, outcome)
    if revision["status"] == "error":
        _append_error(errors, "optional_revision", revision["error"])

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
            "prompt_template_versions": {
                "plan_suggestions": "offline-suggestions-v1",
                "proposal_fixtures": "offline-proposals-v1",
                "claim_revision": "claim-revision-v1",
            },
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
    destination = (
        Path(log_path)
        if log_path is not None
        else _default_run_path(spec.problem_id, run_id, started_at, runs_dir)
    )
    record_schema = sanitize_run_record_for_log(record_schema)
    save_run_record(destination, record_schema)
    run_record = record_schema
    run_record["log_path"] = str(destination)
    return run_record


def _emergency_error_record(
    spec: ProblemSpec,
    error: Exception,
    *,
    started_at: datetime,
    duration_seconds: float,
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
    return {
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
            "prompt_template_versions": {
                "plan_suggestions": "offline-suggestions-v1",
                "proposal_fixtures": "offline-proposals-v1",
                "claim_revision": "claim-revision-v1",
            },
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
            "failure_category": type(error).__name__,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m abacus")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run one JSON problem through the local evidence pipeline")
    run_parser.add_argument("problem", help="path to a validated problem JSON file")
    run_parser.add_argument(
        "--output",
        help="exact run-log path (default: unique timestamp+UUID under runs/); existing files are never overwritten",
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
        print(render_run_summary(record, record_path=record_path))
        return 1 if "incomplete_marker" in record else 0
    if args.command == "summarize-runs":
        entries = list_run_records(args.runs_dir, problem_id=args.problem_id)
        records = [load_run_record(item["path"]) for item in entries["runs"]]
        summary = summarize_run_usage(records)
        summary["problem_id"] = args.problem_id
        summary["incomplete_run_count"] = len(entries["incomplete"])
        summary["invalid_file_count"] = len(entries["invalid_files"])
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    try:
        spec = load_problem(args.problem)
    except ProblemValidationError as error:
        print(f"Problem validation failed: {error}", file=sys.stderr)
        return 2

    requested_log_path = Path(args.output) if args.output else None
    pipeline_started_at = datetime.now(timezone.utc)
    pipeline_started_clock = time.perf_counter()
    try:
        record = run_problem(spec, requested_log_path)
    except Exception as error:
        failure = _emergency_error_record(
            spec,
            error,
            started_at=pipeline_started_at,
            duration_seconds=round(time.perf_counter() - pipeline_started_clock, 6),
        )
        failure = sanitize_run_record_for_log(failure)
        log_path = requested_log_path
        if log_path is None or log_path.exists():
            log_path = _default_run_path(
                spec.problem_id,
                failure["run_id"],
                pipeline_started_at,
            )
        save_run_record(log_path, failure)
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
