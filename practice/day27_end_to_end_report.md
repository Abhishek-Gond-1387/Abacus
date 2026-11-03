# Day 27 — End-to-end pilot

The command `python -m abacus run <problem.json>` validates the problem file and its input cases, executes the configured local checks, applies the evidence decision policy, optionally records a claim revision after a confirmed counterexample, and saves a JSON run log.

## Results

| Example | Cases | Outcome | Evidence |
|---|---:|---|---|
| `p01_true_sort` | 31 | `TESTS_PASSED` | All fixed, Hypothesis, and offline proposal cases agreed with the trusted reference. |
| `p02_false_sort` | 31 | `REFUTED` | Input `[3, -1, 3, 0]` produced `[-1, 0, 3]` instead of `[-1, 0, 3, 3]`; replay reproduced the mismatch. |

The false example's optional offline revision proposes returning distinct sorted values. The original claim remains the scored claim and its `REFUTED` label remains unchanged. Suggestions and proposal fixtures are marked as offline suggestions; none are treated as facts.

## Run logs and budget

- `runs/p01_true_sort.json`
- `runs/p02_false_sort.json`
- Both logs record 0 model calls, 0 tokens, and $0 estimated cost. No provider API was called.
- An injected optional proposal-stage failure is recorded with its error and budget usage; the run returns `ERROR` and still saves its JSON log.

The pilot demonstrates the evidence flow with local fixtures. It does not provide a live model integration or formal proof; a finite passing run remains `TESTS_PASSED`.
