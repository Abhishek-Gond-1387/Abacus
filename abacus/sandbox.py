"""Fail-closed Docker boundary for one explicitly requested untrusted function."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFICATION_REPORT = PROJECT_ROOT / "practice" / "day37_sandbox_verification.md"
EXECUTION_FLAG = "ABACUS_UNTRUSTED_EXECUTION"
IMAGE = "abacus-sandbox-day37:local"
MEMORY_BYTES = 256 * 1024 * 1024
FILE_BYTES = 8 * 1024 * 1024
SCRATCH_BYTES = 16 * 1024 * 1024
PROCESS_LIMIT = 64
CPU_SECONDS = 5
WALL_SECONDS = 5.0
MAX_SOURCE_BYTES = 256 * 1024
MAX_INPUT_BYTES = 512 * 1024
MAX_STREAM_BYTES = 1024 * 1024
REQUIRED_PROBES = (
    "identity", "host-file", "network", "privilege", "processes",
    "memory", "file-size", "wall-time", "output-flood",
)
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
CONTAINER_ID_PATTERN = re.compile(r"^[0-9a-f]{12,64}$")


class SandboxError(RuntimeError):
    """A requested untrusted run was refused or failed inside the sandbox."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VerifiedRuntime:
    runtime_version: str
    image_id: str


def bounded_process(
    argv: list[str],
    *,
    input_bytes: bytes | None = None,
    timeout: float = 10.0,
    output_limit: int = MAX_STREAM_BYTES,
) -> dict[str, Any]:
    """Run a host command with capped combined output and a deadline."""
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except OSError:
        return {"returncode": None, "reason": "launch_error", "stdout": b"", "stderr": b"", "output_bytes": 0}

    captured = {"stdout": bytearray(), "stderr": bytearray()}
    state: dict[str, Any] = {"bytes": 0, "reason": None}
    lock = threading.Lock()

    def drain(name: str, pipe: Any) -> None:
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
    for reader in readers:
        reader.start()

    def send_input() -> None:
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

    writer = threading.Thread(target=send_input, daemon=True)
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
    for reader in readers:
        reader.join(timeout=1.0)
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


def _read_verified_image(report_path: Path) -> tuple[str, str]:
    try:
        report = report_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SandboxError("verification_report_unavailable") from exc
    if "**Status: PASS.**" not in report:
        raise SandboxError("day37_verification_not_passed")

    runtime_match = re.search(r"^- Docker engine: `linux\|([^`]+)`$", report, re.MULTILINE)
    image_match = re.search(r"^- Image: `([^;]+); image ID `(sha256:[0-9a-f]{64})`; base `python@sha256:[0-9a-f]{64}``$", report, re.MULTILINE)
    if not runtime_match or not image_match or image_match.group(1) != IMAGE:
        raise SandboxError("verification_report_incomplete")
    for probe in REQUIRED_PROBES:
        if not re.search(rf"^\| {re.escape(probe)} \| PASS \|", report, re.MULTILINE):
            raise SandboxError("day37_probe_not_passed")
    return runtime_match.group(1), image_match.group(2)


def _config_errors(details: Mapping[str, Any], expected_image_id: str) -> list[str]:
    config = details.get("Config") or {}
    host = details.get("HostConfig") or {}
    errors = []
    labels = config.get("Labels") or {}
    if details.get("Image") != expected_image_id:
        errors.append("container image ID mismatch")
    if labels.get("org.abacus.purpose") != "untrusted-execution":
        errors.append("container purpose label mismatch")
    if config.get("User") != "65534:65534" or config.get("OpenStdin") is not True:
        errors.append("container user/stdin mismatch")
    if config.get("Entrypoint") != ["python"] or config.get("Cmd") != ["-I", "-S", "/opt/abacus/executor.py"]:
        errors.append("container entrypoint mismatch")
    if host.get("NetworkMode") != "none" or host.get("ReadonlyRootfs") is not True:
        errors.append("network/rootfs control mismatch")
    if host.get("NanoCpus") != 1_000_000_000:
        errors.append("CPU quota mismatch")
    if host.get("Memory") != MEMORY_BYTES or host.get("MemorySwap") != MEMORY_BYTES:
        errors.append("memory/swap limit mismatch")
    if host.get("PidsLimit") != PROCESS_LIMIT:
        errors.append("process limit mismatch")
    if host.get("Privileged") is not False or host.get("Devices") or host.get("Binds"):
        errors.append("privileged/device/bind-mount control mismatch")
    if host.get("CapAdd") or "ALL" not in (host.get("CapDrop") or []):
        errors.append("capability control mismatch")
    security = host.get("SecurityOpt") or []
    if "no-new-privileges=true" not in security or "seccomp=unconfined" in security:
        errors.append("security profile mismatch")
    if (host.get("LogConfig") or {}).get("Type") != "none":
        errors.append("container log driver mismatch")
    limits = {item.get("Name"): item for item in host.get("Ulimits") or []}
    for name, value in (("cpu", CPU_SECONDS), ("fsize", FILE_BYTES)):
        limit = limits.get(name) or {}
        if limit.get("Soft") != value or limit.get("Hard") != value:
            errors.append(f"{name} ulimit mismatch")
    tmpfs = host.get("Tmpfs") or {}
    for destination, mode in (("/tmp", "1777"), ("/work", "700")):
        options = tmpfs.get(destination, "")
        if any(part not in options for part in ("size=16m", "noexec", "nosuid", "nodev", f"mode={mode}")):
            errors.append(f"{destination} tmpfs mismatch")
    mounts = details.get("Mounts") or []
    if {item.get("Destination") for item in mounts} != {"/tmp", "/work"}:
        errors.append("unexpected or missing mount")
    if any(item.get("Type") != "tmpfs" for item in mounts):
        errors.append("non-tmpfs mount is present")
    env_names = [str(item).split("=", 1)[0] for item in config.get("Env") or []]
    if any(re.search(r"key|token|secret|password|credential|auth|aws|azure|gcp", name, re.I) for name in env_names):
        errors.append("credential-like environment variable is present")
    return errors


class SandboxRunner:
    """Launch candidates only in the image and limits verified by Day 37."""

    def __init__(
        self,
        *,
        image: str = IMAGE,
        report_path: Path = VERIFICATION_REPORT,
        environment: Mapping[str, str] | None = None,
        executable_resolver: Callable[[str], str | None] = shutil.which,
        process_runner: Callable[..., dict[str, Any]] = bounded_process,
    ) -> None:
        self.image = image
        self.report_path = Path(report_path)
        self.environment = environment
        self.executable_resolver = executable_resolver
        self.process_runner = process_runner

    def _env(self) -> Mapping[str, str]:
        return os.environ if self.environment is None else self.environment

    def _docker(self, args: list[str], *, input_bytes: bytes | None = None, timeout: float = 10.0, output_limit: int = MAX_STREAM_BYTES) -> bytes:
        result = self.process_runner(
            ["docker", *args], input_bytes=input_bytes, timeout=timeout, output_limit=output_limit
        )
        if result.get("reason") == "wall_time_limit":
            raise SandboxError("docker_command_timeout")
        if result.get("reason") == "output_limit":
            raise SandboxError("docker_output_limit")
        if result.get("returncode") != 0:
            raise SandboxError("docker_command_failed")
        return result.get("stdout", b"")

    def preflight(self, *, explicit_opt_in: bool) -> VerifiedRuntime:
        if not explicit_opt_in:
            raise SandboxError("explicit_opt_in_required")
        if self._env().get(EXECUTION_FLAG) != "1":
            raise SandboxError("execution_flag_disabled")
        recorded_runtime, recorded_image_id = _read_verified_image(self.report_path)
        if self.image != IMAGE:
            raise SandboxError("unapproved_image")
        if not self.executable_resolver("docker"):
            raise SandboxError("docker_runtime_unavailable")
        try:
            runtime = self._docker(["version", "--format", "{{.Server.Os}}|{{.Server.Version}}"], timeout=10.0, output_limit=4096).decode("utf-8").strip()
            runtime_os, runtime_version = runtime.split("|", 1)
        except (SandboxError, UnicodeDecodeError, ValueError) as exc:
            raise SandboxError("docker_runtime_unavailable") from exc
        if runtime_os != "linux" or not runtime_version or runtime_version != recorded_runtime:
            raise SandboxError("docker_runtime_mismatch")

        template = '{{.Id}}|{{.Os}}|{{index .Config.Labels "org.abacus.day37"}}|{{index .Config.Labels "org.abacus.executor"}}'
        try:
            inspected = self._docker(["image", "inspect", "--format", template, self.image], timeout=10.0, output_limit=4096).decode("utf-8").strip()
        except (SandboxError, UnicodeDecodeError) as exc:
            raise SandboxError("verified_image_unavailable") from exc
        parts = inspected.split("|")
        if len(parts) != 4 or not IMAGE_ID_PATTERN.fullmatch(parts[0]):
            raise SandboxError("image_inspection_invalid")
        image_id, operating_system, verification_label, executor_label = parts
        if operating_system != "linux" or verification_label != "fixed-purpose-sandbox-probes" or executor_label != "python-json-v2":
            raise SandboxError("image_policy_mismatch")
        if image_id != recorded_image_id:
            raise SandboxError("verified_image_changed")
        return VerifiedRuntime(runtime_version=runtime_version, image_id=image_id)

    def execute(self, source: str, value: Any, *, explicit_opt_in: bool) -> dict[str, Any]:
        verified = self.preflight(explicit_opt_in=explicit_opt_in)
        if type(source) is not str or not source.strip():
            raise SandboxError("invalid_source")
        try:
            source_bytes = source.encode("utf-8")
        except UnicodeError as exc:
            raise SandboxError("invalid_source") from exc
        if len(source_bytes) > MAX_SOURCE_BYTES:
            raise SandboxError("source_too_large")
        try:
            input_bytes = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
            raise SandboxError("input_not_json") from exc
        if len(input_bytes) > MAX_INPUT_BYTES:
            raise SandboxError("input_too_large")
        try:
            request = json.dumps(
                {"source": source, "input": value},
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
            raise SandboxError("request_not_json") from exc
        if len(request) > MAX_STREAM_BYTES:
            raise SandboxError("request_too_large")

        container_name = f"abacus-untrusted-{uuid.uuid4().hex[:12]}"
        container_id: str | None = None
        creation_attempted = False
        failure: SandboxError | None = None
        response: dict[str, Any] | None = None
        create_args = [
            "create", "--interactive", "--name", container_name,
            "--label", "org.abacus.purpose=untrusted-execution",
            "--network", "none", "--read-only", "--user", "65534:65534",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
            "--cpus", "1", "--memory", str(MEMORY_BYTES), "--memory-swap", str(MEMORY_BYTES),
            "--pids-limit", str(PROCESS_LIMIT), "--ulimit", f"cpu={CPU_SECONDS}:{CPU_SECONDS}",
            "--ulimit", f"fsize={FILE_BYTES}:{FILE_BYTES}",
            "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
            "--tmpfs", f"/work:rw,noexec,nosuid,nodev,size=16m,mode=700,uid=65534,gid=65534",
            "--log-driver", "none", "--entrypoint", "python", verified.image_id,
            "-I", "-S", "/opt/abacus/executor.py",
        ]
        try:
            creation_attempted = True
            try:
                created_output = self._docker(create_args, timeout=15.0, output_limit=4096).decode("ascii").strip()
            except (SandboxError, UnicodeDecodeError) as exc:
                raise SandboxError("sandbox_start_failed") from exc
            if not CONTAINER_ID_PATTERN.fullmatch(created_output):
                raise SandboxError("sandbox_start_failed")
            container_id = created_output

            try:
                details = json.loads(self._docker(["inspect", container_id], output_limit=128 * 1024).decode("utf-8"))[0]
            except (SandboxError, UnicodeDecodeError, json.JSONDecodeError, IndexError, TypeError) as exc:
                raise SandboxError("sandbox_inspection_failed") from exc
            if _config_errors(details, verified.image_id):
                raise SandboxError("sandbox_policy_mismatch")

            result = self.process_runner(
                ["docker", "start", "--attach", "--interactive", container_id],
                input_bytes=request,
                timeout=WALL_SECONDS,
                output_limit=MAX_STREAM_BYTES,
            )
            if result.get("reason") == "wall_time_limit":
                raise SandboxError("sandbox_wall_time_limit")
            if result.get("reason") == "output_limit":
                raise SandboxError("sandbox_output_limit")
            try:
                state = json.loads(self._docker(["inspect", container_id], output_limit=128 * 1024).decode("utf-8"))[0].get("State") or {}
            except (SandboxError, UnicodeDecodeError, json.JSONDecodeError, IndexError, TypeError) as exc:
                raise SandboxError("sandbox_result_unavailable") from exc
            if result.get("returncode") != 0 or state.get("ExitCode") != 0 or state.get("OOMKilled") is True:
                raise SandboxError("sandbox_execution_failed")
            try:
                response = json.loads(result.get("stdout", b"").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SandboxError("sandbox_result_invalid") from exc
            if type(response) is not dict or response.get("status") != "ok" or set(response) != {"status", "result"}:
                raise SandboxError("candidate_execution_error")
        except SandboxError as exc:
            failure = exc
        finally:
            if creation_attempted:
                target = container_id or container_name
                cleanup = self.process_runner(["docker", "rm", "--force", target], timeout=10.0, output_limit=4096)
                absent = self.process_runner(["docker", "inspect", target], timeout=10.0, output_limit=4096)
                cleanup_text = cleanup.get("stderr", b"").decode("utf-8", "replace").lower()
                absent_text = absent.get("stderr", b"").decode("utf-8", "replace").lower()
                cleanup_ok = (
                    cleanup.get("returncode") == 0 and bool(cleanup.get("stdout", b"").strip())
                ) or (
                    cleanup.get("returncode") != 0
                    and ("no such container" in cleanup_text or "no such object" in cleanup_text)
                )
                absent_ok = absent.get("returncode") != 0 and (
                    "no such container" in absent_text or "no such object" in absent_text
                )
                if not cleanup_ok or not absent_ok:
                    failure = SandboxError("sandbox_cleanup_failed")

        if failure is not None:
            raise failure
        if response is None:
            raise SandboxError("sandbox_result_invalid")
        return {
            "execution_origin": "untrusted_sandbox",
            "runtime_version": verified.runtime_version,
            "image_id": verified.image_id,
            "result": response["result"],
        }
