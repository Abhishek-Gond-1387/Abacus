# Verdict semantics — Week 4 freeze

The canonical run-level label is `run_outcome.outcome`. `reason`, evidence, and failure fields explain that label; they do not replace it. A case-level `category` such as `CASE_PASSED` or `PROPERTY_VIOLATION` describes one input only and is not a run verdict.

## Frozen meanings

| Run outcome | Meaning | Required evidence or condition |
|---|---|---|
| `REFUTED` | The claim has a counterexample under its configured contract and usable oracle. | A contract-valid output mismatch was replayed successfully. The log includes the exact input, actual output, expected output, and `replay_confirmed: true`. One confirmed counterexample is sufficient even if other checks fail. |
| `TESTS_PASSED` | Every scheduled finite check and required method completed without a counterexample. | A usable oracle was configured and all recorded evidence passed. This is evidence from a finite test run, not a proof. |
| `UNRESOLVED` | Available evidence cannot support either a refutation or a completed finite-test result. | Examples include incomplete evidence, a timeout or budget stop, conflicting/invalid evidence, or no usable oracle. The reason field identifies which limitation occurred. |
| `ERROR` | An external or internal failure prevented a dependable evaluation. | The log includes an error reason and `failure_category`. If a confirmed counterexample was already established, the decision policy keeps `REFUTED`; the failure remains in the run's error log. |

`PROVEN` remains reserved for a future formal checker with an identified proof checker and proof-evidence reference. No finite-test path can emit it.

## Sample log walkthrough

These are compact examples of the `run_outcome` object. Full Day 27 logs retain the surrounding claim, contract, cases, evidence, revision, and budget fields.

### Refutation

From the Day 27 false-sort run:

```json
{
  "outcome": "REFUTED",
  "reason": "confirmed_counterexample",
  "test_count": 31,
  "counterexample": {
    "input": [3, -1, 3, 0],
    "actual": [-1, 0, 3],
    "expected": [-1, 0, 3, 3],
    "test_id": "fixed-3",
    "replay_confirmed": true
  }
}
```

The target dropped a duplicate. The exact input was run again and produced the same mismatch, so the evidence policy returned `REFUTED`.

### Finite tests passed

From the Day 27 true-sort run:

```json
{
  "outcome": "TESTS_PASSED",
  "reason": "no_counterexample_found",
  "message": "All scheduled finite tests passed; this is not a proof.",
  "test_count": 31,
  "methods": ["fixed", "hypothesis", "proposals"],
  "counterexample": null
}
```

All 31 scheduled cases passed. This supports only the finite tests recorded in that run; it does not establish correctness for every possible input.

### Insufficient evidence

An incomplete run has no counterexample and did not complete all required checks:

```json
{
  "outcome": "UNRESOLVED",
  "reason": "incomplete_evidence",
  "message": "Not all scheduled tests and required methods completed.",
  "test_count": 1,
  "methods": ["fixed"]
}
```

### Evaluation error

An evaluation stage failed before a verdict could be supported:

```json
{
  "outcome": "ERROR",
  "reason": "internal_error",
  "message": "Internal evaluation failed for test 'proposal-generation-1'.",
  "test_count": 29,
  "methods": ["proposals"],
  "failure_category": "OPTIONAL_PROPOSAL_GENERATION"
}
```

The reason separates an evaluator failure (`ERROR`) from a run that completed its available work but lacks enough evidence (`UNRESOLVED`).

## Claim revisions

A revision is a separate proposal attached after an allowed trigger. It does not rewrite the scored claim or its label. In the Day 27 false-sort log, `original_claim` and `scored_claim` remain “The function returns every input integer in ascending order and preserves duplicates.” The original/scored label remains `REFUTED`; the separate revised proposal asks for distinct sorted values and records relation `changes_meaning`.

The CLI has no separate verdict viewer; its summary uses the run-level outcome and reason, while the JSON log contains the supporting evidence. Invalid problem JSON is rejected before a run starts and currently exits with a validation message rather than creating a run outcome.
