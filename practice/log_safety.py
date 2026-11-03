"""Redact credentials before writing diagnostic or run data to disk."""

from __future__ import annotations

import os
import re
from typing import Any


REDACTED = "[REDACTED]"

_SENSITIVE_KEYS = {
    "apikey",
    "access_token",
    "refreshtoken",
    "idtoken",
    "authtoken",
    "tokenvalue",
    "tokenstring",
    "tokenheader",
    "clientsecret",
    "password",
    "passwd",
    "pwd",
    "authorization",
    "proxyauthorization",
    "privatekey",
    "credential",
    "credentials",
    "cookie",
    "setcookie",
    "sessionkey",
    "signingkey",
}
_SENSITIVE_KEYS_NORMALIZED = frozenset(
    re.sub(r"[^a-z0-9]", "", item.lower()) for item in _SENSITIVE_KEYS
)
_SENSITIVE_ENV_NAME = re.compile(
    r"(?:^|[_-])(?:API[_-]?KEY|ACCESS[_-]?TOKEN|REFRESH[_-]?TOKEN|"
    r"AUTH[_-]?TOKEN|TOKEN|CLIENT[_-]?SECRET|SECRET|PASSWORD|PASSWD|"
    r"CREDENTIAL|PRIVATE[_-]?KEY|AUTHORIZATION|COOKIE)(?:$|[_-])",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?P<label>\b(?:api[ _-]?key|access[_-]?token|refresh[_-]?token|"
    r"auth[_-]?token|token|client[_-]?secret|secret|password|passwd|authorization|"
    r"private[_-]?key|credential|cookie)\b)(?P<sep>\s*[:=]\s*)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_OR_BASIC = re.compile(r"(?i)\b(Bearer|Basic)(\s+)[A-Za-z0-9._~+/=-]+")
_KNOWN_TOKEN_FORMAT = re.compile(
    r"(?i)\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|"
    r"github_pat_[A-Za-z0-9_]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|gsk_[A-Za-z0-9]{20,}|"
    r"hf_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,}|AKIA[A-Z0-9]{16})\b"
)
_JWT = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])")
_URL_CREDENTIALS = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]*://)[^/@\s:]+:[^/@\s]+@"
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----.*?"
    r"-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----",
    re.DOTALL,
)


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return normalized.endswith("token") or any(
        sensitive in normalized
        for sensitive in _SENSITIVE_KEYS_NORMALIZED
    )


def _environment_secrets() -> tuple[str, ...]:
    values = {
        value
        for name, value in os.environ.items()
        if _SENSITIVE_ENV_NAME.search(name) and value
    }
    return tuple(sorted(values, key=len, reverse=True))


def _redact_text(value: str, secrets: tuple[str, ...]) -> str:
    value = _PRIVATE_KEY_BLOCK.sub(REDACTED, value)
    value = _BEARER_OR_BASIC.sub(lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}", value)
    value = _URL_CREDENTIALS.sub(lambda match: f"{match.group(1)}{REDACTED}@", value)
    value = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group('label')}{match.group('sep')}{REDACTED}", value
    )
    value = _KNOWN_TOKEN_FORMAT.sub(REDACTED, value)
    value = _JWT.sub(REDACTED, value)
    for secret in secrets:
        value = value.replace(secret, REDACTED)
    return value


def sanitize_for_log(value: Any) -> Any:
    """Return a JSON-compatible copy with secret fields and text redacted.

    Numeric usage fields such as ``input_tokens`` and ``tokens_actual`` remain
    intact because token counts are not credentials.
    """
    secrets = _environment_secrets()

    def sanitize(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: REDACTED if _is_sensitive_key(key) else sanitize(child)
                for key, child in item.items()
            }
        if isinstance(item, list):
            return [sanitize(child) for child in item]
        if isinstance(item, tuple):
            return tuple(sanitize(child) for child in item)
        if isinstance(item, str):
            return _redact_text(item, secrets)
        return item

    return sanitize(value)
