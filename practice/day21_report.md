# Day 21 — Input source comparison

This is a bounded review of two intentionally faulty, hand-written targets. Each source uses the same input contract and trusted reference for a given problem. A confirmed counterexample is an in-contract input whose target output differs from that reference. This report records case-level evidence, not final run verdicts.

- Python: 3.15.2
- Hypothesis: 6.170.14
- Hypothesis setting: seed 2103; up to 100 examples; integer values from -20 through 20; lists up to 8 items.
- LLM proposals: offline proposal fixtures drafted for this review; no provider API was called.

## Seed contracts

### sort-preserves-duplicates

- Claim: Return the input integers in ascending order, preserving duplicates.
- Contract: A list containing only integers; empty lists are allowed.

### largest-negative-values

- Claim: For a non-empty integer list, return its largest value.
- Contract: A non-empty list containing only integers.

## Offline LLM proposal inspection

### sort-preserves-duplicates

- `[3, 1, 2]` — Try a short unsorted list.
- `"not a list"` — Malformed proposal used to check validation.

### largest-negative-values

- `[2, 1, 3]` — Try a small positive list.
- `[]` — Empty list is outside the non-empty contract.

## Final outcome vocabulary

A case-level CASE_PASSED result means only that one input satisfied the property. It is not the run-level TESTS_PASSED verdict.

- REFUTED
- TESTS_PASSED
- PROVEN
- UNRESOLVED
- ERROR

Outcome reasons include confirmed_counterexample, no_counterexample_found, budget_exhausted, conflicting_evidence, and external_error.

| Seed problem | Source | Cases generated | Valid | Confirmed counterexamples | Runtime (ms) | Failures |
|---|---|---:|---:|---:|---:|---|
| sort-preserves-duplicates | Fixed edge cases | 5 | 5 | 1 | 0.082 | None |
| sort-preserves-duplicates | Hypothesis | 36 | 36 | 18 | 224.700 | None |
| sort-preserves-duplicates | Offline LLM proposals | 2 | 1 | 0 | 0.016 | OUT_OF_CONTRACT: 1 |
| largest-negative-values | Fixed edge cases | 4 | 4 | 2 | 0.023 | None |
| largest-negative-values | Hypothesis | 15 | 15 | 2 | 41.511 | None |
| largest-negative-values | Offline LLM proposals | 2 | 1 | 0 | 0.021 | OUT_OF_CONTRACT: 1 |

## Findings

### sort-preserves-duplicates — Fixed edge cases

- input `[4, 4]` → PROPERTY_VIOLATION (target returned `[4]`, reference expected `[4, 4]`)

### sort-preserves-duplicates — Hypothesis

- input `[-3, -13, -3, -19]` → PROPERTY_VIOLATION (target returned `[-19, -13, -3]`, reference expected `[-19, -13, -3, -3]`)
- input `[-3, -13, -3, -3]` → PROPERTY_VIOLATION (target returned `[-13, -3]`, reference expected `[-13, -3, -3, -3]`)
- input `[-3, -3, -3, -3]` → PROPERTY_VIOLATION (target returned `[-3]`, reference expected `[-3, -3, -3, -3]`)
- input `[-11, -9, 6, -15, 18, 19, -11, -7]` → PROPERTY_VIOLATION (target returned `[-15, -11, -9, -7, 6, 18, 19]`, reference expected `[-15, -11, -11, -9, -7, 6, 18, 19]`)
- input `[-11, -9, 6, -11, 18, 19, -11, -7]` → PROPERTY_VIOLATION (target returned `[-11, -9, -7, 6, 18, 19]`, reference expected `[-11, -11, -11, -9, -7, 6, 18, 19]`)
- input `[-11, -9, 6, -11, 18, -11, -11, -7]` → PROPERTY_VIOLATION (target returned `[-11, -9, -7, 6, 18]`, reference expected `[-11, -11, -11, -11, -9, -7, 6, 18]`)
- input `[-11, -9, 6, -11, -11, -11, -11, -7]` → PROPERTY_VIOLATION (target returned `[-11, -9, -7, 6]`, reference expected `[-11, -11, -11, -11, -11, -9, -7, 6]`)
- input `[-11, -9, 6, -11, -11, -11, 6, -7]` → PROPERTY_VIOLATION (target returned `[-11, -9, -7, 6]`, reference expected `[-11, -11, -11, -11, -9, -7, 6, 6]`)
- input `[-11, -9, -11, -11, -11, -11, 6, -7]` → PROPERTY_VIOLATION (target returned `[-11, -9, -7, 6]`, reference expected `[-11, -11, -11, -11, -11, -9, -7, 6]`)
- input `[4, -18, 4]` → PROPERTY_VIOLATION (target returned `[-18, 4]`, reference expected `[-18, 4, 4]`)
- input `[-18, -18, 4]` → PROPERTY_VIOLATION (target returned `[-18, 4]`, reference expected `[-18, -18, 4]`)
- input `[-18, 4, 4]` → PROPERTY_VIOLATION (target returned `[-18, 4]`, reference expected `[-18, 4, 4]`)
- input `[4, 4, 4]` → PROPERTY_VIOLATION (target returned `[4]`, reference expected `[4, 4, 4]`)
- input `[5, 12, -16, 12, -12, 9, -13, -11]` → PROPERTY_VIOLATION (target returned `[-16, -13, -12, -11, 5, 9, 12]`, reference expected `[-16, -13, -12, -11, 5, 9, 12, 12]`)
- input `[5, 12, -12, 12, -12, 9, -13, -11]` → PROPERTY_VIOLATION (target returned `[-13, -12, -11, 5, 9, 12]`, reference expected `[-13, -12, -12, -11, 5, 9, 12, 12]`)
- input `[4, 4, 0]` → PROPERTY_VIOLATION (target returned `[0, 4]`, reference expected `[0, 4, 4]`)
- input `[4, 4]` → PROPERTY_VIOLATION (target returned `[4]`, reference expected `[4, 4]`)
- input `[0, 0]` → PROPERTY_VIOLATION (target returned `[0]`, reference expected `[0, 0]`)

### sort-preserves-duplicates — Offline LLM proposals

- input `"not a list"` → OUT_OF_CONTRACT (Input did not satisfy the seed problem contract.)

### largest-negative-values — Fixed edge cases

- input `[-7]` → PROPERTY_VIOLATION (target returned `0`, reference expected `-7`)
- input `[-4, -1, -9]` → PROPERTY_VIOLATION (target returned `0`, reference expected `-1`)

### largest-negative-values — Hypothesis

- input `[-15]` → PROPERTY_VIOLATION (target returned `0`, reference expected `-15`)
- input `[-1]` → PROPERTY_VIOLATION (target returned `0`, reference expected `-1`)

### largest-negative-values — Offline LLM proposals

- input `[]` → OUT_OF_CONTRACT (Input did not satisfy the seed problem contract.)

## Interpretation

The fixed and Hypothesis sources find the seeded defects. The offline LLM-style proposals miss both defects because they do not include duplicate values or an all-negative list. The malformed sort proposal and empty largest proposal are rejected as OUT_OF_CONTRACT before the target or oracle is called.

This small, intentionally seeded comparison demonstrates the evidence flow; it does not measure general LLM or property-based-testing performance. Hypothesis stops a problem's run after its first confirmed mismatch and may evaluate extra examples while shrinking it. Hypothesis's generated count includes property function invocations during shrinking. Runtime is local wall-clock time for source generation and harness checks; it does not include any model latency.
