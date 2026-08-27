import { useMemo, useRef, useState } from "react";
import { scaleLinear } from "d3-scale";
import { area, line, stack, stackOrderNone, stackOffsetNone, curveMonotoneX } from "d3-shape";
import { useStore } from "../state/store";
import { categorical } from "../lib/palette";
import { pct, people } from "../lib/format";
import type { RegionSeries } from "../lib/types";

const M = { top: 16, right: 128, bottom: 30, left: 52 };

interface Props {
  series: RegionSeries;
  years: number[];
  labels: string[];
  width: number;
  height: number;
}

export default function TimeSeries({ series, years, labels, width, height }: Props) {
  const { window: win, year, visible, chartMode, dark, setYear } = useStore();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverYear, setHoverYear] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);

  const colors = categorical(dark);
  const iw = Math.max(10, width - M.left - M.right);
  const ih = Math.max(10, height - M.top - M.bottom);

  const inWindow = useMemo(
    () => years.map((y, i) => ({ y, i })).filter((d) => d.y >= win[0] && d.y <= win[1]),
    [years, win]
  );

  const x = useMemo(
    () => scaleLinear().domain([win[0], win[1]]).range([0, iw]),
    [win, iw]
  );

  // Stacked bands are built over the canonical religion order and merely
  // *filtered* by visibility, never re-sorted. Sorting by size would repaint
  // every band whenever the year changed, which breaks the one rule that makes
  // a stacked chart readable: colour identifies the religion, not its rank.
  const shownIdx = useMemo(
    () => labels.map((_, i) => i).filter((i) => visible[i]),
    [labels, visible]
  );

  const rows = useMemo(
    () => inWindow.map(({ y, i }) => {
      const row: Record<string, number> = { year: y };
      shownIdx.forEach((ri) => { row[String(ri)] = series.shares[i]?.[ri] ?? 0; });
      return row;
    }),
    [inWindow, shownIdx, series]
  );

  const stacked = useMemo(() => {
    if (chartMode !== "stack") return null;
    return stack<Record<string, number>>()
      .keys(shownIdx.map(String))
      .order(stackOrderNone)
      .offset(stackOffsetNone)(rows);
  }, [rows, shownIdx, chartMode]);

  const yMax = useMemo(() => {
    if (chartMode === "stack") {
      return Math.max(0.05, ...rows.map((r) => shownIdx.reduce((s, ri) => s + r[String(ri)], 0)));
    }
    return Math.max(0.02, ...rows.flatMap((r) => shownIdx.map((ri) => r[String(ri)])));
  }, [rows, shownIdx, chartMode]);

  const y = useMemo(
    // In stack mode the parts sum to exactly 1, so the axis is pinned to
    // [0, 1]. Letting .nice() round the domain up to 1.2 would leave a fifth of
    // the plot empty and imply the total varies, which it cannot.
    () => (chartMode === "stack"
      ? scaleLinear().domain([0, 1]).range([ih, 0])
      : scaleLinear().domain([0, yMax]).nice(5).range([ih, 0])),
    [yMax, ih, chartMode]
  );

  const areaGen = useMemo(
    () => area<[number, number] & { data: Record<string, number> }>()
      .x((d) => x(d.data.year))
      .y0((d) => y(d[0]))
      .y1((d) => y(d[1]))
      .curve(curveMonotoneX),
    [x, y]
  );

  const lineGen = useMemo(
    () => line<{ year: number; v: number }>()
      .x((d) => x(d.year))
      .y((d) => y(d.v))
      .curve(curveMonotoneX),
    [x, y]
  );

  const yearFromEvent = (clientX: number): number => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return year;
    const px = clientX - rect.left - M.left;
    const raw = x.invert(Math.max(0, Math.min(iw, px)));
    return Math.max(win[0], Math.min(win[1], Math.round(raw)));
  };

  const activeYear = hoverYear ?? year;
  const activeIdx = years.indexOf(activeYear);
  const surface = dark ? "#1a1a19" : "#fcfcfb";

  /** Direct labels: only where a band is thick enough to hold text without collision. */
  const endLabels = useMemo(() => {
    const last = rows[rows.length - 1];
    if (!last) return [];
    const out: { ri: number; yPos: number; text: string; v: number }[] = [];
    if (chartMode === "stack" && stacked) {
      stacked.forEach((band, k) => {
        const seg = band[band.length - 1];
        const h = Math.abs(y(seg[0]) - y(seg[1]));
        if (h < 13) return;
        out.push({
          ri: shownIdx[k],
          yPos: (y(seg[0]) + y(seg[1])) / 2,
          text: labels[shownIdx[k]],
          v: last[String(shownIdx[k])],
        });
      });
    } else {
      shownIdx.forEach((ri) => out.push({
        ri, yPos: y(last[String(ri)]), text: labels[ri], v: last[String(ri)],
      }));
      out.sort((a, b) => a.yPos - b.yPos);
      // Nudge apart so end labels never overlap, then push back up from the
      // bottom: nudging alone walks the last labels off the plot when several
      // near-zero series converge on the axis.
      for (let i = 1; i < out.length; i++) {
        if (out[i].yPos - out[i - 1].yPos < 12) out[i].yPos = out[i - 1].yPos + 12;
      }
      for (let i = out.length - 1; i > 0; i--) {
        if (out[i].yPos > ih) out[i].yPos = ih;
        if (out[i].yPos - out[i - 1].yPos < 12) out[i - 1].yPos = out[i].yPos - 12;
      }
    }
    return out;
  }, [rows, stacked, shownIdx, labels, y, chartMode, ih]);

  return (
    <svg
      ref={svgRef}
      width={width}
      height={height}
      role="img"
      aria-label={`Religious composition of ${series.name}, ${win[0]} to ${win[1]}`}
      style={{ display: "block", cursor: dragging ? "grabbing" : "crosshair", touchAction: "none" }}
      onPointerMove={(e) => {
        const yr = yearFromEvent(e.clientX);
        setHoverYear(yr);
        if (dragging) setYear(yr);
      }}
      onPointerLeave={() => { setHoverYear(null); setDragging(false); }}
      onPointerDown={(e) => {
        (e.target as Element).setPointerCapture?.(e.pointerId);
        setDragging(true);
        setYear(yearFromEvent(e.clientX));
      }}
      onPointerUp={() => setDragging(false)}
    >
      <g transform={`translate(${M.left},${M.top})`}>
        {y.ticks(5).map((t) => (
          <g key={t} transform={`translate(0,${y(t)})`}>
            <line x2={iw} className="grid" />
            <text x={-8} dy="0.32em" textAnchor="end" className="tick">{pct(t, 0)}</text>
          </g>
        ))}

        {x.ticks(Math.min(9, Math.max(2, Math.round(iw / 70)))).map((t) => (
          <text key={t} x={x(t)} y={ih + 20} textAnchor="middle" className="tick">{t}</text>
        ))}

        {chartMode === "stack" && stacked
          ? stacked.map((band, k) => (
              <path
                key={shownIdx[k]}
                d={areaGen(band as never) ?? undefined}
                fill={colors[shownIdx[k]]}
                // 2px surface-coloured seam between adjacent fills, so bands stay
                // separable when neighbouring hues are close for CVD readers.
                stroke={surface}
                strokeWidth={2}
              />
            ))
          : shownIdx.map((ri) => (
              <path
                key={ri}
                d={lineGen(rows.map((r) => ({ year: r.year, v: r[String(ri)] }))) ?? undefined}
                fill="none"
                stroke={colors[ri]}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}

        {endLabels.map((l) => (
          <text
            key={l.ri}
            x={iw + 8}
            y={l.yPos}
            dy="0.32em"
            className="end-label"
          >
            <tspan className="end-swatch" fill={colors[l.ri]}>■ </tspan>
            {l.text} <tspan className="end-value">{pct(l.v, 1)}</tspan>
          </text>
        ))}

        {activeIdx >= 0 && activeYear >= win[0] && activeYear <= win[1] && (
          <g className="playhead" transform={`translate(${x(activeYear)},0)`}>
            <line y2={ih} />
            {shownIdx.map((ri) => {
              const v = series.shares[activeIdx]?.[ri] ?? 0;
              let cy: number;
              if (chartMode === "stack" && stacked) {
                const k = shownIdx.indexOf(ri);
                const row = stacked[k]?.[rows.findIndex((r) => r.year === activeYear)];
                if (!row) return null;
                cy = (y(row[0]) + y(row[1])) / 2;
                if (Math.abs(y(row[0]) - y(row[1])) < 8) return null;
              } else {
                cy = y(v);
              }
              return (
                <circle
                  key={ri}
                  cy={cy}
                  r={4}
                  fill={colors[ri]}
                  // 2px surface ring keeps overlapping markers distinguishable
                  stroke={surface}
                  strokeWidth={2}
                />
              );
            })}
          </g>
        )}
      </g>
      {hoverYear !== null && (
      <Tooltip
        series={series}
        yearIdx={activeIdx}
        year={activeYear}
        labels={labels}
        colors={colors}
        shownIdx={shownIdx}
        x={M.left + x(activeYear)}
        width={width}
        height={height}
      />
      )}
    </svg>
  );
}

function Tooltip({
  series, yearIdx, year, labels, colors, shownIdx, x, width, height,
}: {
  series: RegionSeries; yearIdx: number; year: number; labels: string[];
  colors: string[]; shownIdx: number[]; x: number; width: number; height: number;
}) {
  if (yearIdx < 0) return null;
  const rows = shownIdx
    .map((ri) => ({ ri, v: series.shares[yearIdx]?.[ri] ?? 0 }))
    .sort((a, b) => b.v - a.v)
    .slice(0, 6);
  const w = 196;
  const h = 30 + rows.length * 16;
  const left = x + 14 + w > width ? x - 14 - w : x + 14;
  const top = Math.min(M.top + 4, height - h - 4);
  const pop = series.population[yearIdx] ?? 0;

  return (
    <foreignObject x={left} y={top} width={w} height={h} pointerEvents="none">
      <div className="tooltip">
        <div className="tooltip-head">
          {year} · {people(pop)} people
        </div>
        {rows.map((r) => (
          <div className="tooltip-row" key={r.ri}>
            <span className="dot" style={{ background: colors[r.ri] }} />
            <span className="tooltip-label">{labels[r.ri]}</span>
            <span className="tooltip-value">{pct(r.v, 1)}</span>
          </div>
        ))}
      </div>
    </foreignObject>
  );
}
