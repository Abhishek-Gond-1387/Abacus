# Abacus learning notes

## Environment

- Python: 3.15.2
- Virtual environment: `.venv`

## Learned

- Small functions are easier to check when their input and edge-case behavior are clear.
- `pathlib.Path` keeps file paths independent of the terminal's current directory.
- JSON round-trips preserve structured data; UTF-8 keeps non-ASCII text readable.

## Confusing

- The `py` launcher is unavailable here; use the working `python` command.
- `largest([])` has no natural largest value, so this exercise raises `ValueError`.

## Earlier setup history

- Day 4 completed: reviewed and committed the setup, then practiced a second one-line commit.
- Day 5: the API example and dependencies are ready. A restricted 30-day API key is stored only in the ignored .env file. The first live request attempt failed during DNS lookup. Later requests reached the API but returned HTTP 429; the Day 6 retry identified `credit_balance_exhausted`, meaning the organization has no prepaid API credits. The usage dashboard shows Free tier, $0.00 spend, and no logged usage. The limits page lists gpt-5.4-mini at 10 RPM and 50 RPD for this tier, so this is not a request-frequency error. Upgrade tier opens an Add payment details form stating that the credit card will be saved. No payment details or purchase were submitted; never record or paste the key here.
- Day 6: added a reusable `src/abacus/` package with environment-based OpenAI settings, a single-request helper that returns available token usage, safe error categories, and an offline fixed-response stub. The demo uses the stub by default; `--live` explicitly opts into one API request. The editable package install succeeded, and the offline demo ran successfully without an API request. One live request returned HTTP 429 with code `credit_balance_exhausted`; no payment details or credits were added.
- 2026-11-03 update: switched the default provider to Google's Gemini API free tier (`gemini-3.1-flash-lite`) using Google's documented OpenAI-compatible Chat Completions endpoint. The adapter retains optional OpenAI support. A Gemini API key from Google AI Studio still needs to be entered locally as `GEMINI_API_KEY`; live verification is pending until that is configured. Google's free-tier terms say submitted content may be used to improve its products, so do not send secrets or private data.

## Day 7 — Week 1 review

- Learned: a fresh Python 3.15.2 virtual environment can run `hello.py`, `practice/day02.py`, and `practice/day03.py` using the documented setup.
- Unclear: whether this Google project has Gemini free-tier access; a live API request remains pending until `GEMINI_API_KEY` is configured.
- Failed: none of the clean-environment script checks failed. The live API call was not attempted because no Gemini key is configured.
- Fixed: Day 6 now defaults to Gemini and its offline stub still runs. `.env` stays ignored by Git; `.env.example` contains placeholders only.
- Next week's goal: begin Day 8 by defining a precise problem record and validating its required fields before adding model-generated tests.

## Day 8 — Define a problem record

- Added a standard-library validator and documented the field types, required fields, labels, domain object, and false-claim counterexample rule.
- Added hand-authored true and false sorting records. The original `claim` is stored separately and is never rewritten by model output; the loader does not execute `code` or call an LLM.
- Validated both example files and checked that missing `id`, an invalid label, and a false record without `known_counterexample` are rejected.
- Next: Day 9 — implement the independent trusted sorting property and test it against a correct and faulty candidate.

## Day 9 — Trusted sorting property

- Added oracle `sorted-integer-list-v1`, using Python's `sorted` as the independent reference.
- The checker requires exact integer-list inputs and outputs, preserves duplicates, accepts empty lists, compares against sorted order, and rejects candidate input mutation.
- Tested the correct candidate on empty, single-item, duplicate, negative, and already-sorted lists. The reverse-sort candidate fails on the Day 8 witness `[1, 2]`; an in-place sort also fails the no-mutation rule.
- Limits: this covers finite lists of built-in integers and one input per check. It does not prove a universal claim, execute record code, or sandbox untrusted targets.
- Next: Day 10 — make input-domain and precondition validation explicit before running a target.

## Day 10 — Validate inputs and preconditions

- Added machine-checkable precondition IDs to both sorting problem records and registered their meaning against `sorted-integer-list-v1`.
- Added `validate_input(problem, input_value)`. It checks the record's oracle/domain/preconditions and returns `VALID` or `OUTSIDE_CONTRACT` with a reason.
- The fixed edge-case generator and sorting oracle share `validate_input`. The oracle skips the target for out-of-contract inputs and records `OUTSIDE_CONTRACT` separately from `REFUTED` and target `ERROR`.
- Added valid and invalid input fixtures. Tests confirm valid edge cases stay in contract, invalid values never call the target or become `REFUTED`, and target exceptions remain `ERROR`.
## Day 11 — Run trusted code in a child process

- Added `abacus.runner.run_trusted_program()`. It writes the snippet to a temporary directory, runs it with the current Python interpreter, captures output using reader threads, enforces a combined output-byte cap, and removes the temporary directory on completion and failure.
- The structured result reports exit code, stdout/stderr, truncation flags, duration, timeout/output-limit flags, and a category for success, assertion failure, syntax error, other traceback exception, plain nonzero exit, timeout, output limit, or start error.
- The child gets only basic platform environment variables so parent API keys are not forwarded automatically.
- The runner is for trusted code only, not a security sandbox. A child can still read and write files available to the current user.
- Added tests for normal output, assertion failure, syntax error, runtime exception, timeout cleanup, noisy output limits and cleanup, plus plain nonzero exits. At Day 11 completion, 15 tests passed and `compileall` succeeded.

## Day 12 — Build the independent test harness

- Added `check_case(problem, input_value)`, accepting either a validated record mapping or a JSON path.
- It checks the registered input contract first and returns `OUT_OF_CONTRACT` without starting a subprocess for invalid inputs.
- For valid cases it runs the record's hand-authored candidate through the bounded Day 11 runner, records target exceptions separately, and feeds the captured return value plus mutation snapshot into the trusted sorting oracle.
- Evidence includes problem ID, input snapshot, contract validity/reason, returned value or exception, oracle result, status, explanation, and subprocess metadata.
- Added `check_cases(problem, cases)`, which preserves completed results if a later case or the input iterator fails. Its batch log says “tests passed” for passing fixtures and says finite checks are not a proof.
- Tests cover the true sorting record on edge cases, the false record's concrete `[1, 2]` witness, contract rejection without target execution, target exceptions, mutation detection, path loading, and batch result preservation.
- At Day 12 completion, the full suite passed (23 tests); `compileall` and `git diff --check` also succeeded.

## Day 13 — Save and replay candidate counterexamples

- Defined schema version 1 for counterexamples: problem ID, integer-list input, source/optional seed, contract validity, observed target result and oracle status, expected property/output, and SHA-256 hashes of both target code and the canonical problem record.
- Added `save_counterexample()`, which only saves contract-valid oracle refutations and writes atomically through a same-directory temporary file plus `os.replace`.
- Added schema validation and `replay_counterexample()`. Replay reruns the case through the Day 12 harness, compares the observed target result and oracle expectation, exposes both version-match flags, and returns `UNRESOLVED` if the mismatch no longer reproduces.
- Added `python -m abacus.counterexamples record|replay` commands and saved the Day 9 false sorting witness in `counterexamples/sort-ascending-false-day9.json`.
- Tested replay with matching hashes, temporarily changed the target code to confirm the hash mismatch is visible and the fixed case is `UNRESOLVED`, and simulated an atomic replace failure to confirm the old file survives and the temporary file is removed.
- Verification: the record/replay CLI reproduced the saved `[1, 2]` mismatch with both version hashes matching. The full suite passes (28 tests); `compileall` and `git diff --check` succeed.

## Day 14 — Week 2 review and threat model

- Added `docs/threat-model.md` with the problem → contract → execution → oracle → evidence/replay flow.
- Recorded the subprocess's reliability controls and its security limits: user-level file access (including `.env`), network access, no memory/disk quota, and best-effort process-tree termination.
- Rule: only hand-authored, source-reviewed records may run. Model-generated code stays disabled until a real OS isolation boundary is implemented and verified for files, network, secrets, descendants, and resources.
- Reviewed the labels from source and the saved witness: `sorted(values)` satisfies the stated property; reverse sorting fails on `[1, 2]` with `[2, 1]` instead of `[1, 2]`. Noted that the executable oracle also relies on Python's `sorted`, so it does not independently validate that built-in implementation.
- Evidence rules distinguish contract violations and execution failures from oracle refutations; finite `PASSED` cases are not proofs, and non-reproducing saved cases remain `UNRESOLVED`.
- Next week's goal (Week 3): add deterministic and other useful input proposals while keeping the independent harness as the only judge of counterexamples.

## Day 15 — Add deterministic edge cases

- Added `abacus.edge_cases` with eight named sorting boundaries, three seeded random cases, and one separately labeled boolean out-of-contract case. Each fixture explains what it checks and is validated against the shared contract.
- Set the default random seed to `1501` and generator version to `sorted-integer-edge-cases-v1`.
- Added an atomic JSON run-record writer that stores the exact case list, explanations, seed, generator/Python versions, and harness outcomes.
- Ran the same problem and seed twice; the generated case sequences and statuses matched. All 11 valid cases passed; the boolean fixture remained `OUT_OF_CONTRACT` and the harness did not run its target.
- Saved the run at `runs/day15-sorting-edge-cases.json`. The edge-case test module passes; the complete project suite was not run for this documentation/generator step.

## Day 16 — Learn Hypothesis for property-based testing

- Installed Hypothesis `6.170.14` and pinned it as the optional `test` extra, so normal runtime installs do not gain a test-only dependency.
- The editable-extra pip install hit a setuptools temporary-path parsing error in this sandbox; installing the pinned Hypothesis package directly succeeded and the optional extra remains declared for normal setups.
- Added a contract-valid list strategy with integers from `-20` to `20`, list lengths from 0 to 12, and bounded deterministic settings (`max_examples=20`, 5-second deadline). The false-target search uses `max_examples=40` while Hypothesis shrinks its failure.
- The correct record passed generated cases through `check_case`; no model-written assertion or code is executed.
- Hypothesis found and shrank the faulty reverse-sort witness to `[0, 1]`. The harness confirmed contract validity and the independent oracle refuted the result: target `[1, 0]`, expected `[0, 1]`.
- The bounded pass means `TESTS_PASSED` for this strategy and run configuration, never `PROVEN` for every finite integer list.
- At Day 16 completion, the minimized witness had not yet been saved; Day 17 below records and replays it.

## Day 17 — Preserve shrinking and replay

- Added `abacus.hypothesis_capture.find_and_save_sorting_failure()`. It runs Hypothesis `find()` with explicit seed/settings, lets the Day 12 harness decide whether a generated input is refuted, rechecks the minimized input, and saves it with the Day 13 counterexample writer.
- Saved source metadata includes Hypothesis version `6.170.14`, strategy bounds, `max_examples=40`, `database=None`, `deadline_ms=5000`, and random seed `17017`.
- Saved the minimized `[0, 1]` witness to `counterexamples/sort-ascending-false-hypothesis-day17.json`; the record confirms contract validity, target `[1, 0]`, and expected output `[0, 1]`.
- Added a regression test that loads and replays this record with the ordinary harness, without using Hypothesis. Both focused Day 17 tests pass.

## Day 18 — Model proposed test inputs

- Added `abacus.proposals`, which prompts the configured model for up to five candidate inputs and rationales using the claim, code, domain, and preconditions. The requested response is strict JSON and has no verdict field.
- Added schema-aware parsing that rejects malformed JSON, duplicate keys, wrong types, extra fields, and oversized proposal lists. Malformed proposals are logged and returned as parse errors; no greedy regex extraction is used.
- Every proposal is checked against the registered input contract before execution. Out of contract values are logged and recorded as `REJECTED_OUT_OF_CONTRACT` without running target code. Valid values are passed to the trusted Day 12 harness and recorded with source `model_proposed` plus harness/oracle evidence.
- Added offline tests for valid harness flow, malformed and wrong-type responses, extra verdict fields, duplicate keys, and boolean out of contract input. The focused Day 18 test module passes (5 tests).
- No `GEMINI_API_KEY` is configured in this environment, so no live model request was made; the integration test used an injected structured response.

## Day 19 — Build the falsifier step

- Added `abacus.falsifier` with a separate adversarial prompt. It includes the claim, candidate code, domain, preconditions, property description, and oracle ID, but omits the expected label and the false seed's known counterexample.
- The falsifier requests only candidate inputs and rationales. Any top-level model `verdict` or `label` is ignored; strict proposal parsing and input-contract validation still apply.
- Each run is saved as an atomic JSON report containing the proposal, rationale, contract result, harness/oracle evidence, and replay result. Harness-refuted inputs are saved with the Day 13 counterexample format and replayed; only `REPRODUCED` replay is reported as `REFUTED`. Passing inputs are `REJECTED`; out-of-contract and non-refuting execution failures remain `INVALID_EVIDENCE`.
- Offline tests injected `[1, 2]` for the false seed and confirmed the oracle refutation plus replay. A deliberately incorrect model-supplied `verdict: TRUE` was discarded. The same input passed for the true seed and was recorded as rejected evidence; a boolean input was rejected before target execution. All 4 focused Day 19 tests pass.
- `GEMINI_API_KEY` is not configured here, so the model's actual discovery ability was not tested and no live API request was made.

## Day 20 — Add failure categories

- Added shared `FailureCategory` values for `OUT_OF_CONTRACT`, `TARGET_EXCEPTION`, `PROPERTY_VIOLATION`, `TEST_ORACLE_DEFECT`, `TIMEOUT`, `SANDBOX_FAILURE`, `API_ERROR`, `PARSE_ERROR`, and `INTERNAL_ERROR`, with a short definition and example for every category in `docs/failure-categories.md`.
- Harness case evidence now records one applicable category alongside its status and evidence. Proposal inputs carry contract/harness categories; API and malformed-response failures are `API_ERROR` and `PARSE_ERROR`. Falsifier reports include per-case and run-level categories.
- Kept failure classification separate from the final outcome: a timeout yields `UNRESOLVED`, a passing input is `REJECTED` as a falsifier candidate, and `REFUTED` still requires a trusted oracle refutation plus successful saved-counterexample replay.
- Added focused fixtures for contract rejection, target exceptions, property violations, oracle defects, timeouts, runner/output-protocol failures, API errors, parse errors, and internal errors. Harness (13), proposal (6), and falsifier (6) focused tests all pass.
- Runner failures use `SANDBOX_FAILURE` as a category label for the bounded execution boundary; the current runner is not an OS security sandbox.

## Day 21 review

Fixed edge cases and Hypothesis both exposed the duplicate-removal bug in the sorting seed and the incorrect result for all-negative inputs in the largest-value seed. Fixed cases made the boundary rationale visible; Hypothesis explored contract-valid lists and reduced its failing examples. Both sources used the same contract and trusted reference for each seed.

The offline LLM-style proposals found neither seeded bug: they proposed a sorted list without duplicates and a positive-only list. The invalid string and empty-list proposals were rejected as OUT_OF_CONTRACT before target execution. This shows why proposals need an independent checker; these fixtures were drafted for this review and did not come from a provider API.

## Day 22 outcomes

Added shared run-level outcome and reason enums plus a serializable outcome record. A completed finite suite is recorded as TESTS_PASSED with its count and methods; PROVEN remains in the vocabulary but requires formal-checker evidence and is not emitted by any finite-test helper. The Day 21 report now calls an individual passing case CASE_PASSED so it cannot be mistaken for a run verdict.

## Day 23 decision policy

Added a pure decide function that consumes normalized contract/evidence records and selects only REFUTED, TESTS_PASSED, UNRESOLVED, or ERROR. A counterexample must be contract-valid, use the configured oracle, and reproduce on replay; incomplete, invalid, conflicting, timed-out, and oracle-less runs stay UNRESOLVED. API and internal failures return ERROR with their category.

Standard-library fixtures cover the outcome paths and verify that changing extra LLM annotations does not change a result. The policy has no path to PROVEN; finite passing evidence remains TESTS_PASSED.

## Day 24 claim revisions

Added immutable original claim and label fields, separate revision text/reason/relation, and a trigger-evidence gate for revision prompts. The example narrows “all integer lists” to “non-empty integer lists” after a confirmed empty-list counterexample; the original REFUTED label and scored claim stay unchanged.

The revision view shows the original and proposed claim side by side and labels which one is scored. Revision proposals are structured fixtures; no provider API is called.

## Day 25 run budgets

Added a tracker that reserves call, token, estimated cost, and expected wall time before each model call. Retries count as new attempts; failed calls retain their estimates if actual usage is unknown. Budget exhaustion with incomplete evidence returns UNRESOLVED and saves a partial JSON log with configured limits, usage, and stop reason.

The tiny-token-budget example is blocked before making a call. Standard-library fixtures cover normal completion, retries, each budget limit, usage overruns, and partial-log serialization.

## Day 26 checker validation

Added manual expected-output fixtures for correct sort and largest functions, plus known mutants that remove duplicates or return zero for all-negative lists. The fixtures catch both target defects. A deliberately faulty sort oracle is itself flagged against the handwritten answers; when used to judge the correct sorter, it falsely reports a property violation for duplicate inputs.

Replayed all saved Day 21 counterexamples and confirmed they still reproduce. The sort idempotence relation passes for the duplicate-removing mutant, so it cannot replace checking the full duplicate-preservation contract. The manually written expected outputs were reviewed against the stated contracts, but no independent human reviewer was available; broader oracle soundness remains uncertain.

## Day 27 end-to-end pilot

Added `python -m abacus run <problem.json>`. The CLI validates JSON inputs and allowlisted target/oracle identifiers before evaluation. It runs fixed cases, bounded seeded Hypothesis cases, and offline proposal fixtures through the shared evidence policy; mismatches must reproduce before they can yield REFUTED. Each run saves its evidence, final outcome, optional revision record, errors, and budget usage as JSON.

The true sorting fixture finished 31 checks as TESTS_PASSED. The duplicate-removing fixture finished 31 checks and returned REFUTED from replay-confirmed input `[3, -1, 3, 0]`; its optional offline claim revision preserves the original scored claim and label. The run logs are in `runs/p01_true_sort.json` and `runs/p02_false_sort.json`. This pilot uses offline suggestion/proposal fixtures only and made zero provider calls. A failure-injection fixture confirms an optional proposal-stage error is logged with budget usage and yields ERROR.

## Day 28 verdict semantics review

Recorded the run-level meanings of REFUTED, TESTS_PASSED, UNRESOLVED, and ERROR with compact examples from the Day 27 logs and policy shapes. `CASE_PASSED` and `PROPERTY_VIOLATION` remain case-level labels. A finite test pass is explicitly not a proof; PROVEN remains reserved for identified formal proof evidence. The refutation example names the input, actual output, expected output, and successful replay. The false example's revision keeps the original scored claim and REFUTED label intact.

Open design questions for later work: should rejected problem files produce a distinct validation record/log; should unexpected pipeline exceptions use the same complete versioned record and budget fields as normal runs; what evidence is sufficient to set an oracle as usable; and what formal proof artifact format/version should be required before any path can issue PROVEN? These are recorded as questions and do not change the current outcome labels.

## Day 29 versioned run records

Added schema version 2 and validation before every CLI run record is saved. Records now carry a UUID; problem/dataset versions and hashes; original claim and contract; target and runner code hashes; Git/software versions; template/provider/model identity; generation methods, seeds, and settings; proposal fixtures; validated inputs; oracle outputs and replay details; outcome reason and evidence references; revision data; and duration, token, cost, call, budget, and error fields. Unknown provenance/usage is explicit rather than silently treated as zero.

Generated and validated one complete sample plus one partial UNRESOLVED sample. The validator rejects a missing dataset version, outcome reason, or evidence reference, and accepts a partial run only with a stated incomplete status/reason. Day 27's previous records are schema-v1 examples; new runs write v2. Run filenames still use the problem ID and can be overwritten; Day 30 will make filenames unique. The Day 28 question about uniform error records is addressed for caught/unexpected pipeline failures; process termination before the save step remains an open recovery case.

## Day 30 atomic, unique run storage

Default run filenames now include the problem ID, UTC timestamp, and UUID. The existing `runs/` Git ignore rule was confirmed. `save_run_record()` refuses an existing destination, writes and syncs a same-directory temporary file, renames it to the final path, then removes the `.incomplete` marker. The marker records run ID, final filename, temporary filename, and start time while a save is in progress, so interruption leaves recoverable state beside any partial file.

Added `list-runs` and `show-run <run_id>` commands. Repeated-run fixtures create two independently valid files for the same problem; interrupted-rename simulation leaves the marker and temporary file available for inspection. A caller-supplied `--output` path is also protected from overwrite. Directory fsync is skipped on Windows; file contents are flushed and synced before rename.

## Day 31 secret-safe logs

Added a shared redaction layer at the run-record and budget-log write boundaries. It replaces values in credential-named fields and scrubs labeled key/value text, authorization headers, common provider token formats, private-key blocks, and configured secret values found in the process environment. Run records are also sanitized before being returned from the pipeline. Numeric token-usage counters stay intact. Because redaction can change proposal text stored in the dataset, the dataset SHA-256 is recomputed from the sanitized body; the problem-spec SHA-256 remains the original input fingerprint. This catches recognized patterns and named fields, not arbitrary unmarked secret text.

The fake secret sentinel is split in the fixture source, injected through a sensitive environment variable, and confirmed absent from the saved error log and captured CLI output.

## Day 32 resource usage

Added provider token-usage normalization for common input/output field names. When calls exist but usage is missing, token and cost values remain unknown; zero is reported only for a run with no provider calls. Budget tracking now separates call attempts, successful calls, failures, and retries, and keeps provider-reported token totals distinct from estimates. Run records include planning/proposal/test/total durations and an optional model-specific pricing snapshot with its source URL and checked date. `summarize-runs` reports median/range metrics across saved runs. This pilot still makes no provider calls, so its API tokens and pricing are not applicable. Pricing is not prefilled because no provider/model has been selected.

## Day 33 readable run viewer

Added `python -m abacus view-run <RUN_ID>` while retaining `show-run` for raw JSON. The text summary shows the original claim/contract, verdict/reason, completed and scheduled counts, methods, candidate counterexamples with replay status, errors, incomplete reasons, and a path to the full evidence. Model suggestions and proposal fixtures are explicitly labeled unverified and kept apart from harness evidence. `TESTS_PASSED` always carries the note “No counterexample found in these tests; not a proof.” True, false, unresolved, and error fixtures cover the viewer.

## Day 34 retries and partial failures

Added a provider-call wrapper that retries only explicitly safe transient failures with at most two retries and exponential backoff. Authentication/configuration errors stop immediately. Timeouts, connection loss, and 5xx response loss are not retried because the provider may have completed the request; the failure carries ambiguous outcome and billing status. Every call attempt is reserved against the existing call, token, cost, and duration budgets, while failed-call categories and retry counts remain in the tracker events.

The pipeline now saves atomic checkpoints after each completed test, proposal, and revision stage. Run discovery and the viewer expose interrupted checkpoints; a later pipeline exception builds a schema-valid `ERROR` record from the latest checkpoint and retains its evidence, stage timing, errors, proposal state, and budget snapshot. Simulated late failure confirms completed evidence survives. This project still makes no real provider calls; retries are tested with local stubs.

## Day 35 audit from saved records

Added four validated v2 examples in `practice/samples/day35_*.v2.json`. The REFUTED and TESTS_PASSED examples each contain 31 completed checks. The UNRESOLVED example contains 6 of 31 checks after a stubbed generator returned no Hypothesis cases; its record labels the evidence incomplete. The ERROR example contains 29 completed checks and records the optional proposal-fixture failure. All four capture the problem dataset, contract, generation settings, target/runner hashes, Git revision, model template versions, evidence, outcome reason, and completion state.

Replayed the REFUTED example's saved `fixed-3` input `[3, -1, 3, 0]`. The target again returned `[-1, 0, 3]`; the oracle again returned `[-1, 0, 3, 3]`, matching the record's replay-confirmed counterexample. Scanned tracked source, ignored `runs/` JSON logs, and checked-in examples for recognized token/private-key patterns; no matches were found. The Day 31 secret-redaction regression is included in the verification suite.

These examples make no provider calls, so provider/model IDs are explicitly null and prompt template versions identify the offline fixture paths. No current offline-run field was missing. Before adding hosted-model evaluation, record the redacted prompt or a stable prompt hash and the request parameters alongside the existing provider/model IDs and template versions; exact hosted responses may still vary.

## Day 36 sandbox boundary

Documented the trust boundary and a fail-closed Docker Desktop Linux-container design in `practice/day36_sandbox_design.md`. The proposed runtime is Docker Desktop's per-user WSL 2 backend; the container receives bounded JSON through stdin, has no network or host mounts, runs as a fixed non-root user with a read-only root filesystem, and uses capped tmpfs, CPU, memory/swap, process, file-size, wall-time, and output limits. The host validates results and removes the disposable container in every exit path. `ABACUS_UNTRUSTED_EXECUTION` stays off by default, and no host-execution fallback is permitted.

## Day 37 sandbox verification

Added a minimal fixed-purpose probe image and a bounded Docker verification harness under `sandbox/day37/`. The probe harness accepts no candidate source. The image also has a separate Day 38 JSON executor; its CLI route remains closed unless the Day 37 report, exact image ID/runtime, and both opt-ins match. It resolves the official Python base tag to a repository digest before building, launches each harmless probe with the Day 36 limits, checks container settings before start, caps captured output, and removes each exact disposable container after its probe. See `practice/day37_sandbox_verification.md` for the current status. The image build and isolation probes remain pending because this machine currently has no Docker/Podman CLI and no WSL installation.

## Day 38 route untrusted execution through the sandbox

Added `abacus/sandbox.py` and the `execute-untrusted` CLI route. Candidate code is read only after the required `--allow-untrusted-code`, `ABACUS_UNTRUSTED_EXECUTION=1`, and Day 37 verification receipt pass. The runner checks the exact Docker version and image ID, inspects security controls before starting, streams bounded JSON, applies the Day 36 limits, and removes the named container on every attempted start. Startup/runtime/cleanup errors return a structured `ERROR`; the candidate is never passed to a host Python subprocess. Ordinary benchmark records and the run viewer label targets as `trusted_allowlist`; the separate execution result labels requested candidate code `untrusted_sandbox` and records hashes without source text or host paths. The current Day 37 report is BLOCKED, so actual untrusted code was not run.

Current machine check: Docker and Podman CLIs are absent and WSL reports not installed. The registry reports Windows 10 Home Single Language, 26H2, build 26300, so the supported OS build should be confirmed in Settings; RAM and virtualization also remain unverified. WSL enablement may require administrator elevation, so no runtime was installed during this design task. Day 37 must verify the host prerequisites and isolation probes before changing the default-off state. Docker Desktop's WSL backend shares a kernel; Enhanced Container Isolation is noted as an optional Business-subscription feature, not an assumed control.

## Day 39 module boundaries

Split the CLI's supporting code into `abacus/schemas.py` (validated inert problem data), `abacus/targets.py` (checked-in target/oracle allowlists), `abacus/experiment.py` (bounded case generation and trusted evidence collection), `abacus/llm.py` (provider interface and offline proposal fixtures), `abacus/prompts.py` (stable prompt/fixture identifiers), and `abacus/verifier.py` (pure outcome policy). `abacus/cli.py` retains command parsing and run orchestration; `abacus/sandbox.py` retains the isolated execution boundary. Module docstrings identify responsibility and trust level where code handles or executes data.

Kept the package at repository-root `abacus/` instead of moving it to `src/`: the existing documented `python -m abacus` workflow and project-root imports continue to work without packaging/install changes. Moved the verifier after checking current references and Git history; `practice/decision.py` remains a compatibility re-export for older examples/tests. Prompt/fixture version identifiers are centralized and copied into normal, emergency, and generated example run records. The provider boundary is only an interface: there is no configured client and it makes no network calls. The Day 37 sandbox verification remains BLOCKED, so Day 38 candidate execution remains gated off.

Verification after the move: `python -m abacus --help` loaded from the project root; 57 focused unit tests passed; both seed problems completed 31 checks with no provider call. `p01_true_sort` returned `TESTS_PASSED` (finite evidence only); `p02_false_sort` returned `REFUTED` with the saved counterexample replay confirmed. The run outputs are ignored under `runs/`.

## Day 40 structured model outputs

Added immutable response records and strict parsers in `abacus/schemas.py` for hypothesis statements, plan suggestions, and candidate input proposals. The parser accepts strict JSON and complete `json` fences; caps each response at 16 KiB, text at 1,000 characters, plans/proposal sets at 20 entries, candidate lists at 100 signed 64-bit integers, and rejects duplicate keys and non-standard JSON constants. Refusal, empty, oversized, truncated, invalid JSON, extra text, unknown fields, and schema/type errors are reported by distinct categories. Provider text is never stored or echoed in errors. The parser is not yet connected to a hosted API because no provider client is configured; `LLMClient` documents the validation requirement.

The Day 40 fixture suite covers valid values, fences, refusals, empty/truncated/invalid responses, prefix/suffix prose, unknown fields, wrong types, duplicate keys, non-standard constants, limits, and response non-disclosure. No SDK dependency or network call was added.

## Day 41 automated regression suite

Added `practice/run_test_suites.py` as the single documented test command. The initial root-level discovery tried to import Day 1–20 tests against the current root `abacus` package, producing nine import errors because those tests target the historical `src/abacus` package. The runner executes the two maintained suites in separate subprocesses with the correct package paths; it preserves all tests rather than disabling the older suite.

The complete run passed: 52 Day 1–20 tests plus 102 Day 21+ tests, 154 total, in 63.99 seconds. Coverage includes problem and output schemas, contract validation, outcomes, claim revisions, budgets/costs, counterexample save/replay, atomic storage, secret redaction, partial records/checkpoints, injected provider/API stubs, sandbox fail-closed behavior, and regression fixtures. Missing-provider-key log lines in API fixtures are expected; tests did not make live API calls.

## Day 42 clean-install review

Created a detached clean worktree at Day 41 HEAD, made a new Python 3.15 virtual environment, and installed `requirements.txt` plus `requirements-dev.txt` without a `.env` file or API key. The README now gives the full Windows PowerShell setup and offline test command in one place. No API key or project-specific setup step was needed for the suite and current CLI. A temporary-path override was used only to work around the managed shell's brace-containing temporary directory and is not a project prerequisite.

The complete runner passed on the fresh environment: 52 historical Day 1–20 tests and 102 current Day 21+ tests (154 total) in 81.14 seconds. The CLI help also loaded from the clean environment. `p01_true_sort` ran 31 checks and returned `TESTS_PASSED` (finite evidence only); `p02_false_sort` ran 31 checks and returned `REFUTED` with the `[3, -1, 3, 0]` counterexample replay confirmed. Both runs reported `provider_api_called: false`. The two older Day 8 seed records validated successfully using the historical `src/abacus/` package from `tests/` with `PYTHONPATH` pointed at `src/`; the README's old root-level command was invalid after the package split and is now corrected.

`.gitignore` now explicitly excludes `.env`, `runs/`, `.venv/`, Python bytecode, Hypothesis/pytest/mypy/ruff caches, coverage output, and build artifacts.

## Day 43 GitHub Actions regression workflow

Added `.github/workflows/ci.yml`. It runs the unified 154-test suite on pushes and pull requests for `main`, plus manual dispatch, using Python 3.11 (the package's declared minimum) and 3.14 on Ubuntu 24.04. The workflow follows the Day 42 clean install, uses a pip cache keyed by both requirements files, has a 10-minute job timeout, grants only `contents: read`, and supplies no provider credentials. `actions/checkout` and `actions/setup-python` are pinned to verified release commit SHAs.

Local checks: manually reviewed workflow triggers, matrix, action references, permissions, dependency paths, and command indentation; `git diff --check` passed. No YAML/actionlint parser is installed in this environment, so a machine YAML parse and GitHub-hosted matrix run remain pending until the workflow reaches GitHub.

## Day 44 CLI smoke checks

Added `practice/test_day44_cli_smoke.py`; because the Day 21+ suite discovers `practice/test_*.py`, these subprocess checks run automatically in CI. They invoke the CLI against `p01_true_sort` and `p02_false_sort`, verify the console summary and saved JSON outcomes, require `provider_api_called` to remain false, and require confirmed counterexample replay for the false seed. Each run writes only to a temporary directory, and the child process receives no provider API keys. Focused test results are recorded after execution.

Verification: the focused smoke suite passed 2/2 tests in 3.76 seconds. The complete unified regression suite passed 156 tests: 52 historical Day 1–20 tests and 104 current Day 21+ tests, in 54.05 seconds. All runs completed without live provider calls.

## Day 45 cross-platform GitHub Actions matrix

Expanded `.github/workflows/ci.yml` to run the same 3.11/3.14 test matrix on both `ubuntu-24.04` and `windows-2025`, for four jobs total. The test command, pinned actions, pip cache, 10-minute timeout, read-only permission, and API-key-free environment remain the same. GitHub's hosted-runner reference lists both labels; its Windows 2025 image includes Python 3.11 and 3.14 tool-cache versions.

The unified suite passed 156/156 on the local Windows environment during Day 44. This workflow-only matrix expansion has not run on GitHub; remote verification remains pending until push. `git diff --check` passed after this change.

## Day 46 Dependabot updates

Added `.github/dependabot.yml` with weekly version-update checks for `github-actions` and `pip`, capped at two and three open PRs respectively. The action references in the workflow remain pinned to commit SHAs and include release tags in same-line comments, which Dependabot uses to track the intended action release. Version updates arrive as PRs and are not auto-merged; the CI workflow checks them when pushed/opened against `main`.

Static review and `git diff --check` passed. No YAML parser is installed locally, and the Dependabot schedule cannot be observed until this configuration is pushed and GitHub processes its first weekly check.

## Day 47 YAML lint gate

Added pinned `yamllint==1.38.0` in CI-only `requirements-ci.txt`, a shared `.yamllint` configuration, and a CI step that runs `yamllint --strict` against both GitHub config files before the tests. The linter is deliberately separate from normal dev requirements: the current PyYAML sdist otherwise requires a Microsoft C++ compiler on Python 3.15, while CI's 3.11/3.14 matrix has compatible wheels. The local PowerShell command sets PyYAML's pure-Python build option for the optional linter install. The configuration disables the document-start rule (not required by GitHub files), exempts mapping keys from the YAML truthy check so GitHub's `on` key is accepted, and keeps duplicate-key/indentation/trailing-space checks active.

Verification: `yamllint --strict .github/workflows/ci.yml .github/dependabot.yml` passed in both Python 3.14 and Python 3.15 environments. The Python 3.15 installation used the documented pure-Python option. Normal Python 3.15 dev requirements remain free of yamllint/PyYAML and do not add an optional toolchain requirement.

## Day 48 Windows YAML line endings

Checked the GitHub Actions runs for the Day 47 commit `b0697f1`. Both Ubuntu jobs passed, while both Windows jobs failed at the strict YAML lint step before the regression suite ran. Public check annotations identified CRLF line endings in `.github/dependabot.yml` and `.github/workflows/ci.yml`; the hosted Windows checkout had converted them even though local lint passed. Added `.gitattributes` with `*.yml text eol=lf` so Git checks YAML files out with LF on every platform. The first GitHub Actions workflow run and the four-job Day 45 matrix were green. The line-ending fix still needs to be pushed and the matrix rerun.
