"""Day 34 durable progress checkpoint fixtures."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from practice.day29_record_examples import complete_sample
from practice.run_checkpoints import load_run_checkpoint, save_run_checkpoint
from practice.run_records import find_run_record, list_run_records, save_run_record
from practice.run_view import render_run_summary


class RunCheckpointTests(unittest.TestCase):
    def test_progress_checkpoint_is_discoverable_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = {
                "checkpoint_version": 1,
                "run_id": str(uuid4()),
                "problem_id": "checkpoint-fixture",
                "stage": "tests_complete",
                "final_path": str(Path(directory) / "final.json"),
                "checkpoint_path": str(Path(directory) / "run.checkpoint"),
                "started_at_utc": "2026-11-03T12:00:00+00:00",
                "duration_seconds": 1.25,
                "scheduled_case_count": 2,
                "generated_case_count": 1,
                "stage_durations_seconds": {"tests": 1.0},
                "evidence": [{"test_id": "fixed-1", "status": "completed"}],
                "case_log": [],
                "errors": [{"error_id": "error-1", "step": "fixed", "error": "fixture"}],
                "proposal_step": {"status": "not_configured"},
                "proposal_evaluation_succeeded": True,
                "revision": {"status": "not_started"},
            }
            path = save_run_checkpoint(Path(directory) / "run.checkpoint", checkpoint)

            loaded = load_run_checkpoint(path)
            entries = list_run_records(directory, problem_id="checkpoint-fixture")
            found = find_run_record(directory, checkpoint["run_id"])

        self.assertEqual(loaded["stage"], "tests_complete")
        self.assertEqual(len(entries["checkpoints"]), 1)
        self.assertIn("progress_checkpoint", found)
        view = render_run_summary(found, record_path=path)
        self.assertIn("INTERRUPTED RUN CHECKPOINT", view)
        self.assertIn("Last completed stage: tests_complete", view)
        self.assertIn("1 completed / 2 scheduled", view)

    def test_stale_checkpoint_is_hidden_after_final_record_is_saved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = complete_sample()
            checkpoint = {
                "checkpoint_version": 1,
                "run_id": record["run_id"],
                "problem_id": record["problem"]["problem_id"],
                "stage": "revision_complete",
                "evidence": [],
                "case_log": [],
                "errors": [],
            }
            save_run_checkpoint(Path(directory) / "stale.checkpoint", checkpoint)
            save_run_record(Path(directory) / "complete.json", record)
            entries = list_run_records(directory)

        self.assertEqual(len(entries["runs"]), 1)
        self.assertEqual(entries["checkpoints"], [])

    def test_checkpoint_loader_rejects_non_uuid_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.checkpoint"
            path.write_text(json.dumps({
                "checkpoint_version": 1,
                "run_id": "not-a-uuid",
                "problem_id": "bad",
                "stage": "tests_complete",
                "evidence": [],
                "case_log": [],
                "errors": [],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "UUID"):
                load_run_checkpoint(path)


if __name__ == "__main__":
    unittest.main()
