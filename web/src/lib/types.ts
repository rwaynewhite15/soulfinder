export type Provenance = "observed" | "interpolated" | "modeled" | "synthetic";
export type Level = "world" | "country" | "admin1";

export interface RegionSeries {
  id: string;
  name: string;
  level: Level;
  /** [year][religion] share of population, rows sum to 1 */
  shares: number[][];
  /** [year] absolute population */
  population: number[];
  provenance: Provenance[];
  /** admin-1 only */
  code?: string;
  geo_id?: string;
  parent?: string;
  lo?: number[][];
  hi?: number[][];
}

export interface RegionBundle {
  years: number[];
  religions: string[];
  labels: Record<string, string>;
  series: RegionSeries[];
}

/** One dasymetric population anchor. `w` is a share of its unit's population. */
export interface DensityPoint {
  u: string;
  lon: number;
  lat: number;
  w: number;
}

export interface Meta {
  generated_at: string;
  years: number[];
  religions: string[];
  labels: Record<string, string>;
  counts: { countries: number; admin1: number };
  diagnostics: {
    validation: {
      n_units: number;
      folds: number;
      tvd_model: number;
      tvd_baseline: number;
      tvd_skill: number;
      aitchison_model: number;
      aitchison_baseline: number;
      per_religion_mae: Record<string, number>;
      worst_units: { unit: string; tvd: number; baseline_tvd: number }[];
    };
    instrument_gap: { anchor_year: number; max_abs_pp: number };
    ipf_diagnostics: { max_marginal_error: number; max_iterations: number };
    world_rollup_check: { max_abs_diff: number; within_tolerance: boolean };
  };
}
