import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import GlobeMap from "./components/GlobeMap";
import FaithAtlas from "./components/FaithAtlas";
import TimeSeries from "./components/TimeSeries";
import RangeBrush from "./components/RangeBrush";
import Controls from "./components/Controls";
import RegionPanel from "./components/RegionPanel";
import DataTable from "./components/DataTable";
import TrendRail from "./components/TrendRail";
import Legend from "./components/Legend";
import { loadAll } from "./lib/data";
import { colorDomain } from "./lib/domain";
import { yearIndex } from "./lib/data";
import { stepFrame } from "./lib/frames";
import { useStore } from "./state/store";
import { sequentialRamp } from "./lib/oklch";
import { categorical } from "./lib/palette";

export default function App() {
  const { data, error, setData, setError, selected, dark, showTable, religion,
          changeBasis, baseYear, window: win, view, chartView } = useStore();
  const chartRef = useRef<HTMLDivElement>(null);
  const [chartWidth, setChartWidth] = useState(900);

  useEffect(() => {
    loadAll().then(setData).catch((e: Error) => setError(e.message));
  }, [setData, setError]);

  useLayoutEffect(() => {
    const el = chartRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      // Round and ignore sub-pixel churn. The observed element's width feeds an
      // SVG rendered back into it, so a jittering measurement is a feedback
      // loop; a floor keeps the chart's inner width positive when the pane is
      // briefly tiny (during a theme swap or view switch).
      const next = Math.max(320, Math.round(entry.contentRect.width));
      setChartWidth((prev) => (Math.abs(prev - next) > 1 ? next : prev));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [data]);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);

  // Keyboard scrubbing: the year slider should be operable without a mouse.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "SELECT") return;
      const st = useStore.getState();
      if (e.key === "ArrowRight") st.setYear(stepFrame(st.years, st.year, 1, st.window[0], st.window[1]));
      else if (e.key === "ArrowLeft") st.setYear(stepFrame(st.years, st.year, -1, st.window[0], st.window[1]));
      else if (e.key === " ") { e.preventDefault(); st.set("playing", !st.playing); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const labels = useMemo(
    () => data ? data.bundle.religions.map((r) => data.bundle.labels[r]) : [],
    [data]
  );

  const legendDomain = useMemo(() => {
    if (!data) return { maxShare: 1, maxDelta: 1 };
    const inUsa = selected === "USA" || selected.startsWith("USA-");
    const bi = yearIndex(data.bundle.years, baseYear);
    return colorDomain(
      inUsa ? data.admin1 : data.countries,
      religion, data.bundle.years.length, changeBasis, bi
    );
  }, [data, selected, religion, changeBasis, baseYear]);

  if (error) {
    return (
      <div className="fatal">
        <h1>Soulfinder</h1>
        <p>{error}</p>
        <pre>npm run data</pre>
      </div>
    );
  }
  if (!data) return <div className="loading">Loading demographic data…</div>;

  const series = data.byId.get(selected) ?? data.byId.get("WLD")!;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <h1>Soulfinder</h1>
            <p className="tagline">
              Religious composition of the world, {data.bundle.years[0]}–
              {data.bundle.years[data.bundle.years.length - 1]}
            </p>
          </div>
        </div>
        <div className="build-note">
          {data.meta.counts.countries} countries · {data.meta.counts.admin1} US states ·
          synthesis skill {(data.meta.diagnostics.validation.tvd_skill * 100).toFixed(0)}%
        </div>
      </header>

      <Controls labels={labels} data={data} />

      <main className="stage">
        <section className="map-pane">
          {view === "atlas" ? (
            <FaithAtlas data={data} />
          ) : (
            <>
              <GlobeMap data={data} />
              <Legend
                label={labels[religion]}
                maxShare={legendDomain.maxShare}
                maxDelta={legendDomain.maxDelta}
                ramp={sequentialRamp(categorical(dark)[religion], 13, dark)}
              />
              <div className="map-hint">Scroll to zoom · click a country to drill in</div>
            </>
          )}
        </section>
        <RegionPanel data={data} />
      </main>

      <section className="chart-pane" ref={chartRef}>
        <div className="chart-head">
          <h2>
            {series.name}
            <span className="chart-sub">
              {chartView === "trends"
                ? "what is changing"
                : useStore.getState().chartMode === "stack"
                  ? "composition over time"
                  : "share over time"} · {win[0]}–{win[1]}
            </span>
          </h2>
          <div className="seg" role="group" aria-label="Lower pane view">
            <button
              className={`seg-btn ${chartView === "series" ? "on" : ""}`}
              onClick={() => useStore.getState().set("chartView", "series")}
            >Over time</button>
            <button
              className={`seg-btn ${chartView === "trends" ? "on" : ""}`}
              onClick={() => useStore.getState().set("chartView", "trends")}
            >Trends</button>
          </div>
        </div>
        {/* The body scrolls; the brush stays pinned below it. The trends rail
            is taller than the chart, and without this it pushed the range
            brush off-screen -- the control that decides the very window the
            rail is summarising. */}
        <div className="chart-body">
          {chartView === "trends" ? (
            <TrendRail series={series} years={data.bundle.years} labels={labels} />
          ) : showTable ? (
            <DataTable series={series} years={data.bundle.years} labels={labels} />
          ) : (
            <TimeSeries
              series={series}
              years={data.bundle.years}
              labels={labels}
              width={chartWidth}
              height={260}
            />
          )}
        </div>
        <RangeBrush series={series} years={data.bundle.years} width={chartWidth} />
      </section>
    </div>
  );
}
