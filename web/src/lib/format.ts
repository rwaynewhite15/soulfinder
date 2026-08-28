export function pct(x: number, digits = 1): string {
  return `${(x * 100).toFixed(digits)}%`;
}

export function pp(x: number, digits = 1): string {
  const v = x * 100;
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)} pp`;
}

export function people(n: number): string {
  const a = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (a >= 1e9) return `${sign}${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${sign}${(a / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${sign}${(a / 1e3).toFixed(0)}K`;
  return `${sign}${Math.round(a)}`;
}

export function signedPeople(n: number): string {
  return `${n >= 0 ? "+" : "−"}${people(Math.abs(n))}`;
}

export const PROVENANCE_LABEL: Record<string, string> = {
  observed: "Observed",
  interpolated: "Interpolated",
  modeled: "Modeled",
  synthetic: "Synthetic",
  historical: "Historical estimate",
};

export const PROVENANCE_NOTE: Record<string, string> = {
  observed: "Reported directly by the source survey for this unit and year.",
  interpolated: "Between two reported years, interpolated along the source trend.",
  modeled: "Reported for this unit in one year, carried across years by the national trend.",
  synthetic: "No subnational survey for this unit. Estimated from covariates, then raked to the national total.",
  historical:
    "Pre-modern reconstruction. Estimated for a macro-region from fragmentary evidence, then mapped onto modern borders that did not exist at the time. Read it as a rough shape, never as a measurement.",
};
