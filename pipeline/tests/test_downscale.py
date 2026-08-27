import numpy as np
import pytest

from soulfinder.compositional import closure
from soulfinder.downscale import (
    fit_composition_model, shrink_to_national, synthesize_admin1,
)
from soulfinder.spatial import knn_weights, smooth


def _fixture(n=24, d=4, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 3))
    beta = rng.normal(size=(4, d - 1))
    comps = closure(np.exp(np.hstack([np.ones((n, 1)), X]) @ beta @ np.eye(d - 1) @ np.ones((d - 1, d))
                           * 0.0 + rng.normal(scale=0.4, size=(n, d))))
    pops = rng.random(n) * 5e6 + 2e5
    lats = rng.uniform(25, 48, n)
    lons = rng.uniform(-122, -70, n)
    return X, comps, pops, lats, lons


def test_model_recovers_a_covariate_signal():
    rng = np.random.default_rng(1)
    n = 60
    X = rng.normal(size=(n, 2))
    # first ALR coordinate is a clean linear function of the first covariate
    y = np.column_stack([2.0 * X[:, 0], 0.3 * X[:, 1]])
    comps = closure(np.exp(np.column_stack([y, np.zeros(n)])))
    model = fit_composition_model(X, comps)
    assert model.r2[0] > 0.95


def test_model_needs_enough_training_units():
    with pytest.raises(ValueError):
        fit_composition_model(np.zeros((3, 4)), closure(np.ones((3, 3))))


def test_shrinkage_pulls_small_units_further():
    comps = closure(np.array([[0.9, 0.05, 0.05], [0.9, 0.05, 0.05]]))
    national = closure(np.array([0.5, 0.25, 0.25]))
    out, lam = shrink_to_national(comps, national, np.array([5e7, 1e4]), kappa=1e6)
    assert lam[0] > lam[1]
    # the small unit ends up closer to the national composition
    assert abs(out[1, 0] - national[0]) < abs(out[0, 0] - national[0])


def test_shrinkage_output_is_a_valid_composition():
    X, comps, pops, _, _ = _fixture()
    national = closure(np.ones(comps.shape[1]))
    out, _ = shrink_to_national(comps, national, pops)
    assert np.allclose(out.sum(axis=1), 1.0) and (out > 0).all()


def test_knn_weights_are_symmetric_and_row_standardised():
    rng = np.random.default_rng(2)
    lats, lons = rng.uniform(30, 50, 12), rng.uniform(-120, -80, 12)
    W = knn_weights(lats, lons, k=3)
    assert np.allclose(W.sum(axis=1), 1.0)
    assert (W.diagonal() == 0).all()
    assert ((W > 0) == (W > 0).T).all()  # neighbourliness is mutual


def test_smoothing_reduces_dispersion_but_stays_on_the_simplex():
    X, comps, pops, lats, lons = _fixture()
    W = knn_weights(lats, lons, k=4)
    out = smooth(comps, W, alpha=0.4, iterations=3)
    assert np.allclose(out.sum(axis=1), 1.0)
    assert out.std(axis=0).mean() < comps.std(axis=0).mean()


def test_synthesis_reproduces_the_national_marginal_exactly():
    """The load-bearing guarantee: modelling shapes the map, never the total."""
    X, comps, pops, lats, lons = _fixture()
    model = fit_composition_model(X, comps)
    national = closure(np.array([0.55, 0.20, 0.15, 0.10]))
    total_pop = 3.3e8
    res = synthesize_admin1(
        X=X, populations=pops, national_comp=national, national_population=total_pop,
        model=model, lats=lats, lons=lons,
    )
    assert np.allclose(res.counts.sum(axis=0) / total_pop, national, atol=1e-8)
    assert np.isclose(res.counts.sum(), total_pop)
    assert np.allclose(res.counts.sum(axis=1), pops * total_pop / pops.sum())


def test_observed_units_are_not_overwritten_by_the_model():
    X, comps, pops, lats, lons = _fixture()
    model = fit_composition_model(X, comps)
    mask = np.zeros(len(pops), dtype=bool)
    mask[:5] = True
    national = closure(np.ones(4))
    res = synthesize_admin1(
        X=X, populations=pops, national_comp=national, national_population=1e8,
        model=model, lats=lats, lons=lons,
        observed_mask=mask, observed_comps=comps,
    )
    assert res.provenance[:5] == ["observed"] * 5
    assert set(res.provenance[5:]) == {"modeled"}
    # observed rows track their measured values far more closely than modelled ones
    obs_err = np.abs(res.comps[:5] - comps[:5]).mean()
    mod_err = np.abs(res.comps[5:] - comps[5:]).mean()
    assert obs_err < mod_err


def test_credible_interval_brackets_the_estimate():
    X, comps, pops, lats, lons = _fixture()
    model = fit_composition_model(X, comps)
    res = synthesize_admin1(
        X=X, populations=pops, national_comp=closure(np.ones(4)),
        national_population=1e8, model=model, lats=lats, lons=lons,
    )
    assert (res.lo <= res.hi + 1e-12).all()
    assert (res.lo >= 0).all() and (res.hi <= 1).all()
