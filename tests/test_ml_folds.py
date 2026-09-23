"""Tests for app.ml.time_folds (PRD R14 embargo)."""

import pandas as pd

from app.ml import N_FOLDS, time_folds


def _series(n: int) -> tuple[pd.Series, pd.Series]:
    t0 = pd.Series(pd.bdate_range("2010-01-01", periods=n))
    t_end = t0 + pd.Timedelta(days=170)  # ~120 trading days later
    return t0, t_end


def test_folds_cover_exactly_the_newer_half() -> None:
    t0, t_end = _series(400)
    folds = time_folds(t0, t_end)
    assert len(folds) == N_FOLDS

    covered: list[int] = []
    for fold in folds:
        covered.extend(fold.test_mask.nonzero()[0].tolist())
    assert sorted(covered) == list(range(200, 400))


def test_folds_are_contiguous_and_disjoint() -> None:
    t0, t_end = _series(400)
    folds = time_folds(t0, t_end)
    seen: set[int] = set()
    for fold in folds:
        idx = fold.test_mask.nonzero()[0]
        assert not (set(idx.tolist()) & seen)
        seen |= set(idx.tolist())
        # contiguous: min..max range has the same count as the block itself
        assert idx.max() - idx.min() + 1 == len(idx)


def test_embargo_no_training_row_leaks_into_the_future() -> None:
    t0, t_end = _series(400)
    folds = time_folds(t0, t_end)
    for fold in folds:
        test_idx = fold.test_mask.nonzero()[0]
        min_t0 = t0.iloc[test_idx].min()
        train_idx = fold.train_mask.nonzero()[0]
        assert (t_end.iloc[train_idx] < min_t0).all()


def test_later_folds_have_more_training_data() -> None:
    t0, t_end = _series(400)
    folds = time_folds(t0, t_end)
    counts = [int(fold.train_mask.sum()) for fold in folds]
    assert counts == sorted(counts)
    assert counts[0] < counts[-1]
