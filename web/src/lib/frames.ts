/**
 * Frame-grid helpers.
 *
 * The year axis is deliberately non-uniform: 50-year steps through antiquity,
 * annual from 2010. So `years[i]` is not `years[0] + i`, and anything that
 * assumed it -- index arithmetic, `indexOf` on an arbitrary year, rounding a
 * pixel position to a whole year -- has to go through here instead.
 */

/** Index of the frame nearest `year`. Binary search; the grid is sorted. */
export function frameIndex(years: number[], year: number): number {
  if (years.length === 0) return 0;
  let lo = 0;
  let hi = years.length - 1;
  if (year <= years[lo]) return lo;
  if (year >= years[hi]) return hi;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (years[mid] === year) return mid;
    if (years[mid] < year) lo = mid;
    else hi = mid;
  }
  return year - years[lo] <= years[hi] - year ? lo : hi;
}

/** Snap an arbitrary year to the nearest frame that actually has data. */
export function snapToFrame(years: number[], year: number): number {
  return years[frameIndex(years, year)];
}

/** Step `delta` frames from `year`, clamped to [lo, hi] in year terms. */
export function stepFrame(
  years: number[], year: number, delta: number, lo: number, hi: number
): number {
  const loI = frameIndex(years, lo);
  const hiI = frameIndex(years, hi);
  const i = Math.min(Math.max(frameIndex(years, year) + delta, loI), hiI);
  return years[i];
}

/** Advance one frame, wrapping to the start of the window. Used by the loop. */
export function nextFrameLooping(years: number[], year: number, lo: number, hi: number): number {
  const hiI = frameIndex(years, hi);
  const i = frameIndex(years, year);
  return i >= hiI ? years[frameIndex(years, lo)] : years[i + 1];
}

/**
 * Label a year for display.
 *
 * Bare "0" or "300" reads as an axis number rather than a date, which matters
 * once the range starts in antiquity. Four-digit years need no help.
 */
export function formatYear(year: number): string {
  return year < 1000 ? `AD ${year}` : String(year);
}

/** Compact form for dense axis ticks. */
export function formatYearShort(year: number): string {
  return year < 1000 ? `${year}` : String(year);
}
