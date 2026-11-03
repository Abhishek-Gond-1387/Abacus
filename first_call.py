"""Make one small request through Abacus' configured model provider."""

from abacus import LLMError, ask


try:
    result = ask(
        "Reply with exactly: Abacus API check passed.",
        max_tokens=32,
    )
except LLMError as error:
    raise SystemExit(f"API call failed ({error.category}): {error}") from None

print(result.text)
