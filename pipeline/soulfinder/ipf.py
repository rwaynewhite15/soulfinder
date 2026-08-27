"""Iterative proportional fitting (raking).

The central guarantee of the whole synthesis. Given a seed matrix of plausible
subnational religion counts -- from a covariate model, which may be wrong --
IPF rescales rows and columns alternately until:

    row sums   == known population of each state/province   (exactly)
    column sums == known national total for each religion    (exactly)

Among all matrices satisfying both sets of marginals, the converged result is
the one minimising KL divergence from the seed (Csiszar's I-projection). In
plain terms: the model gets to decide how a religion is distributed *within* a
country, and never gets to change how large that religion is nationally. A bad
covariate model produces a badly-shaped map; it cannot produce a map that
contradicts the source data it was built from.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class IPFResult:
    matrix: np.ndarray
    iterations: int
    max_marginal_error: float
    converged: bool
    kl_from_seed: float


def ipf(
    seed: np.ndarray,
    row_targets: np.ndarray,
    col_targets: np.ndarray,
    tol: float = 1e-9,
    max_iter: int = 2000,
) -> IPFResult:
    """Rake `seed` (n_rows x n_cols) onto the given marginals."""
    seed = np.asarray(seed, dtype=float)
    row_targets = np.asarray(row_targets, dtype=float)
    col_targets = np.asarray(col_targets, dtype=float)

    if seed.ndim != 2:
        raise ValueError("seed must be 2-D")
    if seed.shape[0] != row_targets.size or seed.shape[1] != col_targets.size:
        raise ValueError(
            f"shape mismatch: seed {seed.shape} vs targets "
            f"({row_targets.size}, {col_targets.size})"
        )
    if (seed < 0).any():
        raise ValueError("seed must be non-negative")

    # IPF only converges if the two marginals agree on the grand total. They
    # come from different sources (a population table and a religion table), so
    # reconcile once up front rather than letting the iteration oscillate.
    row_sum, col_sum = row_targets.sum(), col_targets.sum()
    if row_sum <= 0 or col_sum <= 0:
        raise ValueError("marginal totals must be positive")
    col_targets = col_targets * (row_sum / col_sum)

    m = np.where(seed > 0, seed, 1e-300)
    converged = False
    it = 0
    for it in range(1, max_iter + 1):
        r = m.sum(axis=1)
        m *= np.where(r > 0, row_targets / np.where(r == 0, 1, r), 0.0)[:, None]
        c = m.sum(axis=0)
        m *= np.where(c > 0, col_targets / np.where(c == 0, 1, c), 0.0)[None, :]

        err = max(
            np.abs(m.sum(axis=1) - row_targets).max() / max(row_sum, 1),
            np.abs(m.sum(axis=0) - col_targets).max() / max(row_sum, 1),
        )
        if err < tol:
            converged = True
            break

    err = max(
        np.abs(m.sum(axis=1) - row_targets).max() / max(row_sum, 1),
        np.abs(m.sum(axis=0) - col_targets).max() / max(row_sum, 1),
    )
    return IPFResult(m, it, float(err), converged, _kl(m, seed))


def _kl(fitted: np.ndarray, seed: np.ndarray) -> float:
    """KL divergence of the fitted table from the seed, both closed to 1."""
    p = fitted / fitted.sum()
    q = np.where(seed > 0, seed, 1e-300)
    q = q / q.sum()
    mask = p > 0
    return float(np.sum(p[mask] * np.log(p[mask] / q[mask])))
