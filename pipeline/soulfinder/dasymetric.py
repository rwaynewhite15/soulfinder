"""Dasymetric allocation: turning polygon totals into a population surface.

A choropleth of admin-1 polygons asserts something false -- that Nevada's
religious composition is spread evenly across Nevada, including the 80% of it
nobody lives in. Dasymetric mapping fixes this by redistributing each unit's
totals onto a surface weighted by where people actually are, so the heat map
tracks population rather than administrative geometry.

Production pipelines use a gridded population raster (WorldPop, GHS-POP, Meta
HRSL) as the weighting layer. This module builds an equivalent surface from
real metropolitan coordinates: a Gaussian mixture centred on actual cities,
scaled by metro population, plus a diffuse rural component, all masked to the
unit's true polygon by a point-in-polygon test. The city coordinates are real;
the surface between them is synthetic and is flagged as such everywhere it
surfaces in the UI.

The output weights are deliberately time-invariant. A point carries "this
fraction of the unit's people live here", and the app multiplies that by the
unit's population and composition for whichever year the slider is on. That
keeps one small file serving all 41 years instead of 41 files, and makes
scrubbing the year slider a multiply rather than a fetch.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

KM_PER_DEG = 111.0


def load_polygons(geojson_path: Path, key: str) -> dict[str, list[np.ndarray]]:
    """Read a GeoJSON file into {feature key: [exterior rings as (n,2) arrays]}."""
    with open(geojson_path) as fh:
        gj = json.load(fh)
    out: dict[str, list[np.ndarray]] = {}
    for feat in gj["features"]:
        k = feat.get("properties", {}).get(key)
        if k is None:
            continue
        geom = feat["geometry"]
        if geom is None:
            continue
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        rings = [np.asarray(p[0], dtype=float) for p in polys if p and len(p[0]) >= 4]
        if rings:
            out[str(k)] = rings
    return out


def points_in_rings(pts: np.ndarray, rings: list[np.ndarray]) -> np.ndarray:
    """Ray-casting point-in-polygon, vectorised over points, looped over rings.

    A point inside any exterior ring counts as inside the unit. Interior rings
    (holes) are ignored -- at the resolution of national and state boundaries
    they cover a negligible share of population and cost a lot of geometry.
    """
    inside = np.zeros(len(pts), dtype=bool)
    px, py = pts[:, 0], pts[:, 1]
    for ring in rings:
        x, y = ring[:, 0], ring[:, 1]
        x1, y1 = np.roll(x, 1), np.roll(y, 1)
        hit = np.zeros(len(pts), dtype=bool)
        for i in range(len(x)):
            cond = (y[i] > py) != (y1[i] > py)
            if not cond.any():
                continue
            denom = y1[i] - y[i]
            if denom == 0:
                continue
            xint = (x1[i] - x[i]) * (py - y[i]) / denom + x[i]
            hit ^= cond & (px < xint)
        inside |= hit
    return inside


def _safe_bbox(rings: list[np.ndarray], centroid_lon: float) -> tuple[float, float, float, float]:
    """Bounding box, with an antimeridian guard.

    Alaska and Russia straddle 180 degrees, so a naive bbox spans the entire
    globe and rejection sampling collapses to a near-zero hit rate. When that
    happens, keep only the lobe on the same side of the antimeridian as the
    centroid; the discarded lobe is small in every case here.
    """
    all_pts = np.vstack(rings)
    lon, lat = all_pts[:, 0], all_pts[:, 1]
    if lon.max() - lon.min() > 180:
        side = lon >= 0 if centroid_lon >= 0 else lon < 0
        # Keep the lobe only if it is a real share of the outline; a proportional
        # threshold rather than an absolute vertex count, so the guard works on
        # coarse geometry as well as detailed coastlines.
        if side.sum() >= max(3, int(0.2 * len(lon))):
            lon, lat = lon[side], lat[side]
    return float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max())


def density_at(pts: np.ndarray, cities: np.ndarray, city_pop: np.ndarray, sigma_km: np.ndarray) -> np.ndarray:
    """Evaluate the population-density surface at `pts`.

    Sum of city kernels plus a flat rural floor. The floor is what keeps rural
    population from vanishing entirely: without it every person in a state ends
    up stacked on its largest metro, which is as wrong as spreading them evenly.
    """
    if len(cities) == 0:
        return np.ones(len(pts))
    d_lon = (pts[:, None, 0] - cities[None, :, 0]) * np.cos(np.radians(pts[:, None, 1]))
    d_lat = pts[:, None, 1] - cities[None, :, 1]
    dist_km = np.sqrt(d_lon ** 2 + d_lat ** 2) * KM_PER_DEG
    kernel = np.exp(-0.5 * (dist_km / sigma_km[None, :]) ** 2)
    urban = (kernel * city_pop[None, :]).sum(axis=1)
    return urban + 0.06 * city_pop.sum()


def sigma_for_population(pop: np.ndarray) -> np.ndarray:
    """Metro footprint radius. Bigger cities sprawl further, sub-linearly."""
    return 12.0 + 26.0 * np.sqrt(np.maximum(pop, 1e5) / 1e6)


def allocate_unit(
    rings: list[np.ndarray],
    centroid: tuple[float, float],
    cities_lonlat: np.ndarray,
    cities_pop: np.ndarray,
    n_points: int,
    rng: np.random.Generator,
    oversample: int = 40,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample `n_points` weighted population anchors inside one admin unit.

    Returns (points (n,2) lon/lat, weights summing to 1).
    """
    min_lon, min_lat, max_lon, max_lat = _safe_bbox(rings, centroid[0])
    sigma = sigma_for_population(cities_pop) if len(cities_pop) else np.array([])

    kept_pts: list[np.ndarray] = []
    budget = n_points * oversample
    # Latitude is sampled in sin-space so that samples are uniform per unit of
    # surface area rather than per degree, which would over-weight the poles.
    sin_lo, sin_hi = np.sin(np.radians([min_lat, max_lat]))
    for _ in range(6):
        if sum(len(p) for p in kept_pts) >= n_points * 3:
            break
        cand = np.column_stack([
            rng.uniform(min_lon, max_lon, budget),
            np.degrees(np.arcsin(rng.uniform(sin_lo, sin_hi, budget))),
        ])
        kept_pts.append(cand[points_in_rings(cand, rings)])

    pts = np.vstack(kept_pts) if kept_pts else np.empty((0, 2))
    if len(pts) == 0:  # degenerate sliver: fall back to the centroid
        return np.array([centroid]), np.array([1.0])

    dens = density_at(pts, cities_lonlat, cities_pop, sigma) if len(cities_pop) else np.ones(len(pts))
    # Draw the final anchors *proportional to density* rather than keeping the
    # densest candidates, so rural areas stay represented and the surface is a
    # sample of the population distribution instead of a picture of its peaks.
    p = dens / dens.sum()
    take = min(n_points, len(pts))
    idx = rng.choice(len(pts), size=take, replace=False, p=p)
    chosen, w = pts[idx], dens[idx]
    return chosen, w / w.sum()


def build_surface(
    polygons: dict[str, list[np.ndarray]],
    centroids: dict[str, tuple[float, float]],
    cities_by_unit: dict[str, tuple[np.ndarray, np.ndarray]],
    populations: dict[str, float],
    total_points: int = 9000,
    min_points: int = 12,
    max_points: int = 320,
    seed: int = 11,
) -> list[dict]:
    """Build the whole dasymetric point cloud, one unit at a time.

    Points per unit scale with sqrt(population): a linear split would give
    California 50x the anchors of Wyoming and leave small states as single
    dots, while sqrt keeps small units legible without flattening the
    difference entirely.
    """
    rng = np.random.default_rng(seed)
    units = [u for u in polygons if u in populations and populations[u] > 0]
    if not units:
        return []
    weights = np.array([np.sqrt(populations[u]) for u in units])
    alloc = np.clip((weights / weights.sum() * total_points).astype(int), min_points, max_points)

    out: list[dict] = []
    for unit, n in zip(units, alloc):
        cl, cp = cities_by_unit.get(unit, (np.empty((0, 2)), np.empty(0)))
        pts, w = allocate_unit(polygons[unit], centroids[unit], cl, cp, int(n), rng)
        for (lon, lat), weight in zip(pts, w):
            out.append({
                "u": unit,
                "lon": round(float(lon), 3),
                "lat": round(float(lat), 3),
                "w": round(float(weight), 6),
            })
    return out
