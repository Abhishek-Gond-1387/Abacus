"""End-to-end tests for the Day 27 evidence pilot."""

from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from abacus import cli
from abacus.cli import ProblemValidationError, load_problem, parse_problem, run_problem
from practice.run_records import validate_run_record
from practice.provider_retries import ProviderCallFailure
from practice.run_view import render_run_summary


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBLEMS = PROJECT_ROOT / "problems"


class Day27PipelineTests(unittest.TestCase):
    def test_true_example_is_finite_tests_passed_and_logged(self) -> None:
        spec = load_problem(PROBLEMS / "p01_true_sort.json")
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "true-run.json"
            record = run_problem(spec, log_path)
            saved = json.loads(log_path.read_text(encoding="utf-8"))

        self.assertEqual(record["outcome"]["outcome"], "TESTS_PASSED")
        self.assertEqual(record["outcome"]["test_count"], 31)
        self.assertEqual(saved["outcome"]["outcome"], "TESTS_PASSED")
        self.assertEqual(saved["schema_version"], 2)
        self.assertTrue(saved["run_id"])
        self.assertFalse(saved["model"]["provider_api_called"])
        self.assertTrue(all(not item["applied_as_fact"] for item in saved["model"]["plan_suggestions"]))
        self.assertTrue(saved["problem"]["dataset_sha256"])
        self.assertTrue(saved["target"]["code_sha256"])
        self.assertEqual(saved["budget"]["usage"]["model_calls"], 0)
        usage = saved["usage"]
        self.assertEqual(usage["resource_usage_version"], 1)
        self.assertEqual(usage["provider_reported_token_usage"]["status"], "not_applicable")
        self.assertEqual(usage["pricing"]["status"], "not_applicable")
        self.assertEqual(usage["stage_status"]["planning"], "not_configured")
        self.assertEqual(usage["stage_status"]["tests"], "completed")
        self.assertGreaterEqual(usage["stage_durations_seconds"]["tests"], 0)

    def test_problem_accepts_dated_model_pricing(self) -> None:
        payload = json.loads((PROBLEMS / "p01_true_sort.json").read_text(encoding="utf-8"))
        payload["pricing"] = {
            "provider_id": "fixture-provider",
            "model_id": "fixture-model",
            "input_usd_per_million_tokens": 2.0,
            "output_usd_per_million_tokens": 8.0,
            "source_url": "https://example.com/pricing",
            "checked_at": "2026-11-03",
        }
        spec = parse_problem(payload)
        self.assertEqual(spec.pricing_config.provider_id, "fixture-provider")
        self.assertEqual(spec.pricing_config.checked_at, "2026-11-03")

    def test_false_example_is_refuted_only_after_confirmed_replay(self) -> None:
        spec = load_problem(PROBLEMS / "p02_false_sort.json")
        with tempfile.TemporaryDirectory() as directory:
            record = run_problem(spec, Path(directory) / "false-run.json")

        outcome = record["outcome"]
        self.assertEqual(outcome["outcome"], "REFUTED")
        self.assertEqual(outcome["reason"], "confirmed_counterexample")
        self.assertTrue(outcome["counterexample"]["replay_confirmed"])
        self.assertNotEqual(outcome["counterexample"]["actual"], outcome["counterexample"]["expected"])
        self.assertEqual(record["revision"]["status"], "applied_offline_fixture")
        self.assertEqual(record["revision"]["scored_claim"], record["problem"]["original_claim"])
        self.assertEqual(record["revision"]["scored_label"], "REFUTED")
        self.assertFalse(record["revision"]["provider_api_called"])

    def test_problem_validation_rejects_bad_inputs_before_execution(self) -> None:
        payload = json.loads((PROBLEMS / "p01_true_sort.json").read_text(encoding="utf-8"))
        payload["proposal_fixtures"][0]["input"] = [True, 2]
        with mock.patch.dict(cli.TARGETS, {"sort_correct": mock.Mock(side_effect=AssertionError("must not run"))}):
            with self.assertRaisesRegex(ProblemValidationError, "booleans excluded"):
                parse_problem(payload)

    def test_optional_proposal_failure_still_saves_error_and_budget_log(self) -> None:
        spec = load_problem(PROBLEMS / "p01_true_sort.json")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proposal-failure.json"
            with mock.patch("abacus.cli.collect_offline_proposals", side_effect=RuntimeError("offline proposal source failed")):
                result = run_problem(spec, path)
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(result["outcome"]["outcome"], "ERROR")
        self.assertEqual(saved["model"]["proposal_step"]["status"], "error")
        self.assertEqual(saved["errors"][0]["step"], "optional_proposal_generation")
        self.assertIn("budget", saved)
        self.assertEqual(saved["budget"]["usage"]["model_calls"], 0)

    def test_emergency_pipeline_error_uses_valid_versioned_record(self) -> None:
        spec = load_problem(PROBLEMS / "p01_true_sort.json")
        record = cli._emergency_error_record(
            spec,
            RuntimeError("unexpected local failure"),
            started_at=datetime.now(timezone.utc),
            duration_seconds=0.01,
        )
        self.assertEqual(record["schema_version"], 2)
        self.assertEqual(record["outcome"]["outcome"], "ERROR")
        self.assertEqual(record["outcome"]["evidence_references"], ["error:pipeline-error"])
        self.assertIs(validate_run_record(record), record)

    def test_emergency_provider_error_exposes_ambiguous_outcome_and_billing(self) -> None:
        spec = load_problem(PROBLEMS / "p01_true_sort.json")
        failure = ProviderCallFailure(
            "Provider response was lost.",
            category="response_lost",
            attempts=1,
            outcome_ambiguous=True,
        )
        record = cli._emergency_error_record(
            spec,
            failure,
            started_at=datetime.now(timezone.utc),
            duration_seconds=0.01,
        )

        self.assertEqual(record["outcome"]["failure_category"], "response_lost")
        self.assertTrue(record["outcome"]["outcome_ambiguous"])
        self.assertEqual(record["outcome"]["billing_status"], "ambiguous")
        self.assertIn("billing: ambiguous", render_run_summary(validate_run_record(record)))

    def test_late_pipeline_failure_saves_checkpoint_evidence_in_error_record(self) -> None:
        spec_path = PROBLEMS / "p01_true_sort.json"
        spec = load_problem(spec_path)
        checkpoint_snapshots: list[dict[str, object]] = []
        original_save_checkpoint = cli.save_run_checkpoint

        def capture_checkpoint(path: Path, checkpoint: dict[str, object]) -> Path:
            checkpoint_snapshots.append(dict(checkpoint))
            return original_save_checkpoint(path, checkpoint)

        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "pipeline-error.json"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch("abacus.cli._revision_log", side_effect=RuntimeError("revision stage crashed")),
                mock.patch("abacus.cli.save_run_checkpoint", side_effect=capture_checkpoint),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                result = cli.main(["run", str(spec_path), "--output", str(log_path)])

            saved = json.loads(log_path.read_text(encoding="utf-8"))
            checkpoint_path = log_path.with_name(f"{log_path.name}.{saved['run_id']}.checkpoint")

        self.assertEqual(result, 1)
        self.assertTrue(checkpoint_snapshots)
        self.assertEqual(saved["run_id"], checkpoint_snapshots[-1]["run_id"])
        self.assertEqual(saved["run_status"], "error")
        self.assertEqual(saved["outcome"]["outcome"], "ERROR")
        self.assertEqual(saved["evidence"], checkpoint_snapshots[-1]["evidence"])
        self.assertGreater(saved["completion"]["completed_case_count"], 0)
        self.assertIn("revision stage crashed", saved["errors"][-1]["error"])
        self.assertFalse(checkpoint_path.exists())
        self.assertIs(validate_run_record(saved), saved)


if __name__ == "__main__":
    unittest.main()
