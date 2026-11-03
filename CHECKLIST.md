# Day checklist

## Day 21 — Week 3 review

- [x] Compare fixed edge cases, Hypothesis cases, and offline LLM-style proposals on the same seed problems.
- [x] Use one contract and trusted reference per seed problem.
- [x] Record case counts, valid inputs, confirmed counterexamples, runtime, and failures.
- [x] Fix the Hypothesis seed and confirm repeated runs generate the same case sequence.
- [x] Inspect missed bugs and reject at least one invalid proposal before target execution.
- [x] Record findings in NOTES.md and practice/day21_report.md.

## Day 22 — Define final outcomes in code

- [x] Define the shared REFUTED, TESTS_PASSED, PROVEN, UNRESOLVED, and ERROR vocabulary.
- [x] Add machine-readable outcome reasons and supporting run-record fields.
- [x] Keep PROVEN reserved for a formal checker and proof evidence; finite tests return TESTS_PASSED.
- [x] Update the README glossary and Day 21 report labels.
- [x] Search old PASS, FAIL, and SURVIVED labels and clarify case-level labels.
- [x] Verify a finite passing run records TESTS_PASSED and the finite-test helper cannot return PROVEN.
