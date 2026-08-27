import numpy as np

from soulfinder.compositional import closure
from soulfinder.interpolate import interpolate_population, interpolate_series


def test_knots_are_reproduced_exactly():
    years = np.array([2010, 2030, 2050])
    comps = closure(np.array([[0.8, 0.1, 0.1], [0.7, 0.2, 0.1], [0.6, 0.3, 0.1]]))
    out = interpolate_series(years, comps, years)
    assert np.allclose(out, comps, atol=1e-9)


def test_output_always_lies_on_the_simplex():
    years = np.array([2010, 2030, 2050])
    comps = closure(np.array([[0.98, 0.01, 0.01], [0.5, 0.4, 0.1], [0.02, 0.9, 0.08]]))
    out = interpolate_series(years, comps, np.arange(2010, 2051))
    assert np.allclose(out.sum(axis=1), 1.0)
    assert (out > 0).all()


def test_pchip_does_not_overshoot_a_monotone_series():
    """A natural cubic spline invents a spike here; PCHIP must not."""
    years = np.array([2010, 2030, 2050])
    comps = closure(np.array([[0.90, 0.05, 0.05], [0.60, 0.20, 0.20], [0.55, 0.225, 0.225]]))
    out = interpolate_series(years, comps, np.arange(2010, 2051))
    series = out[:, 0]
    assert series.max() <= comps[:, 0].max() + 1e-9
    assert series.min() >= comps[:, 0].min() - 1e-9
    assert np.all(np.diff(series) <= 1e-9)  # stays monotone decreasing


def test_two_knots_interpolate_linearly_in_logratio_space():
    years = np.array([2010, 2050])
    comps = closure(np.array([[0.8, 0.2], [0.2, 0.8]]))
    out = interpolate_series(years, comps, np.array([2030]))
    assert np.allclose(out[0], [0.5, 0.5], atol=1e-9)


def test_single_knot_is_held_constant():
    out = interpolate_series(np.array([2020]), closure(np.array([[0.6, 0.4]])), np.arange(2010, 2051))
    assert np.allclose(out, 0.6 * np.ones((41, 1)) * np.array([[1, 2 / 3]]), atol=1e-9)


def test_outside_the_knot_range_is_clamped_not_extrapolated():
    """Extrapolating religion 30 years past the data would be fabrication."""
    years = np.array([2020, 2030])
    comps = closure(np.array([[0.7, 0.3], [0.6, 0.4]]))
    out = interpolate_series(years, comps, np.array([1990, 2100]))
    assert np.allclose(out[0], comps[0], atol=1e-9)
    assert np.allclose(out[1], comps[1], atol=1e-9)


def test_population_growth_is_geometric_not_linear():
    """Constant growth rate between knots => midpoint is the geometric mean."""
    out = interpolate_population(np.array([2010, 2050]), np.array([1e6, 4e6]), np.array([2030]))
    assert np.isclose(out[0], 2e6, rtol=1e-9)
