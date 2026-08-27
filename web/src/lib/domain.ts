import type { RegionSeries } from "./types";
import { change } from "./data";

export interface ColorDomain { maxShare: number; maxDelta: number; }

/**
 * Fixed colour domains, computed once over every region and every year.
 *
 * The alternative -- rescaling per frame so the current year always uses the
 * full ramp -- makes the year slider lie: a region whose share never moves
 * would still change colour as its neighbours moved around it. Holding the
 * domain fixed means every colour change on the map is a change in the data.
 */
export function colorDomain(
  pool: RegionSeries[],
  religion: number,
  nYears: number,
  changeBasis: "share" | "people",
  baseIdx: number
): ColorDomain {
  let maxShare = 0;
  let maxDelta = 0;
  for (const s of pool) {
    for (let i = 0; i < nYears; i++) {
      maxShare = Math.max(maxShare, s.shares[i]?.[religion] ?? 0);
      maxDelta = Math.max(maxDelta, Math.abs(change(s, baseIdx, i, religion, changeBasis)));
    }
  }
  return { maxShare: Math.max(maxShare, 1e-6), maxDelta: Math.max(maxDelta, 1e-9) };
}
