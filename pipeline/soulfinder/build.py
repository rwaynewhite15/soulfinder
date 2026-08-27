"""Build the web artifacts.

    python3 -m soulfinder.build

Reads sources/, runs interpolation + synthesis + validation, writes JSON into
web/public/data/. Everything the app needs is precomputed here: there is no
server, and the year slider is a client-side array lookup.
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
from .config import (
    GEO_SOURCES,
    RELIGION_LABELS,
    RELIGIONS,
    WEB_DATA,
    YEARS,
)
from .benchmark import benchmark_to_anchor, instrument_gap, population_weighted_composition
from .dasymetric import build_surface, load_polygons
from .downscale import COVARIATES, fit_composition_model, synthesize_admin1
from .interpolate import densify_national, rollup_world
from .validate import check_world_rollup, cross_validate

# Published world composition, used only as an independent check on the rollup.
# The year the observed state-level survey was fielded; the benchmark anchor.
ANCHOR_YEAR = 2014

PUBLISHED_WORLD_2010 = {
    "christian": 0.314, "muslim": 0.232, "unaffiliated": 0.164, "hindu": 0.150,
    "buddhist": 0.071, "folk": 0.059, "other": 0.008, "jewish": 0.002,
}


def _round_shares(arr: np.ndarray, places: int = 5) -> list[list[float]]:
    return [[round(float(v), places) for v in row] for row in np.asarray(arr)]


def build_national(out: dict) -> pd.DataFrame:
    national = sio.load_national_religion()
    population = sio.resolve_row_residual(national, sio.load_population())

    dense = densify_national(national, population)
    world = rollup_world(dense)

    names = national.drop_duplicates("iso3").set_index("iso3")["country"].to_dict()
    series = []
    for iso3, grp in dense.groupby("iso3"):
        grp = grp.sort_values("year")
        series.append({
            "id": iso3,
            "name": names.get(iso3, iso3),
            "level": "country",
            "shares": _round_shares(grp[RELIGIONS].to_numpy()),
            "population": [round(float(p)) for p in grp["population"]],
            "provenance": list(grp["provenance"]),
        })

    world = world.sort_values("year")
    series.insert(0, {
        "id": "WLD",
        "name": "World",
        "level": "world",
        "shares": _round_shares(world[RELIGIONS].to_numpy()),
        "population": [round(float(p)) for p in world["population"]],
        "provenance": list(world["provenance"]),
    })

    w2010 = world[world.year == 2010].iloc[0].to_dict()
    out["world_rollup_check"] = check_world_rollup(w2010, PUBLISHED_WORLD_2010)
    return dense


def build_admin1(out: dict, dense: pd.DataFrame) -> tuple[list[dict], pd.DataFrame]:
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
        obs_idx.loc[c, RELIGIONS].to_numpy(float) if c in obs_idx.index else np.full(len(RELIGIONS), np.nan)
        for c in df["admin1_code"]
    ])

    X = df[COVARIATES].to_numpy(float)
    pops = df["population"].to_numpy(float)
    lats, lons = df["lat"].to_numpy(float), df["lon"].to_numpy(float)

    usa = dense[dense.iso3 == "USA"].sort_values("year")
    years_arr = usa["year"].to_numpy()
    national_raw = usa[RELIGIONS].to_numpy(float)

    # Benchmark the national projection onto the level actually measured by the
    # state survey. Without this the IPF marginal comes from a different
    # instrument than the state data, and forces its ~6pp disagreement onto the
    # states -- see soulfinder/benchmark.py.
    anchor_comp = population_weighted_composition(comps_true, pops)
    raw_at_anchor = national_raw[int(np.argmin(np.abs(years_arr - ANCHOR_YEAR)))]
    out["instrument_gap"] = {
        "anchor_year": ANCHOR_YEAR,
        "national_series": {r: round(float(v), 5) for r, v in zip(RELIGIONS, raw_at_anchor)},
        "subnational_rollup": {r: round(float(v), 5) for r, v in zip(RELIGIONS, anchor_comp)},
        **instrument_gap(raw_at_anchor, anchor_comp),
    }
    national_bm = benchmark_to_anchor(national_raw, years_arr, ANCHOR_YEAR, anchor_comp)

    # --- validation, against the one year we have observed state data for ----
    anchor_i = int(np.argmin(np.abs(years_arr - ANCHOR_YEAR)))
    pop_anchor = float(usa["population"].iloc[anchor_i])
    report = cross_validate(
        X=X, comps_true=comps_true, populations=pops, lats=lats, lons=lons,
        unit_names=df["admin1_name"].tolist(), national_comp=national_bm[anchor_i],
        national_population=pop_anchor,
    )
    out["validation"] = report.to_dict()

    # --- production run: fit on everything, synthesise every year ------------
    model = fit_composition_model(X, comps_true)
    shares_by_year, lo_by_year, hi_by_year, pops_by_year = [], [], [], []
    ipf_diag = []
    for k, (_, row) in enumerate(usa.iterrows()):
        res = synthesize_admin1(
            X=X, populations=pops, national_comp=national_bm[k],
            national_population=float(row["population"]), model=model,
            lats=lats, lons=lons,
            observed_mask=observed_mask, observed_comps=comps_true,
        )
        shares_by_year.append(res.comps)
        lo_by_year.append(res.lo)
        hi_by_year.append(res.hi)
        pops_by_year.append(res.counts.sum(axis=1))
        ipf_diag.append({"year": int(row["year"]), "iters": res.ipf_iterations,
                         "err": res.ipf_error, "kl": res.ipf_kl})

    out["ipf_diagnostics"] = {
        "max_marginal_error": max(d["err"] for d in ipf_diag),
        "max_iterations": max(d["iters"] for d in ipf_diag),
        "mean_kl_from_seed": float(np.mean([d["kl"] for d in ipf_diag])),
    }

    shares = np.stack(shares_by_year)   # (years, units, D)
    lo = np.stack(lo_by_year)
    hi = np.stack(hi_by_year)
    unit_pops = np.stack(pops_by_year)

    # Observed state data exists for one survey year only. Every other year is
    # that anchor carried forward by the national trend, which is a weaker claim
    # -- so only the anchor year is labelled `observed`.
    series = []
    for i, row in df.iterrows():
        code = row["admin1_code"]
        is_obs = bool(observed_mask[i])
        series.append({
            "id": f"USA-{code}",
            "code": code,
            "geo_id": row["geo_id"],
            "name": row["admin1_name"],
            "level": "admin1",
            "parent": "USA",
            "shares": _round_shares(shares[:, i, :]),
            "lo": _round_shares(lo[:, i, :]),
            "hi": _round_shares(hi[:, i, :]),
            "population": [round(float(p)) for p in unit_pops[:, i]],
            "provenance": [
                ("observed" if (is_obs and y == 2014) else ("modeled" if is_obs else "synthetic"))
                for y in YEARS
            ],
        })
    return series, df


def build_density(out: dict, dense: pd.DataFrame, admin1_df: pd.DataFrame) -> None:
    cities = sio.load_cities()
    geo_dir = WEB_DATA / "geo"

    # --- countries -----------------------------------------------------------
    country_polys = load_polygons(geo_dir / "countries.geojson", "iso3")
    cc = pd.read_csv(GEO_SOURCES / "country_centroids.csv")
    country_centroids = {r.iso3: (float(r.lon), float(r.lat)) for r in cc.itertuples()}
    pop_2020 = dense[dense.year == 2020].set_index("iso3")["population"].to_dict()

    cities_by_country: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for iso3, grp in cities.groupby("iso3"):
        cities_by_country[iso3] = (
            grp[["lon", "lat"]].to_numpy(float), grp["population"].to_numpy(float)
        )

    world_pts = build_surface(
        polygons={k: v for k, v in country_polys.items() if k in pop_2020},
        centroids=country_centroids,
        cities_by_unit=cities_by_country,
        populations={k: float(v) for k, v in pop_2020.items()},
        total_points=7000,
    )

    # --- US states -----------------------------------------------------------
    state_polys = load_polygons(geo_dir / "us-states.geojson", "geo_id")
    state_centroids = {r.geo_id: (float(r.lon), float(r.lat)) for r in admin1_df.itertuples()}
    state_pops = {r.geo_id: float(r.population) for r in admin1_df.itertuples()}
    us_cities = cities[cities.iso3 == "USA"]
    code_to_geo = dict(zip(admin1_df["admin1_code"], admin1_df["geo_id"]))
    cities_by_state: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for code, grp in us_cities.groupby("admin1_code"):
        gid = code_to_geo.get(code)
        if gid:
            cities_by_state[gid] = (grp[["lon", "lat"]].to_numpy(float), grp["population"].to_numpy(float))

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


def _write(name: str, payload) -> Path:
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    path = WEB_DATA / name
    with open(path, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Soulfinder web data artifacts")
    ap.add_argument("--skip-density", action="store_true", help="skip the dasymetric surface (slow)")
    args = ap.parse_args()

    t0 = time.time()
    diagnostics: dict = {}

    national_series: list[dict] = []
    dense = build_national(diagnostics)

    # rebuild the national series payload (build_national returns the panel)
    national = sio.load_national_religion()
    names = national.drop_duplicates("iso3").set_index("iso3")["country"].to_dict()
    world = rollup_world(dense).sort_values("year")
    national_series.append({
        "id": "WLD", "name": "World", "level": "world",
        "shares": _round_shares(world[RELIGIONS].to_numpy()),
        "population": [round(float(p)) for p in world["population"]],
        "provenance": list(world["provenance"]),
    })
    for iso3, grp in dense.groupby("iso3"):
        grp = grp.sort_values("year")
        national_series.append({
            "id": iso3, "name": names.get(iso3, iso3), "level": "country",
            "shares": _round_shares(grp[RELIGIONS].to_numpy()),
            "population": [round(float(p)) for p in grp["population"]],
            "provenance": list(grp["provenance"]),
        })

    admin1_series, admin1_df = build_admin1(diagnostics, dense)

    if not args.skip_density:
        build_density(diagnostics, dense, admin1_df)

    _write("regions.json", {
        "years": YEARS,
        "religions": RELIGIONS,
        "labels": RELIGION_LABELS,
        "series": national_series + admin1_series,
    })

    _write("meta.json", {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "years": YEARS,
        "religions": RELIGIONS,
        "labels": RELIGION_LABELS,
        "counts": {
            "countries": sum(1 for s in national_series if s["level"] == "country"),
            "admin1": len(admin1_series),
        },
        "diagnostics": diagnostics,
    })

    v = diagnostics.get("validation", {})
    print(f"regions: {len(national_series) + len(admin1_series)} series x {len(YEARS)} years")
    print(f"IPF: max marginal error {diagnostics['ipf_diagnostics']['max_marginal_error']:.2e}")
    print(f"validation: out-of-sample TVD {v.get('tvd_model', 0):.4f} "
          f"vs national-average baseline {v.get('tvd_baseline', 0):.4f} "
          f"(skill {v.get('tvd_skill', 0):+.1%})")
    ig = diagnostics.get("instrument_gap", {})
    print(f"instrument gap at {ig.get('anchor_year')}: {ig.get('max_abs_pp', 0):.1f}pp max "
          f"(benchmarked away before raking)")
    rc = diagnostics.get("world_rollup_check", {})
    print(f"world rollup vs published 2010: max abs diff {rc.get('max_abs_diff', 0):.4f} "
          f"({'ok' if rc.get('within_tolerance') else 'OUT OF TOLERANCE'})")
    if "density" in diagnostics:
        print(f"density: {diagnostics['density']['world_points']} world + "
              f"{diagnostics['density']['us_points']} US anchors")
    print(f"done in {time.time() - t0:.1f}s -> {WEB_DATA}")


if __name__ == "__main__":
    main()
