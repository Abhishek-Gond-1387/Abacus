"""Build-independent, fail-closed verifier for the Day 37 probe image."""

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path


IMAGE_DEFAULT = "abacus-sandbox-day37:local"
MEMORY_BYTES = 256 * 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
WALL_SECONDS = 5.0
REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_DEFAULT = REPO_ROOT / "practice" / "day37_sandbox_verification.md"


class VerificationError(RuntimeError):
    pass


def bounded_process(argv, *, input_bytes=None, timeout=10.0, output_limit=MAX_OUTPUT_BYTES):
    """Run a fixed local command while bounding time and combined pipe output."""
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except OSError as exc:
        return {"returncode": None, "reason": "launch_error", "error": type(exc).__name__, "stdout": b"", "stderr": b""}

    captured = {"stdout": bytearray(), "stderr": bytearray()}
    state = {"bytes": 0, "reason": None}
    lock = threading.Lock()

    def drain(name, pipe):
        try:
            while True:
                chunk = os.read(pipe.fileno(), 8192)
                if not chunk:
                    return
                with lock:
                    remaining = max(0, output_limit - state["bytes"])
                    accepted = chunk[:remaining]
                    captured[name].extend(accepted)
                    state["bytes"] += len(accepted)
                    if len(chunk) > remaining and state["reason"] is None:
                        state["reason"] = "output_limit"
                        try:
                            process.kill()
                        except OSError:
                            pass
        except (OSError, ValueError):
            return

    readers = [
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in readers:
        thread.start()

    def write_input():
        if input_bytes is None:
            return
        try:
            process.stdin.write(input_bytes)
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass

    writer = threading.Thread(target=write_input, daemon=True)
    if input_bytes is not None:
        writer.start()

    deadline = time.monotonic() + timeout
    while process.poll() is None:
        if state["reason"] == "output_limit":
            break
        if time.monotonic() >= deadline:
            with lock:
                if state["reason"] is None:
                    state["reason"] = "wall_time_limit"
            try:
                process.kill()
            except OSError:
                pass
            break
        time.sleep(0.02)

    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)
    if input_bytes is not None:
        writer.join(timeout=1.0)
    for thread in readers:
        thread.join(timeout=1.0)
    for pipe in (process.stdin, process.stdout, process.stderr):
        if pipe is not None:
            try:
                pipe.close()
            except OSError:
                pass
    return {
        "returncode": process.returncode,
        "reason": state["reason"],
        "stdout": bytes(captured["stdout"]),
        "stderr": bytes(captured["stderr"]),
        "output_bytes": state["bytes"],
    }


def docker(argv, *, input_bytes=None, timeout=10.0, output_limit=MAX_OUTPUT_BYTES):
    result = bounded_process(
        ["docker", *argv], input_bytes=input_bytes, timeout=timeout, output_limit=output_limit
    )
    if result["reason"]:
        raise VerificationError(f"docker {' '.join(argv[:2])} stopped by {result['reason']}")
    if result["returncode"] != 0:
        detail = result["stderr"].decode("utf-8", "replace")[-800:].strip()
        raise VerificationError(f"docker {' '.join(argv[:2])} failed ({result['returncode']}): {detail}")
    return result


def decode_json(result, label):
    try:
        return json.loads(result["stdout"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"Docker returned invalid {label} JSON") from exc


def inspect_container(identifier):
    return decode_json(docker(["inspect", identifier], output_limit=128 * 1024), "container")[0]


def inspect_image(image):
    return decode_json(docker(["image", "inspect", image], output_limit=128 * 1024), "image")[0]


def verify_image(image_details):
    config = image_details.get("Config") or {}
    labels = config.get("Labels") or {}
    base_image = labels.get("org.abacus.base-image", "")
    errors = []
    if labels.get("org.abacus.day37") != "fixed-purpose-sandbox-probes":
        errors.append("fixed-probe image label is missing")
    if not re.fullmatch(r"python@sha256:[0-9a-f]{64}", base_image):
        errors.append("base image is not an immutable Python repository digest")
    if config.get("Entrypoint") != ["python", "/opt/abacus/probe.py"]:
        errors.append("unexpected image entrypoint")
    if config.get("User") != "65534:65534":
        errors.append("image default user is not non-root")
    if config.get("WorkingDir") != "/work":
        errors.append("unexpected image working directory")
    if image_details.get("Os") != "linux":
        errors.append("probe image is not Linux")
    if errors:
        raise VerificationError("image rejected before container creation: " + ", ".join(errors))
    return base_image


def verify_container_config(details):
    config = details.get("Config") or {}
    host = details.get("HostConfig") or {}
    errors = []
    if config.get("User") != "65534:65534":
        errors.append("non-root user mismatch")
    if config.get("OpenStdin") is not True:
        errors.append("bounded JSON stdin is not enabled")
    if host.get("NetworkMode") != "none":
        errors.append("network is not disabled")
    if host.get("ReadonlyRootfs") is not True:
        errors.append("root filesystem is writable")
    if host.get("NanoCpus") != 1_000_000_000:
        errors.append("CPU quota mismatch")
    if host.get("Memory") != MEMORY_BYTES or host.get("MemorySwap") != MEMORY_BYTES:
        errors.append("memory/swap limit mismatch")
    if host.get("PidsLimit") != 64:
        errors.append("process limit mismatch")
    if host.get("Privileged") is not False:
        errors.append("privileged mode is enabled")
    if host.get("Devices"):
        errors.append("device mappings are present")
    if host.get("Binds"):
        errors.append("host bind mount is present")
    if host.get("CapAdd"):
        errors.append("capabilities were added")
    if "ALL" not in (host.get("CapDrop") or []):
        errors.append("Linux capabilities were not all dropped")
    if "no-new-privileges=true" not in (host.get("SecurityOpt") or []):
        errors.append("no-new-privileges is missing")
    if "seccomp=unconfined" in (host.get("SecurityOpt") or []):
        errors.append("default seccomp profile is disabled")
    if (host.get("LogConfig") or {}).get("Type") != "none":
        errors.append("container log driver is not disabled")

    ulimits = {item.get("Name"): item for item in host.get("Ulimits") or []}
    for name, value in (("cpu", 5), ("fsize", 8 * 1024 * 1024)):
        entry = ulimits.get(name) or {}
        if entry.get("Soft") != value or entry.get("Hard") != value:
            errors.append(f"{name} ulimit mismatch")

    tmpfs = host.get("Tmpfs") or {}
    for target, mode in (("/tmp", "1777"), ("/work", "700")):
        options = tmpfs.get(target, "")
        if "size=16m" not in options or "noexec" not in options or "nosuid" not in options or "nodev" not in options:
            errors.append(f"{target} tmpfs options mismatch")
        if f"mode={mode}" not in options:
            errors.append(f"{target} tmpfs mode mismatch")

    mounts = details.get("Mounts") or []
    if any(item.get("Type") == "bind" for item in mounts):
        errors.append("container has a bind mount")
    mount_targets = {item.get("Destination") for item in mounts}
    if mount_targets != {"/tmp", "/work"}:
        errors.append("unexpected or missing container mount")
    if any(item.get("Type") != "tmpfs" for item in mounts):
        errors.append("non-tmpfs container mount is present")

    env_names = [str(item).split("=", 1)[0] for item in config.get("Env") or []]
    if any(re.search(r"key|token|secret|password|credential|auth|aws|azure|gcp", name, re.I) for name in env_names):
        errors.append("credential-like environment variable is present")
    return errors


def probe_container(action, payload, image):
    name = f"abacus-d37-{action}-{uuid.uuid4().hex[:12]}"
    create_args = [
        "create",
        "--interactive",
        "--name", name,
        "--label", "org.abacus.purpose=day37-fixed-probe",
        "--network", "none",
        "--read-only",
        "--user", "65534:65534",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges=true",
        "--cpus", "1",
        "--memory", str(MEMORY_BYTES),
        "--memory-swap", str(MEMORY_BYTES),
        "--pids-limit", "64",
        "--ulimit", "cpu=5:5",
        "--ulimit", f"fsize={8 * 1024 * 1024}:{8 * 1024 * 1024}",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
        "--tmpfs", "/work:rw,noexec,nosuid,nodev,size=16m,mode=700,uid=65534,gid=65534",
        "--log-driver", "none",
        image,
        action,
    ]
    create_result = docker(create_args, timeout=15.0, output_limit=4096)
    identifier = create_result["stdout"].decode("ascii", "replace").strip()
    if not re.fullmatch(r"[0-9a-f]{12,64}", identifier):
        bounded_process(["docker", "rm", "--force", name], timeout=10.0, output_limit=4096)
        raise VerificationError("Docker create returned an invalid container ID")

    row = {"action": action, "passed": False, "detail": "not completed"}
    removed = False
    try:
        details = inspect_container(identifier)
        config_errors = verify_container_config(details)
        if config_errors:
            raise VerificationError("container config rejected before start: " + ", ".join(config_errors))

        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 1024 * 1024:
            raise VerificationError("probe input exceeds the 1 MiB JSON limit")
        result = bounded_process(
            ["docker", "start", "--attach", "--interactive", identifier],
            input_bytes=encoded,
            timeout=WALL_SECONDS,
            output_limit=MAX_OUTPUT_BYTES,
        )
        state = inspect_container(identifier).get("State") or {}
        row.update(
            {
                "returncode": result["returncode"],
                "container_exit": state.get("ExitCode"),
                "oom_killed": bool(state.get("OOMKilled")),
                "timed_out": result["reason"] == "wall_time_limit",
                "output_limited": result["reason"] == "output_limit",
                "output_bytes": result.get("output_bytes", 0),
            }
        )
        stdout = result["stdout"].decode("utf-8", "replace")
        parsed = None
        if stdout.strip():
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError:
                parsed = None

        if action == "identity":
            row["observed"] = parsed
            passed = bool(
                parsed
                and parsed.get("uid") != 0
                and parsed.get("rootfs_write_blocked") is True
                and parsed.get("memory_max") == str(MEMORY_BYTES)
                and parsed.get("pids_max") == "64"
                and parsed.get("cpu_max") in ("100000 100000", "100000 100000\n")
                and parsed.get("file_size_limit_bytes") == [8 * 1024 * 1024, 8 * 1024 * 1024]
                and parsed.get("tmpfs_work_bytes", MEMORY_BYTES + 1) <= 16 * 1024 * 1024
                and parsed.get("tmpfs_tmp_bytes", MEMORY_BYTES + 1) <= 16 * 1024 * 1024
                and result["returncode"] == 0
            )
            if parsed:
                row["detail"] = (
                    f"Python {parsed.get('python', 'unknown')}; uid/gid {parsed.get('uid')}/{parsed.get('gid')}; "
                    f"cgroups memory={parsed.get('memory_max')}, pids={parsed.get('pids_max')}, cpu={parsed.get('cpu_max')}; "
                    "read-only rootfs and ulimits checked"
                )
            else:
                row["detail"] = "identity/resource observation missing"
        elif action in ("host-file", "network"):
            row["observed"] = parsed
            passed = bool(parsed and parsed.get("blocked") is True and result["returncode"] == 0)
            row["detail"] = "access attempt blocked" if passed else "access attempt was not blocked"
        elif action == "privilege":
            row["observed"] = parsed
            passed = bool(
                parsed
                and parsed.get("non_root") is True
                and parsed.get("raw_socket_blocked") is True
                and parsed.get("device_blocked") is True
                and result["returncode"] == 0
            )
            row["detail"] = "non-root identity, raw socket, and kernel device restrictions observed" if passed else "privilege/device control was not observed"
        elif action == "processes":
            row["observed"] = parsed
            passed = bool(
                parsed
                and parsed.get("limit_blocked") is True
                and 1 <= parsed.get("started", 999) <= 63
                and result["returncode"] == 0
            )
            row["detail"] = "process creation stopped at the configured pids limit" if passed else "pids limit was not observed"
        elif action == "memory":
            row["observed"] = parsed
            passed = bool(
                (parsed and parsed.get("limited") is True and result["returncode"] == 0)
                or (state.get("OOMKilled") is True and state.get("ExitCode") == 137)
            )
            row["detail"] = "allocation was limited by the configured memory cap" if passed else "memory cap was not observed"
        elif action == "file-size":
            row["observed"] = parsed
            passed = bool(
                parsed
                and parsed.get("blocked") is True
                and parsed.get("bytes_written", MEMORY_BYTES + 1) <= 8 * 1024 * 1024
                and result["returncode"] == 0
            )
            row["detail"] = "file growth stopped at the configured per-file limit" if passed else "file-size limit was not observed"
        elif action == "wall-time":
            passed = result["reason"] == "wall_time_limit"
            row["detail"] = "five-second host supervisor timeout stopped the sleeping probe" if passed else "wall-time limit was not observed"
        elif action == "output-flood":
            passed = result["reason"] == "output_limit" and result.get("output_bytes", 0) <= MAX_OUTPUT_BYTES
            row["detail"] = "combined stdout/stderr capture was capped at 1 MiB" if passed else "output cap was not observed"
        else:
            passed = False
            row["detail"] = "unknown action"

        row["passed"] = passed
    finally:
        cleanup = bounded_process(["docker", "rm", "--force", identifier], timeout=10.0, output_limit=4096)
        cleanup_text = cleanup["stdout"].decode("utf-8", "replace").strip()
        removed = cleanup["returncode"] == 0 and bool(cleanup_text)
        row["cleanup"] = "removed" if removed else "failed"
        absent = bounded_process(["docker", "inspect", identifier], timeout=10.0, output_limit=4096)
        absent_error = absent["stderr"].decode("utf-8", "replace").lower()
        row["cleanup_verified"] = absent["returncode"] != 0 and (
            "no such container" in absent_error or "no such object" in absent_error
        )
        if not removed or not row["cleanup_verified"]:
            row["passed"] = False
            row["detail"] += "; container cleanup was not verified"
    return row


def current_revision():
    result = bounded_process(["git", "rev-parse", "--short", "HEAD"], timeout=3.0, output_limit=256)
    if result["returncode"] == 0:
        return result["stdout"].decode("ascii", "replace").strip()
    return "unknown"


def write_report(path, *, status, runtime="NOT AVAILABLE", image="NOT BUILT", rows=None, error=None):
    rows = rows or []
    result_rows = {row["action"]: row for row in rows}
    actions = ("identity", "host-file", "network", "privilege", "processes", "memory", "file-size", "wall-time", "output-flood")
    lines = [
        "# Day 37 — Isolated runner verification",
        "",
        f"**Status: {status}.**",
        "",
        f"- Recorded: {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}",
        f"- Host: `{platform.platform()}`",
        f"- Git revision: `{current_revision()}`",
        f"- Docker engine: `{runtime}`",
        f"- Image: `{image}`",
        "- Generated-code execution: **off**",
        "",
        "## Host prerequisite baseline",
        "",
        "The Day 36 check on 2026-11-03 found Docker and Podman CLIs absent and WSL not installed. The registry snapshot reported Windows 10 Home Single Language, DisplayVersion 26H2, build 26300, while the Windows platform API reports Windows 11 / 10.0.26300; confirm the edition and build in Settings before installing a backend. RAM and hardware virtualization remain unchecked. This is historical context; check the host again before acting.",
        "",
        "Docker's [current Windows requirements](https://docs.docker.com/desktop/setup/install/windows-install/) list supported builds/editions, WSL 2.1.5+, virtualization, and 8 GB RAM for the WSL backend. Docker also documents [Docker VMM](https://docs.docker.com/desktop/features/vmm/) as a beta Windows backend on newer Desktop releases. First-time WSL enablement requires administrator privileges.",
        "",
        "## Probe outcomes",
        "",
        "| Probe | Result | Notes |",
        "|---|---|---|",
    ]
    for action in actions:
        row = result_rows.get(action)
        if row is None:
            outcome, note = "NOT RUN", ""
        else:
            outcome = "PASS" if row.get("passed") else "FAIL"
            note = row.get("detail", "")
            if row.get("cleanup"):
                note += f"; cleanup: {row['cleanup']}"
        lines.append(f"| {action} | {outcome} | {note.replace('|', '/')} |")
    lines.extend(
        [
            "",
            "## Assessment",
            "",
            "This verification harness runs fixed probes only. It does not execute model-generated or user-supplied source code. Keep Abacus untrusted-code execution disabled until every required probe passes on the intended runtime and an experienced reviewer accepts the isolation boundary.",
        ]
    )
    if error:
        lines.extend(["", "## Blocker", "", error.replace("\n", " ")])
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run_verification(image, rows):
    if not shutil.which("docker"):
        raise VerificationError("Docker CLI is unavailable; no image was built and no probe was started.")
    version = docker(["version", "--format", "{{.Server.Os}}|{{.Server.Version}}"], timeout=10.0, output_limit=4096)
    runtime = version["stdout"].decode("utf-8", "replace").strip()
    parts = runtime.split("|", 1)
    if len(parts) != 2 or parts[0] != "linux" or not parts[1]:
        raise VerificationError("A running Linux Docker Engine is required; no probe was started.")

    inspected_image = inspect_image(image)
    base_image = verify_image(inspected_image)

    host_file = None
    try:
        marker = "abacus-day37-" + uuid.uuid4().hex
        handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="abacus-day37-", suffix=".txt", delete=False)
        host_file = Path(handle.name)
        handle.write(marker)
        handle.close()

        payloads = {
            "identity": {},
            "host-file": {"host_path": str(host_file), "marker": marker},
            "network": {},
            "privilege": {},
            "processes": {},
            "memory": {},
            "file-size": {},
            "wall-time": {},
            "output-flood": {},
        }
        for action, payload in payloads.items():
            try:
                row = probe_container(action, payload, image)
            except VerificationError as exc:
                rows.append({"action": action, "passed": False, "detail": str(exc)})
                raise
            rows.append(row)
        return runtime, f"{image}; image ID `{inspected_image.get('Id', 'unknown')}`; base `{base_image}`"
    finally:
        if host_file is not None:
            try:
                host_file.unlink()
            except FileNotFoundError:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=IMAGE_DEFAULT)
    parser.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    args = parser.parse_args(argv)

    runtime = "NOT AVAILABLE"
    image_info = args.image + " (not verified)"
    rows = []
    try:
        runtime, image_info = run_verification(args.image, rows)
        status = "PASS" if all(row.get("passed") for row in rows) and len(rows) == 9 else "FAIL"
        error = None if status == "PASS" else "At least one required probe failed. Keep untrusted-code execution disabled."
        write_report(args.report, status=status, runtime=runtime, image=image_info, rows=rows, error=error)
        print(f"Day 37 verification: {status}. Report: {args.report}")
        return 0 if status == "PASS" else 1
    except VerificationError as exc:
        status = "BLOCKED" if not rows else "FAIL"
        write_report(args.report, status=status, runtime=runtime, image=image_info, rows=rows, error=str(exc))
        print(f"Day 37 verification: {status}. {exc}", file=sys.stderr)
        print(f"Report: {args.report}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
