"""Run legacy and current test suites with their respective package roots."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _summary_count(output: str) -> int | None:
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "Ran" and parts[2] == "tests":
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


def main() -> int:
    legacy_environment = os.environ.copy()
    legacy_environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    suites = (
        (
            "Day 1-20 legacy tests",
            PROJECT_ROOT / "tests",
            [sys.executable, "-m", "unittest", "discover", "-v"],
            legacy_environment,
        ),
        (
            "Day 21+ current tests",
            PROJECT_ROOT,
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "practice",
                "-p",
                "test_*.py",
                "-v",
            ],
            os.environ.copy(),
        ),
    )

    total_started = time.perf_counter()
    test_count = 0
    successful = True
    for label, directory, command, environment in suites:
        print(f"\n=== {label} ===", flush=True)
        started = time.perf_counter()
        result = subprocess.run(
            command,
            cwd=directory,
            env=environment,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        elapsed = time.perf_counter() - started
        output = result.stdout + result.stderr
        print(output, end="" if output.endswith("\n") else "\n")
        count = _summary_count(output)
        if count is not None:
            test_count += count
        successful = successful and result.returncode == 0
        print(
            f"{label}: {'PASS' if result.returncode == 0 else 'FAIL'}, "
            f"{count if count is not None else 'unknown'} tests, {elapsed:.2f}s"
        )

    total_elapsed = time.perf_counter() - total_started
    print(
        f"\nFULL SUITE: {'PASS' if successful else 'FAIL'}, "
        f"{test_count} tests, {total_elapsed:.2f}s"
    )
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
