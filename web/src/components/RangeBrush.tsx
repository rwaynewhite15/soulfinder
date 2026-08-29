import { useMemo, useRef, useState } from "react";
import { scaleLinear } from "d3-scale";
import { area, stack, stackOrderNone, stackOffsetNone, curveMonotoneX } from "d3-shape";
import { useStore } from "../state/store";
import { categorical } from "../lib/palette";
import type { RegionSeries } from "../lib/types";
import { formatYearShort, snapToFrame } from "../lib/frames";

const M = { top: 4, right: 128, bottom: 16, left: 52 };
// Wide enough to always leave at least two frames inside the window.
const MIN_SPAN = 100;

/**
 * Focus-and-context strip under the main chart.
 *
 * Shows the whole 2010-2050 range at all times and lets the user drag a window
 * out of it, which is what the main chart zooms to. Keeping the full range
 * permanently visible is the point: a zoomed line chart with no overview hides
 * whether the window you are looking at is typical or the one interesting
 * stretch in forty years.
 */
export default function RangeBrush({
  series, years, width,
}: { series: RegionSeries; years: number[]; width: number }) {
  const { window: win, year, visible, dark, setWindow, setYear } = useStore();
  const ref = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<null | "lo" | "hi" | "move" | "year">(null);
  const [grabOffset, setGrabOffset] = useState(0);

  const height = 56;
  const iw = Math.max(10, width - M.left - M.right);
  const ih = height - M.top - M.bottom;
  const colors = categorical(dark);
  const surface = dark ? "#1a1a19" : "#fcfcfb";

  const x = useMemo(
    () => scaleLinear().domain([years[0], years[years.length - 1]]).range([0, iw]),
    [years, iw]
  );
  const y = useMemo(() => scaleLinear().domain([0, 1]).range([ih, 0]), [ih]);

  const shownIdx = useMemo(() => visible.map((v, i) => (v ? i : -1)).filter((i) => i >= 0), [visible]);

  const stacked = useMemo(() => {
    const rows = years.map((yr, i) => {
      const row: Record<string, number> = { year: yr };
      shownIdx.forEach((ri) => { row[String(ri)] = series.shares[i]?.[ri] ?? 0; });
      return row;
    });
    return stack<Record<string, number>>()
      .keys(shownIdx.map(String)).order(stackOrderNone).offset(stackOffsetNone)(rows);
  }, [years, shownIdx, series]);

  const areaGen = useMemo(
    () => area<[number, number] & { data: Record<string, number> }>()
      .x((d) => x(d.data.year)).y0((d) => y(d[0])).y1((d) => y(d[1])).curve(curveMonotoneX),
    [x, y]
  );

  const yearAt = (clientX: number) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return years[0];
    const px = clientX - rect.left - M.left;
    return snapToFrame(years, x.invert(Math.max(0, Math.min(iw, px))));
  };

  const onMove = (clientX: number) => {
    const yr = yearAt(clientX);
    const lo = years[0];
    const hi = years[years.length - 1];
    if (drag === "lo") setWindow([Math.max(lo, Math.min(yr, win[1] - MIN_SPAN)), win[1]]);
    else if (drag === "hi") setWindow([win[0], Math.min(hi, Math.max(yr, win[0] + MIN_SPAN))]);
    else if (drag === "year") setYear(Math.max(win[0], Math.min(win[1], yr)));
    else if (drag === "move") {
      const span = win[1] - win[0];
      let start = yr - grabOffset;
      start = Math.max(lo, Math.min(start, hi - span));
      setWindow([start, start + span]);
    }
  };

  return (
    <svg
      ref={ref}
      width={width}
      height={height}
      className="brush"
      style={{ display: "block", touchAction: "none" }}
      aria-label="Year range selector"
      onPointerMove={(e) => drag && onMove(e.clientX)}
      onPointerUp={() => setDrag(null)}
      onPointerLeave={() => setDrag(null)}
    >
      <g transform={`translate(${M.left},${M.top})`}>
        {stacked.map((band, k) => (
          <path
            key={shownIdx[k]}
            d={areaGen(band as never) ?? undefined}
            fill={colors[shownIdx[k]]}
            opacity={0.5}
            stroke={surface}
            strokeWidth={1}
          />
        ))}

        <rect x={0} y={0} width={Math.max(0, x(win[0]))} height={ih} className="brush-mask" />
        <rect
          x={x(win[1])} y={0}
          width={Math.max(0, iw - x(win[1]))} height={ih}
          className="brush-mask"
        />

        <rect
          x={x(win[0])} y={0} width={Math.max(1, x(win[1]) - x(win[0]))} height={ih}
          className="brush-window"
          onPointerDown={(e) => {
            (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
            setGrabOffset(yearAt(e.clientX) - win[0]);
            setDrag("move");
          }}
        />

        {(["lo", "hi"] as const).map((side) => (
          // The handler sits on the group, not on the invisible hit rect: the
          // visible line and grip are painted on top of that rect and would
          // otherwise swallow the pointerdown, leaving the handle ungrabbable.
          <g
            key={side}
            transform={`translate(${x(side === "lo" ? win[0] : win[1])},0)`}
            style={{ cursor: "ew-resize" }}
            onPointerDown={(e) => {
              (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
              setDrag(side);
            }}
          >
            {/* generous invisible hit target; the visible handle stays thin */}
            <rect x={-7} y={0} width={14} height={ih} fill="transparent" />
            <line y2={ih} className="brush-handle" />
            <rect x={-3} y={ih / 2 - 9} width={6} height={18} rx={2} className="brush-grip" />
          </g>
        ))}

        <g
          transform={`translate(${x(year)},0)`}
          style={{ cursor: "grab" }}
          onPointerDown={(e) => {
            (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
            setDrag("year");
          }}
        >
          <rect x={-8} y={-M.top} width={16} height={height} fill="transparent" />
          <line y1={-M.top} y2={ih} className="brush-playhead" />
          <circle cy={-M.top + 3} r={3.5} className="brush-playhead-dot" />
        </g>

        <text x={x(win[0])} y={ih + 12} className="tick" textAnchor="start">{formatYearShort(win[0])}</text>
        <text x={x(win[1])} y={ih + 12} className="tick" textAnchor="end">{formatYearShort(win[1])}</text>
      </g>
    </svg>
  );
}
