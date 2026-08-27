"""Spatial weights and smoothing over the admin-1 adjacency graph."""
from __future__ import annotations

import numpy as np

from .compositional import clr, clr_inv

EARTH_RADIUS_KM = 6371.0


def haversine_matrix(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Great-circle distance (km) between every pair of centroids."""
    lat = np.radians(np.asarray(lats, dtype=float))
    lon = np.radians(np.asarray(lons, dtype=float))
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    a = np.sin(dlat / 2) ** 2 + np.cos(lat)[:, None] * np.cos(lat)[None, :] * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def knn_weights(lats: np.ndarray, lons: np.ndarray, k: int = 5) -> np.ndarray:
    """Row-standardised k-nearest-neighbour spatial weights.

    Contiguity (shared-border) weights would be the textbook choice, but they
    strand islands -- Hawaii and Alaska get no neighbours at all and drop out
    of the smoother. KNN weights keep every unit connected, which matters more
    here than the exact definition of adjacency.
    """
    d = haversine_matrix(lats, lons)
    n = d.shape[0]
    np.fill_diagonal(d, np.inf)
    k = min(k, n - 1)
    w = np.zeros((n, n))
    idx = np.argsort(d, axis=1)[:, :k]
    rows = np.repeat(np.arange(n), k)
    w[rows, idx.ravel()] = 1.0
    w = (w + w.T) / 2.0  # symmetrise: neighbourliness should be mutual
    rs = w.sum(axis=1, keepdims=True)
    return np.divide(w, rs, out=np.zeros_like(w), where=rs > 0)


def smooth(comps: np.ndarray, weights: np.ndarray, alpha: float = 0.25, iterations: int = 2) -> np.ndarray:
    """Laplacian smoothing of compositions over the spatial graph.

    A lightweight stand-in for an intrinsic conditional autoregressive (ICAR)
    prior: religion does not respect administrative boundaries, so a state's
    estimate should borrow strength from its neighbours. `alpha` is how far each
    unit moves toward its neighbours' compositional centre per pass. Done in CLR
    space so the result is a valid composition, and so "averaging" means the
    geometric mean rather than the arithmetic one.
    """
    z = clr(comps)
    for _ in range(iterations):
        z = (1 - alpha) * z + alpha * (weights @ z)
    return clr_inv(z)
