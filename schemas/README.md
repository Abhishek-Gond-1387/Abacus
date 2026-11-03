# Problem record contract

The validator is implemented in `src/abacus/problems.py` using only the Python standard library. It parses JSON and checks structure; it never executes the record's `code` field and never calls an LLM.

## Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | non-empty lowercase kebab-case string | Yes | Stable unique record identifier. |
| `title` | non-empty string | Yes | Short human-readable name. |
| `claim` | non-empty string | Yes | Original claim, kept verbatim as the record's canonical claim. Do not replace it with a later model interpretation. |
| `code` | non-empty string | Yes | Candidate Python source, stored but not executed by the loader. |
| `domain` | object | Yes | Requires non-empty `input_type`, `output_type`, and `description` strings. |
| `preconditions` | array of non-empty strings | Yes | Contract-specific predicate identifiers; the sorting records use `input_is_list` and `elements_are_exact_ints`. |
| `property_description` | non-empty string | Yes | Plain-language statement of the property to check. |
| `oracle_id` | non-empty string | Yes | Identifier reserved for the trusted reference/checker. |
| `expected_label` | `TRUE` or `FALSE` | Yes | Hand-authored truth label for the claim about the supplied code. |
| `label_rationale` | non-empty string | Yes | Reason for the label, independent of any model suggestion. |
| `family` | non-empty string | Yes | Problem family, such as `sorting`. |
| `known_counterexample` | object or `null` | Required for `FALSE` | A false claim requires `input`, `expected_output`, and `actual_output`; optional `reason` explains the witness. A true claim omits this field or sets it to `null`. |

Unknown top-level fields, unknown `domain` fields, and unknown counterexample fields are rejected so typos do not silently change the record.

`src/abacus/contracts.py` maps the sorting oracle ID and these predicate identifiers to executable checks. The record's `domain.input_type` must also match the registered contract. The target oracle and the fixed example generator both call `validate_input`, so they share one domain definition.

## Validate records

From the project root, run:

```powershell
.\.venv\Scripts\python.exe -m abacus.problems problems\sort-ascending-true.json problems\sort-ascending-false.json
```

The loader reports structural errors with field names. It does not prove that a label is correct; the rationale and counterexample are hand-authored evidence to be checked by later trusted-oracle work.
