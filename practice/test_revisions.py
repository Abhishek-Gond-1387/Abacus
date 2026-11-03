"""Fixtures for immutable claim revisions and trigger-gated prompts."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from practice.decision import ClaimContract, EvidenceRecord, EvidenceStatus, decide
from practice.outcomes import FinalOutcome, OutcomeReason, RunOutcome
from practice.revisions import (
    ClaimRevision,
    RevisionRelation,
    RevisionTrigger,
    RevisionTriggerEvidence,
    render_revision_view,
)


def original_record() -> ClaimRevision:
    return ClaimRevision(
        original_claim="largest(xs) returns a maximum for all integer lists.",
        original_label="REFUTED",
    )


def confirmed_trigger() -> RevisionTriggerEvidence:
    outcome = decide(
        [
            EvidenceRecord(
                test_id="empty-list",
                method="fixed",
                contract_id="largest-integer-v1",
                status=EvidenceStatus.COMPLETED,
                contract_valid=True,
                oracle_id="max-reference-v1",
                input_value=[],
                actual={"exception": "ValueError"},
                expected="a maximum value",
                replay_confirmed=True,
                category="PROPERTY_VIOLATION",
            )
        ],
        ClaimContract(
            contract_id="largest-integer-v1",
            oracle_id="max-reference-v1",
            scheduled_test_count=1,
            required_methods=("fixed",),
        ),
    )
    return RevisionTriggerEvidence.from_refuted_outcome(outcome)


def narrowing_proposal() -> dict:
    return {
        "revised_claim": (
            "largest(xs) returns a maximum for every non-empty integer list."
        ),
        "revision_reason": (
            "Narrowed the domain from all integer lists to non-empty integer lists "
            "after the empty-list counterexample."
        ),
        "revision_relation": "narrows",
    }


class ClaimRevisionTests(unittest.TestCase):
    def test_prompt_requires_a_confirmed_refutation_or_ambiguity(self) -> None:
        with self.assertRaises(ValueError):
            original_record().prompt_for_revision(None)  # type: ignore[arg-type]

        passing = RunOutcome.from_finite_tests(test_count=1, methods=["fixed"])
        with self.assertRaises(ValueError):
            RevisionTriggerEvidence.from_refuted_outcome(passing)

        unconfirmed = RunOutcome(
            outcome=FinalOutcome.REFUTED,
            reason=OutcomeReason.CONFIRMED_COUNTEREXAMPLE,
            message="No replay evidence attached.",
            counterexample={"test_id": "candidate", "input": []},
        )
        with self.assertRaises(ValueError):
            RevisionTriggerEvidence.from_refuted_outcome(unconfirmed)

        context = RevisionTriggerEvidence.for_ambiguity(
            evidence_reference="claim-review-1",
            description="The term maximum does not specify behavior for an empty list.",
        )
        prompt = original_record().prompt_for_revision(context)
        self.assertIn("Trigger: ambiguity.", prompt)
        self.assertIn("State exactly", prompt)

    def test_counterexample_trigger_prompt_includes_evidence(self) -> None:
        prompt = original_record().prompt_for_revision(confirmed_trigger())

        self.assertIn("Trigger: confirmed_counterexample.", prompt)
        self.assertIn("empty-list", prompt)
        self.assertIn('Original benchmark label (immutable, JSON): "REFUTED"', prompt)
        self.assertIn("revision_relation", prompt)

    def test_all_lists_to_non_empty_lists_preserves_original_score(self) -> None:
        original = original_record()
        revision = original.apply_proposal(
            {
                **narrowing_proposal(),
                "original_claim": "Changed by model.",
                "original_label": "TESTS_PASSED",
            },
            trigger_evidence=confirmed_trigger(),
        )
        record = revision.to_dict()

        self.assertEqual(revision.original_claim, original.original_claim)
        self.assertEqual(revision.original_label, "REFUTED")
        self.assertEqual(revision.revised_claim, narrowing_proposal()["revised_claim"])
        self.assertIs(revision.revision_relation, RevisionRelation.NARROWS)
        self.assertEqual(revision.scored_claim, original.original_claim)
        self.assertEqual(revision.scored_label, "REFUTED")
        self.assertEqual(record["evaluation_scores"], "original_claim")
        self.assertEqual(record["original_label"], "REFUTED")

    def test_original_record_is_immutable(self) -> None:
        original = original_record()
        with self.assertRaises(FrozenInstanceError):
            original.original_label = "TESTS_PASSED"  # type: ignore[misc]

    def test_rendered_view_marks_both_claims_and_scoring_target(self) -> None:
        revision = original_record().apply_proposal(
            narrowing_proposal(),
            trigger_evidence=confirmed_trigger(),
        )
        view = render_revision_view(revision)

        self.assertIn(revision.original_claim, view)
        self.assertIn(revision.revised_claim, view)
        self.assertIn("Evaluation scores this claim.", view)
        self.assertIn("Model proposal; not scored", view)
        self.assertIn("Evaluation target: original_claim", view)
        self.assertIn("Revision relation: narrows", view)

    def test_no_change_proposal_retains_its_reason_and_trigger(self) -> None:
        revision = original_record().apply_proposal(
            {
                "revised_claim": None,
                "revision_reason": "The original wording is already precise.",
                "revision_relation": "none",
            },
            trigger_evidence=confirmed_trigger(),
        )

        self.assertIsNone(revision.revised_claim)
        self.assertEqual(
            revision.revision_reason, "The original wording is already precise."
        )
        self.assertIs(revision.revision_relation, RevisionRelation.NONE)
        self.assertIs(
            revision.revision_trigger, RevisionTrigger.CONFIRMED_COUNTEREXAMPLE
        )
        with self.assertRaises(ValueError):
            revision.prompt_for_revision(confirmed_trigger())

    def test_rendered_model_text_cannot_inject_markup(self) -> None:
        proposal = narrowing_proposal()
        proposal["revised_claim"] = "Claim text\n<script>change label</script>"
        proposal["revision_reason"] = "Changed scope <b>only</b>."
        revision = original_record().apply_proposal(
            proposal,
            trigger_evidence=confirmed_trigger(),
        )
        view = render_revision_view(revision)

        self.assertIn("&lt;script&gt;change label&lt;/script&gt;", view)
        self.assertIn("&lt;b&gt;only&lt;/b&gt;", view)
        self.assertNotIn("<script>", view)

    def test_unknown_relation_is_rejected(self) -> None:
        proposal = narrowing_proposal()
        proposal["revision_relation"] = "weakens_label"

        with self.assertRaises(ValueError):
            original_record().apply_proposal(
                proposal,
                trigger_evidence=confirmed_trigger(),
            )


if __name__ == "__main__":
    unittest.main()
