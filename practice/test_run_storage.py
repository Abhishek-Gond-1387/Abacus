"""Atomic save and unique run-discovery fixtures for Day 30."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from abacus import cli
from abacus.cli import load_problem, run_problem
from practice.day29_record_examples import complete_sample
from practice.run_records import (
    find_run_record,
    list_run_records,
    load_run_record,
    save_run_record,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBLEM = PROJECT_ROOT / "problems" / "p01_true_sort.json"


class RunStorageTests(unittest.TestCase):
    def test_two_runs_of_same_problem_keep_unique_files_and_are_inspectable(self) -> None:
        spec = load_problem(PROBLEM)
        with tempfile.TemporaryDirectory() as directory:
            first = run_problem(spec, runs_dir=directory)
            second = run_problem(spec, runs_dir=directory)
            paths = {Path(first["log_path"]), Path(second["log_path"])}
            self.assertEqual(len(paths), 2)
            self.assertTrue(all(path.exists() for path in paths))
            records = list_run_records(directory, problem_id=spec.problem_id)
            self.assertEqual(len(records["runs"]), 2)
            self.assertEqual(len({item["run_id"] for item in records["runs"]}), 2)
            for item in records["runs"]:
                loaded = load_run_record(item["path"])
                self.assertEqual(loaded["problem"]["problem_id"], spec.problem_id)
                self.assertEqual(loaded["problem"]["dataset_sha256"], spec.dataset_sha256)

            output = io.StringIO()
            with redirect_stdout(output):
                result = cli.main(["list-runs", spec.problem_id, "--runs-dir", directory])
            self.assertEqual(result, 0)
            listing = json.loads(output.getvalue())
            selected_id = listing["runs"][0]["run_id"]

            output = io.StringIO()
            with redirect_stdout(output):
                result = cli.main(["show-run", selected_id, "--runs-dir", directory])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output.getvalue())["run_id"], selected_id)

            output = io.StringIO()
            with redirect_stdout(output):
                result = cli.main(["view-run", selected_id, "--runs-dir", directory])
            self.assertEqual(result, 0)
            self.assertIn("RUN SUMMARY", output.getvalue())
            self.assertIn("Full evidence record:", output.getvalue())

            output = io.StringIO()
            with redirect_stdout(output):
                result = cli.main(["summarize-runs", spec.problem_id, "--runs-dir", directory])
            self.assertEqual(result, 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["run_count"], 2)
            self.assertEqual(summary["model_calls_total"], 0)
            self.assertEqual(summary["provider_reported_token_usage"]["status"], "not_applicable")
            self.assertEqual(summary["duration_seconds"]["count"], 2)

    def test_successful_atomic_save_leaves_valid_json_without_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = save_run_record(Path(directory) / "sample.json", complete_sample())
            self.assertEqual(load_run_record(path)["run_status"], "complete")
            self.assertFalse(Path(str(path) + ".incomplete").exists())
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_interrupted_rename_leaves_marker_and_recoverable_temp_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interrupted.json"
            with mock.patch("practice.run_records.os.replace", side_effect=OSError("simulated stop")):
                with self.assertRaisesRegex(OSError, "simulated stop"):
                    save_run_record(path, complete_sample())

            marker_path = Path(str(path) + ".incomplete")
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertEqual(marker["state"], "writing")
            self.assertEqual(marker["final_path"], path.name)
            self.assertTrue((path.parent / marker["temporary_path"]).exists())
            found = find_run_record(directory, marker["run_id"])
            self.assertIn("incomplete_marker", found)

    def test_existing_destination_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = save_run_record(Path(directory) / "existing.json", complete_sample())
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                save_run_record(path, complete_sample())
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
