"""Model-proposed test inputs, checked only by the trusted Abacus harness."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .contracts import InputStatus, validate_input
from .failure_categories import FailureCategory
from .harness import CaseEvidence, HarnessStatus, check_case
from .llm import LLMResult, ask
from .problems import load_problem, validate_problem
from .errors import LLMError


logger = logging.getLogger(__name__)
MAX_PROPOSALS = 5
MAX_RATIONALE_LENGTH = 500

SYSTEM_PROMPT = (
    "You propose candidate test inputs only. Do not judge whether the claim is true, "
    "do not give a pass/fail label or verdict, and do not write or execute code. "
    "Return exactly the requested JSON object."
)


class ProposalFormatError(ValueError):
    """The model response is malformed or does not match the proposal schema."""


class ProposalStatus(str, Enum):
    CHECKED = "CHECKED"
    REJECTED_OUT_OF_CONTRACT = "REJECTED_OUT_OF_CONTRACT"


@dataclass(frozen=True)
class ProposedInput:
    input_value: Any
    rationale: str


@dataclass(frozen=True)
class IdeaEvidence:
    input_value: Any
    rationale: str
    source: str
    status: ProposalStatus
    contract_status: InputStatus
    contract_reason: str | None
    harness_evidence: CaseEvidence | None
    failure_category: FailureCategory | None = None

    def as_dict(self) -> dict[str, Any]:
        evidence = self.harness_evidence
        return {
            "source": self.source,
            "input": self.input_value,
            "rationale": self.rationale,
            "status": self.status.value,
            "contract_status": self.contract_status.value,
            "contract_reason": self.contract_reason,
            "harness_status": evidence.status.value if evidence else None,
            "failure_category": (
                self.failure_category.value if self.failure_category else None
            ),
            "harness_explanation": evidence.explanation if evidence else None,
            "target_result": evidence.target_result if evidence else None,
            "oracle_status": (
                evidence.oracle_result.status.value
                if evidence and evidence.oracle_result
                else None
            ),
        }


@dataclass(frozen=True)
class ProposalBatch:
    problem_id: str
    ideas: tuple[IdeaEvidence, ...] = ()
    parse_error: str | None = None
    request_error: str | None = None
    provider: str | None = None
    model: str | None = None
    usage: dict[str, int] | None = None
    failure_category: FailureCategory | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "source": "model_proposed",
            "provider": self.provider,
            "model": self.model,
            "usage": self.usage,
            "parse_error": self.parse_error,
            "request_error": self.request_error,
            "failure_category": (
                self.failure_category.value if self.failure_category else None
            ),
            "candidate_inputs": [idea.as_dict() for idea in self.ideas],
        }


def _resolve_problem(problem: Any) -> dict[str, Any]:
    if isinstance(problem, (str, Path)):
        return load_problem(problem)
    if isinstance(problem, Mapping):
        record = dict(problem)
    else:
        record = problem
    validate_problem(record)
    return record


def build_test_idea_prompt(problem: Any) -> tuple[str, str]:
    """Build a prompt that asks only for candidate inputs and rationales."""

    record = _resolve_problem(problem)
    context = {
        "claim": record["claim"],
        "code": record["code"],
        "domain": record["domain"],
        "preconditions": record["preconditions"],
    }
    user_prompt = (
        "Suggest up to five concrete input values that might expose a problem in "
        "the candidate. Follow the stated domain and preconditions when possible. "
        "Return exactly this JSON shape, with no Markdown fences or extra fields:\n"
        '{"candidate_inputs":[{"input":<JSON value>,"rationale":"short reason"}]}\n'
        "Do not include a truth judgment, label, verdict, expected answer, or code. "
        "The trusted checker will validate each input and decide its outcome.\n\n"
        "Problem context:\n"
        f"{json.dumps(context, ensure_ascii=True, indent=2)}"
    )
    return SYSTEM_PROMPT, user_prompt


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProposalFormatError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> None:
    raise ProposalFormatError(f"invalid JSON constant: {value}")


def parse_proposal_response(
    response_text: str,
    *,
    ignore_labels: bool = False,
) -> tuple[ProposedInput, ...]:
    """Parse the exact JSON schema; never extract JSON with a brace regex."""

    if not isinstance(response_text, str) or not response_text.strip():
        raise ProposalFormatError("response must be non-empty JSON text")
    try:
        data = json.loads(
            response_text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_json_constant,
        )
    except ProposalFormatError:
        raise
    except json.JSONDecodeError as error:
        raise ProposalFormatError(
            f"invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}"
        ) from None

    if ignore_labels and isinstance(data, dict):
        labels = {"verdict", "label"} & set(data)
        if labels:
            logger.warning(
                "Ignoring model-supplied label fields: %s",
                ", ".join(sorted(labels)),
            )
            data = {key: value for key, value in data.items() if key not in labels}

    if not isinstance(data, dict) or set(data) != {"candidate_inputs"}:
        raise ProposalFormatError(
            "response must contain only the 'candidate_inputs' field"
        )
    candidates = data["candidate_inputs"]
    if not isinstance(candidates, list):
        raise ProposalFormatError("candidate_inputs must be a JSON array")
    if len(candidates) > MAX_PROPOSALS:
        raise ProposalFormatError(f"candidate_inputs may contain at most {MAX_PROPOSALS} items")

    parsed: list[ProposedInput] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or set(candidate) != {"input", "rationale"}:
            raise ProposalFormatError(
                f"candidate_inputs[{index}] must contain exactly input and rationale"
            )
        rationale = candidate["rationale"]
        if (
            not isinstance(rationale, str)
            or not rationale.strip()
            or len(rationale) > MAX_RATIONALE_LENGTH
        ):
            raise ProposalFormatError(
                f"candidate_inputs[{index}].rationale must be a non-empty string "
                f"of at most {MAX_RATIONALE_LENGTH} characters"
            )
        parsed.append(ProposedInput(candidate["input"], rationale.strip()))
    return tuple(parsed)


def evaluate_proposal_response(
    problem: Any,
    response_text: str,
    *,
    ignore_labels: bool = False,
) -> ProposalBatch:
    """Validate each suggested input before running the trusted harness."""

    record = _resolve_problem(problem)
    try:
        proposals = parse_proposal_response(
            response_text,
            ignore_labels=ignore_labels,
        )
    except ProposalFormatError as error:
        logger.warning("Rejected malformed model proposal for %s: %s", record["id"], error)
        return ProposalBatch(
            problem_id=record["id"],
            parse_error=str(error),
            failure_category=FailureCategory.PARSE_ERROR,
        )

    ideas: list[IdeaEvidence] = []
    for proposal in proposals:
        validation = validate_input(record, proposal.input_value)
        if validation.status is InputStatus.OUTSIDE_CONTRACT:
            logger.warning(
                "Rejected model-proposed input for %s as OUT_OF_CONTRACT: %s",
                record["id"],
                validation.reason,
            )
            ideas.append(
                IdeaEvidence(
                    input_value=proposal.input_value,
                    rationale=proposal.rationale,
                    source="model_proposed",
                    status=ProposalStatus.REJECTED_OUT_OF_CONTRACT,
                    contract_status=validation.status,
                    contract_reason=validation.reason,
                    harness_evidence=None,
                    failure_category=FailureCategory.OUT_OF_CONTRACT,
                )
            )
            continue

        evidence = check_case(record, proposal.input_value)
        logger.info(
            "Checked model-proposed input for %s: harness=%s",
            record["id"],
            evidence.status.value,
        )
        ideas.append(
            IdeaEvidence(
                input_value=proposal.input_value,
                rationale=proposal.rationale,
                source="model_proposed",
                status=ProposalStatus.CHECKED,
                contract_status=validation.status,
                contract_reason=validation.reason,
                harness_evidence=evidence,
                failure_category=evidence.failure_category,
            )
        )
    return ProposalBatch(problem_id=record["id"], ideas=tuple(ideas))


def request_test_ideas(
    problem: Any,
    *,
    max_tokens: int = 512,
    settings: Any | None = None,
    ask_function: Callable[..., LLMResult] | None = None,
) -> ProposalBatch:
    """Request candidate inputs and pass them to the trusted harness pipeline."""

    record = _resolve_problem(problem)
    system, prompt = build_test_idea_prompt(record)
    request = ask_function or ask
    request_kwargs: dict[str, Any] = {}
    if settings is not None:
        request_kwargs["settings"] = settings
    try:
        result = request(
            prompt,
            system=system,
            max_tokens=max_tokens,
            **request_kwargs,
        )
    except LLMError as error:
        logger.warning("Model test-idea request failed for %s: %s", record["id"], error)
        return ProposalBatch(
            problem_id=record["id"],
            request_error=f"{error.category}: {error}",
            failure_category=FailureCategory.API_ERROR,
        )

    batch = evaluate_proposal_response(record, result.text)
    return ProposalBatch(
        problem_id=batch.problem_id,
        ideas=batch.ideas,
        parse_error=batch.parse_error,
        provider=result.provider,
        model=result.model,
        usage=result.usage,
        failure_category=batch.failure_category,
    )
