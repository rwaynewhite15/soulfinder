"""Splicing two instruments that disagree.

The national panel and the subnational panel come from different surveys with
different questionnaires, vintages, and sampling frames. For the US in 2014 they
disagree by roughly 6 points on the Christian share -- a gap between two real
products, not a coding error, and one that shows up whenever cross-national
projections are combined with a domestic religion survey.

Using the national level as an IPF marginal over subnational data measured by
the other instrument forces that entire 6-point gap onto the states, which
distorts them by more than the covariate model can recover. Cross-validation
catches this immediately: it reports the model doing *worse* than assuming
every state matches the national average.

The standard remedy is to benchmark one series to the other: take the LEVEL
from the instrument that measured the units directly, and the TREND from the
instrument that covers the time span. Concretely, in log-ratio space,

    used(y) = observed(anchor) (+) [ national(y) (-) national(anchor) ]

which reproduces the observed composition exactly in the anchor year and
applies the national series' year-on-year relative changes on top of it. Levels
come from the survey that measured states; change over time comes from the
projection built to model change over time. Neither series is asked to do the
other's job.
"""
from __future__ import annotations

import numpy as np

from .compositional import clr, clr_inv, closure


def benchmark_to_anchor(
    national_by_year: np.ndarray,
    years: np.ndarray,
    anchor_year: int,
    anchor_composition: np.ndarray,
) -> np.ndarray:
    """Re-level a national series onto an observed anchor, preserving its trend.

    national_by_year: (n_years, D). Returns the same shape, benchmarked.
    """
    national_by_year = np.asarray(national_by_year, dtype=float)
    years = np.asarray(years)
    idx = int(np.argmin(np.abs(years - anchor_year)))

    z = clr(national_by_year)
    shift = clr(np.asarray(anchor_composition, dtype=float)[None, :]) - z[idx][None, :]
    return clr_inv(z + shift)


def population_weighted_composition(comps: np.ndarray, populations: np.ndarray) -> np.ndarray:
    """The composition implied by a set of units and their populations.

    This is a *count* aggregation, not a compositional average: it answers
    "what fraction of all these people are Christian", which is exactly the
    quantity an IPF column marginal has to match. The compositional (geometric)
    centre answers a different question and would not reconcile with counts.
    """
    comps = np.asarray(comps, dtype=float)
    pops = np.asarray(populations, dtype=float)
    return closure((comps * pops[:, None]).sum(axis=0))


def instrument_gap(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    """Per-category difference between two compositions, in percentage points."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return {"max_abs_pp": float(np.abs(a - b).max() * 100), "l1_pp": float(np.abs(a - b).sum() * 100)}
