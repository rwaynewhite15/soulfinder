"""The historical layer: religious composition from year 0 to the modern panel.

Two decisions shape this module, and both are about honesty rather than
convenience.

**History is regional, never national.** "France, 800 AD" describes a polity
that did not exist in anything like its current borders, and a per-country
historical series would dress a regional estimate up as national fact. So the
historical layer is estimated for eight macro-regions. Countries inherit their
region's composition for pre-modern frames, flagged `historical`, which is a
*mapping onto modern borders* and is labelled as one everywhere it surfaces.

**The two eras are spliced, not concatenated.** The historical table and the
modern country panel are different reconstructions, and they disagree at the
handoff year. Butting them together would put a visible step in every series at
2010 -- an artefact of two sources meeting, which a viewer would read as a real
event. The same benchmarking used for the US state survey applies here: the
modern panel sets the level at the handoff, the historical table supplies the
shape of everything before it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .benchmark import benchmark_to_anchor, population_weighted_composition
from .compositional import closure
from .config import HANDOFF_YEAR, HISTORICAL_FRAMES, RELIGION_FOUNDED, RELIGIONS, YEARS
from .interpolate import interpolate_population, interpolate_series
from .io import _read_csv


def enforce_founding(comps: np.ndarray, years: np.ndarray) -> np.ndarray:
    """Re-impose exact zeros before a religion existed, then re-close.

    Log-ratio space has no representation for zero, so a structural zero is
    carried as an epsilon and comes back as roughly 0.06% -- enough to render
    as "Muslim 0.1%" in the year 0 frame. The mass removed here is
    redistributed proportionally across the parts that did exist.
    """
    out = np.array(comps, dtype=float, copy=True)
    for religion, founded in RELIGION_FOUNDED.items():
        j = RELIGIONS.index(religion)
        out[np.asarray(years) < founded, j] = 0.0
    return closure(out)


def load_macro_regions() -> pd.DataFrame:
    return _read_csv("macro_regions.csv")


def load_historical_religion() -> pd.DataFrame:
    df = _read_csv("historical_religion.csv")
    df[RELIGIONS] = df[RELIGIONS].fillna(0.0)
    df[RELIGIONS] = closure(df[RELIGIONS].to_numpy(dtype=float))
    return df.sort_values(["region", "year"]).reset_index(drop=True)


def load_historical_population() -> pd.DataFrame:
    df = _read_csv("historical_population.csv")
    df["population"] = df["population_millions"].astype(float) * 1e6
    return df[["region", "year", "population"]].sort_values(["region", "year"]).reset_index(drop=True)


def region_anchor_compositions(dense: pd.DataFrame, region_of: dict[str, str]) -> dict[str, np.ndarray]:
    """Each region's composition at the handoff, rolled up from its countries.

    This is the level the historical series is benchmarked onto, so that the
    two eras meet without a step.
    """
    at = dense[dense.year == HANDOFF_YEAR]
    out: dict[str, np.ndarray] = {}
    for region in sorted(set(region_of.values())):
        members = at[at.iso3.map(region_of).eq(region)]
        if members.empty:
            continue
        out[region] = population_weighted_composition(
            members[RELIGIONS].to_numpy(float), members["population"].to_numpy(float)
        )
    return out


def region_anchor_populations(dense: pd.DataFrame, region_of: dict[str, str]) -> dict[str, float]:
    at = dense[dense.year == HANDOFF_YEAR]
    return {
        region: float(at[at.iso3.map(region_of).eq(region)]["population"].sum())
        for region in sorted(set(region_of.values()))
    }


def build_region_panel(dense: pd.DataFrame, region_of: dict[str, str]) -> dict[str, dict]:
    """Per-region composition and population across every frame in YEARS.

    Frames before the handoff come from the benchmarked historical table;
    frames at or after it are rolled up from the modern country panel, so the
    region series is exact wherever real country data exists.
    """
    hist = load_historical_religion()
    hpop = load_historical_population()
    anchors = region_anchor_compositions(dense, region_of)
    anchor_pops = region_anchor_populations(dense, region_of)

    frames = np.asarray(YEARS, dtype=float)
    n_hist = len(HISTORICAL_FRAMES)
    out: dict[str, dict] = {}

    for region, grp in hist.groupby("region"):
        knots = grp["year"].to_numpy(float)
        comps = interpolate_series(knots, grp[RELIGIONS].to_numpy(float), frames)
        if region in anchors:
            comps = benchmark_to_anchor(comps, frames, HANDOFF_YEAR, anchors[region])

        pg = hpop[hpop.region == region]
        pops = interpolate_population(pg["year"].to_numpy(float), pg["population"].to_numpy(float), frames)
        # Scale the historical population curve so it meets the modern rollup at
        # the handoff, for the same reason the composition is benchmarked.
        if region in anchor_pops and anchor_pops[region] > 0:
            i = YEARS.index(HANDOFF_YEAR)
            pops = pops * (anchor_pops[region] / max(pops[i], 1.0))

        comps = enforce_founding(comps, frames)
        out[region] = {
            "comps": comps[:n_hist],
            "population": pops[:n_hist],
            "comps_all": comps,
            "population_all": pops,
        }
    return out


def world_historical(regions: dict[str, dict]) -> tuple[np.ndarray, np.ndarray]:
    """World composition and population over the historical frames."""
    counts = None
    pops = None
    for r in regions.values():
        c = r["comps"] * r["population"][:, None]
        counts = c if counts is None else counts + c
        pops = r["population"].copy() if pops is None else pops + r["population"]
    return closure(counts), pops


def apportion_to_countries(
    dense: pd.DataFrame,
    regions: dict[str, dict],
    region_of: dict[str, str],
    world_comps: np.ndarray,
    world_pops: np.ndarray,
) -> dict[str, dict]:
    """Give each country a pre-handoff series from its region.

    The region supplies the *shape* of the trajectory; the country's own modern
    composition supplies the level. Handing a country its region's composition
    outright leaves a visible step at the handoff -- measured at 13pp for the
    US and 16pp for India, since neither looks like its regional average -- and
    a viewer reads a step in a timeline as an event rather than as two sources
    meeting. Benchmarking removes it, exactly as it does where the national and
    subnational survey instruments disagree.

    What this asserts is "India's composition moved the way South Asia's did,
    scaled to India's own modern level". That is an interpolation, not a
    reconstruction of Indian religious history, and is flagged `historical`.

    The population split is a *mapping* too: the region's population apportioned
    by the country's share of its region at the handoff. It exists so the globe
    has something to size.
    """
    at = dense[dense.year == HANDOFF_YEAR].set_index("iso3")
    frames = np.asarray(YEARS, dtype=float)
    hist_frames = frames[: len(HISTORICAL_FRAMES)]

    region_totals = {
        r: float(at[at.index.map(lambda i: region_of.get(i)) == r]["population"].sum())
        for r in set(region_of.values())
    }
    world_total = float(at["population"].sum())

    out: dict[str, dict] = {}
    for iso3 in at.index:
        region = region_of.get(iso3)
        if region and region in regions and region_totals.get(region, 0) > 0:
            shape, shape_pop = regions[region]["comps_all"], regions[region]["population"]
            share = float(at.loc[iso3, "population"]) / region_totals[region]
        else:
            # The rest-of-world residual has no macro-region; it follows the world.
            shape = np.vstack([world_comps, np.zeros((len(frames) - len(world_comps), world_comps.shape[1]))])
            shape[len(world_comps):] = world_comps[-1]
            shape_pop = world_pops
            share = float(at.loc[iso3, "population"]) / max(world_total, 1.0)

        anchor = at.loc[iso3, RELIGIONS].to_numpy(float)
        # Anchor on the frame closest to the handoff, so the levelled series
        # meets the modern panel there instead of stepping.
        hist_plus = np.vstack([shape[: len(HISTORICAL_FRAMES)], shape[len(HISTORICAL_FRAMES)]])
        knots = np.append(hist_frames, float(HANDOFF_YEAR))
        levelled = benchmark_to_anchor(hist_plus, knots, HANDOFF_YEAR, anchor)[:-1]
        out[iso3] = {
            "comps": enforce_founding(levelled, hist_frames),
            "population": shape_pop * share,
        }
    return out


def reconcile_to_parent(
    child_comps: list[np.ndarray],
    child_pops: list[np.ndarray],
    parent_comps: np.ndarray,
    parent_pops: np.ndarray,
) -> list[np.ndarray]:
    """Rake children onto their parent's totals, frame by frame.

    Benchmarking each series onto its own modern anchor fixes the step at the
    handoff but breaks a stronger promise: that drilling from world to country
    to state never crosses a seam where the numbers stop adding up. Independently
    levelled children do not sum to their parent.

    This is the same I-projection used for the modern subnational synthesis, and
    it buys the same guarantee. The children keep their relative shape; the
    parent's totals are restored exactly.
    """
    from .ipf import ipf

    n_frames = len(parent_pops)
    out = [np.zeros_like(c) for c in child_comps]
    for k in range(n_frames):
        pops = np.array([p[k] for p in child_pops], dtype=float)
        if pops.sum() <= 0:
            continue
        seed = np.vstack([c[k] for c in child_comps]) * pops[:, None]
        col = np.asarray(parent_comps[k], dtype=float) * float(parent_pops[k])
        fitted = ipf(seed, pops * (float(parent_pops[k]) / pops.sum()), col)
        counts = fitted.matrix
        totals = counts.sum(axis=1, keepdims=True)
        shares = np.divide(counts, totals, out=np.zeros_like(counts), where=totals > 0)
        for i in range(len(out)):
            out[i][k] = shares[i]
    return out
