# Abacus run-record schema, version 2

`practice/run_records.py` defines the version-2 record contract. `save_run_record()` validates a record before writing JSON; `load_run_record()` validates it when read. Every record has a UUID run ID, schema version, run status, and timezone-aware start/finish timestamps.

## Required record contents

| Section | Stored information |
|---|---|
| `problem` | Problem ID, dataset version, dataset SHA-256, problem-spec SHA-256, original claim, and input contract. The dataset body stores fixed inputs, proposal fixtures, and Hypothesis settings so its hash can be recomputed. |
| `target` | Allowlisted target ID, target-source SHA-256, and runner-source SHA-256. |
| `provenance` | Git revision and dirty state, Python/platform/Hypothesis/Abacus versions. Unknown Git revision is represented by `null` and explained in `unknown_values`. |
| `model` | Provider/model IDs, whether a provider API was called, plan/proposal/revision template versions, and suggestion/proposal status. This pilot records fixture sources and no provider calls. |
| `generation` | Methods, seeds, settings and budgets, scheduled/generated/validated counts, and per-method counts. |
| `model_proposals` | Each proposal ID, source, input, rationale, validation flag, and evaluation status. |
| `validated_candidates` | Candidate inputs with their test ID, method, and contract-validation result. |
| `evidence` | Per-test contract, status, input, target output, oracle ID/output, category, and replay confirmation. |
| `replay_details` | Replayed test IDs, inputs, reproduced outputs, and confirmation status. |
| `outcome` | Run-level outcome and required reason, message, methods/count, and evidence references. REFUTED includes its replay-confirmed counterexample. |
| `completion` | `complete`, `partial`, or `error`, scheduled/completed counts, and explicit incomplete reasons. This is separate from the verdict: a refutation can remain conclusive if later checks stop. |
| `usage` and `budget` | Model-call attempts, successful/failed/retry counts, provider-reported input/output/total tokens, per-stage and total duration, dated pricing snapshot, estimated/actual cost, configured limits, and explicit unknown values. With no provider call, token use and pricing are `not_applicable`; a call without usage or price metadata is `unknown`, never guessed as zero. |
| `revision` and `errors` | Optional separate claim revision and structured errors. Revision never replaces the scored original claim. |

SHA-256 values use canonical UTF-8 JSON with sorted keys and compact separators for problem/dataset data. Target hashes cover the allowlisted function source. `run_status` describes execution completeness; `outcome.outcome` describes the evidence verdict.

Before a run record is written, credential-like fields and recognizable secrets in text are redacted. Budget logs use the same text/field sanitizer. The stored `dataset_sha256` is recalculated from the redacted dataset body so validation still succeeds; `problem_spec_sha256` remains the SHA-256 fingerprint of the original problem input and does not contain its plaintext.

New resource fields use `usage.resource_usage_version: 1`; older schema-v2 records without that marker remain loadable. Provider usage accepts `input_tokens`/`output_tokens` and the common `prompt_tokens`/`completion_tokens` aliases. Add an optional `pricing` object to a problem only after checking a provider's current official pricing page; the record stores the URL and `checked_at` date. `python -m abacus summarize-runs [problem_id]` reports per-run medians and ranges and keeps unknown/not-applicable counts distinct.

## Samples

- `practice/samples/run_complete.v2.json` is a complete two-case `TESTS_PASSED` record.
- `practice/samples/run_partial.v2.json` is an accepted `UNRESOLVED` record with one of two cases completed and `completion.status: "partial"` because of a round limit.

Run `python -m practice.day29_record_examples` to regenerate these files. The script uses `save_run_record()`, so both records are schema-validated before they are written. The schema tests also reject records missing the dataset version, outcome reason, or evidence references.

Day 27's earlier ad hoc records used schema version 1. New CLI runs use version 2. Default run files use a timestamp and UUID, and the save layer refuses to overwrite an existing destination.
