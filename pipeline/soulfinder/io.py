"""Source loaders. Every loader returns tidy frames with validated schemas."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .compositional import closure
from .config import RELIGIONS, SOURCES


def _read_csv(name: str) -> pd.DataFrame:
    """Read a source CSV, skipping the leading `#` provenance header block."""
    path = SOURCES / name
    if not path.exists():
        raise FileNotFoundError(f"missing source file: {path}")
    return pd.read_csv(path, comment="#")


def load_national_religion() -> pd.DataFrame:
    """Long frame: iso3, country, year, <religion shares summing to 1>."""
    df = _read_csv("national_religion.csv")
    missing = [c for c in RELIGIONS if c not in df.columns]
    if missing:
        raise ValueError(f"national_religion.csv missing columns: {missing}")
    df[RELIGIONS] = df[RELIGIONS].fillna(0.0)
    # Source is in percent and rounded, so rows rarely sum to exactly 100.
    # Closing the rows here is the whole correction -- no per-part fudging.
    df[RELIGIONS] = closure(df[RELIGIONS].to_numpy(dtype=float))
    return df.sort_values(["iso3", "year"]).reset_index(drop=True)


def load_population() -> pd.DataFrame:
    """Long frame: iso3, year, population (absolute people)."""
    df = _read_csv("country_population.csv")
    df["population"] = df["population_millions"].astype(float) * 1e6
    return df[["iso3", "year", "population"]].sort_values(["iso3", "year"]).reset_index(drop=True)


def load_admin1_covariates() -> pd.DataFrame:
    df = _read_csv("admin1_covariates.csv")
    df["population"] = df["population_millions"].astype(float) * 1e6
    df["geo_id"] = df["geo_id"].astype(str).str.zfill(2)
    return df.reset_index(drop=True)


def load_admin1_observed() -> pd.DataFrame:
    df = _read_csv("admin1_religion_observed.csv")
    df[RELIGIONS] = df[RELIGIONS].fillna(0.0)
    df[RELIGIONS] = closure(df[RELIGIONS].to_numpy(dtype=float))
    return df.reset_index(drop=True)


def load_cities() -> pd.DataFrame:
    """Real city coordinates. These anchor the dasymetric density field."""
    df = _read_csv("cities.csv")
    df["population"] = df["population_millions"].astype(float) * 1e6
    return df.reset_index(drop=True)


def resolve_row_residual(
    national: pd.DataFrame, population: pd.DataFrame, world_code: str = "WLD", row_code: str = "ROW"
) -> pd.DataFrame:
    """Derive the rest-of-world population as `world total - sum(countries)`.

    The seed table covers ~50 countries, roughly 80% of world population. Rather
    than pretend that is the world, the remainder is carried explicitly as one
    residual region so that the world rollup reconciles to the published world
    total by construction instead of by luck.
    """
    pop = population.copy()
    world = pop[pop.iso3 == world_code].set_index("year")["population"]
    named = pop[~pop.iso3.isin([world_code, row_code])]
    covered = named.groupby("year")["population"].sum()

    rows = []
    for year, total in world.items():
        residual = float(total) - float(covered.get(year, 0.0))
        if residual < 0:
            raise ValueError(
                f"country populations for {year} exceed the world control total "
                f"by {-residual:,.0f}; check country_population.csv"
            )
        rows.append({"iso3": row_code, "year": int(year), "population": residual})

    out = pd.concat([named, pd.DataFrame(rows)], ignore_index=True)
    return out.sort_values(["iso3", "year"]).reset_index(drop=True)


def composition_matrix(df: pd.DataFrame) -> np.ndarray:
    """Extract the religion columns as an (n, D) array in canonical order."""
    return df[RELIGIONS].to_numpy(dtype=float)
