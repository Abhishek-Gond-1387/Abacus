# Day 37 fixed-purpose sandbox probes

This folder contains a minimal Python standard-library image and a host-side verifier for the Day 36 controls. The probe entrypoint dispatches nine fixed, harmless probes and never evaluates source. The image also includes a separate JSON executor used by the Day 38 CLI path; that entrypoint is allowed only after every Day 37 probe passes and both explicit opt-ins are present.

## Build and verify

Use a running Docker Desktop Linux-container engine. The build script pulls the official Python slim tag, resolves its repository digest, then builds offline from that digest. No dependencies are installed in the image. The verifier checks every created container's settings before starting its probe, uses no bind mounts or credentials, caps combined stdout/stderr at 1 MiB, enforces a five-second wall limit, and removes each exact named container in a `finally` path.

```powershell
powershell -ExecutionPolicy Bypass -File sandbox/day37/build.ps1
python sandbox/day37/verify.py
```

The verification report is written to `practice/day37_sandbox_verification.md`. A missing runtime or any configuration mismatch stops the run before the probe starts. The Day 38 CLI executor remains unavailable until this report passes and both explicit opt-ins are present.

## Boundary

The host-file probe checks that a known host-only canary path is not mounted into the container, and the verifier independently rejects any bind mount. It does not claim protection from Docker Engine, Linux kernel, hypervisor, or Windows vulnerabilities. The memory and CPU cgroup values, observed limits, Docker version, Python version, image ID, and base digest are recorded when the probes actually run.
