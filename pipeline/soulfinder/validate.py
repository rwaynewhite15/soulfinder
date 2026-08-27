"""Does the synthesis actually beat the obvious alternative?

Synthetic subnational religion data is only defensible if you can show what it
costs you. The obvious alternative -- "assume every state looks like the
national average" -- is free, so the model has to beat it by enough to justify
the extra assumptions.

The US is the only country here with observed admin-1 composition, so it is the
test bed. K-fold cross-validation hides a fold's states, fits the covariate
model on the rest, runs the full four-stage synthesis, and scores the hidden
states against truth. Every number this reports is an out-of-sample number.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

from .compositional import aitchison_distance, total_variation_distance
from .config import RELIGIONS
from .downscale import COVARIATES, fit_composition_model, synthesize_admin1


@dataclass
class ValidationReport:
    n_units: int
    folds: int
    aitchison_model: float
    aitchison_baseline: float
    tvd_model: float
    tvd_baseline: float
    tvd_skill: float          # fraction of baseline error removed
    worst_units: list[dict]
    per_religion_mae: dict[str, float]
    model_r2: dict[str, float]

    def to_dict(self) -> dict:
        return asdict(self)


def cross_validate(
    X: np.ndarray,
    comps_true: np.ndarray,
    populations: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
    unit_names: list[str],
    national_comp: np.ndarray,
    national_population: float,
    folds: int = 5,
    seed: int = 3,
) -> ValidationReport:
    n = X.shape[0]
    rng = np.random.default_rng(seed)
    order = rng.permutation(n)
    fold_id = np.zeros(n, dtype=int)
    fold_id[order] = np.arange(n) % folds

    pred = np.zeros_like(comps_true)

    for f in range(folds):
        test = fold_id == f
        train = ~test
        model = fit_composition_model(X[train], comps_true[train])
        # The held-out states enter the synthesis exactly as an unmeasured
        # country's provinces would: no observed values, only covariates.
        res = synthesize_admin1(
            X=X,
            populations=populations,
            national_comp=national_comp,
            national_population=national_population,
            model=model,
            lats=lats,
            lons=lons,
            observed_mask=train,
            observed_comps=comps_true,
        )
        pred[test] = res.comps[test]

    baseline = np.repeat(national_comp[None, :], n, axis=0)

    ait_m = aitchison_distance(pred, comps_true)
    ait_b = aitchison_distance(baseline, comps_true)
    tvd_m = total_variation_distance(pred, comps_true)
    tvd_b = total_variation_distance(baseline, comps_true)

    worst_idx = np.argsort(-tvd_m)[:5]
    worst = [
        {"unit": unit_names[i], "tvd": float(tvd_m[i]), "baseline_tvd": float(tvd_b[i])}
        for i in worst_idx
    ]

    mae = {r: float(np.abs(pred[:, j] - comps_true[:, j]).mean()) for j, r in enumerate(RELIGIONS)}
    full_model = fit_composition_model(X, comps_true)
    r2 = {f"alr_{i}": float(v) for i, v in enumerate(full_model.r2)}

    return ValidationReport(
        n_units=n,
        folds=folds,
        aitchison_model=float(ait_m.mean()),
        aitchison_baseline=float(ait_b.mean()),
        tvd_model=float(tvd_m.mean()),
        tvd_baseline=float(tvd_b.mean()),
        tvd_skill=float(1 - tvd_m.mean() / tvd_b.mean()) if tvd_b.mean() > 0 else 0.0,
        worst_units=worst,
        per_religion_mae=mae,
        model_r2=r2,
    )


def check_world_rollup(world_row: dict, published: dict, tolerance: float = 0.03) -> dict:
    """Compare the derived world composition against published world figures.

    A large gap means the country panel and the published world total disagree
    -- most likely the countries in the seed do not add up to the world, or the
    rest-of-world residual is mis-specified. Worth surfacing rather than hiding.
    """
    diffs = {k: float(world_row.get(k, 0.0) - v) for k, v in published.items()}
    worst = max(diffs.items(), key=lambda kv: abs(kv[1])) if diffs else ("", 0.0)
    return {
        "diffs": diffs,
        "max_abs_diff": abs(worst[1]),
        "worst_category": worst[0],
        "within_tolerance": abs(worst[1]) <= tolerance,
        "tolerance": tolerance,
    }
