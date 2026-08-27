"""Compositional-data primitives.

Religious composition is compositional data: a vector of strictly positive
parts carrying only *relative* information, constrained to a fixed total. The
usual Euclidean operations are invalid on the simplex -- interpolating two
compositions componentwise can leave the simplex, and ordinary regression on
raw shares happily predicts negative percentages that then have to be clipped,
which silently destroys the constant-sum constraint.

Everything downstream (interpolation, regression, smoothing, shrinkage) is
therefore done in log-ratio coordinates, where the simplex becomes a real
vector space, and mapped back at the end. Aitchison (1986) is the reference.
"""
from __future__ import annotations

import numpy as np

from .config import ZERO_REPLACEMENT


def closure(x: np.ndarray, total: float = 1.0) -> np.ndarray:
    """Rescale the last axis so it sums to `total` (the closure operator, C)."""
    x = np.asarray(x, dtype=float)
    s = x.sum(axis=-1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(s > 0, x / np.where(s == 0, 1.0, s), 0.0)
    return out * total


def replace_zeros(p: np.ndarray, delta: float = ZERO_REPLACEMENT) -> np.ndarray:
    """Multiplicative replacement of rounded zeros (Martin-Fernandez et al.).

    Zeros are replaced with `delta` and the *non-zero* parts are scaled down by
    (1 - n_zero * delta) so the composition still sums to one and, critically,
    the ratios among the observed parts are preserved. Naively adding a
    constant to every part would distort exactly those ratios, which are the
    only thing a compositional analysis is allowed to depend on.
    """
    p = closure(np.asarray(p, dtype=float))
    zeros = p <= 0
    n_zero = zeros.sum(axis=-1, keepdims=True)
    if not zeros.any():
        return p
    keep_scale = 1.0 - n_zero * delta
    out = np.where(zeros, delta, p * keep_scale)
    return closure(out)


def alr(p: np.ndarray, ref: int = -1) -> np.ndarray:
    """Additive log-ratio. Maps the D-simplex to R^(D-1) against a reference part."""
    p = replace_zeros(p)
    ref_part = np.take(p, [ref], axis=-1)
    idx = [i for i in range(p.shape[-1]) if i % p.shape[-1] != ref % p.shape[-1]]
    return np.log(np.take(p, idx, axis=-1) / ref_part)


def alr_inv(y: np.ndarray, ref: int = -1) -> np.ndarray:
    """Inverse ALR (a softmax with an implicit zero for the reference part)."""
    y = np.asarray(y, dtype=float)
    d = y.shape[-1] + 1
    ref_i = ref % d
    full = np.concatenate(
        [y[..., :ref_i], np.zeros(y.shape[:-1] + (1,)), y[..., ref_i:]], axis=-1
    )
    full = full - full.max(axis=-1, keepdims=True)  # overflow guard
    e = np.exp(full)
    return closure(e)


def clr(p: np.ndarray) -> np.ndarray:
    """Centred log-ratio. Symmetric in the parts; sums to zero along the last axis."""
    p = replace_zeros(p)
    log_p = np.log(p)
    return log_p - log_p.mean(axis=-1, keepdims=True)


def clr_inv(z: np.ndarray) -> np.ndarray:
    z = np.asarray(z, dtype=float)
    z = z - z.max(axis=-1, keepdims=True)
    return closure(np.exp(z))


def perturb(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Compositional addition: the simplex's group operation."""
    return closure(replace_zeros(p) * replace_zeros(q))


def power(p: np.ndarray, a: float) -> np.ndarray:
    """Compositional scalar multiplication."""
    return closure(replace_zeros(p) ** a)


def aitchison_distance(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Distance on the simplex. The metric error should be reported in.

    Euclidean distance between share vectors treats a 0.1 -> 0.2 change and a
    0.5 -> 0.6 change as identical. They are not: the first doubles a group,
    the second grows it by a fifth. Aitchison distance is the CLR-space
    Euclidean distance, so it measures relative change and is invariant to
    which parts you happen to have grouped together.
    """
    return np.linalg.norm(clr(p) - clr(q), axis=-1)


def total_variation_distance(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Half the L1 distance. Interpretable as "share of people misassigned"."""
    p = closure(np.asarray(p, dtype=float))
    q = closure(np.asarray(q, dtype=float))
    return 0.5 * np.abs(p - q).sum(axis=-1)


def geometric_mean_composition(p: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    """The compositional centre (closed geometric mean), optionally weighted.

    This is the correct notion of "average composition"; the arithmetic mean of
    shares is biased toward whichever parts happen to be large.
    """
    z = clr(p)
    if weights is None:
        zbar = z.mean(axis=0)
    else:
        w = np.asarray(weights, dtype=float)
        w = w / w.sum()
        zbar = (z * w[:, None]).sum(axis=0)
    return clr_inv(zbar)
