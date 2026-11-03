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
