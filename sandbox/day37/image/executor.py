"""Control process for candidate execution inside a restricted container."""

import json
import os
import selectors
import signal
import subprocess
import sys
import time


MAX_REQUEST_BYTES = 1024 * 1024
MAX_CHILD_OUTPUT_BYTES = 512 * 1024
CHILD_WALL_SECONDS = 4.0


def _kill_worker_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        try:
            process.kill()
        except OSError:
            pass


def _run_worker(request_bytes):
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", "/opt/abacus/worker.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
        )
    except OSError:
        return "worker_start_failure", b""

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    total = 0
    reason = None

    try:
        remaining = memoryview(request_bytes)
        while remaining:
            count = process.stdin.write(remaining)
            if not count:
                raise BrokenPipeError
            remaining = remaining[count:]
        process.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        reason = "worker_input_failure"
        _kill_worker_group(process)

    deadline = time.monotonic() + CHILD_WALL_SECONDS
    while selector.get_map() or process.poll() is None:
        if reason is None and time.monotonic() >= deadline:
            reason = "worker_timeout"
            _kill_worker_group(process)
        events = selector.select(0.05)
        for key, _ in events:
            try:
                chunk = os.read(key.fileobj.fileno(), 8192)
            except OSError:
                chunk = b""
            if not chunk:
                selector.unregister(key.fileobj)
                key.fileobj.close()
                continue
            limit_remaining = max(0, MAX_CHILD_OUTPUT_BYTES - total)
            captured[key.data].extend(chunk[:limit_remaining])
            total += min(len(chunk), limit_remaining)
            if len(chunk) > limit_remaining and reason is None:
                reason = "worker_output_limit"
                _kill_worker_group(process)
        if reason is not None and process.poll() is not None and not events:
            break

    selector.close()
    try:
        return_code = process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        _kill_worker_group(process)
        process.wait()
        return "worker_cleanup_failure", b""
    if reason is not None:
        return reason, b""
    if return_code != 0:
        return "worker_nonzero_exit", b""
    return None, bytes(captured["stdout"])


def main():
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        print(json.dumps({"status": "error", "reason": "request_too_large"}))
        return 2
    try:
        request = json.loads(raw.decode("utf-8"))
        if type(request) is not dict or set(request) != {"source", "input"}:
            raise ValueError("invalid request shape")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        print(json.dumps({"status": "error", "reason": "invalid_request"}))
        return 2

    reason, worker_output = _run_worker(raw)
    if reason is not None:
        response = {"status": "error", "reason": reason}
    else:
        try:
            response = json.loads(worker_output.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            response = {"status": "error", "reason": "invalid_worker_response"}
    if type(response) is not dict or response.get("status") not in {"ok", "error"}:
        response = {"status": "error", "reason": "invalid_worker_response"}
    sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
