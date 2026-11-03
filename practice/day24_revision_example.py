"""Write an offline example of a claim revision without changing its label."""

from pathlib import Path

if __package__:
    from .decision import ClaimContract, EvidenceRecord, EvidenceStatus, decide
    from .outcomes import FinalOutcome
    from .revisions import (
        ClaimRevision,
        RevisionRelation,
        RevisionTriggerEvidence,
        render_revision_view,
    )
else:
    from decision import ClaimContract, EvidenceRecord, EvidenceStatus, decide
    from outcomes import FinalOutcome
    from revisions import (
        ClaimRevision,
        RevisionRelation,
        RevisionTriggerEvidence,
        render_revision_view,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "practice" / "day24_revision_view.md"


def main() -> None:
    original = ClaimRevision(
        original_claim=(
            "largest(xs) returns the maximum value for every list of integers."
        ),
        original_label=FinalOutcome.REFUTED.value,
    )
    confirmed_failure = decide(
        [
            EvidenceRecord(
                test_id="empty-list-counterexample",
                method="fixed",
                contract_id="largest-integer-v1",
                status=EvidenceStatus.COMPLETED,
                contract_valid=True,
                oracle_id="max-reference-v1",
                input_value=[],
                actual={"exception": "ValueError"},
                expected="a maximum integer",
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
    trigger = RevisionTriggerEvidence.from_refuted_outcome(confirmed_failure)
    prompt = original.prompt_for_revision(trigger)
    if "State exactly which words" not in prompt:
        raise AssertionError("Revision prompt must request exact changes.")

    # This offline fixture represents a narrowing proposal; no model API is called.
    revised = original.apply_proposal(
        {
            "revised_claim": (
                "largest(xs) returns the maximum value for every non-empty "
                "list of integers."
            ),
            "revision_reason": (
                "Narrowed the input domain from all integer lists to non-empty "
                "integer lists because the empty list was a confirmed counterexample."
            ),
            "revision_relation": RevisionRelation.NARROWS.value,
        },
        trigger_evidence=trigger,
    )
    view = render_revision_view(revised)
    REPORT_PATH.write_text(view, encoding="utf-8")
    print(view)
    print(f"Saved view: {REPORT_PATH}")


if __name__ == "__main__":
    main()
