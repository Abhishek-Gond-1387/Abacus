# Day 35 — Audit runs from saved records

The four version-2 records in `practice/samples/day35_*.v2.json` were produced by the local pipeline and validated with `load_run_record()`. Their provenance points to commit `e69fa561fae29662e6e97c8c6ce035cb8370d8ce`; all were generated from a clean checkout. No provider API was called.

| Sample | Verdict / status | Evidence | Reason or recorded error |
|---|---|---:|---|
| `day35_refuted.v2.json` | REFUTED / complete | 31 / 31 | `confirmed_counterexample` |
| `day35_tests_passed.v2.json` | TESTS_PASSED / complete | 31 / 31 | `no_counterexample_found`; finite tests are not proof |
| `day35_unresolved.v2.json` | UNRESOLVED / partial | 6 / 31 | `incomplete_evidence`; the fixture simulated an empty Hypothesis generation result |
| `day35_error.v2.json` | ERROR / error | 29 / 31 | `optional_proposal_generation`: offline proposal fixture unavailable |

## Counterexample replay

The saved REFUTED record points to `fixed-3`, input `[3, -1, 3, 0]`. Running the recorded allowlisted target and oracle again returned:

- Target: `[-1, 0, 3]`
- Oracle: `[-1, 0, 3, 3]`
- Saved evidence: `replay_confirmed: true`
- Independent replay: confirmed; both outputs match the record and still disagree.

## Reproduction context

Each record stores the problem dataset and contract, target ID and source hash, runner hash, Git revision and dirty state, Hypothesis seed/range/size/example settings, budget limits, prompt-template versions, proposal/evidence statuses, and outcome references. A reviewer can validate each record and identify the exact code revision and local settings that produced it.

The provider and model IDs are `null` because these runs used offline fixtures; `provider_api_called` is `false`. Template versions and stored fixture inputs are sufficient to understand the recorded offline suggestions and proposals. There is no hosted response whose exact reproduction needs explanation.

## Secret scan and schema gaps

Scanned tracked repository files, JSON files in ignored `runs/`, and the four checked-in sample records for common provider-token, bearer-token, access-key, and private-key patterns. No matches were found. The Day 31 fake-secret regression test also passes as part of the test suite. Logs are redacted at the write boundary, but this scan only recognizes common formats and cannot detect arbitrary unmarked secret text.

No schema field is missing for the current offline-only runs. Before any hosted-model evaluation is added, include the redacted prompt or a stable prompt hash and the provider request parameters (for example sampling settings and output-token limit); existing provider/model IDs and template versions are already recorded. A hosted model's response can still vary even with those fields.

Re-run the saved-record checks with:

    .\.venv\Scripts\python.exe -m unittest practice.test_day35_audit practice.test_log_safety
