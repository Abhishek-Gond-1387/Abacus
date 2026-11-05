# Local free sandbox and AI setup

Current host check: `wsl.exe` is present, but WSL is not installed; the Docker CLI is unavailable. The Day 37 isolation report remains `BLOCKED`. Abacus therefore refuses to execute submitted Python until the steps below and the repository's full sandbox verification are complete.

## Docker Desktop and WSL 2

Docker Desktop is free for personal use under its current license. The paid subscription is not needed for personal use; do not enable a paid subscription. Docker's current Windows requirements include WSL 2.1.5 or later, supported 64-bit Windows builds, hardware virtualization, and at least 8 GB RAM. Check the current [Docker Windows requirements](https://docs.docker.com/desktop/setup/install/windows-install/) before installing.

1. Open **PowerShell as Administrator** and run:

   ```powershell
   wsl --install
   ```

   Restart Windows when prompted. Microsoft documents this as the standard WSL install path; it installs WSL and the default Ubuntu distribution.
2. After restart, open PowerShell and run:

   ```powershell
   wsl --update
   wsl --status
   wsl --list --verbose
   ```

   Confirm WSL is version 2 and at least version 2.1.5.
3. Install Docker Desktop using its [official Windows installer instructions](https://docs.docker.com/desktop/setup/install/windows-install/). Choose a per-user install and the WSL 2 backend. Accept Docker's terms only if the personal-use license applies to your use.
4. Start Docker Desktop, select Linux containers, and confirm:

   ```powershell
   docker version
   docker info --format '{{.OSType}}'
   ```

   The engine must report `linux`. Docker Desktop also requires hardware virtualization enabled in BIOS/UEFI.
5. From the repository root, build the pinned sandbox image and run the fixed Day 37 isolation probes:

   ```powershell
   powershell -ExecutionPolicy Bypass -File sandbox/day37/build.ps1
   .\.venv\Scripts\python.exe sandbox/day37/verify.py
   ```

   Keep `ABACUS_UNTRUSTED_EXECUTION=0` until `practice/day37_sandbox_verification.md` records `PASS` for every required probe and the generated image/runtime match the report. A rebuilt image needs a fresh full verification.

Abacus's custom-code page only accepts a Python `candidate(values)` function and one integer-array input, and checks it against the built-in ascending integer-sort claim. One `TESTS_PASSED` result is evidence for that input only, never a proof. Submitted source is not retained; check output is session-only.

## General AI questions

The Ask AI page is disabled unless the backend operator explicitly sets `ABACUS_QA_ENABLED=1` and configures Gemini in the server-only environment or ignored `.env` file. The pilot rejects OpenAI-provider fallback and caps each answer at 512 output tokens. The browser never receives the provider key. Gemini availability and quotas depend on the provider account; if enabling it would require a paid plan or billing, leave the feature disabled. Do not paste keys into chat or enter secrets/private information as questions.

AI messages remain in browser-tab memory only. They are not stored in the database. No provider call is made while the feature is disabled or merely while checking capability status.

Microsoft's WSL instructions: [Install WSL](https://learn.microsoft.com/en-us/windows/wsl/install). Docker's current license terms: [Docker Desktop license](https://docs.docker.com/subscription-billing/desktop-license/).
