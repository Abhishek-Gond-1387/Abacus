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
