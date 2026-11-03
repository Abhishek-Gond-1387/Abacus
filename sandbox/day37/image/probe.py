"""Fixed, harmless probes for Day 37; this file never executes supplied code."""

import errno
import json
import os
import signal
import socket
import sys
import time


def read_text(path):
    try:
        with open(path, "r", encoding="ascii") as handle:
            return handle.read().strip()
    except (OSError, UnicodeError):
        return None


def emit(value):
    sys.stdout.write(json.dumps(value, sort_keys=True) + "\n")
    sys.stdout.flush()


def identity(_payload):
    rootfs_write_blocked = False
    try:
        with open("/abacus-rootfs-write-probe", "wb") as handle:
            handle.write(b"probe")
    except OSError:
        rootfs_write_blocked = True
    else:
        os.unlink("/abacus-rootfs-write-probe")

    import resource

    cpu_soft, cpu_hard = resource.getrlimit(resource.RLIMIT_CPU)
    file_soft, file_hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    emit(
        {
            "action": "identity",
            "uid": os.getuid(),
            "gid": os.getgid(),
            "rootfs_write_blocked": rootfs_write_blocked,
            "python": sys.version.split()[0],
            "cpu_limit_seconds": [cpu_soft, cpu_hard],
            "file_size_limit_bytes": [file_soft, file_hard],
            "memory_max": read_text("/sys/fs/cgroup/memory.max"),
            "pids_max": read_text("/sys/fs/cgroup/pids.max"),
            "cpu_max": read_text("/sys/fs/cgroup/cpu.max"),
            "tmpfs_work_bytes": os.statvfs("/work").f_blocks * os.statvfs("/work").f_frsize,
            "tmpfs_tmp_bytes": os.statvfs("/tmp").f_blocks * os.statvfs("/tmp").f_frsize,
        }
    )


def host_file(payload):
    path = payload.get("host_path")
    marker = payload.get("marker")
    if not isinstance(path, str) or not isinstance(marker, str):
        raise ValueError("host-file probe requires a path and marker")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            contents = handle.read(512)
    except OSError:
        emit({"action": "host-file", "blocked": True})
    else:
        emit({"action": "host-file", "blocked": marker not in contents})


def network(_payload):
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=1.5):
            emit({"action": "network", "blocked": False})
    except OSError:
        emit({"action": "network", "blocked": True})


def privilege(_payload):
    raw_socket_blocked = False
    try:
        probe_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    except OSError:
        raw_socket_blocked = True
    else:
        probe_socket.close()

    device_blocked = False
    try:
        descriptor = os.open("/dev/kmsg", os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        device_blocked = True
    else:
        os.close(descriptor)
    emit(
        {
            "action": "privilege",
            "non_root": os.geteuid() != 0,
            "raw_socket_blocked": raw_socket_blocked,
            "device_blocked": device_blocked,
        }
    )


def processes(_payload):
    children = []
    blocked = False
    try:
        for _ in range(128):
            try:
                pid = os.fork()
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.ENOMEM):
                    raise
                blocked = True
                break
            if pid == 0:
                time.sleep(30)
                os._exit(0)
            children.append(pid)
    finally:
        for pid in children:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for pid in children:
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
    emit({"action": "processes", "started": len(children), "limit_blocked": blocked})


def memory(_payload):
    memory_limit = read_text("/sys/fs/cgroup/memory.max")
    if memory_limit != str(256 * 1024 * 1024):
        emit({"action": "memory", "limited": False, "reason": "cgroup memory limit unavailable"})
        return

    chunks = []
    try:
        for _ in range(128):
            chunks.append(bytearray(b"x" * (8 * 1024 * 1024)))
    except MemoryError:
        emit({"action": "memory", "limited": True, "reason": "MemoryError"})
        return
    emit({"action": "memory", "limited": False, "reason": "allocation ceiling reached"})


def file_size(_payload):
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    path = "/work/day37-file-size-probe.bin"
    written = 0
    blocked = False
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            block = b"x" * (1024 * 1024)
            while written < 10 * 1024 * 1024:
                try:
                    count = os.write(descriptor, block)
                except OSError as exc:
                    if exc.errno == errno.EFBIG:
                        blocked = True
                        break
                    raise
                written += count
        finally:
            os.close(descriptor)
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    emit({"action": "file-size", "blocked": blocked, "bytes_written": written})


def wall_time(_payload):
    time.sleep(60)
    emit({"action": "wall-time", "limited": False})


def output_flood(_payload):
    block = b"x" * 8192
    remaining = 2 * 1024 * 1024
    while remaining:
        written = os.write(1, block[: min(remaining, len(block))])
        remaining -= written


ACTIONS = {
    "identity": identity,
    "host-file": host_file,
    "network": network,
    "privilege": privilege,
    "processes": processes,
    "memory": memory,
    "file-size": file_size,
    "wall-time": wall_time,
    "output-flood": output_flood,
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ACTIONS:
        emit({"error": "unsupported probe action"})
        return 2
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("probe input must be a JSON object")
        ACTIONS[sys.argv[1]](payload)
    except Exception as exc:
        emit({"action": sys.argv[1], "error": type(exc).__name__})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
