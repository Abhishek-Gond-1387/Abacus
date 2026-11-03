# Abacus

Abacus is a research prototype for checking precise claims about Python functions. It will search for candidate counterexamples and use trusted checks to decide what the evidence supports. A passing finite test run is not a proof of correctness.

This repository contains the Day 1–3 setup and Python practice exercises, plus Day 21–39 review work from the 56-day build plan. The comparison review uses Hypothesis for bounded case generation.

## Day 39 module boundaries

The importable package stays at `abacus/` in the repository root so `python -m abacus` continues to work from this directory without an installation step. Schemas and inert problem-file validation live in `abacus/schemas.py`; checked-in target/oracle allowlists live in `abacus/targets.py`; deterministic case generation and trusted evidence collection live in `abacus/experiment.py`; provider interfaces and offline proposal fixtures live in `abacus/llm.py`; prompt/fixture identifiers live in `abacus/prompts.py`; isolation stays in `abacus/sandbox.py`; and outcome policy lives in `abacus/verifier.py`. The CLI coordinates these parts. The `practice.decision` module remains as a compatibility import for examples and tests that use its old path.

## Run the exercises

From this directory:

```powershell
.\.venv\Scripts\python.exe hello.py
.\.venv\Scripts\python.exe practice\day02.py
.\.venv\Scripts\python.exe practice\day03.py
```

The Day 3 script anchors its sample files to the project directory, so it also works when launched from another current directory.

## Day 21 comparison

Install the development dependency and run the comparison:

    .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
    .\.venv\Scripts\python.exe practice\day21_review.py

The review compares fixed edge cases, Hypothesis cases, and offline LLM-style proposal fixtures on two deliberately faulty seed functions. All sources share each problem's input contract and trusted reference. The script writes the results to practice/day21_report.md. The proposal fixtures do not call a provider API, and the generated test cases are checked as evidence rather than treated as a proof.

## Verdict glossary

The shared run-level vocabulary and record are in practice/outcomes.py:

- REFUTED: a contract-valid counterexample has been confirmed.
- TESTS_PASSED: the scheduled finite tests passed; this does not prove correctness.
- PROVEN: reserved for a sound formal checker and proof evidence. No current test-only path can emit it.
- UNRESOLVED: evidence or budget is insufficient or conflicting.
- ERROR: an external or internal error prevented evaluation.

Each run outcome carries a machine-readable reason, such as confirmed_counterexample, no_counterexample_found, budget_exhausted, conflicting_evidence, or external_error. CASE_PASSED is a case-level label in the Day 21 report; it does not mean the whole run is TESTS_PASSED. The Day 21 report is the static comparison view; `python -m abacus view-run` shows a saved run in the terminal. There is no graphical viewer.

## Day 23 decision policy

The pure `decide` function in `abacus/verifier.py` selects a run outcome from normalized evidence and a claim contract. It checks contract and oracle identifiers, replay confirmation for counterexamples, completion counts, and failure status. Extra LLM wording in a record is ignored. It never calls a model, target function, or oracle. `practice/decision.py` re-exports it for compatibility.

A completed evidence record includes test_id, method, contract_id, status, contract_valid, oracle_id, input, actual, and expected. A mismatching output needs replay_confirmed set to true before it can refute a claim. One confirmed counterexample is sufficient even if other scheduled tests did not finish; otherwise incomplete or uncertain runs remain unresolved.

Run the policy fixtures with the standard library:

    .\.venv\Scripts\python.exe -m unittest practice.test_decision

## Day 24 claim revisions

Revision records live in practice/revisions.py. A prompt requires a confirmed REFUTED outcome or recorded ambiguity. The record keeps original_claim and original_label immutable, stores the proposal and its relation separately, and marks the original claim as the one still scored.

Generate the offline example view and run its fixtures:

    .\.venv\Scripts\python.exe practice\day24_revision_example.py
    .\.venv\Scripts\python.exe -m unittest practice.test_revisions

The example narrows an all-integer-lists claim to non-empty integer lists after an empty-list counterexample. It does not call a provider API. The view is saved to practice/day24_revision_view.md.

## Day 25 run budgets

BudgetTracker in practice/budgets.py tracks rounds, wall time, model-call attempts, tokens, and estimated/actual cost. Reserve a call before sending it; the reservation checks remaining budgets and includes the expected duration. Each retry is another call attempt and consumes the same budgets. Failed calls keep their estimate because usage may be unknown.

Incomplete evidence after a budget stop is recorded as UNRESOLVED with reason budget_exhausted. The JSON run log stores configured limits, usage, events, and the stop reason.

Run the tiny-budget example and fixtures:

    .\.venv\Scripts\python.exe practice\day25_budget_example.py
    .\.venv\Scripts\python.exe -m unittest practice.test_budgets

The example writes practice/day25_tiny_budget_log.json without making a provider call.

## Day 26 checker validation

Run the checker audit and its fixtures:

    .\.venv\Scripts\python.exe practice\day26_validation.py
    .\.venv\Scripts\python.exe -m unittest practice.test_day26_validation

The audit compares correct and deliberately faulty sort/largest functions against manually written expected outputs, checks an intentionally defective oracle, replays every Day 21 saved counterexample, and demonstrates that sort idempotence misses duplicate removal. Results are written to practice/day26_checker_report.md. The finite fixtures reduce shared-oracle risk for these cases but do not establish full oracle soundness; the manual answers have not had an independent human review.

## Day 27 end-to-end pilot

Run a JSON problem through validation, fixed cases, seeded Hypothesis cases, offline proposal fixtures, replay, the evidence decision policy, optional revision, and JSON logging:

    .\.venv\Scripts\python.exe -m abacus run problems/p01_true_sort.json
    .\.venv\Scripts\python.exe -m abacus run problems/p02_false_sort.json
    .\.venv\Scripts\python.exe -m unittest practice.test_day27_pipeline

Problem files are validated before evaluation. Targets and oracles are selected from a small allowlist; JSON files cannot name Python code to execute. The pilot uses offline suggestion/proposal fixtures and makes no provider API calls. Run logs are saved under runs/ and include evidence, replay, verdict, revision state, errors, and budget usage. The true fixture can return TESTS_PASSED; the false fixture can return REFUTED only after a mismatch reproduces on replay.

## Day 28 verdict semantics

The run-level meanings and annotated examples for REFUTED, TESTS_PASSED, UNRESOLVED, and ERROR are recorded in practice/verdict_semantics.md. A case-level CASE_PASSED is not a run-level verdict. PROVEN remains reserved for formal proof evidence.

## Day 29 versioned run records

New CLI runs use schema version 2, including run UUID, dataset/version and code hashes, claim/contract, generation settings and seeds, proposals/candidates, oracle/replay evidence, outcome references, software/Git provenance, and usage/budget fields. See practice/run_record_schema.md. Regenerate the validated complete/partial examples with `python -m practice.day29_record_examples`; validate fixtures with `python -m unittest practice.test_run_records`.

## Day 30 unique run storage

Each default run gets a timestamp-plus-UUID filename in `runs/`; that directory is ignored by Git. Saves validate first, write and flush a same-directory temporary file, then rename it into place. An `.incomplete` sidecar records the run ID and temporary path if a save is interrupted. Existing destination files are never overwritten.

List saved runs or filter by problem, then inspect one by its run ID:

    .\.venv\Scripts\python.exe -m abacus list-runs
    .\.venv\Scripts\python.exe -m abacus list-runs p01_true_sort
    .\.venv\Scripts\python.exe -m abacus show-run <RUN_ID>
    .\.venv\Scripts\python.exe -m unittest practice.test_run_storage

## Day 31 secret-safe logs

Run records and budget logs pass through a redaction layer before being written. It removes values under credential-like field names, recognizable authorization/token formats, labeled secret assignments, private-key blocks, and configured secret values from environment variables. Numeric usage counters such as `input_tokens` remain available. The saved dataset hash is recalculated from the redacted dataset body; `problem_spec_sha256` remains a fingerprint of the original input file.

## Day 32 resource usage

Each run records model-call attempts, successful and failed calls, retry attempts, provider-reported input/output tokens, stage durations, total duration, and cost status. Missing response usage or pricing is recorded as `unknown`; no provider call is `not_applicable`. The current pilot makes no provider calls, so its token use is not applicable and its API cost is zero.

Provider pricing is optional per problem. When a provider/model is selected, supply `provider_id`, `model_id`, `input_usd_per_million_tokens`, `output_usd_per_million_tokens`, `source_url`, and `checked_at` from the current pricing page. Omit the configuration while rates are unknown; the logger will not substitute zero.

Use `python -m abacus summarize-runs [problem_id]` for per-run medians and ranges. Its output keeps unknown and not-applicable counts separate from measured values.

## Day 33 readable run viewer

Open a saved run by UUID without reading its raw JSON:

    .\.venv\Scripts\python.exe -m abacus view-run <RUN_ID>

The viewer keeps model suggestions in a separate unverified section, shows harness-recorded checks and replay status, preserves errors and incomplete reasons, and links to the full evidence record. A `TESTS_PASSED` run displays “No counterexample found in these tests; not a proof.”

## Day 34 retries and partial failures

Provider adapters can use `practice.provider_retries.call_with_retries()` for bounded retries. Only explicitly safe transient failures such as rate limits retry; authentication, model/configuration, schema, and programming errors stop. Timeouts, lost responses, and server errors are treated as ambiguous and are not sent again automatically. Each actual attempt reserves model-call, token, cost, and time budgets, and its failure category is kept in the budget event log.

The run pipeline writes an atomic progress checkpoint after the test, proposal, and revision stages. If a later stage crashes, the emergency `ERROR` record keeps evidence already completed and the latest saved budget/error state. `list-runs`, `show-run`, and `view-run` can inspect checkpoints. The current pilot still has no provider integration, so retry behavior is exercised with local stubs and makes no network calls.

Run the Day 34 fixtures with:

    .\.venv\Scripts\python.exe -m unittest practice.test_provider_retries practice.test_run_checkpoints practice.test_day27_pipeline

## Day 35 run audit

Four validated examples are checked in under `practice/samples/day35_*.v2.json`. They cover REFUTED, TESTS_PASSED, UNRESOLVED, and ERROR. The audit report records their evidence, reasons, replay result, settings, provenance, and secret scan: `practice/day35_run_audit.md`.

Replay and validate those samples with:

    .\.venv\Scripts\python.exe -m unittest practice.test_day35_audit

## Day 36 sandbox design

The trust-boundary decision and control checklist are in `practice/day36_sandbox_design.md`. Docker Desktop with Linux containers on WSL 2 is the conditional candidate. This machine currently has no Docker/Podman CLI and WSL is not installed, so generated-code execution remains disabled. Do not execute candidate code on the host if a container preflight or isolation control fails.

## Day 38 untrusted execution gate

`python -m abacus execute-untrusted SOURCE.py --input INPUT.json --allow-untrusted-code` is the only CLI path for candidate source. It also requires `ABACUS_UNTRUSTED_EXECUTION=1`, a Day 37 report with every probe passing, the exact recorded image ID and Docker version, and a matching Linux engine. The current Day 37 report is BLOCKED, so this command returns a structured `ERROR` before it reads the candidate files. It never falls back to host execution. Ordinary benchmark runs record `target.execution_origin: trusted_allowlist`; untrusted execution results are labeled `untrusted_sandbox` and include source/input hashes instead of source text or host paths.
