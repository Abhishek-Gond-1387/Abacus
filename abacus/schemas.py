"""Strict schemas for untrusted problem JSON and model responses; none is executable code."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from practice.budgets import BudgetConfig
from practice.usage_metrics import PricingConfig

from .targets import ORACLES, TARGETS


MAX_MODEL_OUTPUT_BYTES = 16 * 1024
MAX_MODEL_TEXT_CHARS = 1_000
MAX_PLAN_SUGGESTIONS = 20
MAX_CANDIDATE_PROPOSALS = 20
MAX_PROPOSAL_INPUT_ITEMS = 100
MAX_PROPOSAL_INTEGER = (2**63) - 1
ModelOutputKind = Literal["hypothesis", "plan", "candidate_proposals"]


class ModelOutputError(ValueError):
    """A model response was refused or failed strict parsing/validation."""

    category = "model_output_error"


class ModelOutputRefusalError(ModelOutputError):
    category = "refusal"


class ModelOutputEmptyError(ModelOutputError):
    category = "empty_response"


class ModelOutputTooLargeError(ModelOutputError):
    category = "oversized_response"


class ModelOutputTruncatedError(ModelOutputError):
    category = "truncated_response"


class ModelOutputParseError(ModelOutputError):
    category = "invalid_json"


class ModelOutputExtraTextError(ModelOutputError):
    category = "extra_text"


class ModelOutputSchemaError(ModelOutputError):
    category = "wrong_type_or_missing_field"


class ModelOutputUnknownFieldsError(ModelOutputSchemaError):
    category = "unknown_fields"


@dataclass(frozen=True)
class HypothesisOutput:
    hypothesis: str
    rationale: str


@dataclass(frozen=True)
class PlanOutput:
    suggestions: tuple[str, ...]


@dataclass(frozen=True)
class CandidateInputProposal:
    input: tuple[int, ...]
    rationale: str


@dataclass(frozen=True)
class CandidateProposalsOutput:
    proposals: tuple[CandidateInputProposal, ...]


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant {value}.")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key.")
        result[key] = value
    return result


def _unwrap_json_fence(value: str) -> str:
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if len(lines) < 3 or lines[-1].strip() != "```":
        raise ModelOutputExtraTextError("A fenced JSON response must end with its closing fence.")
    language = lines[0][3:].strip().lower()
    if language not in {"", "json"}:
        raise ModelOutputParseError("Only plain JSON or a ```json code fence is accepted.")
    return "\n".join(lines[1:-1]).strip()


def _is_truncated_json(value: str, error: json.JSONDecodeError) -> bool:
    if error.msg.startswith("Unterminated string"):
        return True
    if not value.startswith(("{", "[")):
        return False
    if error.pos < max(0, len(value) - 1):
        return False
    stack: list[str] = []
    in_string = False
    escaped = False
    matching = {"}": "{", "]": "["}
    for character in value:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "{[":
            stack.append(character)
        elif character in "}]":
            if not stack or stack.pop() != matching[character]:
                return False
    return bool(stack) or in_string


def _json_after_prefix(value: str) -> bool:
    """Classify a valid JSON value after prose as extra text without accepting it."""
    positions = [position for mark in ("{", "[") if (position := value.find(mark)) > 0]
    if not positions:
        return False
    decoder = json.JSONDecoder(
        object_pairs_hook=_strict_object,
        parse_constant=_reject_nonstandard_json_constant,
    )
    try:
        decoder.raw_decode(value, min(positions))
    except (json.JSONDecodeError, ValueError, RecursionError):
        return False
    return True


def _decode_model_json(response_text: Any, *, refused: bool) -> Any:
    if refused:
        raise ModelOutputRefusalError("The provider marked this response as a refusal.")
    if type(response_text) is not str:
        raise ModelOutputSchemaError("Provider response must be text.")
    if not response_text.strip():
        raise ModelOutputEmptyError("Provider response was empty.")
    try:
        response_bytes = response_text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ModelOutputParseError("Provider response is not valid UTF-8 text.") from error
    if len(response_bytes) > MAX_MODEL_OUTPUT_BYTES:
        raise ModelOutputTooLargeError(
            f"Provider response exceeds the {MAX_MODEL_OUTPUT_BYTES}-byte limit."
        )

    value = _unwrap_json_fence(response_text.strip())
    if not value:
        raise ModelOutputEmptyError("Provider response contained no JSON content.")
    decoder = json.JSONDecoder(
        object_pairs_hook=_strict_object,
        parse_constant=_reject_nonstandard_json_constant,
    )
    try:
        parsed, end = decoder.raw_decode(value)
    except json.JSONDecodeError as error:
        if _is_truncated_json(value, error):
            raise ModelOutputTruncatedError("Provider response ended before the JSON value was complete.") from error
        if _json_after_prefix(value):
            raise ModelOutputExtraTextError("Provider response has text before its JSON value.") from error
        raise ModelOutputParseError("Provider response is not valid JSON.") from error
    except RecursionError as error:
        raise ModelOutputParseError("Provider response exceeds the JSON parser nesting limit.") from error
    except ValueError as error:
        raise ModelOutputParseError("Provider response contains non-standard or duplicate JSON values.") from error

    if value[end:].strip():
        raise ModelOutputExtraTextError("Provider response has text after its JSON value.")
    if type(parsed) is dict and set(parsed) == {"refusal"}:
        refusal = parsed["refusal"]
        if type(refusal) is str and refusal.strip():
            raise ModelOutputRefusalError("The provider returned a refusal response.")
    return parsed


def _require_object_fields(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ModelOutputSchemaError(f"{label} must be a JSON object.")
    unknown = value.keys() - expected
    missing = expected - value.keys()
    if unknown:
        raise ModelOutputUnknownFieldsError(f"{label} contains unknown fields.")
    if missing:
        raise ModelOutputSchemaError(f"{label} is missing required fields: {', '.join(sorted(missing))}.")
    return value


def _validated_text(value: Any, label: str) -> str:
    if type(value) is not str:
        raise ModelOutputSchemaError(f"{label} must be a string.")
    cleaned = value.strip()
    if not cleaned:
        raise ModelOutputSchemaError(f"{label} cannot be empty.")
    if len(cleaned) > MAX_MODEL_TEXT_CHARS:
        raise ModelOutputSchemaError(f"{label} exceeds the {MAX_MODEL_TEXT_CHARS}-character limit.")
    return cleaned


def parse_model_output(
    output_kind: ModelOutputKind,
    response_text: Any,
    *,
    refused: bool = False,
) -> HypothesisOutput | PlanOutput | CandidateProposalsOutput:
    """Parse bounded JSON text into a strict model-output schema; never retain raw text."""
    if output_kind not in {"hypothesis", "plan", "candidate_proposals"}:
        raise ValueError(f"Unsupported model output kind: {output_kind!r}.")
    value = _decode_model_json(response_text, refused=refused)

    if output_kind == "hypothesis":
        item = _require_object_fields(value, {"hypothesis", "rationale"}, "hypothesis")
        return HypothesisOutput(
            hypothesis=_validated_text(item["hypothesis"], "hypothesis.hypothesis"),
            rationale=_validated_text(item["rationale"], "hypothesis.rationale"),
        )

    if output_kind == "plan":
        item = _require_object_fields(value, {"suggestions"}, "plan")
        suggestions = item["suggestions"]
        if type(suggestions) is not list:
            raise ModelOutputSchemaError("plan.suggestions must be an array.")
        if len(suggestions) > MAX_PLAN_SUGGESTIONS:
            raise ModelOutputSchemaError(f"plan.suggestions exceeds the {MAX_PLAN_SUGGESTIONS}-item limit.")
        return PlanOutput(
            suggestions=tuple(
                _validated_text(text, f"plan.suggestions[{index}]")
                for index, text in enumerate(suggestions)
            )
        )

    item = _require_object_fields(value, {"proposals"}, "candidate_proposals")
    proposals = item["proposals"]
    if type(proposals) is not list:
        raise ModelOutputSchemaError("candidate_proposals.proposals must be an array.")
    if len(proposals) > MAX_CANDIDATE_PROPOSALS:
        raise ModelOutputSchemaError(
            f"candidate_proposals.proposals exceeds the {MAX_CANDIDATE_PROPOSALS}-item limit."
        )
    validated: list[CandidateInputProposal] = []
    for index, proposal in enumerate(proposals):
        label = f"candidate_proposals.proposals[{index}]"
        fields = _require_object_fields(proposal, {"input", "rationale"}, label)
        candidate_input = fields["input"]
        if type(candidate_input) is not list:
            raise ModelOutputSchemaError(f"{label}.input must be an array of integers.")
        if len(candidate_input) > MAX_PROPOSAL_INPUT_ITEMS:
            raise ModelOutputSchemaError(
                f"{label}.input exceeds the {MAX_PROPOSAL_INPUT_ITEMS}-item limit."
            )
        if any(type(number) is not int for number in candidate_input):
            raise ModelOutputSchemaError(f"{label}.input must contain integers (booleans excluded).")
        if any(abs(number) > MAX_PROPOSAL_INTEGER for number in candidate_input):
            raise ModelOutputSchemaError(f"{label}.input integers must fit in signed 64-bit range.")
        validated.append(
            CandidateInputProposal(
                input=tuple(candidate_input),
                rationale=_validated_text(fields["rationale"], f"{label}.rationale"),
            )
        )
    return CandidateProposalsOutput(proposals=tuple(validated))


def parse_hypothesis_output(response_text: Any, *, refused: bool = False) -> HypothesisOutput:
    return parse_model_output("hypothesis", response_text, refused=refused)  # type: ignore[return-value]


def parse_plan_output(response_text: Any, *, refused: bool = False) -> PlanOutput:
    return parse_model_output("plan", response_text, refused=refused)  # type: ignore[return-value]


def parse_candidate_proposals(response_text: Any, *, refused: bool = False) -> CandidateProposalsOutput:
    return parse_model_output("candidate_proposals", response_text, refused=refused)  # type: ignore[return-value]


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
