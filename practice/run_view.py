"""Render a compact, cautious terminal summary for one saved run."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .log_safety import sanitize_for_log


TESTS_PASSED_NOTE = "No counterexample found in these tests; not a proof."


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ": "))


def _display(value: Any) -> str:
    """Escape terminal control characters in text supplied by a run record."""
    rendered = str(value)
    safe_chars = []
    for character in rendered:
        if character.isprintable():
            safe_chars.append(character)
            continue
        codepoint = ord(character)
        safe_chars.append(f"\\x{codepoint:02x}" if codepoint <= 0xff else f"\\u{codepoint:04x}")
    return "".join(safe_chars)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def render_run_summary(
    record: Mapping[str, Any], *, record_path: str | Path | None = None
) -> str:
    """Format a saved run record without mixing suggestions with checked evidence."""
    safe_record = sanitize_for_log(dict(record))
    lines: list[str] = []
    marker = safe_record.get("incomplete_marker")
    if isinstance(marker, Mapping):
        lines.extend(("INCOMPLETE RUN SAVE", f"Run ID: {_display(marker.get('run_id', 'unknown'))}"))
        lines.append(f"Save state: {_display(marker.get('state', 'unknown'))}")
        lines.append(f"Temporary file: {_display(marker.get('temporary_path', 'unknown'))}")
        lines.append("No validated run record is available yet.")
        if record_path is not None:
            lines.append(f"Marker: {_display(sanitize_for_log(str(record_path)))}")
        return "\n".join(lines)

    problem = _mapping(safe_record.get("problem"))
    contract = _mapping(problem.get("contract"))
    outcome = _mapping(safe_record.get("outcome"))
    completion = _mapping(safe_record.get("completion"))
    generation = _mapping(safe_record.get("generation"))
    model = _mapping(safe_record.get("model"))
    usage = _mapping(safe_record.get("usage"))
    token_usage = _mapping(usage.get("provider_reported_token_usage"))
    pricing = _mapping(usage.get("pricing"))
    evidence = safe_record.get("evidence")
    evidence_rows = evidence if isinstance(evidence, list) else []

    lines.extend(("RUN SUMMARY", f"Run ID: {_display(safe_record.get('run_id', 'unknown'))}"))
    lines.append(f"Problem: {_display(problem.get('problem_id', 'unknown'))}")
    lines.append(f"Run status: {_display(safe_record.get('run_status', completion.get('status', 'unknown')))}")
    lines.extend(("", "CLAIM AND CONTRACT"))
    lines.append(f"Original claim: {_display(problem.get('original_claim', 'not recorded'))}")
    lines.append(
        "Contract: "
        f"{_display(contract.get('id', 'unknown'))} | oracle={_display(contract.get('oracle_id', 'unknown'))} | "
        f"input={_display(contract.get('input_type', 'unknown'))}"
    )

    outcome_label = outcome.get("outcome", "unknown")
    lines.extend(("", "RUN VERDICT"))
    lines.append(f"Outcome: {_display(outcome_label)}")
    lines.append(f"Reason: {_display(outcome.get('reason', 'not recorded'))}")
    if outcome.get("message"):
        lines.append(f"Explanation: {_display(outcome['message'])}")
    if outcome_label == "TESTS_PASSED":
        lines.append(TESTS_PASSED_NOTE)
    if outcome.get("failure_category"):
        lines.append(f"Failure category: {_display(outcome['failure_category'])}")

    completed_count = sum(
        isinstance(item, Mapping) and item.get("status") == "completed"
        for item in evidence_rows
    )
    scheduled_count = generation.get(
        "scheduled_case_count", completion.get("scheduled_case_count")
    )
    lines.extend(("", "HARNESS EVIDENCE (executed by code)"))
    count_label = f"{completed_count} completed"
    if type(scheduled_count) is int:
        count_label += f" / {scheduled_count} scheduled"
    lines.append(f"Checks: {count_label}")
    methods = generation.get("methods", outcome.get("methods", []))
    if isinstance(methods, list):
        lines.append(f"Methods: {', '.join(_display(method) for method in methods) or 'none recorded'}")
    method_counts = Counter(
        str(item.get("method", "unknown"))
        for item in evidence_rows
        if isinstance(item, Mapping)
    )
    if method_counts:
        lines.append(
            "Recorded checks by method: "
            + ", ".join(f"{_display(method)}={count}" for method, count in sorted(method_counts.items()))
        )
    test_count = outcome.get("test_count")
    if test_count is not None:
        lines.append(f"Outcome test count: {test_count}")

    candidates = [
        item for item in evidence_rows
        if isinstance(item, Mapping)
        and (
            item.get("category") == "PROPERTY_VIOLATION"
            or ("actual" in item and "expected" in item and item.get("actual") != item.get("expected"))
        )
    ]
    lines.append("Candidate counterexamples:")
    if not candidates:
        lines.append("  none recorded")
    else:
        for candidate in candidates:
            replay_confirmed = candidate.get("replay_confirmed")
            replay_status = (
                "replay confirmed" if replay_confirmed is True
                else "replay attempted but not confirmed" if candidate.get("replay_attempted") is True
                else "not replayed"
            )
            lines.append(
                f"  {_display(candidate.get('test_id', 'unknown'))} "
                f"({_display(candidate.get('method', 'unknown'))}): {replay_status}"
            )
            lines.append(f"    input={_json(candidate.get('input'))}")
            lines.append(f"    actual={_json(candidate.get('actual'))}")
            lines.append(f"    expected={_json(candidate.get('expected'))}")

    lines.extend(("", "MODEL INPUT (unverified; not harness evidence)"))
    suggestions = model.get("plan_suggestions", [])
    if isinstance(suggestions, list) and suggestions:
        for suggestion in suggestions:
            if isinstance(suggestion, Mapping):
                lines.append(f"  suggestion: {_display(suggestion.get('text', ''))}")
            else:
                lines.append(f"  suggestion: {_display(suggestion)}")
    else:
        lines.append("  no suggestions recorded")
    proposals = safe_record.get("model_proposals", [])
    if isinstance(proposals, list) and proposals:
        lines.append("Candidate proposals (evaluated status is shown; proposal alone is not evidence):")
        for proposal in proposals:
            if isinstance(proposal, Mapping):
                lines.append(
                    f"  {_display(proposal.get('proposal_id', 'proposal'))}: input={_json(proposal.get('input'))}; "
                    f"status={_display(proposal.get('evaluation_status', 'unknown'))}"
                )
    else:
        lines.append("  no candidate proposals recorded")

    incomplete_reasons = completion.get("incomplete_reasons", [])
    lines.extend(("", "COMPLETION AND ERRORS"))
    if isinstance(incomplete_reasons, list) and incomplete_reasons:
        lines.append("Incomplete reasons: " + ", ".join(_display(reason) for reason in incomplete_reasons))
    elif safe_record.get("run_status") == "partial":
        lines.append("Incomplete reasons: not recorded")
    else:
        lines.append("Incomplete reasons: none")
    errors = safe_record.get("errors", [])
    if isinstance(errors, list) and errors:
        lines.append("Errors:")
        for error in errors:
            if isinstance(error, Mapping):
                lines.append(
                    f"  {_display(error.get('step', 'unknown step'))}: "
                    f"{_display(error.get('error', 'unspecified error'))}"
                )
    else:
        lines.append("Errors: none recorded")

    duration = usage.get("duration_seconds")
    lines.extend(("", "RESOURCE USAGE"))
    lines.append(f"Provider calls: {usage.get('successful_model_call_count', 'unknown')} successful / "
                 f"{usage.get('model_call_count', 'unknown')} attempts; "
                 f"{usage.get('failed_model_call_count', 'unknown')} failed; "
                 f"{usage.get('retry_call_count', 'unknown')} retries")
    lines.append(
        f"Provider tokens: {_display(token_usage.get('status', 'unknown'))} "
        f"(input={token_usage.get('input_tokens')}, output={token_usage.get('output_tokens')}, "
        f"total={token_usage.get('total_tokens')})"
    )
    lines.append(f"Duration: {duration if duration is not None else 'unknown'} seconds")
    cost = usage.get("actual_cost_usd")
    cost_label = f"${cost:.8f} USD" if type(cost) in {int, float} else _display(pricing.get("status", "unknown"))
    lines.append(f"Actual API cost: {cost_label}")

    if record_path is not None:
        lines.extend(("", f"Full evidence record: {_display(sanitize_for_log(str(record_path)))}"))
    return "\n".join(lines)
