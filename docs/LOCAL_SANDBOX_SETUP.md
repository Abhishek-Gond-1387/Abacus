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

At the `Start-Abacus-With-Gemini.ps1` key prompt, pressing Enter without a key now starts the local app with live AI disabled and sends no provider request. Enter a Free Tier key only if you want live AI answers; do not enable billing.

The Ask Abacus page needs `ABACUS_QA_ENABLED=1` and Gemini configured in the server-only environment or ignored `.env` file. For local setup, get a Gemini API key from Google AI Studio and run `.\Start-Abacus-With-Gemini.ps1`; it prompts for the key without echoing it, keeps it in the server process environment only, and does not save it to disk. The pilot rejects OpenAI-provider fallback and caps each answer at 512 output tokens. Answers stream to the chat as the backend receives them. The browser can start a question while the capability check is still loading; the API remains authoritative and returns a real configuration or quota error when it cannot answer. Capability checks also inspect the custom-code Docker sandbox, so they run in the background and may take longer than the chat shell startup. The browser never receives the provider key. Gemini availability and quotas depend on the provider account; if enabling it would require a paid plan or billing, leave the feature disabled. This launcher does not change Google billing settings; use only an account/key whose free tier is sufficient and billing is off. Do not paste keys into chat or enter secrets/private information as questions.

AI messages remain in browser-tab memory only. They are not stored in the database. No provider call is made merely while checking capability status; submitting a question calls the provider only when the API says the feature is enabled. Streaming reduces the wait before text appears, but Gemini's initial response time and free-tier quota still depend on Google's service.

Microsoft's WSL instructions: [Install WSL](https://learn.microsoft.com/en-us/windows/wsl/install). Docker's current license terms: [Docker Desktop license](https://docs.docker.com/subscription-billing/desktop-license/).
