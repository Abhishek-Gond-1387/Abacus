# Claim revision review

## Original claim

**Benchmark source; immutable. Evaluation scores this claim.**

<pre>largest(xs) returns the maximum value for every list of integers.</pre>

Original label (immutable): REFUTED

## Revised claim

**Model proposal; not scored by the original benchmark evaluation.**

<pre>largest(xs) returns the maximum value for every non-empty list of integers.</pre>

Revision relation: narrows
Revision trigger: confirmed_counterexample
Trigger evidence reference: empty-list-counterexample
Revision reason: Narrowed the input domain from all integer lists to non-empty integer lists because the empty list was a confirmed counterexample.

Evaluation target: original_claim
Scored label: REFUTED
