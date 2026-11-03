"""Safe, user-facing errors from Abacus' language-model adapter."""


class LLMError(RuntimeError):
    """Base class for errors that are safe to show without SDK internals."""

    category = "llm_error"


class LLMConfigurationError(LLMError):
    category = "configuration"


class LLMAuthenticationError(LLMError):
    category = "authentication"


class LLMUsageLimitError(LLMError):
    category = "usage_limit"


class LLMRateLimitError(LLMError):
    category = "rate_limit"


class LLMConnectionError(LLMError):
    category = "connection"


class LLMRequestError(LLMError):
    category = "request"


class LLMProviderError(LLMError):
    category = "provider"
