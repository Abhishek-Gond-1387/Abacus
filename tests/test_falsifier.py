from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from abacus.errors import LLMConfigurationError
from abacus.failure_categories import FailureCategory
from abacus.harness import CaseEvidence, HarnessStatus
from abacus.llm import LLMResult
from abacus.problems import load_problem
from abacus.falsifier import build_falsifier_prompt, run_falsifier


PROBLEMS_DIRECTORY = Path(__file__).resolve().parents[1] / "problems"


class FalsifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.true_problem = load_problem(
            PROBLEMS_DIRECTORY / "sort-ascending-true.json"
        )
        cls.false_problem = load_problem(
            PROBLEMS_DIRECTORY / "sort-ascending-false.json"
        )

    @staticmethod
    def response(input_value: list[int], *, label: str | None = None) -> str:
        data: dict[str, object] = {
            "candidate_inputs": [
                {
                    "input": input_value,
                    "rationale": "This input checks a useful ordering boundary.",
                }
            ]
        }
        if label is not None:
            data["verdict"] = label
        return json.dumps(data)

    def test_prompt_is_adversarial_and_contains_full_contract(self) -> None:
        system, prompt = build_falsifier_prompt(self.false_problem)

        self.assertIn("adversarial", system)
        self.assertIn("Actively try to find inputs", prompt)
        self.assertIn(self.false_problem["claim"], prompt)
        self.assertIn(json.dumps(self.false_problem["code"]), prompt)
        self.assertIn(self.false_problem["property_description"], prompt)
        self.assertIn("preconditions", prompt)
        self.assertIn("Do not include a pass/fail label", prompt)
        self.assertNotIn("known_counterexample", prompt)
        self.assertNotIn("expected_label", prompt)

    def test_false_seed_is_refuted_only_after_counterexample_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            response = self.response([1, 2], label="TRUE")

            def fake_ask(prompt: str, *, system: str, max_tokens: int) -> LLMResult:
                return LLMResult(response, "stub", "test-model")

            report_path = root / "false-report.json"
            report = run_falsifier(
                self.false_problem,
                report_path,
                counterexample_directory=root / "counterexamples",
                ask_function=fake_ask,
            )

            candidate = report["candidate_inputs"][0]
            self.assertEqual(candidate["input"], [1, 2])
            self.assertEqual(candidate["falsifier_status"], "REFUTED")
            self.assertEqual(
                candidate["failure_category"],
                FailureCategory.PROPERTY_VIOLATION.value,
            )
            self.assertEqual(candidate["harness_evidence"]["status"], "REFUTED")
            self.assertEqual(
                candidate["counterexample_replay"]["status"], "REPRODUCED"
            )
            self.assertTrue(Path(candidate["counterexample_path"]).is_file())
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), report)
            self.assertNotIn("verdict", json.dumps(report).lower())

    def test_true_seed_proposal_that_passes_is_rejected_as_non_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            response = self.response([1, 2])

            def fake_ask(prompt: str, *, system: str, max_tokens: int) -> LLMResult:
                return LLMResult(response, "stub", "test-model")

            report = run_falsifier(
                self.true_problem,
                root / "true-report.json",
                counterexample_directory=root / "counterexamples",
                ask_function=fake_ask,
            )

            candidate = report["candidate_inputs"][0]
            self.assertEqual(candidate["harness_evidence"]["status"], "PASSED")
            self.assertEqual(candidate["falsifier_status"], "REJECTED")
            self.assertIsNone(candidate["failure_category"])
            self.assertIsNone(candidate["counterexample_path"])
            self.assertIsNone(candidate["counterexample_replay"])
            self.assertFalse((root / "counterexamples").exists())

    def test_out_of_contract_falsifier_input_is_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            response = self.response([True, 1])

            def fake_ask(prompt: str, *, system: str, max_tokens: int) -> LLMResult:
                return LLMResult(response, "stub", "test-model")

            report = run_falsifier(
                self.false_problem,
                root / "invalid-report.json",
                counterexample_directory=root / "counterexamples",
                ask_function=fake_ask,
            )

            candidate = report["candidate_inputs"][0]
            self.assertEqual(candidate["falsifier_status"], "INVALID_EVIDENCE")
            self.assertEqual(
                candidate["failure_category"],
                FailureCategory.OUT_OF_CONTRACT.value,
            )
            self.assertIsNone(candidate["harness_evidence"])
            self.assertIn("OUTSIDE_CONTRACT", candidate["contract_status"])
            self.assertFalse((root / "counterexamples").exists())

    @patch("abacus.proposals.check_case")
    def test_timeout_is_unresolved_and_never_refuted(self, check_case):
        check_case.return_value = CaseEvidence(
            problem_id=self.false_problem["id"],
            input_value=(1, 2),
            input_valid=True,
            validity_reason=None,
            target_result=None,
            target_exception=None,
            oracle_result=None,
            status=HarnessStatus.TIMEOUT,
            explanation="target exceeded the subprocess timeout",
            failure_category=FailureCategory.TIMEOUT,
        )
        response = self.response([1, 2])

        def fake_ask(prompt: str, *, system: str, max_tokens: int) -> LLMResult:
            return LLMResult(response, "stub", "test-model")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            report = run_falsifier(
                self.false_problem,
                root / "timeout-report.json",
                counterexample_directory=root / "counterexamples",
                ask_function=fake_ask,
            )

        candidate = report["candidate_inputs"][0]
        self.assertEqual(candidate["falsifier_status"], "UNRESOLVED")
        self.assertEqual(candidate["failure_category"], FailureCategory.TIMEOUT.value)
        self.assertIsNone(candidate["counterexample_path"])

    def test_api_and_parse_failures_have_categories_without_candidate_results(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            def missing_key(*args, **kwargs) -> LLMResult:
                raise LLMConfigurationError("GEMINI_API_KEY is missing")

            api_report = run_falsifier(
                self.true_problem,
                root / "api-error.json",
                ask_function=missing_key,
            )
            self.assertEqual(
                api_report["run_failure_category"],
                FailureCategory.API_ERROR.value,
            )
            self.assertEqual(api_report["run_status"], "UNRESOLVED")
            self.assertNotIn("sk-", api_report["request_error"])

            def malformed(*args, **kwargs) -> LLMResult:
                return LLMResult("not JSON", "stub", "test-model")

            parse_report = run_falsifier(
                self.true_problem,
                root / "parse-error.json",
                ask_function=malformed,
            )
            self.assertEqual(
                parse_report["run_failure_category"],
                FailureCategory.PARSE_ERROR.value,
            )
            self.assertEqual(parse_report["run_status"], "INVALID_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
