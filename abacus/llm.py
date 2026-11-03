"""Explicitly configured hosted-provider client and offline proposal fixtures."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Protocol

from .schemas import (
    MAX_MODEL_OUTPUT_BYTES,
    CandidateProposalsOutput,
    HypothesisOutput,
    ModelOutputKind,
    PlanOutput,
    ProblemSpec,
    parse_model_output,
)


DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_SECONDS = 120.0
MAX_OUTPUT_TOKENS = 1_024
MAX_PROMPT_BYTES = 32 * 1024
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class LLMNotConfiguredError(RuntimeError):
    """Raised when a hosted provider is requested without valid local configuration."""


class LLMProviderError(RuntimeError):
    """Safe provider failure; the SDK response body and prompt are never included."""

    category = "provider_error"


class LLMProviderAuthenticationError(LLMProviderError):
    category = "authentication_error"


class LLMProviderRateLimitError(LLMProviderError):
    category = "rate_or_quota_limit"


class LLMProviderConnectionError(LLMProviderError):
    category = "connection_error"


class LLMProviderRequestError(LLMProviderError):
    category = "request_error"


class LLMProviderResponseError(LLMProviderError):
    category = "invalid_provider_response"


class LLMProviderRefusalError(LLMProviderResponseError):
    category = "provider_refusal"


class LLMProviderResponseTooLargeError(LLMProviderResponseError):
    category = "oversized_response"


class LLMClient(Protocol):
    """Narrow provider interface; callers must validate text with `schemas.parse_model_output`."""

    def complete(self, prompt: str, *, model_id: str) -> str:
        """Return an untrusted provider response as text."""
        ...


def _validate_prompt(prompt: str) -> None:
    if type(prompt) is not str or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    try:
        prompt_size = len(prompt.encode("utf-8"))
    except UnicodeEncodeError:
        raise ValueError("prompt must be valid UTF-8 text") from None
    if prompt_size > MAX_PROMPT_BYTES:
        raise ValueError(f"prompt exceeds the {MAX_PROMPT_BYTES}-byte limit")


def _validate_model_id(model_id: str) -> None:
    if type(model_id) is not str or not model_id.strip():
        raise ValueError("model_id must be a non-empty string")


def complete_structured_output(
    client: LLMClient,
    output_kind: ModelOutputKind,
    prompt: str,
    *,
    model_id: str,
) -> HypothesisOutput | PlanOutput | CandidateProposalsOutput:
    """Call a provider and return only a strictly parsed, bounded response record."""
    if output_kind not in {"hypothesis", "plan", "candidate_proposals"}:
        raise ValueError("output_kind must be a supported structured model output.")
    _validate_prompt(prompt)
    _validate_model_id(model_id)
    response_text = client.complete(prompt, model_id=model_id)
    return parse_model_output(output_kind, response_text)


class OpenAICompatibleLLMClient:
    """A bounded Gemini/OpenAI chat client. Construction is local; `complete` sends a request."""

    def __init__(self, provider: str, client: Any) -> None:
        self._provider = provider
        self._client = client

    def complete(self, prompt: str, *, model_id: str) -> str:
        _validate_prompt(prompt)
        _validate_model_id(model_id)

        try:
            from openai import (
                APIConnectionError,
                APIError,
                APIStatusError,
                AuthenticationError,
                BadRequestError,
                RateLimitError,
            )
        except ImportError:
            raise LLMNotConfiguredError(
                "The OpenAI-compatible SDK is missing. Install the runtime requirements first."
            ) from None

        request: dict[str, Any] = {
            "model": model_id.strip(),
            "messages": [{"role": "user", "content": prompt}],
        }
        if self._provider == "gemini":
            request["max_tokens"] = MAX_OUTPUT_TOKENS
        else:
            request["max_completion_tokens"] = MAX_OUTPUT_TOKENS

        try:
            response = self._client.chat.completions.create(**request)
        except AuthenticationError:
            raise LLMProviderAuthenticationError(
                "Provider authentication failed. Check the configured API key."
            ) from None
        except RateLimitError:
            raise LLMProviderRateLimitError(
                "Provider quota or request rate limit was reached."
            ) from None
        except APIConnectionError:
            raise LLMProviderConnectionError(
                "Provider connection failed or timed out."
            ) from None
        except BadRequestError:
            raise LLMProviderRequestError(
                "Provider rejected the request. Check the configured model and request."
            ) from None
        except APIStatusError as error:
            status_code = getattr(error, "status_code", None)
            if type(status_code) is int:
                raise LLMProviderRequestError(
                    f"Provider request failed with HTTP {status_code}."
                ) from None
            raise LLMProviderRequestError("Provider request failed.") from None
        except APIError:
            raise LLMProviderError("Provider request failed.") from None

        choices = getattr(response, "choices", None)
        message = getattr(choices[0], "message", None) if choices else None
        if getattr(message, "refusal", None):
            raise LLMProviderRefusalError("Provider refused the request.")
        response_text = getattr(message, "content", None)
        if type(response_text) is not str or not response_text:
            raise LLMProviderResponseError("Provider returned no text response.")
        try:
            response_size = len(response_text.encode("utf-8"))
        except UnicodeEncodeError:
            raise LLMProviderResponseError("Provider response is not valid UTF-8 text.") from None
        if response_size > MAX_MODEL_OUTPUT_BYTES:
            raise LLMProviderResponseTooLargeError(
                f"Provider response exceeds the {MAX_MODEL_OUTPUT_BYTES}-byte limit."
            )
        return response_text

    def close(self) -> None:
        """Close the SDK's HTTP client when the caller is finished."""
        close = getattr(self._client, "close", None)
        if callable(close):
            close()


def create_llm_client() -> LLMClient:
    """Build a local Gemini/OpenAI client; no request is sent until `complete` is called."""
    project_root = Path(__file__).resolve().parents[1]
    dotenv_path = project_root / ".env"
    if dotenv_path.is_file():
        try:
            from dotenv import load_dotenv
        except ImportError:
            raise LLMNotConfiguredError(
                "python-dotenv is required to load the ignored project .env file."
            ) from None
        load_dotenv(dotenv_path=dotenv_path, override=False)

    provider = os.getenv("ABACUS_LLM_PROVIDER", "gemini").strip().lower()
    if provider not in {"gemini", "openai"}:
        raise LLMNotConfiguredError("ABACUS_LLM_PROVIDER must be 'gemini' or 'openai'.")

    key_name = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    api_key = os.getenv(key_name, "").strip()
    if not api_key:
        raise LLMNotConfiguredError(
            f"{key_name} is missing. Add it to the ignored .env file or set it in the environment."
        )

    timeout_name = "GEMINI_TIMEOUT_SECONDS" if provider == "gemini" else "OPENAI_TIMEOUT_SECONDS"
    timeout_text = os.getenv(timeout_name, str(DEFAULT_TIMEOUT_SECONDS)).strip()
    try:
        timeout_seconds = float(timeout_text)
    except ValueError:
        raise LLMNotConfiguredError(
            f"{timeout_name} must be a finite number between 0 and {MAX_TIMEOUT_SECONDS}."
        ) from None
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise LLMNotConfiguredError(
            f"{timeout_name} must be a finite number between 0 and {MAX_TIMEOUT_SECONDS}."
        )

    try:
        from openai import OpenAI
    except ImportError:
        raise LLMNotConfiguredError(
            "The OpenAI-compatible SDK is missing. Install the runtime requirements first."
        ) from None

    client_options: dict[str, Any] = {
        "api_key": api_key,
        "timeout": timeout_seconds,
        "max_retries": 0,
    }
    if provider == "gemini":
        client_options["base_url"] = GEMINI_OPENAI_BASE_URL
    client = OpenAI(**client_options)
    return OpenAICompatibleLLMClient(provider, client)


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
