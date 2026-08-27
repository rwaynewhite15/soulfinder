import numpy as np

from soulfinder.benchmark import (
    benchmark_to_anchor, instrument_gap, population_weighted_composition,
)
from soulfinder.compositional import clr, closure


def _series():
    years = np.arange(2010, 2051)
    start = np.array([0.78, 0.02, 0.16, 0.04])
    end = np.array([0.66, 0.04, 0.26, 0.04])
    t = ((years - 2010) / 40)[:, None]
    return years, closure(start[None, :] * (1 - t) + end[None, :] * t)


def test_anchor_year_matches_observed_level_exactly():
    years, series = _series()
    anchor = closure(np.array([0.70, 0.03, 0.23, 0.04]))
    out = benchmark_to_anchor(series, years, 2014, anchor)
    assert np.allclose(out[list(years).index(2014)], anchor, atol=1e-12)


def test_trend_is_preserved_exactly_in_logratio_space():
    years, series = _series()
    anchor = closure(np.array([0.70, 0.03, 0.23, 0.04]))
    out = benchmark_to_anchor(series, years, 2014, anchor)
    assert np.allclose(clr(out[-1]) - clr(out[0]), clr(series[-1]) - clr(series[0]), atol=1e-9)


def test_benchmarking_is_a_no_op_when_instruments_already_agree():
    years, series = _series()
    i = list(years).index(2014)
    out = benchmark_to_anchor(series, years, 2014, series[i])
    assert np.allclose(out, series, atol=1e-9)


def test_output_stays_on_the_simplex():
    years, series = _series()
    out = benchmark_to_anchor(series, years, 2050, closure(np.array([0.1, 0.6, 0.2, 0.1])))
    assert np.allclose(out.sum(axis=1), 1.0) and (out > 0).all()


def test_population_weighting_is_a_count_aggregation():
    comps = np.array([[1.0, 0.0], [0.0, 1.0]])
    out = population_weighted_composition(comps, np.array([300.0, 100.0]))
    assert np.allclose(out, [0.75, 0.25])


def test_instrument_gap_reports_percentage_points():
    g = instrument_gap(np.array([0.77, 0.23]), np.array([0.71, 0.29]))
    assert np.isclose(g["max_abs_pp"], 6.0)
