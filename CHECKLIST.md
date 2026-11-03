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

## Day 23 — Implement the evidence-based decision policy

- [x] Add a pure decide(evidence_records, claim_contract) function with no model calls.
- [x] Require contract-valid evidence, the configured usable oracle, and successful replay before REFUTED.
- [x] Return TESTS_PASSED only after every scheduled test and required method completes.
- [x] Return UNRESOLVED for timeout, invalid/conflicting, incomplete, or oracle-less evidence.
- [x] Return ERROR with a category for API and internal failures.
- [x] Keep PROVEN unavailable to the finite-evidence decision path.
- [x] Add fixtures for every outcome, contradictions, insufficient evidence, and ignored LLM wording.

## Day 24 — Store revisions without rewriting history

- [x] Store original_claim, original_label, revised_claim, revision_reason, and revision_relation separately.
- [x] Restrict revision_relation to clarifies, narrows, changes_meaning, or none.
- [x] Gate prompts on a confirmed counterexample or recorded ambiguity; ask for exact changes.
- [x] Keep the original benchmark label and scored claim immutable.
- [x] Render original and revised claims and mark the original as the evaluation target.
- [x] Exercise the all-lists to non-empty-lists narrowing example.

## Day 25 — Add round, time, and token budgets

- [x] Configure maximum rounds, wall time, model-call attempts, tokens, and cost.
- [x] Reserve and check the next call's estimated time/tokens/cost before any API call.
- [x] Return UNRESOLVED with budget_exhausted when evidence is incomplete at a stop.
- [x] Save configured limits, usage, attempts/retries, and stop reason to a partial JSON log.
- [x] Verify normal completion and deliberately tiny budgets.
- [x] Count retries against call, wall-time, token, and cost budgets.

## Day 26 — Check the checker

- [x] Add correct and known-defective sort and largest fixture functions.
- [x] Check fixture outputs against manually written expected answers.
- [x] Inject a faulty oracle and detect its disagreement with the manual fixtures.
- [x] Demonstrate that a faulty oracle can falsely accuse a correct target.
- [x] Check sort idempotence and record that it misses duplicate removal.
- [x] Replay all saved Day 21 counterexamples.
- [x] Record remaining oracle uncertainty and reviewer availability.

## Day 27 — Connect the end-to-end pilot

- [x] Add a CLI command that accepts a JSON problem file.
- [x] Validate the complete problem schema and all supplied test inputs before evaluation.
- [x] Keep plan suggestions labeled as suggestions and target/oracle selection allowlisted.
- [x] Run fixed, deterministic Hypothesis, and optional offline proposal cases through the trusted harness.
- [x] Confirm every mismatch by replay before applying the evidence-based verdict policy.
- [x] Save verdict, evidence, revision, errors, and budget usage to JSON logs.
- [x] Verify a true example returns TESTS_PASSED and a false example returns replay-confirmed REFUTED.
- [x] Inject an optional proposal-stage failure and verify the error and budget log are still saved.

## Day 28 — Week 4 verdict semantics review

- [x] Review run-level labels and separate them from case-level categories.
- [x] Walk through the refutation input, actual output, expected output, and replay result.
- [x] Explain why the true example's TESTS_PASSED result is not a proof.
- [x] Show that a claim revision preserves the original scored claim and label.
- [x] Record unresolved design questions without changing outcome labels.
- [x] Add compact examples that distinguish REFUTED, TESTS_PASSED, UNRESOLVED, and ERROR.

## Day 29 — Design a complete run record

- [x] Add a versioned run-record contract and unique run ID.
- [x] Record problem/dataset version and hash, original claim/contract, target-code hash, template versions, provider/model identity, timestamp, Git revision, and software versions.
- [x] Record generation methods/seeds/counts, proposals, validated candidates, oracle results, and replay evidence.
- [x] Record outcome/reason/references, calls, reported tokens, duration, estimated/actual cost, budgets, and explicit unknown values.
- [x] Add complete and partial sample run records.
- [x] Validate run records before saving; reject missing dataset version, outcome reason, or evidence references.
- [x] Accept a valid partial run only with an explicit partial status and incomplete reason.

## Day 30 — Save runs atomically and uniquely

- [x] Confirm `runs/` is ignored by Git.
- [x] Give each run a unique UUID and timestamp-based default filename.
- [x] Flush a same-directory temporary record and rename it into place without overwriting existing records.
- [x] Leave a parseable `.incomplete` marker with run ID and temporary-file path if save is interrupted.
- [x] Add commands to list runs by problem and inspect a selected run ID.
- [x] Run the same problem twice and verify both records remain distinct and valid.

## Day 31 — Prevent secret leakage in logs

- [x] Redact structured values under credential-like field names before saving logs.
- [x] Scrub labeled secrets, authorization headers, common token formats, private-key blocks, and configured secret environment values from text.
- [x] Apply the sanitizer to versioned run records and budget logs, including emergency run failures.
- [x] Keep numeric usage counters intact and recompute the dataset hash from the sanitized stored dataset.
- [x] Document the redaction scope and hash behavior.
- [x] Trigger a simulated error with a fake environment secret and confirm it is absent from the saved log and captured CLI output.

## Day 32 — Track tokens, calls, time, and cost

- [x] Normalize provider-reported input/output token usage; retain `unknown` when a call has no usage metadata.
- [x] Record model-call attempts, successful calls, failed calls, and retry attempts separately.
- [x] Measure planning, proposal, test, and total durations; mark unconfigured stages explicitly.
- [x] Support model-specific input/output rates with pricing source URL and checked date; leave missing costs unknown.
- [x] Add a run summary with medians and ranges for measured usage.
- [x] Test that absent provider usage stays unknown instead of becoming zero.

## Day 33 — Build a useful run viewer

- [x] Add `view-run <run_id>` for readable summaries while keeping raw `show-run` available.
- [x] Display claim, contract, verdict/reason, test methods/counts, candidate counterexamples, and replay status.
- [x] Separate unverified model suggestions from harness-recorded evidence.
- [x] Mark `TESTS_PASSED` as finite testing, not proof.
- [x] Keep completed evidence, errors, and incomplete reasons visible for partial/error runs.
- [x] Exercise true, false, unresolved, and error run records.

## Day 34 — Handle retries and partial failures

- [x] Classify safe transient errors separately from authentication, model/configuration, schema, programming, and ambiguous response-loss failures.
- [x] Retry only safe transient failures with a small bounded exponential backoff.
- [x] Reserve budgets for each attempt and record failure categories, failed calls, and retry counts.
- [x] Save atomic progress checkpoints after completed test, proposal, and revision stages.
- [x] Avoid retrying timeouts or lost responses automatically and mark their outcome/billing ambiguity.
- [x] Preserve completed checkpoint evidence and budget state in a schema-valid emergency `ERROR` record.
- [x] Simulate transient recovery, permanent authentication failure, ambiguous response loss, budget exhaustion, and a later-stage crash.

## Day 35 — Audit runs from their records

- [x] Save and validate representative REFUTED, TESTS_PASSED, UNRESOLVED, and ERROR run records.
- [x] Independently replay the saved confirmed counterexample from its recorded input.
- [x] Check that offline settings, template versions, code hashes, and Git provenance explain each run; provider/model IDs are explicitly not applicable because no API was called.
- [x] Scan tracked files, saved run files, and checked-in examples for recognized raw-key patterns; run the secret-redaction regression test.
- [x] Record audit gaps and the prompt/request metadata needed before any future hosted-model evaluation.

## Day 36 — Plan the sandbox boundary

- [x] Identify model output, test snippets/values, candidate dependencies, and the host supervisor trust levels.
- [x] Select Docker Desktop Linux containers with a WSL 2 backend as the conditional candidate; verify the current machine has no Docker/Podman CLI and WSL is not installed.
- [x] Specify no network, non-root UID, no secrets/socket/broad host mounts, read-only root filesystem, and bounded scratch/output paths.
- [x] Set initial CPU, memory/swap, process, file-size, output-size, and wall-time limits with corresponding verification probes.
- [x] Define fail-closed behavior, cleanup requirements, and an execution flag that defaults off.
- [x] Record runtime prerequisites and leave container execution disabled pending installation and Day 37 verification.

## Day 37 — Build and verify the isolated runner

- [x] Add a minimal Python standard-library probe image definition pinned to a resolved base-image digest at build time.
- [x] Add a fixed-action probe program; it accepts only named harmless probes and cannot evaluate supplied source code.
- [x] Add a fail-closed Docker build and verification harness with non-root, no-network/no-bind-mount, read-only rootfs, tmpfs, CPU/memory/process/file-size, wall-clock, output, and cleanup controls.
- [ ] Build the image and record the exact image/runtime versions.
- [ ] Run host-file, network, privilege/device, process-count, memory, file-size, rootfs-write, wall-time, output-size, and cleanup probes.
- [ ] Confirm resource-control metadata and observed limits; keep untrusted execution disabled until all probes pass.

## Day 38 — Route untrusted execution through the sandbox

- [x] Add a distinct `abacus/sandbox.py` interface; keep the existing allowlisted benchmark path separate.
- [x] Add `execute-untrusted` CLI with a required explicit opt-in and a second environment opt-in.
- [x] Require the Day 37 PASS report, matching runtime version and exact image ID, and inspect container controls before start.
- [x] Return a structured error on missing runtime, startup failure, invalid result, timeout, output overflow, or cleanup failure; never run candidate code on the host as fallback.
- [x] Label trusted benchmark targets and untrusted sandbox requests in execution records; omit source text and host file paths.
- [x] Add tests for missing runtime, blocked verification, CLI opt-in, nonzero container startup, cleanup, and no host fallback.
- [ ] Run an actual candidate only after Day 37 image and isolation probes pass.

## Day 39 — Organize the project into clear modules

- [x] Put validated inert problem data, trusted target/oracle allowlists, experiment orchestration, provider boundary, prompt IDs, verifier policy, and sandbox boundary in separate responsibility-focused modules.
- [x] Keep `abacus/cli.py` as the command and run orchestrator; retain the working `python -m abacus` package layout at repository root.
- [x] Centralize prompt/fixture version identifiers and record them in normal and emergency run records.
- [x] Check imports and Git history before moving the verdict policy; retain `practice.decision` as a compatibility re-export.
- [x] Add module docstrings describing responsibilities and relevant trust boundaries.
- [x] Run both seed problem examples and focused tests after the module move.
