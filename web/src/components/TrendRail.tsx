import { useMemo } from "react";
import { scaleLinear } from "d3-scale";
import { line, curveMonotoneX } from "d3-shape";
import { useStore } from "../state/store";
import { categorical } from "../lib/palette";
import { pct, people, pp, signedPeople } from "../lib/format";
import { yearIndex } from "../lib/data";
import type { RegionSeries } from "../lib/types";

/**
 * One row per religion: sparkline, endpoints, and how much it moved.
 *
 * The stacked chart answers "what is this region made of"; it is genuinely bad
 * at "what is changing". A band's thickness is easy to read, its *slope* is
 * not, and small categories are invisible in it -- a religion going from 0.5%
 * to 2% quadruples and stays a hairline. So trends get their own view, where
 * every religion is on its own baseline, sorted by how far it actually moved,
 * with the numbers stated rather than estimated from geometry.
 *
 * Sparklines are individually scaled -- each to its own range over the window.
 * That is the right choice for reading *shape* (is this accelerating, flat,
 * reversing?) and the wrong one for comparing magnitudes, so the magnitudes are
 * printed as text beside every sparkline rather than left to the eye.
 */
export default function TrendRail({
  series, years, labels,
}: { series: RegionSeries; years: number[]; labels: string[] }) {
  const { window: win, visible, dark, year, setReligion, religion } = useStore();
  const colors = categorical(dark);
  const surface = dark ? "#1a1a19" : "#fcfcfb";

  const a = yearIndex(years, win[0]);
  const b = yearIndex(years, win[1]);
  const cur = yearIndex(years, year);

  const rows = useMemo(() => {
    const idx = labels.map((_, i) => i).filter((i) => visible[i]);
    return idx
      .map((ri) => {
        const from = series.shares[a]?.[ri] ?? 0;
        const to = series.shares[b]?.[ri] ?? 0;
        const pFrom = from * (series.population[a] ?? 0);
        const pTo = to * (series.population[b] ?? 0);
        const spark = series.shares.slice(a, b + 1).map((r) => r[ri] ?? 0);
        // Compound annual growth in adherents: the rate that actually drives
        // the projection, and the one figure that is comparable across
        // religions of wildly different size.
        const yrs = Math.max(1, years[b] - years[a]);
        const cagr = pFrom > 0 && pTo > 0 ? (pTo / pFrom) ** (1 / yrs) - 1 : 0;
        return { ri, from, to, pFrom, pTo, spark, cagr, dShare: to - from, dPeople: pTo - pFrom };
      })
      .sort((x, y) => Math.abs(y.dShare) - Math.abs(x.dShare));
  }, [series, labels, visible, a, b, years]);

  const W = 132, H = 26;

  return (
    <div className="rail">
      <div className="rail-head">
        <span className="rail-col-name">Religion</span>
        <span className="rail-col-spark">{years[a]} → {years[b]}</span>
        <span className="rail-col num">Share {years[a]}</span>
        <span className="rail-col num">Share {years[b]}</span>
        <span className="rail-col num">Change</span>
        <span className="rail-col num">Adherents {years[b]}</span>
        <span className="rail-col num">Growth / yr</span>
      </div>
      {rows.map((r) => {
        const lo = Math.min(...r.spark), hi = Math.max(...r.spark);
        // Pad a flat series so it draws down the middle instead of on an edge.
        const pad = hi - lo < 1e-6 ? Math.max(hi * 0.15, 1e-4) : (hi - lo) * 0.15;
        const x = scaleLinear().domain([0, r.spark.length - 1]).range([1, W - 1]);
        const y = scaleLinear().domain([lo - pad, hi + pad]).range([H - 3, 3]);
        const d = line<number>().x((_, i) => x(i)).y((v) => y(v)).curve(curveMonotoneX)(r.spark);
        const ci = Math.min(Math.max(cur - a, 0), r.spark.length - 1);
        const rising = r.dShare > 0;
        return (
          <button
            key={r.ri}
            className={`rail-row ${religion === r.ri ? "active" : ""}`}
            onClick={() => setReligion(r.ri)}
            title={`Show ${labels[r.ri]} on the map`}
          >
            <span className="rail-name">
              <span className="dot" style={{ background: colors[r.ri] }} />
              {labels[r.ri]}
            </span>
            <svg width={W} height={H} className="spark" aria-hidden="true">
              <path d={d ?? undefined} fill="none" stroke={colors[r.ri]} strokeWidth={2}
                strokeLinecap="round" strokeLinejoin="round" />
              <circle cx={x(ci)} cy={y(r.spark[ci])} r={3.5} fill={colors[r.ri]}
                stroke={surface} strokeWidth={2} />
            </svg>
            <span className="rail-col num">{pct(r.from, 1)}</span>
            <span className="rail-col num">{pct(r.to, 1)}</span>
            <span className={`rail-col num ${rising ? "up" : "down"}`}>{pp(r.dShare, 1)}</span>
            <span className="rail-col num">
              {people(r.pTo)}
              <span className={`rail-sub ${r.dPeople >= 0 ? "up" : "down"}`}>
                {signedPeople(r.dPeople)}
              </span>
            </span>
            <span className={`rail-col num ${r.cagr >= 0 ? "up" : "down"}`}>
              {(r.cagr * 100).toFixed(2)}%
            </span>
          </button>
        );
      })}
      <p className="rail-note">
        Sorted by how far each religion moved between {years[a]} and {years[b]}.
        Sparklines are each scaled to their own range — read them for shape, and
        the columns for size. “Growth / yr” is compound annual growth in
        adherents, which can be positive while share falls.
      </p>
    </div>
  );
}
