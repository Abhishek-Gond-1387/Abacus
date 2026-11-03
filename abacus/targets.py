"""Checked-in trusted target and oracle functions allowed by problem schemas."""

from __future__ import annotations

from typing import Callable


def sort_correct(values: list[int]) -> list[int]:
    return sorted(values)


def sort_drops_duplicates(values: list[int]) -> list[int]:
    return sorted(set(values))


TARGETS: dict[str, Callable[[list[int]], list[int]]] = {
    "sort_correct": sort_correct,
    "sort_drops_duplicates": sort_drops_duplicates,
}
ORACLES: dict[str, Callable[[list[int]], list[int]]] = {
    "sorted_integer_list_v1": sorted,
}
