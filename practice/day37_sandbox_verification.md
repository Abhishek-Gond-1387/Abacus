# Day 37 — Isolated runner verification

**Status: BLOCKED.**

- Recorded: 2026-11-03T17:25:42+00:00
- Host: `Windows-11-10.0.26300-SP0`
- Git revision: `6f576da`
- Docker engine: `NOT AVAILABLE`
- Image: `abacus-sandbox-day37:local (not verified)`
- Generated-code execution: **off**

The Day 38 change added a separate JSON executor to the image build context. This report predates that image; rebuilding changes its image ID, so all Day 37 probes must run again on the rebuilt image before the Day 38 CLI can pass preflight.

## Host prerequisite baseline

The Day 36 check on 2026-11-03 found Docker and Podman CLIs absent and WSL not installed. The registry snapshot reported Windows 10 Home Single Language, DisplayVersion 26H2, build 26300, while the Windows platform API reports Windows 11 / 10.0.26300; confirm the edition and build in Settings before installing a backend. RAM and hardware virtualization remain unchecked. This is historical context; check the host again before acting.

Docker's [current Windows requirements](https://docs.docker.com/desktop/setup/install/windows-install/) list supported builds/editions, WSL 2.1.5+, virtualization, and 8 GB RAM for the WSL backend. Docker also documents [Docker VMM](https://docs.docker.com/desktop/features/vmm/) as a beta Windows backend on newer Desktop releases. First-time WSL enablement requires administrator privileges.

## Probe outcomes

| Probe | Result | Notes |
|---|---|---|
| identity | NOT RUN |  |
| host-file | NOT RUN |  |
| network | NOT RUN |  |
| privilege | NOT RUN |  |
| processes | NOT RUN |  |
| memory | NOT RUN |  |
| file-size | NOT RUN |  |
| wall-time | NOT RUN |  |
| output-flood | NOT RUN |  |

## Assessment

This verification harness runs fixed probes only. It does not execute model-generated or user-supplied source code. Keep Abacus untrusted-code execution disabled until every required probe passes on the intended runtime and an experienced reviewer accepts the isolation boundary.

## Blocker

Docker CLI is unavailable; no image was built and no probe was started.
