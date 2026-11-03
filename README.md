# Abacus

Abacus is a research prototype for checking precise claims about Python functions. It will search for candidate counterexamples and use trusted checks to decide what the evidence supports. A passing finite test run is not a proof of correctness.

This repository contains the Day 1–3 setup and Python practice exercises, plus Day 21–30 review work from the 56-day build plan. The comparison review uses Hypothesis for bounded case generation.

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

Each run outcome carries a machine-readable reason, such as confirmed_counterexample, no_counterexample_found, budget_exhausted, conflicting_evidence, or external_error. CASE_PASSED is a case-level label in the Day 21 report; it does not mean the whole run is TESTS_PASSED. The Day 21 report is the current results view; this repository does not yet have a separate UI viewer.

## Day 23 decision policy

The pure decide function in practice/decision.py selects a run outcome from normalized evidence and a claim contract. It checks contract and oracle identifiers, replay confirmation for counterexamples, completion counts, and failure status. Extra LLM wording in a record is ignored. It never calls a model, target function, or oracle.

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
