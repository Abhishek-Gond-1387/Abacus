"""Bounded subprocess runner for hand-authored, trusted Python programs.

This module improves execution reliability; it is not a security sandbox.
Child code can still access files and resources available to the current user.
"""

from __future__ import annotations

import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class RunCategory(str, Enum):
    SUCCESS = "SUCCESS"
    ASSERTION_FAILURE = "ASSERTION_FAILURE"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    EXCEPTION = "EXCEPTION"
    NONZERO_EXIT = "NONZERO_EXIT"
    TIMEOUT = "TIMEOUT"
    OUTPUT_LIMIT = "OUTPUT_LIMIT"
    START_ERROR = "START_ERROR"


@dataclass(frozen=True)
class ExecutionResult:
    """Bounded result metadata from one child-process execution."""

    category: RunCategory
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    output_limit_exceeded: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.category is RunCategory.SUCCESS


def _child_environment() -> dict[str, str]:
    """Pass only platform essentials, avoiding inherited API credentials."""

    allowed_names = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH")
    return {
        name: os.environ[name]
        for name in allowed_names
        if name in os.environ
    }


def _stop_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Stop the child and ordinary descendants so pipe readers can finish."""

    if process.poll() is not None:
        return

    if os.name == "nt":
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        taskkill = Path(system_root) / "System32" / "taskkill.exe"
        try:
            subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def run_trusted_program(
    code: str,
    *,
    timeout_seconds: float = 2.0,
    max_output_bytes: int = 8_192,
    temp_root: str | os.PathLike[str] | None = None,
) -> ExecutionResult:
    """Run a trusted Python snippet with timeout and combined output limits.

    ``max_output_bytes`` is a combined stdout+stderr cap. Output is read in
    chunks and retained only up to that cap, so a noisy child cannot grow the
    runner's captured-output buffers without bound. A timeout or output-limit
    breach terminates the child process group/tree where the platform allows.
    """

    if not isinstance(code, str):
        raise TypeError("code must be a string")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be a finite positive number")
    try:
        timeout_value = float(timeout_seconds)
    except (OverflowError, ValueError):
        raise ValueError("timeout_seconds must be a finite positive number") from None
    if not math.isfinite(timeout_value) or timeout_value <= 0:
        raise ValueError("timeout_seconds must be a finite positive number")
    if type(max_output_bytes) is not int or max_output_bytes <= 0:
        raise ValueError("max_output_bytes must be a positive integer")

    started = time.perf_counter()
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}
    captured_bytes = 0
    capture_lock = threading.Lock()
    output_limit_event = threading.Event()
    timed_out = False
    output_limit_exceeded = False
    process: subprocess.Popen[bytes] | None = None
    readers: list[threading.Thread] = []

    def read_stream(name: str, pipe: Any) -> None:
        nonlocal captured_bytes
        while True:
            try:
                chunk = os.read(pipe.fileno(), 4_096)
            except (OSError, ValueError):
                return
            if not chunk:
                return
            with capture_lock:
                remaining = max_output_bytes - captured_bytes
                accepted = chunk[:remaining]
                buffers[name].extend(accepted)
                captured_bytes += len(accepted)
                if len(accepted) != len(chunk):
                    truncated[name] = True
                    output_limit_event.set()

    try:
        with tempfile.TemporaryDirectory(
            prefix="abacus-run-",
            dir=os.fspath(temp_root) if temp_root is not None else None,
        ) as directory:
            program_path = Path(directory) / "program.py"
            program_path.write_text(code, encoding="utf-8")

            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen(
                [sys.executable, "-I", "-X", "utf8", str(program_path)],
                cwd=directory,
                env=_child_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
            deadline = time.perf_counter() + timeout_value

            assert process.stdout is not None
            assert process.stderr is not None
            readers = [
                threading.Thread(
                    target=read_stream,
                    args=("stdout", process.stdout),
                    daemon=True,
                ),
                threading.Thread(
                    target=read_stream,
                    args=("stderr", process.stderr),
                    daemon=True,
                ),
            ]
            try:
                for reader in readers:
                    reader.start()

                while process.poll() is None:
                    if output_limit_event.is_set():
                        output_limit_exceeded = True
                        _stop_process_tree(process)
                        break
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        timed_out = True
                        _stop_process_tree(process)
                        break
                    output_limit_event.wait(min(remaining, 0.01))
            finally:
                if process.poll() is None:
                    _stop_process_tree(process)
                process.wait()
                for reader in readers:
                    if reader.ident is not None:
                        reader.join()
                process.stdout.close()
                process.stderr.close()

            # A stream may reveal the limit while the process is being reaped.
            output_limit_exceeded = output_limit_exceeded or output_limit_event.is_set()
            exit_code = process.returncode

    except OSError as error:
        return ExecutionResult(
            category=RunCategory.START_ERROR,
            exit_code=process.returncode if process is not None else None,
            stdout=buffers["stdout"].decode("utf-8", errors="replace"),
            stderr=buffers["stderr"].decode("utf-8", errors="replace"),
            duration_seconds=time.perf_counter() - started,
            error_message=f"{type(error).__name__}: {error}",
        )

    stderr = buffers["stderr"].decode("utf-8", errors="replace")
    if output_limit_exceeded:
        category = RunCategory.OUTPUT_LIMIT
    elif timed_out:
        category = RunCategory.TIMEOUT
    elif exit_code == 0:
        category = RunCategory.SUCCESS
    elif "SyntaxError" in stderr:
        category = RunCategory.SYNTAX_ERROR
    elif "AssertionError" in stderr:
        category = RunCategory.ASSERTION_FAILURE
    elif "Traceback (most recent call last):" in stderr:
        category = RunCategory.EXCEPTION
    else:
        category = RunCategory.NONZERO_EXIT

    return ExecutionResult(
        category=category,
        exit_code=exit_code,
        stdout=buffers["stdout"].decode("utf-8", errors="replace"),
        stderr=stderr,
        duration_seconds=time.perf_counter() - started,
        timed_out=timed_out,
        output_limit_exceeded=output_limit_exceeded,
        stdout_truncated=truncated["stdout"],
        stderr_truncated=truncated["stderr"],
    )
