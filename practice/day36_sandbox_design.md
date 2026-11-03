# Day 36 — Sandbox boundary and design

## Decision and current machine state

**Candidate runtime:** Docker Desktop for Windows, Linux containers, using the WSL 2 backend and a per-user installation. The container will be disposable and created by an Abacus host-side supervisor. This keeps the container workflow on the Linux runtime used by the Python project while avoiding a Windows-container path.

Use the Windows Docker CLI; do not install a second Docker Engine inside WSL, and leave integration with general-purpose WSL distributions off. Docker documents that its WSL backend can be managed from Windows without a separate Linux distribution. [Docker Desktop WSL backend](https://docs.docker.com/desktop/features/wsl/)

This is a conditional design, not a verified runtime. At the time of this review, `docker` and `podman` are not installed, and `wsl --list --quiet` reports that WSL is not installed. The Windows registry reports `Windows 10 Home Single Language`, `26H2`, build `26300`; because the product name and version/build do not line up clearly, verify the actual supported Windows edition/build in Settings before installation. Virtualization and available RAM also remain unchecked. Docker Desktop's current Windows guidance requires a supported Windows build, WSL 2.1.5 or later, virtualization, and at least 8 GB RAM; enabling WSL for the first time requires administrator elevation. Recheck those requirements before installing or running anything. [Docker Desktop Windows installation requirements](https://docs.docker.com/desktop/setup/install/windows-install/), [Windows permission requirements](https://docs.docker.com/desktop/setup/install/windows-permission-requirements)

Docker Desktop's WSL backend has a shared Linux kernel, and WSL files remain accessible from Windows. The design therefore mounts no host directory at runtime and makes no claim that ordinary containers are a complete VM boundary. Enhanced Container Isolation provides an extra layer, but Docker documents it as a Business-subscription feature and requires WSL 2.6 or later. It is not assumed to be available. [Docker Desktop WSL security notes](https://docs.docker.com/desktop/features/wsl/), [Enhanced Container Isolation requirements](https://docs.docker.com/desktop/enterprise/hardened-desktop/enhanced-container-isolation/)

## Trust boundary

| Input/component | Trust level | Handling |
|---|---|---|
| Model-generated Python source | Untrusted | Execute only inside the disposable sandbox, after the explicit opt-in and runtime preflight are implemented. |
| User/benchmark test snippets and JSON values | Untrusted data | Pass as bounded JSON input; never interpolate into a host shell command. |
| Dependencies imported by candidate code | Untrusted | Use only dependencies already present in the minimal pinned image; do not install at run time. |
| Abacus host supervisor, allowlist, and image build definition | Trusted control plane | Keep separate from candidate code; hash/version the image and supervisor. |
| Docker Desktop/WSL kernel and Windows host | Privileged boundary | Do not expose the Docker socket, host paths, devices, credentials, or host networking to the container. |

Today Abacus executes only its checked-in allowlisted target/oracle functions. It does not execute model-generated source. Those current functions remain the trusted local path; this design does not turn on generated-code execution.

## Runtime controls to implement

| Risk | Required control | Verification |
|---|---|---|
| Network access | Start with `--network none`; do not publish ports or use host networking. | A harmless DNS/HTTP probe must fail from inside the container. Docker documents `none` as an isolated network with only loopback. [None network driver](https://docs.docker.com/engine/network/drivers/none/) |
| Host files and secrets | No host bind mounts, home/repository mounts, `.env`, credentials, devices, or Docker socket. Send at most 1 MiB of JSON on stdin. Keep the environment to a small allowlist. | Probe for a host-only fixture and a fake secret; neither should be readable or present. Docker warns that mounting its socket grants access to the daemon. [Container run reference](https://docs.docker.com/reference/cli/docker/container/run/) |
| Filesystem writes | Use `--read-only`; only `/tmp` and `/work` are writable tmpfs mounts, each with a 16 MiB cap and `noexec,nosuid,nodev`. Candidate source and scratch data stay inside `/work`; no host output mount. | Attempt rootfs writes and oversized scratch writes; both must fail or hit the configured cap. |
| Privilege | Run as a fixed non-root UID/GID such as `65532:65532`; use `--cap-drop=ALL`, `--security-opt=no-new-privileges=true`, Docker's default seccomp profile, and no `--privileged`, added capabilities, or devices. | Verify `id` reports non-root; probes for privilege escalation and device access fail. |
| CPU and memory | `--cpus=1`, `--memory=256m`, `--memory-swap=256m` (no extra swap), and `--ulimit cpu=5:5`. These values are initial conservative limits and may be tuned only from measured fixture needs. | Confirm limits in container metadata and observe resource probes stop within them. Docker documents the CPU, memory, and memory-plus-swap controls. [Resource constraints](https://docs.docker.com/engine/containers/resource_constraints/) |
| Processes and file growth | `--pids-limit=64`, `--ulimit fsize=8388608:8388608`, and tmpfs caps above. | Fork bomb and large-file probes must be bounded. `fsize` is a per-file limit; tmpfs size caps aggregate scratch use. [Container run reference](https://docs.docker.com/reference/cli/docker/container/run/), [tmpfs mounts](https://docs.docker.com/engine/storage/tmpfs) |
| Wall time and output | Host supervisor enforces a 5-second wall-time limit, streams output with a 1 MiB maximum, and kills the exact container by ID on timeout or output overflow. | A sleeping program and an output flood must be stopped; no unlimited output is buffered in host memory. |
| Cleanup | Unique container name/ID for each run; remove it in a `finally` path on success, nonzero exit, timeout, and supervisor failure. Delete per-run host scratch after validating the bounded result. | After every probe, verify no run container or scratch directory remains. |

The image should contain only the Python runtime and pinned dependencies needed by the harness, built before the run and referenced by immutable digest. Launch with `--pull=never` so a run cannot fetch or replace its image. Candidate source is written inside the container by a trusted supervisor from the bounded stdin payload. The result is a single bounded JSON document on stdout; the host validates it before saving a run record.

## Fail-closed and default-off policy

1. Keep the future `ABACUS_UNTRUSTED_EXECUTION` setting at `0` by default. No generated source may run because of a problem-file field alone.
2. Before launch, require the expected Docker Desktop/Engine version, Linux backend, image digest, and all configured controls. If any check is missing or reports unsupported, return a structured error and do not run code.
3. If container creation, execution, timeout cleanup, or result validation fails, return `ERROR`/`UNRESOLVED` with the failure reason. Never fall back to `exec`, `subprocess`, or Python evaluation on the Windows host.
4. Keep runtime installation and security verification as separate gates. The current machine has neither WSL nor a container CLI, so this design is not ready to execute untrusted code.

## Day 37 verification checklist

- [ ] Verify Windows version/edition, virtualization, RAM, WSL 2 version, and Docker Desktop Linux backend.
- [ ] Pin and build the minimal image; verify it contains no credentials and does not fetch dependencies at run time.
- [ ] Confirm Docker reports resource-control support before enabling execution.
- [ ] Run harmless host-file, network, privilege, process-count, memory, file-size, wall-time, output-size, and cleanup probes.
- [ ] Keep the execution flag off if any probe or runtime control is uncertain.

## Official references

- [Install Docker Desktop on Windows](https://docs.docker.com/desktop/setup/install/windows-install/)
- [Docker Desktop WSL 2 backend](https://docs.docker.com/desktop/features/wsl/)
- [Docker run options](https://docs.docker.com/reference/cli/docker/container/run/)
- [Docker `none` network](https://docs.docker.com/engine/network/drivers/none/)
- [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)
