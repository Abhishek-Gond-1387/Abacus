# Abacus

Abacus is a research prototype for checking precise claims about Python functions. It searches for candidate counterexamples and uses trusted checks to decide what the evidence supports. A passing finite test run is not a proof of correctness.

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

Validate both examples with:

```powershell
.\.venv\Scripts\python.exe -m abacus.problems problems\sort-ascending-true.json problems\sort-ascending-false.json
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
