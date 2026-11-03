"""Generate validated complete and partial schema-v2 sample run records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .outcomes import FinalOutcome, OutcomeReason, RunOutcome
from .run_records import RUN_RECORD_SCHEMA_VERSION, load_run_record, save_run_record


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = PROJECT_ROOT / "practice" / "samples"
FIXED_TIMESTAMP = "2026-11-03T00:00:00+00:00"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _base_record(run_id: str, *, partial: bool) -> dict[str, Any]:
    method_list = ["fixed", "hypothesis"] if partial else ["fixed"]
    dataset_version = "sample-sort-cases-v1"
    dataset = {
        "fixed_cases": [[5, 2]] if partial else [[3, 1], [4, 4]],
        "proposal_fixtures": [],
        "hypothesis": {"seed": 2901, "max_examples": 1 if partial else 0},
    }
    dataset_canonical = json.dumps(
        {"dataset_version": dataset_version, **dataset},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    schedule = 2
    return {
        "schema_version": RUN_RECORD_SCHEMA_VERSION,
        "run_id": run_id,
        "run_status": "partial" if partial else "complete",
        "timestamps": {
            "started_at_utc": FIXED_TIMESTAMP,
            "finished_at_utc": FIXED_TIMESTAMP,
            "duration_seconds": 0.012,
        },
        "problem": {
            "problem_id": "sample-sort",
            "dataset_version": dataset_version,
            "dataset_sha256": hashlib.sha256(dataset_canonical.encode("utf-8")).hexdigest(),
            "problem_spec_sha256": _digest("sample-sort-problem-v1"),
            "dataset": dataset,
            "original_claim": "Return all input integers in ascending order, preserving duplicates.",
            "contract": {
                "id": "sample-sort-contract-v1",
                "oracle_id": "sorted_integer_list_v1",
                "input_type": "integer_list",
                "allow_empty": True,
            },
        },
        "target": {
            "id": "sort_correct",
            "code_sha256": _digest("sample target source hash"),
            "runner_code_sha256": _digest("sample runner source hash"),
        },
        "provenance": {
            "git_revision": None,
            "git_dirty": False,
            "software_versions": {
                "python": "3.15.2",
                "hypothesis": "6.170.14",
                "platform": "sample-platform",
                "abacus": "0.1.0-pilot",
            },
        },
        "model": {
            "provider_id": None,
            "model_id": None,
            "provider_api_called": False,
            "provider_identity_status": "not_applicable_no_provider_call",
            "proposal_step": {"status": "not_configured", "provider_api_called": False, "count": 0},
            "prompt_template_versions": {
                "plan_suggestions": "offline-suggestions-v1",
                "proposal_fixtures": "offline-proposals-v1",
                "claim_revision": "claim-revision-v1",
            },
            "plan_suggestions": [
                {"text": "Try repeated integers.", "source": "offline_fixture", "applied_as_fact": False}
            ],
        },
        "generation": {
            "methods": method_list,
            "random_seeds": {"hypothesis": 2901} if partial else {},
            "settings": {"sample": True},
            "scheduled_case_count": schedule,
            "generated_case_count": 0 if partial else 2,
            "validated_candidate_count": 1 if partial else 2,
            "case_counts_by_method": {"fixed": 1 if partial else 2, **({"hypothesis": 0} if partial else {})},
        },
        "model_proposals": [],
        "validated_candidates": [],
        "evidence": [],
        "replay_details": [],
        "outcome": {},
        "completion": {
            "status": "partial" if partial else "complete",
            "scheduled_case_count": schedule,
            "completed_case_count": 1 if partial else 2,
            "incomplete_reasons": ["round_limit"] if partial else [],
        },
        "revision": {"status": "skipped", "reason": "No confirmed counterexample."},
        "usage": {
            "model_call_count": 0,
            "provider_reported_token_usage": {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "status": "not_applicable",
            },
            "duration_seconds": 0.012,
            "estimated_cost_usd": 0.0,
            "actual_cost_usd": 0.0,
            "unknown_values": [],
        },
        "budget": {
            "budget_configured": {"max_rounds": 1, "max_model_calls": 0, "max_tokens": 0},
            "usage": {"rounds": 1, "model_calls": 0, "tokens_actual": 0, "cost_actual_usd": 0.0},
            "stop_reason": "round_limit" if partial else None,
        },
        "errors": [],
        "unknown_values": [
            {"field": "provenance.git_revision", "reason": "Illustrative sample is not tied to a source checkout."}
        ],
    }


def complete_sample() -> dict[str, Any]:
    record = _base_record("29a6b963-7d22-4a32-b3c5-8f8a1a4cc001", partial=False)
    record["evidence"] = [
        {
            "test_id": "fixed-1", "method": "fixed", "contract_id": "sample-sort-contract-v1",
            "status": "completed", "contract_valid": True, "oracle_id": "sorted_integer_list_v1",
            "input": [3, 1], "actual": [1, 3], "expected": [1, 3], "replay_confirmed": None,
            "category": "CASE_PASSED",
        },
        {
            "test_id": "fixed-2", "method": "fixed", "contract_id": "sample-sort-contract-v1",
            "status": "completed", "contract_valid": True, "oracle_id": "sorted_integer_list_v1",
            "input": [4, 4], "actual": [4, 4], "expected": [4, 4], "replay_confirmed": None,
            "category": "CASE_PASSED",
        },
    ]
    record["validated_candidates"] = [
        {"test_id": row["test_id"], "method": row["method"], "input": row["input"], "contract_valid": True}
        for row in record["evidence"]
    ]
    outcome = RunOutcome.from_finite_tests(test_count=2, methods=("fixed",)).to_dict()
    outcome["evidence_references"] = ["fixed-1", "fixed-2"]
    record["outcome"] = outcome
    return record


def partial_sample() -> dict[str, Any]:
    record = _base_record("29a6b963-7d22-4a32-b3c5-8f8a1a4cc002", partial=True)
    evidence = {
        "test_id": "fixed-1", "method": "fixed", "contract_id": "sample-sort-contract-v1",
        "status": "completed", "contract_valid": True, "oracle_id": "sorted_integer_list_v1",
        "input": [5, 2], "actual": [2, 5], "expected": [2, 5], "replay_confirmed": None,
        "category": "CASE_PASSED",
    }
    record["evidence"] = [evidence]
    record["validated_candidates"] = [
        {"test_id": "fixed-1", "method": "fixed", "input": [5, 2], "contract_valid": True}
    ]
    outcome = RunOutcome(
        outcome=FinalOutcome.UNRESOLVED,
        reason=OutcomeReason.BUDGET_EXHAUSTED,
        message="The round limit stopped evaluation before all scheduled cases completed.",
        test_count=1,
        methods=("fixed",),
    ).to_dict()
    outcome["evidence_references"] = ["fixed-1"]
    record["outcome"] = outcome
    return record


def main() -> None:
    for name, record in (
        ("run_complete.v2.json", complete_sample()),
        ("run_partial.v2.json", partial_sample()),
    ):
        destination = SAMPLE_DIR / name
        if destination.exists():
            if load_run_record(destination) != record:
                raise FileExistsError(f"Refusing to replace a different sample run record: {destination}")
        else:
            save_run_record(destination, record)
        print(destination)


if __name__ == "__main__":
    main()
