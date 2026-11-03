"""Provider boundary and offline fixtures. Provider responses are untrusted data; no API client is configured."""

from __future__ import annotations

from typing import Any, Protocol

from .schemas import ProblemSpec


class LLMNotConfiguredError(RuntimeError):
    """Raised when code requests a hosted provider that this pilot has not configured."""


class LLMClient(Protocol):
    """Narrow provider interface; callers must validate text with `schemas.parse_model_output`."""

    def complete(self, prompt: str, *, model_id: str) -> str:
        """Return an untrusted provider response as text."""
        ...


def create_llm_client() -> LLMClient:
    """No hosted provider adapter is registered; this function performs no network access."""
    raise LLMNotConfiguredError("No hosted LLM provider is configured.")


def collect_offline_proposals(spec: ProblemSpec) -> list[dict[str, Any]]:
    """Return inert proposal fixtures; this pilot never calls a model provider."""
    return list(spec.proposals)


def model_proposal_records(spec: ProblemSpec, *, evaluated: bool) -> list[dict[str, Any]]:
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
