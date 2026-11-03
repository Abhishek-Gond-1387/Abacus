"""Environment-backed configuration for the model adapter."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from .errors import LLMConfigurationError


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LLMSettings:
    """Settings for one provider. The secret is deliberately hidden from repr."""

    provider: str
    model: str
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if self.provider not in {"gemini", "openai"}:
            raise LLMConfigurationError(
                "ABACUS_LLM_PROVIDER must be 'gemini' or 'openai'."
            )
        if not isinstance(self.model, str) or not self.model.strip():
            raise LLMConfigurationError(
                f"{self.provider.upper()}_MODEL cannot be empty."
            )
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise LLMConfigurationError(
                f"{self.provider.upper()}_TIMEOUT_SECONDS must be a finite number greater than zero."
            )

    @classmethod
    def from_env(cls) -> "LLMSettings":
        """Load .env without overriding explicitly-set process environment values."""

        dotenv_path = PROJECT_ROOT / ".env"
        if dotenv_path.is_file():
            try:
                from dotenv import load_dotenv
            except ImportError:
                raise LLMConfigurationError(
                    "python-dotenv is required to load the project's .env file. "
                    "Install the project dependencies first."
                ) from None
            load_dotenv(dotenv_path=dotenv_path, override=False)

        provider = os.getenv("ABACUS_LLM_PROVIDER", "gemini").strip().lower()
        if provider not in {"gemini", "openai"}:
            raise LLMConfigurationError(
                "ABACUS_LLM_PROVIDER must be 'gemini' or 'openai'."
            )

        prefix = provider.upper()
        default_model = (
            "gemini-3.1-flash-lite" if provider == "gemini" else "gpt-5.4-mini"
        )
        model = os.getenv(f"{prefix}_MODEL", default_model).strip()
        api_key = os.getenv(f"{prefix}_API_KEY", "").strip() or None

        timeout_text = os.getenv(f"{prefix}_TIMEOUT_SECONDS", "20").strip()
        try:
            timeout_seconds = float(timeout_text)
        except ValueError:
            raise LLMConfigurationError(
                f"{prefix}_TIMEOUT_SECONDS must be a positive number."
            ) from None
        if not model:
            raise LLMConfigurationError(f"{prefix}_MODEL cannot be empty.")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise LLMConfigurationError(
                f"{prefix}_TIMEOUT_SECONDS must be a finite number greater than zero."
            )

        return cls(
            provider=provider,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
