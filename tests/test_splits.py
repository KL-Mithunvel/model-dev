import pytest

from studio.splits import assign_splits, split_counts, validate_ratios

RATIOS = {"train": 0.8, "val": 0.1, "test": 0.1}


def test_counts_add_up_for_many_sizes():
    for total in range(0, 60):
        counts = split_counts(total, RATIOS)
        assert sum(counts.values()) == total
        assert all(value >= 0 for value in counts.values())


def test_counts_known_values():
    assert split_counts(10, RATIOS) == {"train": 8, "val": 1, "test": 1}
    assert split_counts(2000, RATIOS) == {"train": 1600, "val": 200, "test": 200}
    assert split_counts(3, RATIOS) == {"train": 3, "val": 0, "test": 0}


def test_assignment_is_deterministic_and_seed_sensitive():
    ids = list(range(1, 101))
    assert assign_splits(ids, RATIOS, seed=1) == assign_splits(list(reversed(ids)), RATIOS, seed=1)
    assert assign_splits(ids, RATIOS, seed=1) != assign_splits(ids, RATIOS, seed=2)


def test_assignment_respects_counts_and_covers_every_id():
    ids = list(range(1, 51))
    result = assign_splits(ids, RATIOS, seed=7)
    assert set(result) == set(ids)
    tally = {name: list(result.values()).count(name) for name in RATIOS}
    assert tally == split_counts(50, RATIOS)


def test_empty_and_duplicate_ids():
    assert assign_splits([], RATIOS, seed=1) == {}
    assert len(assign_splits([5, 5, 5], RATIOS, seed=1)) == 1


def test_two_way_split_with_missing_name_means_zero():
    result = assign_splits(range(10), {"train": 0.7, "val": 0.3}, seed=0)
    assert "test" not in result.values()


@pytest.mark.parametrize(
    "ratios, message",
    [
        ({"train": 0.5, "val": 0.2}, "sum to 1"),
        ({"train": 1.2, "val": -0.2}, "negative"),
        ({"train": 1.0, "dev": 0.0}, "Unknown"),
    ],
)
def test_invalid_ratios_are_rejected(ratios, message):
    with pytest.raises(ValueError, match=message):
        validate_ratios(ratios)
