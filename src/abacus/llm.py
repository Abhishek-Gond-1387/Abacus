"""Small Gemini/OpenAI adapter plus a deterministic, offline stub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import LLMSettings
from .errors import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMConnectionError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRequestError,
    LLMUsageLimitError,
)


@dataclass(frozen=True)
class LLMResult:
    """Text and non-secret metadata returned by a model provider."""

    text: str
    provider: str
    model: str
    usage: dict[str, int] | None = None


def _validate_call(prompt: str, system: str | None, max_tokens: int) -> None:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    if system is not None and not isinstance(system, str):
        raise TypeError("system must be a string or None")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
        raise TypeError("max_tokens must be a positive integer")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be a positive integer")


def _usage_dict(usage: Any) -> dict[str, int] | None:
    if usage is None:
        return None

    result: dict[str, int] = {}
    aliases = {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "total_tokens": ("total_tokens",),
    }
    for normalized_name, names in aliases.items():
        value = None
        for name in names:
            value = getattr(usage, name, None)
            if value is not None:
                break
        if isinstance(value, int) and not isinstance(value, bool):
            result[normalized_name] = value
    return result or None


def ask(
    prompt: str,
    system: str | None = None,
    max_tokens: int = 128,
    *,
    settings: LLMSettings | None = None,
) -> LLMResult:
    """Send one request and return text with usage metadata when available.

    SDK retries are disabled so failures never trigger hidden repeat requests.
    Provider exception bodies are not copied into user-facing messages.
    """

    _validate_call(prompt, system, max_tokens)
    resolved = settings or LLMSettings.from_env()
    if not resolved.api_key:
        key_name = "GEMINI_API_KEY" if resolved.provider == "gemini" else "OPENAI_API_KEY"
        raise LLMConfigurationError(
            f"{key_name} is missing. Add it to the ignored .env file or set it in the environment."
        )

    try:
        from openai import (
            APIConnectionError,
            APIStatusError,
            AuthenticationError,
            BadRequestError,
            OpenAI,
            RateLimitError,
        )
    except ImportError:
        raise LLMConfigurationError(
            "The OpenAI-compatible Python SDK is not installed. Install the project dependencies first."
        ) from None

    try:
        client_options: dict[str, Any] = {
            "api_key": resolved.api_key,
            "timeout": resolved.timeout_seconds,
            "max_retries": 0,
        }
        if resolved.provider == "gemini":
            client_options["base_url"] = "https://generativelanguage.googleapis.com/v1beta/openai/"

        with OpenAI(**client_options) as client:
            if resolved.provider == "gemini":
                messages: list[dict[str, str]] = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": prompt})
                response = client.chat.completions.create(
                    model=resolved.model,
                    messages=messages,
                    max_tokens=max_tokens,
                )
                choices = getattr(response, "choices", None)
                message = getattr(choices[0], "message", None) if choices else None
                response_text = getattr(message, "content", None)
                if not isinstance(response_text, str):
                    raise LLMProviderError("The Gemini API returned no text response.")
            else:
                response = client.responses.create(
                    model=resolved.model,
                    input=prompt,
                    instructions=system if system else None,
                    max_output_tokens=max_tokens,
                )
                response_text = response.output_text
    except AuthenticationError:
        raise LLMAuthenticationError(
            "API authentication failed. Check the configured API key."
        ) from None
    except RateLimitError as error:
        code = getattr(error, "code", None)
        if code in ("insufficient_quota", "billing_hard_limit_reached"):
            raise LLMUsageLimitError(
                f"The API account has no available quota or has reached its spend limit (code: {code})."
            ) from None
        if code == "rate_limit_exceeded":
            raise LLMRateLimitError(
                f"The API request rate limit was reached (code: {code}). Wait before trying again."
            ) from None
        if (
            isinstance(code, str)
            and len(code) <= 64
            and code.isascii()
            and code.replace("_", "").isalnum()
        ):
            raise LLMUsageLimitError(
                f"The API returned a rate or usage limit error (code: {code}). "
                "Check account limits and credits."
            ) from None
        raise LLMUsageLimitError(
            "The API returned a rate or usage limit error. Check account limits and credits."
        ) from None
    except APIConnectionError:
        raise LLMConnectionError(
            "Could not connect to the API or the request timed out. Check the network."
        ) from None
    except BadRequestError:
        raise LLMRequestError(
            "The API rejected the request. Check the model name and request settings."
        ) from None
    except APIStatusError as error:
        status_code = getattr(error, "status_code", None)
        if isinstance(status_code, int):
            raise LLMProviderError(
                f"The API request failed with HTTP {status_code}."
            ) from None
        raise LLMProviderError("The API request failed.") from None

    actual_model = getattr(response, "model", None)
    return LLMResult(
        text=response_text,
        provider=resolved.provider,
        model=actual_model if isinstance(actual_model, str) and actual_model else resolved.model,
        usage=_usage_dict(getattr(response, "usage", None)),
    )


def stub_ask(
    prompt: str,
    system: str | None = None,
    max_tokens: int = 128,
) -> LLMResult:
    """Return a fixed result without loading credentials or making a network call."""

    _validate_call(prompt, system, max_tokens)
    return LLMResult(
        text="This is a stub response; no API request was made.",
        provider="stub",
        model="fixed-response",
        usage=None,
    )
