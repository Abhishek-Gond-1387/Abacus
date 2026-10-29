# Abacus

Abacus is a research prototype for checking precise claims about Python functions. It will search for candidate counterexamples and use trusted checks to decide what the evidence supports. A passing finite test run is not a proof of correctness.

This repository currently contains the Day 1–3 setup and Python practice exercises from the 56-day build plan. It uses only the Python standard library.

## Run the exercises

From this directory:

```powershell
.\.venv\Scripts\python.exe hello.py
.\.venv\Scripts\python.exe practice\day02.py
.\.venv\Scripts\python.exe practice\day03.py
```

The Day 3 script anchors its sample files to the project directory, so it also works when launched from another current directory.
