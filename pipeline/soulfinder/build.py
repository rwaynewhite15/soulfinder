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
from .benchmark import benchmark_to_anchor, instrument_gap, population_weighted_composition
from .config import GEO_SOURCES, RELIGION_LABELS, RELIGIONS, WEB_DATA, YEARS
from .dasymetric import build_surface, load_polygons
from .downscale import COVARIATES, fit_composition_model, synthesize_admin1
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
                for y in YEARS
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Soulfinder web data artifacts")
    ap.add_argument("--skip-density", action="store_true", help="skip the dasymetric surface")
    args = ap.parse_args()

    t0 = time.time()
    diag: dict = {}

    national = sio.load_national_religion()
    population = sio.resolve_row_residual(national, sio.load_population())
    dense = densify_national(national, population)

    admin1_df, observed_mask, comps_true = load_admin1_frame()
    dense = apply_benchmark(dense, "USA", comps_true, admin1_df["population"].to_numpy(float), diag)

    admin1_series = build_admin1(diag, dense, admin1_df, observed_mask, comps_true)

    world = rollup_world(dense).sort_values("year")
    diag["world_rollup_check"] = check_world_rollup(
        world[world.year == 2010].iloc[0].to_dict(), PUBLISHED_WORLD_2010
    )

    names = national.drop_duplicates("iso3").set_index("iso3")["country"].to_dict()
    series = [{
        "id": "WLD", "name": "World", "level": "world",
        "shares": _round_shares(world[RELIGIONS].to_numpy()),
        "population": [round(float(p)) for p in world["population"]],
        "provenance": list(world["provenance"]),
    }]
    for iso3, grp in dense.groupby("iso3"):
        grp = grp.sort_values("year")
        series.append({
            "id": iso3, "name": names.get(iso3, iso3), "level": "country",
            "shares": _round_shares(grp[RELIGIONS].to_numpy()),
            "population": [round(float(p)) for p in grp["population"]],
            "provenance": list(grp["provenance"]),
        })

    if not args.skip_density:
        build_density(diag, dense, admin1_df)

    _write("regions.json", {
        "years": YEARS, "religions": RELIGIONS, "labels": RELIGION_LABELS,
        "series": series + admin1_series,
    })
    _write("meta.json", {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "years": YEARS, "religions": RELIGIONS, "labels": RELIGION_LABELS,
        "counts": {
            "countries": sum(1 for s in series if s["level"] == "country"),
            "admin1": len(admin1_series),
        },
        "diagnostics": diag,
    })

    v = diag["validation"]
    print(f"regions: {len(series) + len(admin1_series)} series x {len(YEARS)} years")
    print(f"IPF: max marginal error {diag['ipf_diagnostics']['max_marginal_error']:.2e}")
    print(f"validation: out-of-sample TVD {v['tvd_model']:.4f} vs "
          f"national-average baseline {v['tvd_baseline']:.4f} (skill {v['tvd_skill']:+.1%})")
    ig = diag["instrument_gap"]
    print(f"instrument gap for {ig['iso3']} at {ig['anchor_year']}: {ig['max_abs_pp']:.1f}pp "
          f"-> benchmarked into the canonical series")
    rc = diag["world_rollup_check"]
    print(f"world rollup vs published 2010: max abs diff {rc['max_abs_diff']:.4f} "
          f"({'ok' if rc['within_tolerance'] else 'OUT OF TOLERANCE'})")
    if "density" in diag:
        print(f"density: {diag['density']['world_points']} world + {diag['density']['us_points']} US anchors")
    print(f"done in {time.time() - t0:.1f}s -> {WEB_DATA}")


if __name__ == "__main__":
    main()
