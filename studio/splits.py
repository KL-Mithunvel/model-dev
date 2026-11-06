"""Deterministic train/val/test assignment (pure logic, no I/O).

Stratification by class is added in Stage 2/3, once labels exist.
"""

import random
from collections.abc import Mapping, Sequence

SPLIT_NAMES = ("train", "val", "test")
_TOLERANCE = 1e-6


def validate_ratios(ratios: Mapping[str, float]) -> dict[str, float]:
    """Return a full ratio dict (missing splits = 0).

    Raises:
        ValueError: unknown split name, a negative ratio, or ratios that do not sum to 1.
    """
    unknown = set(ratios) - set(SPLIT_NAMES)
    if unknown:
        raise ValueError(f"Unknown split name(s): {sorted(unknown)}; use {list(SPLIT_NAMES)}")
    full = {name: float(ratios.get(name, 0.0)) for name in SPLIT_NAMES}
    if any(value < 0 for value in full.values()):
        raise ValueError("Split ratios must not be negative.")
    if abs(sum(full.values()) - 1.0) > _TOLERANCE:
        raise ValueError(f"Split ratios must sum to 1, got {sum(full.values()):.4f}.")
    return full


def split_counts(total: int, ratios: Mapping[str, float]) -> dict[str, int]:
    """Split ``total`` items into whole counts per split using the largest-remainder method."""
    full = validate_ratios(ratios)
    exact = {name: total * ratio for name, ratio in full.items()}
    counts = {name: int(value) for name, value in exact.items()}
    leftover = total - sum(counts.values())
    by_remainder = sorted(SPLIT_NAMES, key=lambda n: (exact[n] - counts[n], full[n]), reverse=True)
    for name in by_remainder[:leftover]:
        counts[name] += 1
    return counts


def assign_splits(
    image_ids: Sequence[int], ratios: Mapping[str, float], seed: int
) -> dict[int, str]:
    """Assign each id to a split. Same ids + ratios + seed always give the same result."""
    ordered = sorted(set(image_ids))
    random.Random(seed).shuffle(ordered)
    counts = split_counts(len(ordered), ratios)
    assignment: dict[int, str] = {}
    cursor = 0
    for name in SPLIT_NAMES:
        for image_id in ordered[cursor : cursor + counts[name]]:
            assignment[image_id] = name
        cursor += counts[name]
    return assignment
