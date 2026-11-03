"""Fixtures for validating Day 26 targets, oracles, and saved failures."""

from __future__ import annotations

import unittest

if __package__:
    from .day26_validation import (
        LARGEST_CASES,
        SORT_CASES,
        audit_oracle,
        evaluate_known_cases,
        flawed_sort_oracle,
        largest_correct,
        largest_oracle,
        largest_returns_zero_for_negative_lists,
        replay_saved_counterexamples,
        sort_correct,
        sort_drops_duplicates,
        sort_idempotence,
        sort_oracle,
    )
else:
    from day26_validation import (
        LARGEST_CASES,
        SORT_CASES,
        audit_oracle,
        evaluate_known_cases,
        flawed_sort_oracle,
        largest_correct,
        largest_oracle,
        largest_returns_zero_for_negative_lists,
        replay_saved_counterexamples,
        sort_correct,
        sort_drops_duplicates,
        sort_idempotence,
        sort_oracle,
    )


class CheckerValidationTests(unittest.TestCase):
    def test_correct_targets_and_oracles_match_manual_fixtures(self) -> None:
        sorting = evaluate_known_cases(sort_correct, sort_oracle, SORT_CASES)
        largest = evaluate_known_cases(largest_correct, largest_oracle, LARGEST_CASES)
        for row in (*sorting, *largest):
            self.assertEqual(row["category"], "CASE_PASSED")
            self.assertTrue(row["oracle_matches_fixture"])
            self.assertTrue(row["target_matches_fixture"])

    def test_duplicate_removing_sort_mutant_is_caught(self) -> None:
        rows = evaluate_known_cases(sort_drops_duplicates, sort_oracle, SORT_CASES)
        self.assertTrue(any(row["category"] == "PROPERTY_VIOLATION" for row in rows))

    def test_zero_initializing_largest_mutant_is_caught(self) -> None:
        rows = evaluate_known_cases(
            largest_returns_zero_for_negative_lists, largest_oracle, LARGEST_CASES
        )
        self.assertTrue(any(row["category"] == "PROPERTY_VIOLATION" for row in rows))

    def test_manual_fixtures_flag_faulty_oracle(self) -> None:
        rows = audit_oracle(flawed_sort_oracle, SORT_CASES)
        self.assertTrue(any(row["category"] == "TEST_ORACLE_DEFECT" for row in rows))

    def test_faulty_oracle_falsely_accuses_correct_target(self) -> None:
        rows = evaluate_known_cases(sort_correct, flawed_sort_oracle, SORT_CASES)
        duplicate_row = next(row for row in rows if row["input"] == [4, 4])
        self.assertEqual(duplicate_row["category"], "PROPERTY_VIOLATION")
        self.assertFalse(duplicate_row["oracle_matches_fixture"])
        self.assertTrue(duplicate_row["target_matches_fixture"])

    def test_idempotence_misses_duplicate_removal_bug(self) -> None:
        self.assertTrue(sort_idempotence(sort_drops_duplicates, [4, 4]))
        self.assertNotEqual(sort_drops_duplicates([4, 4]), [4, 4])

    def test_all_saved_day21_counterexamples_replay(self) -> None:
        rows = replay_saved_counterexamples()
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(row["still_counterexample"] for row in rows))


if __name__ == "__main__":
    unittest.main()
