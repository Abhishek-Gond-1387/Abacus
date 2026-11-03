from __future__ import annotations

import json
import unittest
from pathlib import Path

from abacus.harness import HarnessStatus
from abacus.errors import LLMConfigurationError
from abacus.failure_categories import FailureCategory
from abacus.llm import LLMResult
from abacus.problems import load_problem
from abacus.proposals import (
    ProposalStatus,
    build_test_idea_prompt,
    evaluate_proposal_response,
    request_test_ideas,
)


PROBLEMS_DIRECTORY = Path(__file__).resolve().parents[1] / "problems"


class ModelProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.true_problem = load_problem(
            PROBLEMS_DIRECTORY / "sort-ascending-true.json"
        )

    def test_prompt_includes_claim_code_domain_and_preconditions(self) -> None:
        system, prompt = build_test_idea_prompt(self.true_problem)

        self.assertIn("candidate test inputs only", system)
        self.assertIn(self.true_problem["claim"], prompt)
        self.assertIn(json.dumps(self.true_problem["code"]), prompt)
        self.assertIn("input_type", prompt)
        self.assertIn("input_is_list", prompt)
        self.assertIn("Do not include a truth judgment", prompt)

    def test_valid_model_idea_is_checked_by_the_harness(self) -> None:
        text = json.dumps(
            {
                "candidate_inputs": [
                    {"input": [3, 1, 2], "rationale": "Mixed order exercises sorting."}
                ]
            }
        )
        received: dict[str, str] = {}

        def fake_ask(prompt: str, *, system: str, max_tokens: int) -> LLMResult:
            received["prompt"] = prompt
            received["system"] = system
            return LLMResult(text, "stub", "test-model")

        batch = request_test_ideas(self.true_problem, ask_function=fake_ask)

        self.assertEqual(batch.provider, "stub")
        self.assertEqual(batch.model, "test-model")
        self.assertEqual(len(batch.ideas), 1)
        self.assertEqual(batch.ideas[0].source, "model_proposed")
        self.assertEqual(batch.ideas[0].status, ProposalStatus.CHECKED)
        self.assertIsNone(batch.ideas[0].failure_category)
        self.assertEqual(batch.ideas[0].harness_evidence.status, HarnessStatus.PASSED)
        self.assertEqual(
            batch.ideas[0].harness_evidence.oracle_result.status.value,
            "PASSED",
        )
        self.assertNotIn("verdict", batch.as_dict())
        self.assertIn("Do not include a truth judgment", received["prompt"])
        self.assertIn("candidate test inputs only", received["system"])

    def test_malformed_json_is_rejected_and_logged(self) -> None:
        malformed = '{"candidate_inputs":['

        with self.assertLogs("abacus.proposals", level="WARNING") as captured:
            batch = evaluate_proposal_response(self.true_problem, malformed)

        self.assertTrue(batch.parse_error)
        self.assertEqual(batch.failure_category, FailureCategory.PARSE_ERROR)
        self.assertEqual(batch.ideas, ())
        self.assertIn("Rejected malformed", captured.output[0])

    def test_wrong_types_duplicate_keys_and_verdict_fields_are_rejected(self) -> None:
        invalid_responses = (
            json.dumps({"candidate_inputs": "not-an-array"}),
            json.dumps(
                {"candidate_inputs": [{"input": [1], "rationale": 42}]}
            ),
            '{"candidate_inputs":[],"verdict":"TRUE"}',
            '{"candidate_inputs":[],"candidate_inputs":[]}',
        )

        for response in invalid_responses:
            with self.subTest(response=response):
                batch = evaluate_proposal_response(self.true_problem, response)
                self.assertTrue(batch.parse_error)
                self.assertEqual(batch.failure_category, FailureCategory.PARSE_ERROR)
                self.assertEqual(batch.ideas, ())

    def test_out_of_contract_proposal_is_rejected_without_execution(self) -> None:
        problem = dict(self.true_problem)
        problem["code"] = "raise AssertionError('out-of-contract target ran')"
        response = json.dumps(
            {
                "candidate_inputs": [
                    {
                        "input": [True, 1],
                        "rationale": "Boolean value probes a Python type edge.",
                    }
                ]
            }
        )

        with self.assertLogs("abacus.proposals", level="WARNING") as captured:
            batch = evaluate_proposal_response(problem, response)

        self.assertEqual(len(batch.ideas), 1)
        idea = batch.ideas[0]
        self.assertEqual(idea.source, "model_proposed")
        self.assertEqual(idea.status, ProposalStatus.REJECTED_OUT_OF_CONTRACT)
        self.assertEqual(idea.failure_category, FailureCategory.OUT_OF_CONTRACT)
        self.assertIsNone(idea.harness_evidence)
        self.assertIn("booleans are excluded", idea.contract_reason)
        self.assertIn("OUT_OF_CONTRACT", captured.output[0])

    def test_model_configuration_failure_has_safe_api_category(self) -> None:
        def missing_key(*args, **kwargs) -> LLMResult:
            raise LLMConfigurationError("GEMINI_API_KEY is missing")

        batch = request_test_ideas(self.true_problem, ask_function=missing_key)

        self.assertEqual(batch.failure_category, FailureCategory.API_ERROR)
        self.assertIn("configuration", batch.request_error)
        self.assertNotIn("sk-", batch.request_error)


if __name__ == "__main__":
    unittest.main()
