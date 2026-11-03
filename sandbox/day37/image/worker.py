"""Run candidate source in a short-lived child process inside the container."""

import contextlib
import io
import json
import sys


MAX_REQUEST_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 256 * 1024


def main():
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        print(json.dumps({"status": "error", "reason": "request_too_large"}))
        return 2
    try:
        request = json.loads(raw.decode("utf-8"))
        if type(request) is not dict or set(request) != {"source", "input"}:
            raise ValueError("invalid request shape")
        source = request["source"]
        if type(source) is not str or not source.strip() or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("invalid source")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        print(json.dumps({"status": "error", "reason": "invalid_request"}))
        return 2

    captured = io.StringIO()
    try:
        namespace = {"__name__": "__abacus_untrusted_candidate__"}
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            exec(compile(source, "<untrusted-candidate>", "exec"), namespace, namespace)
            candidate = namespace.get("candidate")
            if not callable(candidate):
                raise TypeError("candidate function is missing")
            result = candidate(request["input"])
        response = {"status": "ok", "result": result}
        encoded = json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except Exception as exc:
        response = {"status": "error", "reason": "candidate_error", "exception_type": type(exc).__name__}
        encoded = json.dumps(response, separators=(",", ":"))
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
