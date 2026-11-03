# Day 21 — Input source comparison

This is a bounded review of two intentionally faulty, hand-written targets. Each source uses the same input contract and trusted reference for a given problem. A confirmed counterexample is an in-contract input whose target output differs from that reference.

- Python: 3.15.2
- Hypothesis: 6.170.14
- Hypothesis setting: up to 100 examples; integer values from -20 through 20; lists up to 8 items; deterministic mode.
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

| Seed problem | Source | Cases generated | Valid | Confirmed counterexamples | Runtime (ms) | Failures |
|---|---|---:|---:|---:|---:|---|
| sort-preserves-duplicates | Fixed edge cases | 5 | 5 | 1 | 0.094 | None |
| sort-preserves-duplicates | Hypothesis | 35 | 35 | 12 | 279.686 | None |
| sort-preserves-duplicates | Offline LLM proposals | 2 | 1 | 0 | 0.015 | OUT_OF_CONTRACT: 1 |
| largest-negative-values | Fixed edge cases | 4 | 4 | 2 | 0.021 | None |
| largest-negative-values | Hypothesis | 16 | 16 | 3 | 22.588 | None |
| largest-negative-values | Offline LLM proposals | 2 | 1 | 0 | 0.012 | OUT_OF_CONTRACT: 1 |

## Findings

### sort-preserves-duplicates — Fixed edge cases

- input `[4, 4]` → PROPERTY_VIOLATION (target returned `[4]`, reference expected `[4, 4]`)

### sort-preserves-duplicates — Hypothesis

- input `[-2, -2]` → PROPERTY_VIOLATION (target returned `[-2]`, reference expected `[-2, -2]`)
- input `[16, -1, 13, 16, 20, 15]` → PROPERTY_VIOLATION (target returned `[-1, 13, 15, 16, 20]`, reference expected `[-1, 13, 15, 16, 16, 20]`)
- input `[16, -1, 13, 16, 20, 16]` → PROPERTY_VIOLATION (target returned `[-1, 13, 16, 20]`, reference expected `[-1, 13, 16, 16, 16, 20]`)
- input `[16, 16, 13, 16, 20, 16]` → PROPERTY_VIOLATION (target returned `[13, 16, 20]`, reference expected `[13, 16, 16, 16, 16, 20]`)
- input `[16, 16, 16, 16, 20, 16]` → PROPERTY_VIOLATION (target returned `[16, 20]`, reference expected `[16, 16, 16, 16, 16, 20]`)
- input `[16, 16]` → PROPERTY_VIOLATION (target returned `[16]`, reference expected `[16, 16]`)
- input `[15, 4, 15, -3]` → PROPERTY_VIOLATION (target returned `[-3, 4, 15]`, reference expected `[-3, 4, 15, 15]`)
- input `[15, 4, 15, 15]` → PROPERTY_VIOLATION (target returned `[4, 15]`, reference expected `[4, 15, 15, 15]`)
- input `[15, 15, 15, 15]` → PROPERTY_VIOLATION (target returned `[15]`, reference expected `[15, 15, 15, 15]`)
- input `[16, -17, -17, -1, 6, -4, -19, -9]` → PROPERTY_VIOLATION (target returned `[-19, -17, -9, -4, -1, 6, 16]`, reference expected `[-19, -17, -17, -9, -4, -1, 6, 16]`)
- input `[2, 2]` → PROPERTY_VIOLATION (target returned `[2]`, reference expected `[2, 2]`)
- input `[0, 0]` → PROPERTY_VIOLATION (target returned `[0]`, reference expected `[0, 0]`)

### sort-preserves-duplicates — Offline LLM proposals

- input `"not a list"` → OUT_OF_CONTRACT (Input did not satisfy the seed problem contract.)

### largest-negative-values — Fixed edge cases

- input `[-7]` → PROPERTY_VIOLATION (target returned `0`, reference expected `-7`)
- input `[-4, -1, -9]` → PROPERTY_VIOLATION (target returned `0`, reference expected `-1`)

### largest-negative-values — Hypothesis

- input `[-18]` → PROPERTY_VIOLATION (target returned `0`, reference expected `-18`)
- input `[-16]` → PROPERTY_VIOLATION (target returned `0`, reference expected `-16`)
- input `[-1]` → PROPERTY_VIOLATION (target returned `0`, reference expected `-1`)

### largest-negative-values — Offline LLM proposals

- input `[]` → OUT_OF_CONTRACT (Input did not satisfy the seed problem contract.)

## Interpretation

The fixed and Hypothesis sources find the seeded defects. The offline LLM-style proposals miss both defects because they do not include duplicate values or an all-negative list. The malformed sort proposal and empty largest proposal are rejected as OUT_OF_CONTRACT before the target or oracle is called.

This small, intentionally seeded comparison demonstrates the evidence flow; it does not measure general LLM or property-based-testing performance. Hypothesis stops a problem's run after its first confirmed mismatch and may evaluate extra examples while shrinking it. Hypothesis's generated count includes property function invocations during shrinking. Runtime is local wall-clock time for source generation and harness checks; it does not include any model latency.
