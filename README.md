# Abacus

Abacus is a research prototype for checking precise claims about Python functions. It will search for candidate counterexamples and use trusted checks to decide what the evidence supports. A passing finite test run is not a proof of correctness.

This repository contains the Day 1–3 setup and Python practice exercises, plus a Day 21 comparison review from the 56-day build plan. The review uses Hypothesis for bounded case generation.

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
