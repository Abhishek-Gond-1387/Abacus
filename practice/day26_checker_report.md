# Day 26 — Check the checker

The fixtures use manually written expected outputs to inspect both target functions and the oracle. They cover duplicate preservation and negative-only maximum inputs. These finite fixtures catch the included defects but do not prove either implementation correct for every integer list.

## Validation results

| Check | Result |
|---|---|
| Correct target fixtures and reference agree with manual answers | PASS |
| Duplicate-removing sort mutant is caught | CAUGHT |
| Zero-initialized maximum mutant is caught | CAUGHT |
| Duplicate-removing oracle disagrees with manual fixtures | DETECTED |
| Bad oracle would falsely accuse correct sort | YES |
| Saved Day 21 counterexamples replayed | 23 |
| Saved Day 21 counterexamples still reproduce | 23 |
| Duplicate-removal mutant passes sort idempotence | YES |

The intentionally faulty oracle returns sorted unique values. The manual duplicate fixtures flag it as TEST_ORACLE_DEFECT; using it anyway makes the correct sorter appear to violate the contract. This demonstrates that an oracle defect can reverse a verdict.

Sort idempotence (`sort(sort(xs)) == sort(xs)`) is useful but incomplete: duplicate removal is idempotent and still violates duplicate preservation. The manual contract fixtures are needed to catch that defect.

## Day 21 replay

| Problem | Saved input | Replay |
|---|---|---|
| sort-preserves-duplicates | `[4, 4]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[-3, -13, -3, -19]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[-3, -13, -3, -3]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[-3, -3, -3, -3]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[-11, -9, 6, -15, 18, 19, -11, -7]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[-11, -9, 6, -11, 18, 19, -11, -7]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[-11, -9, 6, -11, 18, -11, -11, -7]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[-11, -9, 6, -11, -11, -11, -11, -7]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[-11, -9, 6, -11, -11, -11, 6, -7]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[-11, -9, -11, -11, -11, -11, 6, -7]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[4, -18, 4]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[-18, -18, 4]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[-18, 4, 4]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[4, 4, 4]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[5, 12, -16, 12, -12, 9, -13, -11]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[5, 12, -12, 12, -12, 9, -13, -11]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[4, 4, 0]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[4, 4]` | PROPERTY_VIOLATION |
| sort-preserves-duplicates | `[0, 0]` | PROPERTY_VIOLATION |
| largest-negative-values | `[-7]` | PROPERTY_VIOLATION |
| largest-negative-values | `[-4, -1, -9]` | PROPERTY_VIOLATION |
| largest-negative-values | `[-15]` | PROPERTY_VIOLATION |
| largest-negative-values | `[-1]` | PROPERTY_VIOLATION |

## Remaining uncertainty

The expected outputs were reviewed directly against the stated contracts, and no independent human reviewer was available for this run. Handwritten fixtures reduce shared-oracle risk on these examples, but they cannot establish full oracle soundness or cover all inputs. A broader independent review is still useful before treating an oracle as trusted.
