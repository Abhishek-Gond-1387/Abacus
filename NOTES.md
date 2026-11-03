# Abacus learning notes

## Environment

- Python: 3.15.2
- Virtual environment: `.venv`

## Learned

- Small functions are easier to check when their input and edge-case behavior are clear.
- `pathlib.Path` keeps file paths independent of the terminal's current directory.
- JSON round-trips preserve structured data; UTF-8 keeps non-ASCII text readable.

## Confusing

- The `py` launcher is unavailable here; use the working `python` command.
- `largest([])` has no natural largest value, so this exercise raises `ValueError`.

## Next

- Day 4 completed: staged named files, reviewed the staged diff, and created the first local commit.
- Day 24 completed; Day 25: add round, time, and token budgets.

## Day 21 review

Fixed edge cases and Hypothesis both exposed the duplicate-removal bug in the sorting seed and the incorrect result for all-negative inputs in the largest-value seed. Fixed cases made the boundary rationale visible; Hypothesis explored contract-valid lists and reduced its failing examples. Both sources used the same contract and trusted reference for each seed.

The offline LLM-style proposals found neither seeded bug: they proposed a sorted list without duplicates and a positive-only list. The invalid string and empty-list proposals were rejected as OUT_OF_CONTRACT before target execution. This shows why proposals need an independent checker; these fixtures were drafted for this review and did not come from a provider API.

## Day 22 outcomes

Added shared run-level outcome and reason enums plus a serializable outcome record. A completed finite suite is recorded as TESTS_PASSED with its count and methods; PROVEN remains in the vocabulary but requires formal-checker evidence and is not emitted by any finite-test helper. The Day 21 report now calls an individual passing case CASE_PASSED so it cannot be mistaken for a run verdict.

## Day 23 decision policy

Added a pure decide function that consumes normalized contract/evidence records and selects only REFUTED, TESTS_PASSED, UNRESOLVED, or ERROR. A counterexample must be contract-valid, use the configured oracle, and reproduce on replay; incomplete, invalid, conflicting, timed-out, and oracle-less runs stay UNRESOLVED. API and internal failures return ERROR with their category.

Standard-library fixtures cover the outcome paths and verify that changing extra LLM annotations does not change a result. The policy has no path to PROVEN; finite passing evidence remains TESTS_PASSED.

## Day 24 claim revisions

Added immutable original claim and label fields, separate revision text/reason/relation, and a trigger-evidence gate for revision prompts. The example narrows “all integer lists” to “non-empty integer lists” after a confirmed empty-list counterexample; the original REFUTED label and scored claim stay unchanged.

The revision view shows the original and proposed claim side by side and labels which one is scored. Revision proposals are structured fixtures; no provider API is called.
