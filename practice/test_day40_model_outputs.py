"""Fixture checks for the bounded, strict Day 40 model-output parsers."""

from __future__ import annotations

import json
import unittest

from abacus.schemas import (
    MAX_CANDIDATE_PROPOSALS,
    MAX_MODEL_OUTPUT_BYTES,
    MAX_MODEL_TEXT_CHARS,
    MAX_PLAN_SUGGESTIONS,
    MAX_PROPOSAL_INPUT_ITEMS,
    MAX_PROPOSAL_INTEGER,
    CandidateInputProposal,
    CandidateProposalsOutput,
    HypothesisOutput,
    ModelOutputEmptyError,
    ModelOutputExtraTextError,
    ModelOutputParseError,
    ModelOutputRefusalError,
    ModelOutputSchemaError,
    ModelOutputTooLargeError,
    ModelOutputTruncatedError,
    ModelOutputUnknownFieldsError,
    PlanOutput,
    parse_candidate_proposals,
    parse_hypothesis_output,
    parse_plan_output,
)


class StructuredModelOutputTests(unittest.TestCase):
    def test_valid_json_fixtures_return_typed_values(self) -> None:
        self.assertEqual(
            parse_hypothesis_output('{"hypothesis":"duplicates are preserved","rationale":"Check repeats."}'),
            HypothesisOutput("duplicates are preserved", "Check repeats."),
        )
        self.assertEqual(
            parse_plan_output('{"suggestions":["try an empty list","try duplicates"]}'),
            PlanOutput(("try an empty list", "try duplicates")),
        )
        self.assertEqual(
            parse_candidate_proposals(
                '{"proposals":[{"input":[3,-1,3],"rationale":"contains a duplicate"}]}'
            ),
            CandidateProposalsOutput(
                (CandidateInputProposal((3, -1, 3), "contains a duplicate"),)
            ),
        )

    def test_json_code_fences_are_accepted(self) -> None:
        self.assertEqual(
            parse_plan_output('```json\n{"suggestions":["check duplicates"]}\n```'),
            PlanOutput(("check duplicates",)),
        )

    def test_truncated_json_has_a_distinct_error(self) -> None:
        with self.assertRaises(ModelOutputTruncatedError):
            parse_hypothesis_output('{"hypothesis":"incomplete",')

    def test_invalid_json_has_a_distinct_error(self) -> None:
        with self.assertRaises(ModelOutputParseError):
            parse_plan_output('{not json}')
        with self.assertRaises(ModelOutputParseError):
            parse_plan_output('{"suggestions": }')

    def test_text_before_or_after_json_is_rejected_as_extra(self) -> None:
        with self.assertRaises(ModelOutputExtraTextError):
            parse_plan_output('{"suggestions":[]} trailing commentary')
        with self.assertRaises(ModelOutputExtraTextError):
            parse_plan_output('Here is the plan: {"suggestions":[]}')

    def test_empty_and_refusal_responses_are_distinct(self) -> None:
        with self.assertRaises(ModelOutputEmptyError):
            parse_plan_output("  \n")
        with self.assertRaises(ModelOutputRefusalError):
            parse_plan_output('{"refusal":"request declined"}')
        with self.assertRaises(ModelOutputRefusalError):
            parse_plan_output('{"suggestions":[]}', refused=True)

    def test_unknown_fields_have_a_distinct_error(self) -> None:
        untrusted_field = "PRIVATE_RESPONSE_TEXT"
        with self.assertRaises(ModelOutputUnknownFieldsError) as raised:
            parse_hypothesis_output(json.dumps({
                "hypothesis": "statement",
                "rationale": "why",
                untrusted_field: 1,
            }))
        self.assertNotIn(untrusted_field, str(raised.exception))

    def test_wrong_types_and_boolean_integer_substitution_are_rejected(self) -> None:
        with self.assertRaises(ModelOutputSchemaError):
            parse_plan_output('{"suggestions":"not an array"}')
        with self.assertRaises(ModelOutputSchemaError):
            parse_candidate_proposals('{"proposals":[{"input":[true],"rationale":"why"}]}')

    def test_text_and_collection_limits_are_enforced(self) -> None:
        with self.assertRaises(ModelOutputTooLargeError):
            parse_plan_output(" " + ("x" * MAX_MODEL_OUTPUT_BYTES))
        too_many = json.dumps({"proposals": [{"input": [], "rationale": "case"}] * (MAX_CANDIDATE_PROPOSALS + 1)})
        with self.assertRaises(ModelOutputSchemaError):
            parse_candidate_proposals(too_many)
        with self.assertRaises(ModelOutputSchemaError):
            parse_hypothesis_output(
                json.dumps({"hypothesis": "x" * (MAX_MODEL_TEXT_CHARS + 1), "rationale": "why"})
            )
        with self.assertRaises(ModelOutputSchemaError):
            parse_plan_output(json.dumps({"suggestions": ["x"] * (MAX_PLAN_SUGGESTIONS + 1)}))
        with self.assertRaises(ModelOutputSchemaError):
            parse_candidate_proposals(
                json.dumps({"proposals": [{"input": [1] * (MAX_PROPOSAL_INPUT_ITEMS + 1), "rationale": "why"}]})
            )
        with self.assertRaises(ModelOutputSchemaError):
            parse_candidate_proposals(
                json.dumps({"proposals": [{"input": [MAX_PROPOSAL_INTEGER + 1], "rationale": "why"}]})
            )

    def test_duplicate_keys_and_nonstandard_constants_are_rejected(self) -> None:
        with self.assertRaises(ModelOutputParseError):
            parse_plan_output('{"suggestions":[],"suggestions":["hidden"]}')
        with self.assertRaises(ModelOutputParseError):
            parse_plan_output('{"suggestions":[NaN]}')

    def test_errors_do_not_echo_untrusted_response_content(self) -> None:
        secret_like_text = '{"suggestions":"DO_NOT_ECHO_THIS"}'
        with self.assertRaises(ModelOutputSchemaError) as raised:
            parse_plan_output(secret_like_text)
        self.assertNotIn("DO_NOT_ECHO_THIS", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
