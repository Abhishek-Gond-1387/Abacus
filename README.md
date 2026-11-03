# Abacus

Abacus is a research prototype for checking precise claims about Python functions. It searches for candidate counterexamples and uses trusted checks to decide what the evidence supports. A passing finite test run is not a proof of correctness. This repository tracks the Day 1–55 learning work.

The Day 1–3 exercises use Python's standard library. Day 5 and Day 6 use the OpenAI-compatible Python SDK and `python-dotenv`; Gemini is the default provider, with OpenAI available as an optional provider. Day 6 puts live requests behind a reusable helper and includes an offline stub.

## Run the exercises

From this directory:

```powershell
.\.venv\Scripts\Activate.ps1
python --version
.\.venv\Scripts\python.exe hello.py
.\.venv\Scripts\python.exe practice\day02.py
.\.venv\Scripts\python.exe practice\day03.py
deactivate
```

The Day 3 script anchors its sample files to the project directory, so it also works when launched from another current directory.

For a new setup, create the environment first with `python -m venv .venv`. Keep API keys in the ignored `.env` file; `.env.example` contains placeholders, and `.env` must never be committed.

## Fresh checkout setup (Windows PowerShell)

From the repository root, install runtime and development dependencies, then run the complete offline regression suite:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe practice\run_test_suites.py
```

The regression suite and seed-problem runs work without `.env`, provider credentials, or network/API calls. Create `.env` from `.env.example` only when you choose to make a live provider request. Git ignores `.env`, run outputs, virtual environments, and test/tool caches.

## Day 5: first API call

Get a Gemini API key from [Google AI Studio](https://aistudio.google.com/), then set `ABACUS_LLM_PROVIDER=gemini` and put the key in `GEMINI_API_KEY` in `.env`. If `.env` does not exist yet, copy `.env.example` first. `.env` is ignored by Git; never commit the key or paste it into chat or `NOTES.md`.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe first_call.py
```

The example sends one request through the reusable helper, caps output at 32 tokens, disables automatic retries, and prints only the response text. It exits without making a request if `GEMINI_API_KEY` is missing. The default model is `gemini-3.1-flash-lite`; Google currently lists free input and output for this model on the Gemini API free tier. Free-tier quota and account eligibility still apply. See [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) and [OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai).

Google says content submitted on the free tier may be used to improve its products. Do not send secrets, private source code, or personal data in free-tier prompts. See [Gemini API terms](https://ai.google.dev/gemini-api/terms).

## Day 6: reusable model helper

The `src/abacus/` package centralizes provider settings, requests, usage metadata, and safe error categories. `ask()` defaults to Gemini, reads `GEMINI_API_KEY` from the environment or ignored project `.env`, and disables SDK retries. Gemini requests use Google's OpenAI-compatible Chat Completions endpoint. Set `ABACUS_LLM_PROVIDER=openai` to use the optional OpenAI Responses API instead. `stub_ask()` returns a fixed response without reading credentials or using the network.

Install the package and dependencies with the command above, then run the offline demonstration:

```powershell
.\.venv\Scripts\python.exe -m abacus.day6_demo
```

The demo runs the stub by default. To also make one live request—which uses provider quota and may incur charges depending on the provider and account tier—run:

```powershell
.\.venv\Scripts\python.exe -m abacus.day6_demo --live
```

Configure `ABACUS_LLM_PROVIDER`, `GEMINI_MODEL`, `GEMINI_API_KEY`, and optionally `GEMINI_TIMEOUT_SECONDS` in `.env` or the process environment. When using OpenAI, use `OPENAI_MODEL`, `OPENAI_API_KEY`, and optionally `OPENAI_TIMEOUT_SECONDS`. The `.env.example` file contains placeholders only.

## Day 8: problem records

The record contract and field types are documented in [`schemas/README.md`](schemas/README.md). `src/abacus/problems.py` validates JSON structure without executing candidate code or calling a model. The two hand-authored examples in `problems/` show one true and one false sorting claim. `claim` remains the canonical original wording; any later model interpretation must be stored separately.

The historical validator is in `src/abacus/`, while the current package is at the repository root. From PowerShell, validate both older examples with:

```powershell
$previousPythonPath = $env:PYTHONPATH
Push-Location tests
try {
    $env:PYTHONPATH = (Resolve-Path ..\src).Path
    ..\.venv\Scripts\python.exe -m abacus.problems ..\problems\sort-ascending-true.json ..\problems\sort-ascending-false.json
    if ($LASTEXITCODE -ne 0) { throw "Problem validation failed." }
}
finally {
    if ($null -eq $previousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $previousPythonPath
    }
    Pop-Location
}
```

## Day 9: trusted sorting property

`src/abacus/sorting_oracle.py` uses Python's `sorted` as the independent reference for oracle ID `sorted-integer-list-v1`. A passing candidate must return a list containing the same exact integers in nondecreasing order, accept an empty list, and leave its input unchanged. Booleans are excluded even though Python treats them as integers in some contexts.

The check covers one supplied input at a time; passing finite examples does not prove behavior for every possible list. The oracle is appropriate here because Python's `sorted` is a clear reference for finite lists of built-in integers. It does not cover custom comparators, other element types, generators, or arbitrary Python behavior. The checker calls its candidate directly, so only trusted functions may be passed until a separate sandbox exists.

Run the correct/faulty candidate and edge-case checks with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## Day 10: input contracts

`abacus.contracts.validate_input(problem, input_value)` checks a problem's registered domain and predicate identifiers before target evaluation. The sorting problem requires a Python list containing exact built-in integers; booleans are excluded, and empty lists, duplicates, and negative integers are valid. The fixed edge-case generator and sorting oracle both call the same validator.

The oracle result has separate `PASSED`, `REFUTED`, `OUTSIDE_CONTRACT`, and `ERROR` statuses. It does not call the target when the input is outside its contract, so invalid inputs cannot be reported as `REFUTED`.

## Day 11: trusted subprocess runner

`abacus.runner.run_trusted_program()` writes a hand-authored Python snippet to a temporary directory and runs it with the current interpreter. The result includes the exit code, duration, bounded stdout/stderr, truncation flags, and a category: `SUCCESS`, `ASSERTION_FAILURE`, `SYNTAX_ERROR`, `EXCEPTION`, `NONZERO_EXIT`, `TIMEOUT`, `OUTPUT_LIMIT`, or `START_ERROR`. The default timeout is 2 seconds and the default combined stdout+stderr capture limit is 8 KiB. Temporary files are removed when execution finishes or fails.

Use this only for code you trust. The subprocess reduces hangs and unbounded captured output; it is **not a security sandbox**. Child code can still access files and resources available to your user. The child receives only basic platform environment variables, so API keys from the parent process are not passed through.

Run the offline checks with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## Day 12: independent test harness

`abacus.harness.check_case(problem, input_value)` accepts a validated record or its JSON path. It validates the input contract before starting the target, runs the record's hand-authored `candidate(values)` in the bounded Day 11 subprocess runner, and applies the registered trusted sorting oracle to the captured return value and mutation snapshot. Its evidence separates `PASSED`, `REFUTED`, `OUT_OF_CONTRACT`, target `ERROR`, `TIMEOUT`, and `OUTPUT_LIMIT`, with the input, target result or exception, oracle result, and explanation.

`check_cases(problem, cases)` returns every completed case even if a later case or the case iterator fails. Its summary says “tests passed” for passing finite fixtures and explicitly does not claim proof. These are deterministic checks with no LLM call. Run only hand-authored, trusted problem code; subprocess execution is still not a security sandbox.

## Day 13: save and replay counterexamples

`abacus.counterexamples` stores only contract-valid cases the trusted oracle refuted. Each JSON file records the problem ID, input, source and optional seed, validity, observed target output, expected property/output, target-code SHA-256, and canonical problem-record SHA-256. Writes use a temporary file in the destination directory followed by `os.replace`, so a failed write does not replace an existing record.

The Day 9 false sorting witness is saved at `counterexamples/sort-ascending-false-day9.json`. Save another checked failure and replay a saved one with:

```powershell
.\.venv\Scripts\python.exe -m abacus.counterexamples record problems\sort-ascending-false.json '[1, 2]' counterexamples\sort-ascending-false-day9.json --source problem.known_counterexample
.\.venv\Scripts\python.exe -m abacus.counterexamples replay counterexamples\sort-ascending-false-day9.json problems\sort-ascending-false.json
```

Replay reports whether the mismatch reproduced and whether code/record hashes still match. A changed target can show a version mismatch; if the saved mismatch no longer reproduces, the result is `UNRESOLVED` and must not be treated as a refutation.

## Day 14: threat model review

See [the threat model](docs/threat-model.md) for the execution flow, subprocess limits, evidence rules, generated-code restriction, and the independent label review. The current subprocess runner is for trusted code and does not isolate filesystem or network access.

## Day 15: deterministic edge cases

`abacus.edge_cases` generates named sorting boundaries, three repeatable random samples, and a separate boolean out-of-contract case. Each fixture has an explanation and is checked against the shared input contract. The generator records its version, seed, Python version, exact inputs, and harness outcomes in a run record.

Generate and run the saved Day 15 set with:

```powershell
.\.venv\Scripts\python.exe -m abacus.edge_cases problems\sort-ascending-true.json runs\day15-sorting-edge-cases.json --seed 1501
```

The resulting [run record](runs/day15-sorting-edge-cases.json) contains 11 passing contract-valid cases and one `OUT_OF_CONTRACT` case. Repeating the command with the same problem and seed generates the same case sequence in the recorded Python version.

## Day 16: Hypothesis property-based checks

Hypothesis `6.170.14` is pinned as the optional `test` dependency, keeping it out of the runtime install. Install this version directly into the project environment with:

```powershell
.\.venv\Scripts\python.exe -m pip install hypothesis==6.170.14
```

The sorting strategy is `lists(integers(-20..20), min_size=0, max_size=12)`: every generated input satisfies the current `list[int]` contract, while the bounds keep laptop runs small. Tests use `@given`, `max_examples=20` for the correct candidate, deterministic generation, and a 5-second per-example deadline. The faulty reverse-sort is searched through the Day 12 harness; Hypothesis shrinks the mismatch to `[0, 1]`, which the oracle confirms produces `[1, 0]` instead of `[0, 1]`. A property-based pass is still only `TESTS_PASSED` for this bounded strategy, never `PROVEN`. See Hypothesis's [quickstart](https://hypothesis.readthedocs.io/en/latest/quickstart.html), [settings guide](https://hypothesis.readthedocs.io/en/latest/tutorial/settings.html), and [strategy reference](https://hypothesis.readthedocs.io/en/latest/reference/strategies.html) for strategies, example limits, and shrinking behavior.

Run the focused checks with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_hypothesis_sorting.py -v
```

## Day 17: preserve shrinking and replay

`abacus.hypothesis_capture` searches the same bounded list strategy with an explicit seed and settings. When the harness reports an oracle refutation, the hook rechecks the minimized input and saves it using the Day 13 counterexample schema; the `source` field records Hypothesis version, strategy, `max_examples`, deadline, and seed.

Regenerate the Day 17 minimized witness with:

```powershell
.\.venv\Scripts\python.exe -m abacus.hypothesis_capture problems\sort-ascending-false.json counterexamples\sort-ascending-false-hypothesis-day17.json --seed 17017 --max-examples 40 --deadline-ms 5000
```

The saved `[0, 1]` case is also an ordinary harness regression fixture. It replays without invoking Hypothesis:

```powershell
.\.venv\Scripts\python.exe -m abacus.counterexamples replay counterexamples\sort-ascending-false-hypothesis-day17.json problems\sort-ascending-false.json
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_day17_regression.py -v
```

Replay must return `REPRODUCED` with target output `[1, 0]` and expected output `[0, 1]`; otherwise the saved evidence is unresolved.

## Day 18: model proposed test inputs

`abacus.proposals.request_test_ideas(problem)` asks the configured model for up to five concrete inputs and short rationales. The prompt includes the claim, candidate code, input domain, and preconditions, and requests only the JSON schema `{"candidate_inputs":[{"input":...,"rationale":"..."}]}`. The parser requires that exact schema, rejects duplicate keys and extra fields, and does not extract JSON from Markdown or surrounding text.

Each parsed input is checked against the registered contract before the target runs. Out of contract suggestions are logged and included in the batch as `REJECTED_OUT_OF_CONTRACT` without harness evidence. Valid suggestions go through `abacus.harness.check_case`; the returned `ProposalBatch.as_dict()` marks their source as `model_proposed` and records trusted harness and oracle evidence. The model cannot supply an outcome or verdict.

Use it from Python after configuring the provider key locally:

```python
from abacus.proposals import request_test_ideas

batch = request_test_ideas("problems/sort-ascending-true.json")
print(batch.as_dict())
```

Run the offline proposal pipeline checks with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_proposals.py -v
```

The tests use an injected sample model response and make no API request. A live call requires `GEMINI_API_KEY` (or the configured provider's key).

## Day 19: adversarial falsifier

`abacus.falsifier` uses a separate adversarial prompt. It includes the claim, candidate code, domain, preconditions, property description, and oracle ID, while leaving out the expected label and any known counterexample. The model is asked to search for candidate inputs and short rationales; any top-level `verdict` or `label` it adds is ignored and never used as evidence.

Run a falsifier search after configuring the provider key locally:

```powershell
.\.venv\Scripts\python.exe -m abacus.falsifier problems\sort-ascending-false.json runs\day19-falsifier-false.json --counterexample-directory counterexamples\falsifier
```

The atomic JSON report stores each proposal, contract validation, harness/oracle result, and replay result. A harness refutation is saved with the Day 13 counterexample format and replayed. The falsifier status becomes `REFUTED` only when that saved counterexample returns `REPRODUCED`; a passing input is `REJECTED`, while out of contract inputs and execution errors are `INVALID_EVIDENCE`. A false seed's known counterexample is not included in the prompt.

Run the offline Day 19 checks with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_falsifier.py -v
```

These checks inject a sample response for both true and false seed problems. They verify the pipeline and known witness handling, not the live model's ability to discover counterexamples.

## Day 20: explain failures with categories

`abacus.failure_categories.FailureCategory` provides the shared categories `OUT_OF_CONTRACT`, `TARGET_EXCEPTION`, `PROPERTY_VIOLATION`, `TEST_ORACLE_DEFECT`, `TIMEOUT`, `SANDBOX_FAILURE`, `API_ERROR`, `PARSE_ERROR`, and `INTERNAL_ERROR`. Harness case evidence, model proposal evidence, and falsifier reports include the applicable category alongside the detailed evidence. Passing cases have no failure category.

The category definitions and examples are in [the failure category guide](docs/failure-categories.md). Timeouts, target exceptions, oracle defects, and runner failures remain unresolved; they never become `REFUTED`. The falsifier uses `REFUTED` only after an oracle-confirmed counterexample is saved and replayed successfully. Focused category checks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_harness.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_proposals.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_falsifier.py -v
```

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

## Day 39 module boundaries

The importable package stays at `abacus/` in the repository root so `python -m abacus` continues to work from this directory without an installation step. Schemas and inert problem-file validation live in `abacus/schemas.py`; checked-in target/oracle allowlists live in `abacus/targets.py`; deterministic case generation and trusted evidence collection live in `abacus/experiment.py`; provider interfaces and offline proposal fixtures live in `abacus/llm.py`; prompt/fixture identifiers live in `abacus/prompts.py`; isolation stays in `abacus/sandbox.py`; and outcome policy lives in `abacus/verifier.py`. The CLI coordinates these parts. The `practice.decision` module remains as a compatibility import for examples and tests that use its old path.

## Day 40 model-output validation

`abacus.schemas.parse_hypothesis_output`, `parse_plan_output`, and `parse_candidate_proposals` validate provider text as strict JSON and return immutable typed records. Responses are limited to 16 KiB, text fields to 1,000 characters, plans to 20 suggestions, proposals to 20 inputs, and each input to 100 signed 64-bit integers. A plain JSON response or a single complete `json` code fence is accepted. Refusals, empty/truncated/invalid JSON, extra text, unknown fields, wrong types, and oversized responses have distinct error categories. Raw provider text is not retained or included in validation errors. No hosted client is configured; parsing is ready for a future adapter.

Run the fixture checks with:

    .\.venv\Scripts\python.exe -m unittest practice.test_day40_model_outputs

## Day 41 full test suite

Run all maintained test fixtures with:

    .\.venv\Scripts\python.exe practice\run_test_suites.py

The runner executes the Day 1–20 tests against the historical `src/abacus/` package and the Day 21+ tests against the current root `abacus/` package in separate subprocesses. This prevents same-named package imports from masking either suite. Provider-facing checks use injected stubs and do not require an API key or make paid requests.

## Day 42 fresh-install review

The fresh-checkout procedure above was verified in a detached clean worktree with a new virtual environment and both requirements files. No API key or project-specific manual setup was needed for the regression suite or current CLI runs. The two current seed records were run offline; the two historical Day 8 records were validated using the documented historical-package path. `runs/`, `.env`, the virtual environment, and Python/test caches are excluded from Git.

## Day 43 continuous integration

`.github/workflows/ci.yml` runs the complete regression suite on pushes to `main`, pull requests targeting `main`, and manual dispatch. It checks the declared minimum Python version (3.11) and Python 3.14, installs the same runtime and test requirements as the clean-install instructions, and requires no API key or provider request. The workflow grants only `contents: read` and pins its GitHub Actions to verified commit SHAs.

## Day 44 CLI smoke checks

The unified suite now runs the real `python -m abacus run` command in isolated subprocesses for both checked-in current seed records. It checks the saved run JSON and CLI summary: the true seed must return `TESTS_PASSED`, while the false seed must return `REFUTED` with its counterexample replay confirmed. Provider keys are removed from the subprocess environment, and both runs must report that no provider API was called. Run these checks alone with:

```powershell
.\.venv\Scripts\python.exe -m unittest practice.test_day44_cli_smoke
```

## Day 45 cross-platform CI

The GitHub Actions matrix runs the same regression suite on both `ubuntu-24.04` and `windows-2025`, with Python 3.11 and 3.14 on each platform. This covers four OS/Python combinations, including the Windows environment used for local development. Each job retains the same read-only token permission, dependency install, and no-provider-credentials setup.

## Day 46 dependency updates

`.github/dependabot.yml` checks GitHub Actions and Python/pip dependencies weekly. It limits open update pull requests to two for actions and three for Python packages. Because workflow actions are pinned to commit SHAs with release-version comments, Dependabot can propose reviewable SHA updates. Update PRs still need to pass CI and be reviewed before merging; this configuration does not auto-merge them.

## Day 47 GitHub YAML linting

The CI job runs strict `yamllint` checks on the workflow and Dependabot configuration before the regression suite. Its CI-only pinned linter requirement and the `.yamllint` config are shared by local and GitHub checks. From the repository root, run:

```powershell
$env:PYYAML_FORCE_LIBYAML = "0"
.\.venv\Scripts\python.exe -m pip install -r requirements-ci.txt
Remove-Item Env:PYYAML_FORCE_LIBYAML
.\.venv\Scripts\yamllint.exe --strict .github\workflows\ci.yml .github\dependabot.yml
```

The environment setting makes PyYAML use its pure-Python parser when installing the linter under Python 3.15, avoiding a local C++ compiler requirement. It is only needed for this optional lint install; normal runtime and dev requirements do not include PyYAML.

## Day 48 cross-platform YAML line endings

`.gitattributes` pins `.yml` files to LF so Windows checkouts do not convert GitHub Actions and Dependabot configuration files to CRLF. The strict YAML linter checks both files on every CI matrix job.

## Day 49 explicit hosted-provider client

`abacus.llm.create_llm_client()` creates a Gemini or OpenAI-compatible client from `ABACUS_LLM_PROVIDER` and the matching API key in the process environment or ignored project `.env`. Creating the client makes no request. Only calling `complete(prompt, model_id=...)` sends the prompt; it uses a bounded timeout, disables hidden SDK retries, caps output tokens and response bytes, and returns untrusted text for validation with `abacus.schemas.parse_model_output`. The caller supplies the model ID from its own approved configuration.

Provider calls send prompt content to the selected service and may use account quota or incur charges. Keep the offline fixtures as the default workflow and never send secrets or private data in prompts. Gemini's OpenAI-compatible endpoint is documented by [Google](https://ai.google.dev/gemini-api/docs/openai); client timeout and retry settings follow the [official OpenAI Python library](https://github.com/openai/openai-python).

## Day 50 structured provider response boundary

Use `abacus.llm.complete_structured_output(client, output_kind, prompt, model_id=...)` when a hosted response is explicitly requested. It validates the request kind and prompt size before sending anything, then returns only an immutable `HypothesisOutput`, `PlanOutput`, or `CandidateProposalsOutput` after strict JSON/schema checks. Raw provider text stays inside the helper. The returned suggestions remain untrusted: candidate inputs still need contract checking and trusted oracle evaluation before they count as evidence. The normal `python -m abacus run` workflow continues to use offline fixtures and makes no provider calls.

## Day 51 versioned hosted prompts

`abacus.prompts.build_model_prompt(output_kind, spec)` builds a bounded prompt from a validated `ProblemSpec` for hypothesis, test-plan, or candidate-input suggestions. It includes only the claim, contract/oracle identifiers, fixed cases, and existing proposal inputs; target source code is never included. Context is encoded as JSON data with explicit instructions to ignore instructions inside its values. `HOSTED_PROMPT_TEMPLATE_VERSIONS` identifies each prompt version for audit records. Building a prompt is local; a caller must explicitly pass it to `complete_structured_output()` to make a provider request.

## Day 52 prompt preview CLI

Preview the exact bounded prompt and template version without loading provider credentials or sending a network request:

```powershell
.\.venv\Scripts\python.exe -m abacus prompt-preview problems\p01_true_sort.json --kind candidate_proposals
```

Use `--kind hypothesis`, `--kind plan`, or `--kind candidate_proposals`. The JSON result says `provider_api_called: false`; inspect the prompt before any separate explicit provider call. The normal `run` command remains offline.

## Day 53 one-shot hosted suggestions

To request one typed suggestion, use `model-suggest` with the model ID and the required `--send-to-provider` flag:

```powershell
.\.venv\Scripts\python.exe -m abacus model-suggest problems\p01_true_sort.json --kind candidate_proposals --model gemini-3.1-flash-lite --send-to-provider
```

This sends the claim and test-case context to the configured provider, can use provider quota or incur charges, and returns only the strictly parsed result. It makes one request with the existing 1,024 output-token cap and no hidden SDK retries. The command does not save a run record or usage/cost data, apply suggestions, or treat them as evidence; candidate inputs still need trusted contract checks and evaluation. Preview the prompt with `prompt-preview` first. The `--send-to-provider` flag is mandatory, and the regular `run` command remains offline.

## Day 54 evaluate hosted candidate inputs

For `candidate_proposals`, add `--evaluate-proposals` to check each parsed integer-array input with the problem's registered local target and trusted oracle:

```powershell
.\.venv\Scripts\python.exe -m abacus model-suggest problems\p01_true_sort.json --kind candidate_proposals --model gemini-3.1-flash-lite --send-to-provider --evaluate-proposals
```

The explicit provider request behavior and possible quota or charges are the same as Day 53. Evaluation rejects empty arrays when the contract disallows them, and it runs only parsed integer inputs against the allowlisted target/oracle; no model-generated code is executed. Per-input evidence is returned in the command output but is not saved, added to an overall verdict, or a proof. `--evaluate-proposals` is valid only with `--kind candidate_proposals`; without it, the command returns suggestions without local evaluation.

## Day 55 hosted request audit metadata

The JSON success and provider-error outputs from `model-suggest` include `request_metadata`: provider and model IDs, problem and dataset hashes, the prompt template version, prompt SHA-256 and byte count, request start time, timeout, retry count, output-token cap, and sampling-default marker. This supports comparing or identifying the exact request context without printing the prompt body or credentials. Usage and cost are still not recorded, and the metadata does not make a hosted response reproducible because provider behavior may vary.
