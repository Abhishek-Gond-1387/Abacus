"""Run a validated JSON problem through Abacus's local evidence pipeline."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from hypothesis import HealthCheck, given, seed, settings, strategies as st

from practice.budgets import BudgetConfig, BudgetTracker
from practice.decision import ClaimContract, decide
from practice.outcomes import FinalOutcome
from practice.revisions import ClaimRevision, RevisionTriggerEvidence


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProblemValidationError(ValueError):
    """A problem file is malformed or asks for an unsupported operation."""


@dataclass(frozen=True)
class ProblemSpec:
    problem_id: str
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
        {"schema_version", "problem_id", "claim", "target", "contract", "plan_suggestions", "fixed_cases", "hypothesis", "budget"},
        {"proposal_fixtures", "revision_proposal_fixture"},
        "problem",
    )
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise ProblemValidationError("schema_version must be the integer 1.")
    problem_id = _nonempty_text(root["problem_id"], "problem_id")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", problem_id):
        raise ProblemValidationError("problem_id may contain lowercase letters, digits, _ and - only.")
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

    return ProblemSpec(
        problem_id=problem_id,
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
    detail: dict[str, Any] = {"test_id": test_id, "method": method, "input": value}
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
        try:
            replay_actual = target(value.copy())
            replay_expected = oracle(value.copy())
            replay_confirmed = replay_actual == actual and replay_expected == expected and replay_actual != replay_expected
        except Exception:
            replay_confirmed = False

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


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_problem(spec: ProblemSpec, log_path: str | Path) -> dict[str, Any]:
    """Run fixed, Hypothesis, and proposal evidence and always save the run log."""
    tracker = BudgetTracker(spec.budget_config)
    if not tracker.start_round():
        raise RuntimeError("Could not start the local evaluation round.")

    methods = ["fixed", "hypothesis"]
    if spec.proposals:
        methods.append("proposals")
    scheduled_count = len(spec.fixed_cases) + spec.hypothesis["max_examples"] + len(spec.proposals)
    contract = ClaimContract(
        contract_id=spec.contract_id,
        oracle_id=spec.oracle_id,
        scheduled_test_count=scheduled_count,
        required_methods=tuple(methods),
    )
    evidence: list[dict[str, Any]] = []
    case_log: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for index, value in enumerate(spec.fixed_cases, start=1):
        record, detail = _evidence_for_case(
            spec=spec, method="fixed", test_id=f"fixed-{index}", value=value
        )
        evidence.append(record)
        case_log.append(detail)

    hypothesis_cases, generation_error = generate_hypothesis_cases(spec)
    if generation_error:
        errors.append({"step": "hypothesis_generation", "error": generation_error})
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
            record, detail = _evidence_for_case(
                spec=spec, method="hypothesis", test_id=f"hypothesis-{index}", value=value
            )
            evidence.append(record)
            case_log.append(detail)

    proposal_step: dict[str, Any] = {
        "status": "not_configured" if not spec.proposals else "offline_fixtures",
        "provider_api_called": False,
        "count": 0,
    }
    if spec.proposals:
        try:
            proposals = collect_offline_proposals(spec)
            proposal_step["count"] = len(proposals)
            for index, proposal in enumerate(proposals, start=1):
                value = proposal["input"]
                record, detail = _evidence_for_case(
                    spec=spec, method="proposals", test_id=f"proposal-{index}", value=value
                )
                evidence.append(record)
                detail["proposal_source"] = "offline_model_proposal_fixture"
                detail["rationale"] = proposal["rationale"]
                case_log.append(detail)
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            errors.append({"step": "optional_proposal_generation", "error": message})
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

    outcome = decide(evidence, contract)
    revision = _revision_log(spec, outcome)
    if revision["status"] == "error":
        errors.append({"step": "optional_revision", "error": revision["error"]})

    tracker.finish_round()
    completed_count = sum(record.get("status") == "completed" for record in evidence)
    budget = tracker.to_dict(evidence_complete=outcome.outcome is not FinalOutcome.UNRESOLVED)
    budget["usage"]["evaluated_cases"] = completed_count

    run_record = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "problem_id": spec.problem_id,
        "claim": spec.claim,
        "target_id": spec.target_id,
        "contract": {
            "id": spec.contract_id,
            "oracle_id": spec.oracle_id,
            "input_type": "integer_list",
            "allow_empty": spec.allow_empty,
        },
        "plan_suggestions": [
            {"text": text, "source": "offline_model_suggestion_fixture", "applied_as_fact": False}
            for text in spec.suggestions
        ],
        "proposal_step": proposal_step,
        "hypothesis": {**spec.hypothesis, "generated_count": len(hypothesis_cases), "generation_error": generation_error},
        "scheduled_test_count": scheduled_count,
        "evidence": evidence,
        "cases": case_log,
        "run_outcome": outcome.to_dict(),
        "revision": revision,
        "budget": budget,
        "errors": errors,
    }
    destination = Path(log_path)
    _write_json_atomic(destination, run_record)
    run_record["log_path"] = str(destination)
    return run_record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m abacus")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run one JSON problem through the local evidence pipeline")
    run_parser.add_argument("problem", help="path to a validated problem JSON file")
    run_parser.add_argument("--output", help="run log path (default: runs/<problem_id>.json)")
    args = parser.parse_args(argv)

    try:
        spec = load_problem(args.problem)
    except ProblemValidationError as error:
        print(f"Problem validation failed: {error}", file=sys.stderr)
        return 2

    default_log = PROJECT_ROOT / "runs" / f"{spec.problem_id}.json"
    log_path = Path(args.output) if args.output else default_log
    try:
        record = run_problem(spec, log_path)
    except Exception as error:
        # A last-resort log preserves the loadable problem and failure if a stage escapes handling.
        failure = {
            "schema_version": 1,
            "problem_id": spec.problem_id,
            "claim": spec.claim,
            "run_outcome": {
                "outcome": "ERROR",
                "reason": "internal_error",
                "message": "An unexpected pipeline failure prevented a complete run.",
                "failure_category": f"{type(error).__name__}: {error}",
            },
            "errors": [{"step": "pipeline", "error": f"{type(error).__name__}: {error}"}],
            "budget": {"budget_configured": spec.budget_config.to_dict(), "usage": {"model_calls": 0}, "provider_api_called": False},
        }
        _write_json_atomic(log_path, failure)
        print(json.dumps(failure, indent=2, ensure_ascii=False))
        print(f"Saved error log: {log_path}", file=sys.stderr)
        return 1

    print(json.dumps({
        "problem_id": record["problem_id"],
        "outcome": record["run_outcome"]["outcome"],
        "reason": record["run_outcome"]["reason"],
        "test_count": record["run_outcome"]["test_count"],
        "counterexample": record["run_outcome"]["counterexample"],
        "log_path": record["log_path"],
        "provider_api_called": record["proposal_step"]["provider_api_called"],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
