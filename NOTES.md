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
- Day 22 completed; Day 23: define the evidence-based decision policy.

## Day 21 review

Fixed edge cases and Hypothesis both exposed the duplicate-removal bug in the sorting seed and the incorrect result for all-negative inputs in the largest-value seed. Fixed cases made the boundary rationale visible; Hypothesis explored contract-valid lists and reduced its failing examples. Both sources used the same contract and trusted reference for each seed.

The offline LLM-style proposals found neither seeded bug: they proposed a sorted list without duplicates and a positive-only list. The invalid string and empty-list proposals were rejected as OUT_OF_CONTRACT before target execution. This shows why proposals need an independent checker; these fixtures were drafted for this review and did not come from a provider API.

## Day 22 outcomes

Added shared run-level outcome and reason enums plus a serializable outcome record. A completed finite suite is recorded as TESTS_PASSED with its count and methods; PROVEN remains in the vocabulary but requires formal-checker evidence and is not emitted by any finite-test helper. The Day 21 report now calls an individual passing case CASE_PASSED so it cannot be mistaken for a run verdict.
