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
- Next: Day 11 — run trusted code in a child process and classify exits, exceptions, timeouts, and bounded output.
