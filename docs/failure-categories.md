# Abacus failure categories

Failure categories explain why a check or proposal did not produce ordinary passing evidence. They are recorded separately from the harness or falsifier outcome. A failure category by itself never proves a claim false.

| Category | Meaning | Example |
| --- | --- | --- |
| `OUT_OF_CONTRACT` | The input violates the declared domain or preconditions. The target is not run. | A boolean is proposed for a `list[int]` contract that excludes booleans. |
| `TARGET_EXCEPTION` | The candidate raises while loading or processing a valid input. | `candidate([1, 2])` raises `ValueError`. |
| `PROPERTY_VIOLATION` | The trusted oracle confirms the candidate result violates the property. | Reverse sorting returns `[2, 1]` when `[1, 2]` is expected. |
| `TEST_ORACLE_DEFECT` | The independent oracle raises or returns its error status. | The oracle cannot complete a check for a contract-valid input. |
| `TIMEOUT` | The candidate exceeds the configured execution time. | A valid input triggers an infinite loop. |
| `SANDBOX_FAILURE` | The bounded runner or its result protocol fails. This name refers to the execution boundary; the current runner is not a security sandbox. | The child cannot start, exceeds the output cap, or returns no harness protocol result. |
| `API_ERROR` | The model request fails before a usable response is received. | The provider key is missing or the provider rejects the request. |
| `PARSE_ERROR` | The model response does not match the strict JSON proposal schema. | `candidate_inputs` is a string instead of an array. |
| `INTERNAL_ERROR` | Abacus encounters an unexpected error outside the target, oracle, or runner boundary. | Harness evidence assembly raises unexpectedly. |

## Outcome policy

- `CaseEvidence.failure_category` is `null` when a case passes. Refuted cases carry `PROPERTY_VIOLATION`; harness errors carry the most specific category available.
- A timeout, target exception, oracle defect, or runner failure is unresolved evidence. It is not a property refutation.
- The falsifier reports `REFUTED` only after the trusted harness reports `REFUTED`, saves the counterexample, and replay reproduces it. A timeout is reported as `UNRESOLVED`; an input outside the contract is invalid evidence.
- Proposal batches classify request failures as `API_ERROR` and malformed responses as `PARSE_ERROR`. Error messages contain safe provider-facing summaries, not keys or full environment dumps.

The shared enum and definitions live in `src/abacus/failure_categories.py`. Focused fixtures exercise contract rejection, target exceptions, oracle-confirmed violations, oracle defects, timeouts, runner failures, API errors, parse errors, and internal errors.
