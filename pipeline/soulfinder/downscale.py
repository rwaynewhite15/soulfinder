"""Synthesising subnational religious composition where none is published.

National religion data exists for ~200 countries. Subnational data exists for a
handful. This module produces the missing admin-1 (state / province) layer, in
four stages, each of which is a standard small-area-estimation technique rather
than a plausible-looking guess:

    1. COMPOSITIONAL REGRESSION -- learn how religious composition covaries
       with observable characteristics (urbanisation, age, education, migration)
       on the units where truth *is* available, then apply those coefficients to
       units where it is not.

    2. SPATIAL SMOOTHING -- borrow strength from neighbours, because religion is
       spatially autocorrelated and administrative borders are not walls.

    3. SHRINKAGE -- pull small units toward the national composition in
       proportion to how little population they have, so a province of 500k
       people cannot swing to an extreme on the strength of a regression
       residual.

    4. IPF -- rake the result onto the known national totals, which restores
       the source data exactly and discards whatever the model got wrong at the
       aggregate level.

Stage 4 is what makes stages 1-3 safe to ship: they shape the map, they do not
move the national numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .compositional import alr, alr_inv, clr, clr_inv, closure
from .config import N_RELIGIONS
from .ipf import ipf
from .spatial import knn_weights, smooth

COVARIATES = ["urban_share", "median_age", "bachelors_share", "foreign_born_share"]


@dataclass
class CompositionModel:
    """OLS in ALR space: one linear model per log-ratio coordinate."""

    beta: np.ndarray           # (n_features + 1, D - 1)
    mean: np.ndarray           # feature means, for standardisation
    scale: np.ndarray          # feature sds
    residual_sd: np.ndarray    # (D - 1,) residual sd per ALR coordinate
    r2: np.ndarray = field(default_factory=lambda: np.array([]))
    n_train: int = 0

    def design(self, X: np.ndarray) -> np.ndarray:
        Xs = (np.asarray(X, dtype=float) - self.mean) / self.scale
        return np.hstack([np.ones((Xs.shape[0], 1)), Xs])

    def predict(self, X: np.ndarray) -> np.ndarray:
        return alr_inv(self.design(X) @ self.beta)

    def predict_alr(self, X: np.ndarray) -> np.ndarray:
        return self.design(X) @ self.beta


def fit_composition_model(X: np.ndarray, comps: np.ndarray) -> CompositionModel:
    """Regress ALR-transformed composition on standardised covariates.

    Regressing raw shares would need one bounded model per religion plus a
    constraint tying them together; in ALR space the response is unbounded and
    ordinary least squares is valid, and the inverse transform re-imposes both
    positivity and the sum-to-one constraint for free.
    """
    X = np.asarray(X, dtype=float)
    comps = np.asarray(comps, dtype=float)
    if X.shape[0] != comps.shape[0]:
        raise ValueError("X and comps must have the same number of rows")
    if X.shape[0] <= X.shape[1] + 1:
        raise ValueError("not enough training units to fit the covariate model")

    mean = X.mean(axis=0)
    scale = X.std(axis=0)
    scale[scale == 0] = 1.0
    Xs = np.hstack([np.ones((X.shape[0], 1)), (X - mean) / scale])

    Y = alr(comps)  # (n, D-1)
    beta, *_ = np.linalg.lstsq(Xs, Y, rcond=None)
    resid = Y - Xs @ beta
    dof = max(X.shape[0] - Xs.shape[1], 1)
    residual_sd = np.sqrt((resid ** 2).sum(axis=0) / dof)

    ss_res = (resid ** 2).sum(axis=0)
    ss_tot = ((Y - Y.mean(axis=0)) ** 2).sum(axis=0)
    r2 = 1.0 - np.divide(ss_res, ss_tot, out=np.zeros_like(ss_res), where=ss_tot > 0)

    return CompositionModel(beta, mean, scale, residual_sd, r2, X.shape[0])


def shrink_to_national(
    comps: np.ndarray, national: np.ndarray, populations: np.ndarray, kappa: float | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Empirical-Bayes shrinkage of unit estimates toward the national centre.

    lambda_i = n_i / (n_i + kappa) is the usual variance-ratio weight: a unit
    with a lot of population keeps its own estimate, a small one is pulled
    toward the national composition. `kappa` defaults to the median unit
    population, which puts the half-shrinkage point at a typical-sized unit.

    Returns (shrunk compositions, lambda per unit).
    """
    pops = np.asarray(populations, dtype=float)
    if kappa is None:
        kappa = float(np.median(pops))
    lam = pops / (pops + max(kappa, 1.0))
    z = clr(comps)
    z_nat = clr(np.asarray(national, dtype=float)[None, :])
    return clr_inv(z_nat + lam[:, None] * (z - z_nat)), lam


def predictive_interval(
    model: CompositionModel, X: np.ndarray, lam: np.ndarray, draws: int = 400, seed: int = 7
) -> tuple[np.ndarray, np.ndarray]:
    """Monte-Carlo credible band for each unit's share of each religion.

    The regression's uncertainty lives in ALR space, where it is Gaussian; the
    quantity users read is a share, where it is not. Rather than propagate a
    symmetric interval through a nonlinear transform and get an interval that
    can cover negative shares, sample in ALR space, invert each draw, and take
    percentiles of the resulting shares. Shrinkage reduces the spread by the
    same lambda applied to the point estimate.
    """
    rng = np.random.default_rng(seed)
    mu = model.predict_alr(X)                      # (n, D-1)
    sd = model.residual_sd[None, :] * lam[:, None]  # shrunk units are less uncertain
    noise = rng.normal(size=(draws,) + mu.shape) * sd[None, :, :]
    samples = alr_inv(mu[None, :, :] + noise)       # (draws, n, D)
    return np.percentile(samples, 5, axis=0), np.percentile(samples, 95, axis=0)


@dataclass
class DownscaleResult:
    comps: np.ndarray            # (n_units, D) final shares
    counts: np.ndarray           # (n_units, D) people
    lo: np.ndarray               # 5th percentile shares
    hi: np.ndarray               # 95th percentile shares
    lam: np.ndarray              # shrinkage weight per unit
    ipf_iterations: int
    ipf_error: float
    ipf_kl: float
    provenance: list[str]


def synthesize_admin1(
    X: np.ndarray,
    populations: np.ndarray,
    national_comp: np.ndarray,
    national_population: float,
    model: CompositionModel,
    lats: np.ndarray,
    lons: np.ndarray,
    observed_mask: np.ndarray | None = None,
    observed_comps: np.ndarray | None = None,
    smoothing_alpha: float = 0.25,
    k_neighbours: int = 5,
) -> DownscaleResult:
    """Run the four-stage synthesis for one country-year."""
    X = np.asarray(X, dtype=float)
    pops = np.asarray(populations, dtype=float)
    n = X.shape[0]
    if observed_mask is None:
        observed_mask = np.zeros(n, dtype=bool)

    # 1. covariate model
    seed = model.predict(X)

    # Where real subnational data exists, it replaces the model outright --
    # the model is a fallback, never an override.
    if observed_comps is not None and observed_mask.any():
        seed = seed.copy()
        seed[observed_mask] = closure(np.asarray(observed_comps, dtype=float)[observed_mask])

    # 2. spatial smoothing (observed units are held fixed so real data is not
    #    blurred by its modelled neighbours)
    W = knn_weights(lats, lons, k=k_neighbours)
    smoothed = smooth(seed, W, alpha=smoothing_alpha)
    smoothed[observed_mask] = seed[observed_mask]

    # 3. shrinkage toward the national composition
    shrunk, lam = shrink_to_national(smoothed, national_comp, pops)
    shrunk[observed_mask] = seed[observed_mask]
    lam = np.where(observed_mask, 1.0, lam)

    # 4. rake onto the known marginals
    # Population is rescaled to the national control total first: the admin-1
    # populations come from a different vintage than the national projection,
    # and IPF would otherwise silently absorb that discrepancy into religion.
    pop_scaled = pops * (national_population / pops.sum())
    col_targets = np.asarray(national_comp, dtype=float) * national_population
    fitted = ipf(shrunk * pop_scaled[:, None], pop_scaled, col_targets)

    counts = fitted.matrix
    comps = closure(counts)
    lo, hi = predictive_interval(model, X, lam)
    lo[observed_mask] = comps[observed_mask]
    hi[observed_mask] = comps[observed_mask]

    provenance = ["observed" if m else "modeled" for m in observed_mask]

    return DownscaleResult(
        comps=comps,
        counts=counts,
        lo=lo,
        hi=hi,
        lam=lam,
        ipf_iterations=fitted.iterations,
        ipf_error=fitted.max_marginal_error,
        ipf_kl=fitted.kl_from_seed,
        provenance=provenance,
    )
