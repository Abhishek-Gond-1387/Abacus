"""Schema-v2 run-record validation fixtures."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from practice.day29_record_examples import complete_sample, partial_sample
from practice.run_records import (
    RunRecordValidationError,
    load_run_record,
    save_run_record,
    validate_run_record,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = PROJECT_ROOT / "practice" / "samples"


class RunRecordSchemaTests(unittest.TestCase):
    def test_complete_sample_validates_and_round_trips(self) -> None:
        record = complete_sample()
        with tempfile.TemporaryDirectory() as directory:
            path = save_run_record(Path(directory) / "complete.json", record)
            loaded = load_run_record(path)
        self.assertEqual(loaded["run_status"], "complete")
        self.assertEqual(loaded["outcome"]["reason"], "no_counterexample_found")
        self.assertEqual(loaded["problem"]["dataset_version"], "sample-sort-cases-v1")

    def test_partial_sample_is_accepted_with_explicit_incomplete_status(self) -> None:
        record = validate_run_record(partial_sample())
        self.assertEqual(record["run_status"], "partial")
        self.assertEqual(record["completion"]["status"], "partial")
        self.assertEqual(record["completion"]["incomplete_reasons"], ["round_limit"])
        self.assertEqual(record["outcome"]["outcome"], "UNRESOLVED")

    def test_checked_in_samples_validate(self) -> None:
        for name in ("run_complete.v2.json", "run_partial.v2.json"):
            with self.subTest(name=name):
                self.assertEqual(load_run_record(SAMPLES / name)["schema_version"], 2)

    def test_missing_dataset_version_is_rejected_before_saving(self) -> None:
        record = complete_sample()
        del record["problem"]["dataset_version"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            with self.assertRaisesRegex(RunRecordValidationError, "dataset_version"):
                save_run_record(path, record)
            self.assertFalse(path.exists())

    def test_missing_outcome_reason_is_rejected(self) -> None:
        record = complete_sample()
        del record["outcome"]["reason"]
        with self.assertRaisesRegex(RunRecordValidationError, "reason"):
            validate_run_record(record)

    def test_missing_evidence_references_is_rejected(self) -> None:
        record = complete_sample()
        record["outcome"]["evidence_references"] = []
        with self.assertRaisesRegex(RunRecordValidationError, "evidence_references"):
            validate_run_record(record)

    def test_dataset_hash_rejects_changed_inputs(self) -> None:
        record = complete_sample()
        record["problem"]["dataset"]["fixed_cases"][0] = [99]
        with self.assertRaisesRegex(RunRecordValidationError, "dataset_sha256"):
            validate_run_record(record)

    def test_missing_provider_usage_and_price_are_unknown_not_zero(self) -> None:
        record = complete_sample()
        record["model"]["provider_api_called"] = True
        record["model"]["provider_identity_status"] = "configured_provider"
        record["usage"].update({
            "model_call_count": 1,
            "successful_model_call_count": 1,
            "provider_reported_token_usage": {
                "input_tokens": None, "output_tokens": None, "total_tokens": None,
                "status": "unknown",
            },
            "pricing": {
                "status": "unknown", "provider_id": None, "model_id": None,
                "input_usd_per_million_tokens": None, "output_usd_per_million_tokens": None,
                "source_url": None, "checked_at": None,
            },
            "estimated_cost_usd": None,
            "actual_cost_usd": None,
            "unknown_values": [
                "provider_reported_token_usage", "pricing", "estimated_cost_usd", "actual_cost_usd",
            ],
        })
        record["budget"]["usage"].update({"model_calls": 1, "successful_calls": 1})
        validated = validate_run_record(record)
        self.assertIsNone(validated["usage"]["actual_cost_usd"])

        record["usage"]["actual_cost_usd"] = 0.0
        with self.assertRaisesRegex(RunRecordValidationError, "pricing is unknown"):
            validate_run_record(record)


if __name__ == "__main__":
    unittest.main()
