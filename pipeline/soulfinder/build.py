"""Build the web artifacts.

    python3 -m soulfinder.build

Reads sources/, runs interpolation + benchmarking + synthesis + validation, and
writes JSON into web/public/data/. Everything the app needs is precomputed
here: there is no server, and the year slider is a client-side array lookup.

Order matters. Benchmarking happens BEFORE the national series is emitted and
before the world is rolled up, so that every region in the output is on one
canonical series and drilling from world -> country -> state never crosses a
seam where the numbers stop adding up.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import io as sio
from .compositional import closure
from .benchmark import benchmark_to_anchor, instrument_gap, population_weighted_composition
from .config import (
    GEO_SOURCES, HANDOFF_YEAR, HISTORICAL_FRAMES, MACRO_REGIONS, MODERN_FRAMES,
    RELIGION_LABELS, RELIGIONS, WEB_DATA, YEARS,
)
from .dasymetric import build_surface, load_polygons
from .downscale import COVARIATES, fit_composition_model, synthesize_admin1
from .historical import (
    apportion_to_countries, build_region_panel, enforce_founding,
    load_macro_regions, reconcile_to_parent, world_historical,
)
from .interpolate import densify_national, rollup_world
from .validate import check_world_rollup, cross_validate

# The year the observed subnational survey was fielded; the benchmark anchor.
ANCHOR_YEAR = 2014

# Published world composition, used only as an independent check on the rollup.
PUBLISHED_WORLD_2010 = {
    "christian": 0.314, "muslim": 0.232, "unaffiliated": 0.164, "hindu": 0.150,
    "buddhist": 0.071, "folk": 0.059, "other": 0.008, "jewish": 0.002,
}


def _round_shares(arr: np.ndarray, places: int = 5) -> list[list[float]]:
    return [[round(float(v), places) for v in row] for row in np.asarray(arr)]


def _write(name: str, payload) -> Path:
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    path = WEB_DATA / name
    with open(path, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    return path


def load_admin1_frame() -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Admin-1 covariates joined to centroids, plus the observed-truth matrix."""
    cov = sio.load_admin1_covariates()
    obs = sio.load_admin1_observed()
    centroids = pd.read_csv(GEO_SOURCES / "us_state_centroids.csv")
    centroids["geo_id"] = centroids["geo_id"].astype(str).str.zfill(2)

    df = cov.merge(centroids[["geo_id", "lat", "lon"]], on="geo_id", how="left")
    if df["lat"].isna().any():
        missing = df.loc[df["lat"].isna(), "admin1_code"].tolist()
        raise ValueError(f"no centroid for admin1 units: {missing}")

    obs_idx = obs.set_index("admin1_code")
    observed_mask = df["admin1_code"].isin(obs_idx.index).to_numpy()
    comps_true = np.vstack([
        obs_idx.loc[c, RELIGIONS].to_numpy(float) if c in obs_idx.index
        else np.full(len(RELIGIONS), np.nan)
        for c in df["admin1_code"]
    ])
    return df, observed_mask, comps_true


def apply_benchmark(dense: pd.DataFrame, iso3: str, comps_true: np.ndarray,
                    pops: np.ndarray, out: dict) -> pd.DataFrame:
    """Re-level a country's canonical series onto its subnational instrument.

    Where a country has been surveyed directly at the state level, that survey
    measured its people; the cross-national projection did not. So the level
    comes from the survey and the trend from the projection, and the *result*
    becomes the country's canonical series -- not a private input to the
    downscaler. Otherwise the app would show one Christian share for the US and
    a different one for the sum of its states.
    """
    rows = dense[dense.iso3 == iso3].sort_values("year")
    years_arr = rows["year"].to_numpy()
    raw = rows[RELIGIONS].to_numpy(float)

    anchor_comp = population_weighted_composition(comps_true, pops)
    raw_at_anchor = raw[int(np.argmin(np.abs(years_arr - ANCHOR_YEAR)))]
    out["instrument_gap"] = {
        "iso3": iso3,
        "anchor_year": ANCHOR_YEAR,
        "national_series": {r: round(float(v), 5) for r, v in zip(RELIGIONS, raw_at_anchor)},
        "subnational_rollup": {r: round(float(v), 5) for r, v in zip(RELIGIONS, anchor_comp)},
        **instrument_gap(raw_at_anchor, anchor_comp),
    }

    bm = benchmark_to_anchor(raw, years_arr, ANCHOR_YEAR, anchor_comp)
    dense = dense.copy()
    mask = dense.iso3 == iso3
    dense.loc[mask, RELIGIONS] = bm
    # The series is no longer a straight read of the source; say so.
    dense.loc[mask, "provenance"] = "modeled"
    return dense


def build_admin1(out: dict, dense: pd.DataFrame, df: pd.DataFrame,
                 observed_mask: np.ndarray, comps_true: np.ndarray) -> list[dict]:
    X = df[COVARIATES].to_numpy(float)
    pops = df["population"].to_numpy(float)
    lats, lons = df["lat"].to_numpy(float), df["lon"].to_numpy(float)

    usa = dense[dense.iso3 == "USA"].sort_values("year")
    years_arr = usa["year"].to_numpy()
    national = usa[RELIGIONS].to_numpy(float)  # already benchmarked
    anchor_i = int(np.argmin(np.abs(years_arr - ANCHOR_YEAR)))

    report = cross_validate(
        X=X, comps_true=comps_true, populations=pops, lats=lats, lons=lons,
        unit_names=df["admin1_name"].tolist(),
        national_comp=national[anchor_i],
        national_population=float(usa["population"].iloc[anchor_i]),
    )
    out["validation"] = report.to_dict()

    model = fit_composition_model(X, comps_true)
    shares_by_year, lo_by_year, hi_by_year, pops_by_year, diag = [], [], [], [], []
    for k, (_, row) in enumerate(usa.iterrows()):
        res = synthesize_admin1(
            X=X, populations=pops, national_comp=national[k],
            national_population=float(row["population"]), model=model,
            lats=lats, lons=lons,
            observed_mask=observed_mask, observed_comps=comps_true,
        )
        shares_by_year.append(res.comps)
        lo_by_year.append(res.lo)
        hi_by_year.append(res.hi)
        pops_by_year.append(res.counts.sum(axis=1))
        diag.append((res.ipf_iterations, res.ipf_error, res.ipf_kl))

    out["ipf_diagnostics"] = {
        "max_marginal_error": max(d[1] for d in diag),
        "max_iterations": max(d[0] for d in diag),
        "mean_kl_from_seed": float(np.mean([d[2] for d in diag])),
    }

    shares = np.stack(shares_by_year)
    lo, hi = np.stack(lo_by_year), np.stack(hi_by_year)
    unit_pops = np.stack(pops_by_year)

    series = []
    for i, row in df.iterrows():
        is_obs = bool(observed_mask[i])
        series.append({
            "id": f"USA-{row['admin1_code']}",
            "code": row["admin1_code"],
            "geo_id": row["geo_id"],
            "name": row["admin1_name"],
            "level": "admin1",
            "parent": "USA",
            "shares": _round_shares(shares[:, i, :]),
            "lo": _round_shares(lo[:, i, :]),
            "hi": _round_shares(hi[:, i, :]),
            "population": [round(float(p)) for p in unit_pops[:, i]],
            # Observed state data exists for the survey year only; every other
            # year is that anchor carried by the national trend, a weaker claim.
            "provenance": [
                ("observed" if (is_obs and y == ANCHOR_YEAR) else ("modeled" if is_obs else "synthetic"))
                for y in MODERN_FRAMES
            ],
        })
    return series


def build_density(out: dict, dense: pd.DataFrame, admin1_df: pd.DataFrame) -> None:
    cities = sio.load_cities()
    geo_dir = WEB_DATA / "geo"

    country_polys = load_polygons(geo_dir / "countries.geojson", "iso3")
    cc = pd.read_csv(GEO_SOURCES / "country_centroids.csv")
    country_centroids = {r.iso3: (float(r.lon), float(r.lat)) for r in cc.itertuples()}
    pop_2020 = dense[dense.year == 2020].set_index("iso3")["population"].to_dict()

    cities_by_country = {
        iso3: (g[["lon", "lat"]].to_numpy(float), g["population"].to_numpy(float))
        for iso3, g in cities.groupby("iso3")
    }
    world_pts = build_surface(
        polygons={k: v for k, v in country_polys.items() if k in pop_2020},
        centroids=country_centroids,
        cities_by_unit=cities_by_country,
        populations={k: float(v) for k, v in pop_2020.items()},
        total_points=7000,
    )

    state_polys = load_polygons(geo_dir / "us-states.geojson", "geo_id")
    state_centroids = {r.geo_id: (float(r.lon), float(r.lat)) for r in admin1_df.itertuples()}
    state_pops = {r.geo_id: float(r.population) for r in admin1_df.itertuples()}
    code_to_geo = dict(zip(admin1_df["admin1_code"], admin1_df["geo_id"]))
    cities_by_state = {}
    for code, g in cities[cities.iso3 == "USA"].groupby("admin1_code"):
        gid = code_to_geo.get(code)
        if gid:
            cities_by_state[gid] = (g[["lon", "lat"]].to_numpy(float), g["population"].to_numpy(float))

    state_pts = build_surface(
        polygons={k: v for k, v in state_polys.items() if k in state_pops},
        centroids=state_centroids,
        cities_by_unit=cities_by_state,
        populations=state_pops,
        total_points=6000,
        min_points=25,
    )

    out["density"] = {"world_points": len(world_pts), "us_points": len(state_pts)}
    _write("density-world.json", world_pts)
    _write("density-usa.json", state_pts)


def region_modern_rollup(dense: pd.DataFrame, region_of: dict[str, str], region: str) -> tuple[np.ndarray, np.ndarray]:
    """A region's composition and population over the modern frames.

    Rolled up from its member countries rather than read from the historical
    table, so wherever real country data exists the region series is exact.
    """
    members = dense[dense.iso3.map(region_of).eq(region)]
    comps, pops = [], []
    for year in MODERN_FRAMES:
        at = members[members.year == year]
        pop = at["population"].to_numpy(float)
        counts = at[RELIGIONS].to_numpy(float) * pop[:, None]
        total = counts.sum()
        comps.append(counts.sum(axis=0) / total if total > 0 else np.zeros(len(RELIGIONS)))
        pops.append(float(pop.sum()))
    return np.asarray(comps), np.asarray(pops)


def stitch(hist_comps, hist_pops, modern_comps, modern_pops, modern_prov) -> dict:
    """Join the historical and modern halves into one full-length series."""
    return {
        "shares": _round_shares(np.vstack([hist_comps, modern_comps])),
        "population": [round(float(p)) for p in np.concatenate([hist_pops, modern_pops])],
        "provenance": ["historical"] * len(HISTORICAL_FRAMES) + list(modern_prov),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Soulfinder web data artifacts")
    ap.add_argument("--skip-density", action="store_true", help="skip the dasymetric surface")
    args = ap.parse_args()

    t0 = time.time()
    diag: dict = {}

    national = sio.load_national_religion()
    population = sio.resolve_row_residual(national, sio.load_population())
    dense = densify_national(national, population)   # modern frames only

    admin1_df, observed_mask, comps_true = load_admin1_frame()
    dense = apply_benchmark(dense, "USA", comps_true, admin1_df["population"].to_numpy(float), diag)

    admin1_series = build_admin1(diag, dense, admin1_df, observed_mask, comps_true)

    # --- historical layer ------------------------------------------------------
    macro = load_macro_regions()
    region_of = dict(zip(macro["iso3"], macro["region"]))
    regions = build_region_panel(dense, region_of)
    w_comps, w_pops = world_historical(regions)
    country_hist = apportion_to_countries(dense, regions, region_of, w_comps, w_pops)

    # Restore the hierarchy over the historical frames. Each country was
    # levelled onto its own modern anchor, which fixes the handoff step but
    # leaves the members of a region no longer summing to it.
    for code, panel in regions.items():
        members = [i for i in country_hist if region_of.get(i) == code]
        if len(members) < 2:
            continue
        raked = reconcile_to_parent(
            [country_hist[i]["comps"] for i in members],
            [country_hist[i]["population"] for i in members],
            panel["comps"], panel["population"],
        )
        for iso3, comps in zip(members, raked):
            country_hist[iso3]["comps"] = enforce_founding(
                comps, np.asarray(HISTORICAL_FRAMES, dtype=float)
            )

    # The world is then the exact rollup of every country, rather than a
    # separately benchmarked series that would not match its own parts.
    _cty = list(country_hist)
    _counts = sum(country_hist[i]["comps"] * country_hist[i]["population"][:, None] for i in _cty)
    _pops = sum(country_hist[i]["population"] for i in _cty)
    w_comps, w_pops = closure(_counts), _pops
    diag["historical"] = {
        "frames": len(HISTORICAL_FRAMES),
        "first_year": HISTORICAL_FRAMES[0],
        "handoff_year": HANDOFF_YEAR,
        "regions": len(regions),
        "world_population_year_0": round(float(w_pops[0])),
    }

    world_modern = rollup_world(dense).sort_values("year")
    diag["world_rollup_check"] = check_world_rollup(
        world_modern[world_modern.year == 2010].iloc[0].to_dict(), PUBLISHED_WORLD_2010
    )

    names = national.drop_duplicates("iso3").set_index("iso3")["country"].to_dict()
    series: list[dict] = []

    series.append({
        "id": "WLD", "name": "World", "level": "world",
        **stitch(w_comps, w_pops,
                 world_modern[RELIGIONS].to_numpy(float),
                 world_modern["population"].to_numpy(float),
                 world_modern["provenance"]),
    })

    for code, label in MACRO_REGIONS.items():
        if code not in regions:
            continue
        m_comps, m_pops = region_modern_rollup(dense, region_of, code)
        series.append({
            "id": f"R-{code}", "name": label, "level": "region", "parent": "WLD",
            **stitch(regions[code]["comps"], regions[code]["population"],
                     m_comps, m_pops, ["modeled"] * len(MODERN_FRAMES)),
        })

    for iso3, grp in dense.groupby("iso3"):
        grp = grp.sort_values("year")
        h = country_hist[iso3]
        series.append({
            "id": iso3, "name": names.get(iso3, iso3), "level": "country",
            "parent": f"R-{region_of[iso3]}" if iso3 in region_of else "WLD",
            **stitch(h["comps"], h["population"],
                     grp[RELIGIONS].to_numpy(float),
                     grp["population"].to_numpy(float),
                     grp["provenance"]),
        })

    # US states inherit the country's pre-handoff series, split by their share
    # of national population at the handoff -- the same mapping, one level down.
    usa_hist = country_hist["USA"]
    usa_pop_2010 = float(dense[(dense.iso3 == "USA") & (dense.year == HANDOFF_YEAR)]["population"].iloc[0])
    _hist_knots = np.asarray(HISTORICAL_FRAMES + [HANDOFF_YEAR], dtype=float)
    _state_hist: list[np.ndarray] = []
    _state_share: list[float] = []
    for st in admin1_series:
        share = st["population"][0] / usa_pop_2010 if usa_pop_2010 else 0.0
        # Utah is 87% Christian against a 72% national level; handed the national
        # curve outright it steps 12pp at the handoff. Same benchmark as everywhere.
        st_anchor = np.asarray(st["shares"][0], dtype=float)
        st_shape = np.vstack([usa_hist["comps"], usa_hist["comps"][-1]])
        st_hist = benchmark_to_anchor(st_shape, _hist_knots, HANDOFF_YEAR, st_anchor)[:-1]
        st_hist = enforce_founding(st_hist, np.asarray(HISTORICAL_FRAMES, dtype=float))
        _state_hist.append(st_hist)
        _state_share.append(share)
    _raked_states = reconcile_to_parent(
        _state_hist,
        [usa_hist["population"] * sh for sh in _state_share],
        country_hist["USA"]["comps"], country_hist["USA"]["population"],
    )
    for st, st_hist, share in zip(admin1_series, _raked_states, _state_share):
        st_hist = enforce_founding(st_hist, np.asarray(HISTORICAL_FRAMES, dtype=float))
        st.update(stitch(st_hist, usa_hist["population"] * share,
                         np.asarray(st["shares"], dtype=float),
                         np.asarray(st["population"], dtype=float),
                         st["provenance"]))
        for key in ("lo", "hi"):
            if key in st:
                pad = [[0.0] * len(RELIGIONS)] * len(HISTORICAL_FRAMES)
                st[key] = pad + st[key]

    if not args.skip_density:
        build_density(diag, dense, admin1_df)

    _write("regions.json", {
        "years": YEARS, "religions": RELIGIONS, "labels": RELIGION_LABELS,
        "handoffYear": HANDOFF_YEAR,
        "series": series + admin1_series,
    })
    _write("meta.json", {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "years": YEARS, "religions": RELIGIONS, "labels": RELIGION_LABELS,
        "handoffYear": HANDOFF_YEAR,
        "counts": {
            "countries": sum(1 for x in series if x["level"] == "country"),
            "regions": sum(1 for x in series if x["level"] == "region"),
            "admin1": len(admin1_series),
        },
        "diagnostics": diag,
    })

    v = diag["validation"]
    print(f"frames: {len(YEARS)} ({YEARS[0]}..{YEARS[-1]}), "
          f"{len(HISTORICAL_FRAMES)} historical + {len(MODERN_FRAMES)} modern")
    print(f"series: {len(series) + len(admin1_series)}")
    print(f"historical: {len(regions)} macro-regions, world population at year 0 "
          f"{diag['historical']['world_population_year_0'] / 1e6:.0f}M")
    print(f"IPF: max marginal error {diag['ipf_diagnostics']['max_marginal_error']:.2e}")
    print(f"validation: out-of-sample TVD {v['tvd_model']:.4f} vs "
          f"national-average baseline {v['tvd_baseline']:.4f} (skill {v['tvd_skill']:+.1%})")
    ig = diag["instrument_gap"]
    print(f"instrument gap for {ig['iso3']} at {ig['anchor_year']}: {ig['max_abs_pp']:.1f}pp")
    rc = diag["world_rollup_check"]
    print(f"world rollup vs published 2010: max abs diff {rc['max_abs_diff']:.4f} "
          f"({'ok' if rc['within_tolerance'] else 'OUT OF TOLERANCE'})")
    if "density" in diag:
        print(f"density: {diag['density']['world_points']} world + {diag['density']['us_points']} US anchors")
    print(f"done in {time.time() - t0:.1f}s -> {WEB_DATA}")


if __name__ == "__main__":
    main()
