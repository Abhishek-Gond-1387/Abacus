"""Regression coverage for saving and inspecting hosted suggestion audit artifacts."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from abacus import cli
from abacus.hosted_audit import (
    HOSTED_AUDIT_SCHEMA_VERSION,
    HostedAuditValidationError,
    find_hosted_audit_record,
    list_hosted_audit_records,
    load_hosted_audit_record,
    save_hosted_audit_record,
)
from abacus.schemas import parse_candidate_proposals


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBLEM_PATH = PROJECT_ROOT / "problems" / "p02_false_sort.json"


def _sample_record() -> dict[str, object]:
    model_result = parse_candidate_proposals(
        '{"proposals":[{"input":[3,-1,3,0],"rationale":"Duplicate values check multiplicity."}]}'
    )
    return {
        "audit_schema_version": HOSTED_AUDIT_SCHEMA_VERSION,
        "audit_record_id": str(uuid4()),
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        "suggestion_output": {
            "status": "suggestions_ready",
            "output_kind": "candidate_proposals",
            "template_version": "hosted-candidate-proposals-v1",
            "model_id": "offline-test-model",
            "provider_api_called": True,
            "usage_recorded": False,
            "request_metadata": {
                "request_started_at_utc": datetime.now(timezone.utc).isoformat(),
                "provider_id": "gemini",
                "model_id": "offline-test-model",
                "problem_id": "p02_false_sort",
                "dataset_version": "sort-cases-v1",
                "problem_spec_sha256": "a" * 64,
                "dataset_sha256": "b" * 64,
                "prompt_template_version": "hosted-candidate-proposals-v1",
                "prompt_sha256": "c" * 64,
                "prompt_bytes": 100,
                "request_parameters": {
                    "timeout_seconds": 20.0,
                    "automatic_retries": 0,
                    "max_output_tokens": 1_024,
                    "sampling_parameters": "provider_defaults",
                },
            },
            "suggestions_are_evidence": False,
            "result": {
                "proposals": [
                    {"input": list(item.input), "rationale": item.rationale}
                    for item in model_result.proposals
                ]
            },
        },
    }


class _StubHostedClient:
    def audit_metadata(self) -> dict[str, object]:
        return {
            "provider_id": "gemini",
            "timeout_seconds": 20.0,
            "automatic_retries": 0,
            "max_output_tokens": 1_024,
            "sampling_parameters": "provider_defaults",
        }

    def close(self) -> None:
        return None


class HostedAuditTests(unittest.TestCase):
    def test_save_load_list_and_find_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            destination = directory / "nested" / "audit.json"
            record = _sample_record()

            saved_path = save_hosted_audit_record(destination, record)
            loaded = load_hosted_audit_record(saved_path)
            listing = list_hosted_audit_records(destination.parent)

            self.assertEqual(loaded, record)
            self.assertEqual(len(listing["records"]), 1)
            self.assertEqual(listing["records"][0]["audit_record_id"], record["audit_record_id"])
            self.assertEqual(listing["records"][0]["proposal_count"], 1)
            self.assertEqual(listing["incomplete"], [])
            self.assertEqual(listing["invalid_files"], [])
            self.assertEqual(
                find_hosted_audit_record(destination.parent, str(record["audit_record_id"])),
                record,
            )
            self.assertFalse(destination.with_name(destination.name + ".incomplete").exists())

    def test_existing_destination_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "audit.json"
            destination.write_text("keep this file", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                save_hosted_audit_record(destination, _sample_record())

            self.assertEqual(destination.read_text(encoding="utf-8"), "keep this file")

    def test_duplicate_keys_and_oversized_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            duplicate = directory / "duplicate.json"
            duplicate.write_text('{"audit_schema_version":1,"audit_schema_version":1}', encoding="utf-8")
            oversized = directory / "oversized.json"
            oversized.write_bytes(b" " * (512 * 1024 + 1))

            with self.assertRaises(HostedAuditValidationError):
                load_hosted_audit_record(duplicate)
            with self.assertRaises(HostedAuditValidationError):
                load_hosted_audit_record(oversized)
            listing = list_hosted_audit_records(directory)
            self.assertEqual(len(listing["invalid_files"]), 2)

    def test_incomplete_marker_is_reported_and_path_traversal_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            valid_marker = {
                "audit_schema_version": HOSTED_AUDIT_SCHEMA_VERSION,
                "audit_record_id": str(uuid4()),
                "state": "writing",
                "final_path": "audit.json",
                "temporary_path": ".audit.json.tmp",
                "saved_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            (directory / "audit.json.incomplete").write_text(
                json.dumps(valid_marker), encoding="utf-8",
            )
            invalid_marker = {**valid_marker, "final_path": "../outside.json"}
            (directory / "bad.json.incomplete").write_text(
                json.dumps(invalid_marker), encoding="utf-8",
            )

            listing = list_hosted_audit_records(directory)

            self.assertEqual(len(listing["incomplete"]), 1)
            self.assertEqual(len(listing["invalid_files"]), 1)

    def test_cli_saves_and_inspects_without_a_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "audits"
            destination = directory / "proposal.json"
            client = _StubHostedClient()
            parsed_result = parse_candidate_proposals(
                '{"proposals":[{"input":[3,-1,3,0],"rationale":"Check duplicate preservation."}]}'
            )
            stdout = io.StringIO()
            with (
                patch("abacus.cli.create_llm_client", return_value=client),
                patch("abacus.cli.complete_structured_output", return_value=parsed_result),
                contextlib.redirect_stdout(stdout),
            ):
                return_code = cli.main([
                    "model-suggest", str(PROBLEM_PATH), "--kind", "candidate_proposals",
                    "--model", "offline-test-model", "--send-to-provider", "--evaluate-proposals",
                    "--save-audit", str(destination),
                ])

            output = json.loads(stdout.getvalue())
            self.assertEqual(return_code, 0)
            self.assertTrue(output["audit_record_saved"])
            self.assertTrue(output["request_metadata"]["prompt_sha256"])
            saved = load_hosted_audit_record(destination)
            saved_output = saved["suggestion_output"]
            self.assertEqual(saved_output["proposal_evaluation"]["normal_run_record_saved"], False)
            self.assertEqual(saved_output["proposal_evaluation"]["results"][0]["evaluation_status"], "PROPERTY_VIOLATION")

            list_stdout = io.StringIO()
            with (
                patch("abacus.cli.create_llm_client", side_effect=AssertionError("provider must not be created")),
                contextlib.redirect_stdout(list_stdout),
            ):
                list_code = cli.main(["list-audits", "--audits-dir", str(directory)])
            self.assertEqual(list_code, 0)
            listed = json.loads(list_stdout.getvalue())
            self.assertEqual(listed["records"][0]["audit_record_id"], output["audit_record_id"])

            show_stdout = io.StringIO()
            with (
                patch("abacus.cli.create_llm_client", side_effect=AssertionError("provider must not be created")),
                contextlib.redirect_stdout(show_stdout),
            ):
                show_code = cli.main([
                    "show-audit", output["audit_record_id"], "--audits-dir", str(directory),
                ])
            self.assertEqual(show_code, 0)
            self.assertEqual(json.loads(show_stdout.getvalue()), saved)


if __name__ == "__main__":
    unittest.main()
