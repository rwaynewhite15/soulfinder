import numpy as np
import pytest

from soulfinder.ipf import ipf


def test_marginals_are_matched_exactly():
    rng = np.random.default_rng(0)
    seed = rng.random((8, 5)) + 0.05
    rows = rng.random(8) * 1000 + 10
    cols = rng.random(5) * 1000 + 10
    res = ipf(seed, rows, cols)
    assert res.converged
    assert np.allclose(res.matrix.sum(axis=1), rows)
    assert np.allclose(res.matrix.sum(axis=0), cols * rows.sum() / cols.sum())


def test_totals_are_reconciled_when_marginals_disagree():
    """Marginals come from different sources; the grand total is reconciled once."""
    seed = np.ones((3, 3))
    res = ipf(seed, np.array([10.0, 20, 30]), np.array([1.0, 1, 1]))
    assert np.isclose(res.matrix.sum(), 60.0)


def test_uniform_seed_gives_independence_table():
    rows = np.array([100.0, 200.0])
    cols = np.array([90.0, 210.0])
    res = ipf(np.ones((2, 2)), rows, cols)
    expected = np.outer(rows, cols) / rows.sum()
    assert np.allclose(res.matrix, expected)


def test_seed_structure_is_preserved_where_marginals_allow():
    """A seed twice as concentrated in a cell keeps that tilt after raking."""
    seed = np.array([[2.0, 1.0], [1.0, 1.0]])
    res = ipf(seed, np.array([100.0, 100.0]), np.array([100.0, 100.0]))
    assert res.matrix[0, 0] > res.matrix[0, 1]
    assert res.matrix[1, 0] < res.matrix[1, 1]


def test_kl_is_zero_when_seed_already_satisfies_marginals():
    seed = np.array([[10.0, 20.0], [30.0, 60.0]])
    res = ipf(seed, seed.sum(axis=1), seed.sum(axis=0))
    assert res.kl_from_seed < 1e-12


def test_structural_zeros_stay_zero():
    seed = np.array([[1.0, 0.0], [1.0, 1.0]])
    res = ipf(seed, np.array([50.0, 100.0]), np.array([80.0, 70.0]))
    assert res.matrix[0, 1] < 1e-12


def test_rejects_bad_shapes_and_negatives():
    with pytest.raises(ValueError):
        ipf(np.ones((2, 2)), np.ones(3), np.ones(2))
    with pytest.raises(ValueError):
        ipf(-np.ones((2, 2)), np.ones(2), np.ones(2))
    with pytest.raises(ValueError):
        ipf(np.ones((2, 2)), np.zeros(2), np.ones(2))
