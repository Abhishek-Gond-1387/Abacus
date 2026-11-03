# Abacus

Abacus is a research prototype for checking precise claims about Python functions. It will search for candidate counterexamples and use trusted checks to decide what the evidence supports. A passing finite test run is not a proof of correctness.

This repository contains the Day 1–3 setup and Python practice exercises, plus Day 21–23 review work from the 56-day build plan. The comparison review uses Hypothesis for bounded case generation.

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
