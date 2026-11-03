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

## Next

- Day 4 completed: staged named files, reviewed the staged diff, and created the first local commit.
- Day 36 completed; next: Day 37 — build and verify the isolated runner.

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
