"""Validated problem schemas. JSON input is untrusted data and never executable code."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from practice.budgets import BudgetConfig
from practice.usage_metrics import PricingConfig

from .targets import ORACLES, TARGETS


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
