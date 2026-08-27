"""Temporal interpolation: decadal source knots -> a value for every year.

The source datasets publish one composition per decade. The app's year slider
needs one per year. Two failure modes to avoid:

  1. Interpolating raw percentages. Componentwise interpolation of shares does
     not stay on the simplex, and clipping the result back silently breaks the
     constant-sum constraint. Fixed by working in ALR coordinates.

  2. Overshoot. A natural cubic spline through 2010/2030/2050 will bulge past
     both endpoints between knots, inventing local maxima -- a religion that
     grows monotonically in the source data would appear to spike and fall
     back. Since these bulges are indistinguishable from real trend reversals
     once rendered, we use PCHIP, which is shape-preserving: it never
     introduces an extremum that is not in the data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

from .compositional import alr, alr_inv
from .config import RELIGIONS, YEARS


def interpolate_series(knot_years: np.ndarray, knot_comps: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Interpolate compositions across years, shape-preserving, on the simplex.

    knot_comps: (K, D) compositions at K knot years. Returns (len(targets), D).
    """
    knot_years = np.asarray(knot_years, dtype=float)
    order = np.argsort(knot_years)
    knot_years, knot_comps = knot_years[order], np.asarray(knot_comps, dtype=float)[order]

    if len(knot_years) == 1:
        return np.repeat(knot_comps, len(targets), axis=0)

    y = alr(knot_comps)  # (K, D-1)
    if len(knot_years) == 2:
        # PCHIP needs >=2 points and degenerates to linear here; do it directly
        # so the intent is explicit rather than incidental.
        t = (np.asarray(targets, float) - knot_years[0]) / (knot_years[1] - knot_years[0])
        t = np.clip(t, 0.0, 1.0)[:, None]
        interp = y[0][None, :] * (1 - t) + y[1][None, :] * t
    else:
        spline = PchipInterpolator(knot_years, y, axis=0, extrapolate=False)
        clamped = np.clip(np.asarray(targets, float), knot_years[0], knot_years[-1])
        interp = spline(clamped)
    return alr_inv(interp)


def interpolate_population(knot_years, knot_pop, targets) -> np.ndarray:
    """Population interpolated geometrically (constant growth rate between knots).

    Linear interpolation of population implies a growth *rate* that drifts
    between knots; interpolating log-population implies a constant rate, which
    is what a demographic projection actually asserts.
    """
    knot_years = np.asarray(knot_years, dtype=float)
    order = np.argsort(knot_years)
    knot_years, knot_pop = knot_years[order], np.asarray(knot_pop, dtype=float)[order]
    log_p = np.log(np.maximum(knot_pop, 1.0))
    if len(knot_years) == 1:
        return np.repeat(knot_pop, len(targets))
    if len(knot_years) == 2:
        t = np.clip((np.asarray(targets, float) - knot_years[0]) / (knot_years[1] - knot_years[0]), 0, 1)
        out = log_p[0] * (1 - t) + log_p[1] * t
    else:
        spline = PchipInterpolator(knot_years, log_p, extrapolate=False)
        out = spline(np.clip(np.asarray(targets, float), knot_years[0], knot_years[-1]))
    return np.exp(out)


def densify_national(
    national: pd.DataFrame, population: pd.DataFrame, years: list[int] = YEARS
) -> pd.DataFrame:
    """Expand ragged decadal knots into a dense (iso3 x year) panel.

    Each row is tagged `observed` when that year is a source knot and
    `interpolated` otherwise, so the UI can tell the two apart.
    """
    years_arr = np.asarray(years, dtype=float)
    frames = []
    pop_by_iso = {k: v for k, v in population.groupby("iso3")}

    for iso3, grp in national.groupby("iso3"):
        comps = interpolate_series(grp["year"].to_numpy(), grp[RELIGIONS].to_numpy(float), years_arr)
        pgrp = pop_by_iso.get(iso3)
        if pgrp is None:
            continue
        pops = interpolate_population(pgrp["year"].to_numpy(), pgrp["population"].to_numpy(float), years_arr)

        out = pd.DataFrame(comps, columns=RELIGIONS)
        out.insert(0, "iso3", iso3)
        out.insert(1, "country", grp["country"].iloc[0])
        out.insert(2, "year", years)
        out["population"] = pops
        knots = set(grp["year"].astype(int))
        out["provenance"] = ["observed" if y in knots else "interpolated" for y in years]
        frames.append(out)

    return pd.concat(frames, ignore_index=True)


def rollup_world(dense: pd.DataFrame) -> pd.DataFrame:
    """Population-weighted world composition, computed from the country panel.

    Deliberately *derived* rather than read from a world row: if the country
    table and the published world figure disagree, that is a data problem worth
    surfacing, not one to paper over. `soulfinder.validate` checks the gap.
    """
    rows = []
    for year, grp in dense.groupby("year"):
        pop = grp["population"].to_numpy(float)
        counts = grp[RELIGIONS].to_numpy(float) * pop[:, None]
        total = counts.sum()
        rows.append(
            {"iso3": "WLD", "country": "World", "year": int(year), "population": float(pop.sum()),
             **{r: float(v) for r, v in zip(RELIGIONS, counts.sum(axis=0) / total)},
             "provenance": "modeled"}
        )
    return pd.DataFrame(rows)
