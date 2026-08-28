import { useEffect } from "react";
import { useStore } from "../state/store";
import { categorical } from "../lib/palette";
import { formatYear, nextFrameLooping, frameIndex } from "../lib/frames";
import type { AppData } from "../lib/data";

/**
 * Filters sit in one row above the visuals, and every control that changes what
 * the map encodes lives here rather than being scattered across panels.
 */
export default function Controls({ labels, data }: { labels: string[]; data: AppData }) {
  const s = useStore();
  const colors = categorical(s.dark);

  // Autoplay advances one FRAME per tick, not one year: the grid is
  // non-uniform, so stepping by year would stall for 50 ticks between
  // antiquity frames and then sprint through the modern era.
  useEffect(() => {
    if (!s.playing) return;
    const t = setInterval(() => {
      const st = useStore.getState();
      const [lo, hi] = st.window;
      if (st.loop) {
        st.setYear(nextFrameLooping(st.years, st.year, lo, hi));
        return;
      }
      const i = frameIndex(st.years, st.year);
      if (i >= frameIndex(st.years, hi)) st.set("playing", false);
      else st.setYear(st.years[i + 1]);
    }, 200);
    return () => clearInterval(t);
  }, [s.playing, s.loop]);

  return (
    <div className="controls">
      <div className="control-group">
        <button
          className="btn primary"
          onClick={() => {
            // Restarting from the end is only needed when not looping.
            if (!s.loop && s.year >= s.window[1]) s.setYear(s.window[0]);
            s.set("playing", !s.playing);
          }}
          aria-label={s.playing ? "Pause" : "Play through the years"}
        >
          {s.playing ? "❚❚ Pause" : "▶ Play"}
        </button>
        <span className="year-readout" aria-live="polite">{formatYear(s.year)}</span>
        <Toggle on={s.loop} onChange={(v) => s.set("loop", v)} label="Loop" />
      </div>

      <div className="control-group">
        <div className="seg" role="group" aria-label="Map view">
          <button
            className={`seg-btn ${s.view === "globe" ? "on" : ""}`}
            onClick={() => s.set("view", "globe")}
          >Globe</button>
          <button
            className={`seg-btn ${s.view === "atlas" ? "on" : ""}`}
            onClick={() => s.set("view", "atlas")}
            title="All eight religions side by side, one globe each"
          >All faiths</button>
        </div>
      </div>

      <div className="control-group">
        <label className="control-label" htmlFor="region">Region</label>
        <select
          id="region"
          className="select region"
          value={s.selected}
          onChange={(e) => s.select(e.target.value)}
        >
          <option value="WLD">World</option>
          <optgroup label="Macro-regions (carry the historical layer)">
            {data.macroRegions.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </optgroup>
          <optgroup label="Countries">
            {data.countries
              .slice()
              .sort((a, b) => a.name.localeCompare(b.name))
              .map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </optgroup>
          <optgroup label="US states">
            {data.admin1
              .slice()
              .sort((a, b) => a.name.localeCompare(b.name))
              .map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </optgroup>
        </select>
      </div>

      {s.view === "globe" && (
      <div className="control-group">
        <label className="control-label" htmlFor="metric">Map shows</label>
        <select
          id="metric"
          className="select"
          value={s.mapMetric}
          onChange={(e) => s.set("mapMetric", e.target.value as "share" | "change")}
        >
          <option value="share">Share of population</option>
          <option value="change">Change since baseline</option>
        </select>
      </div>
      )}

      {s.view === "globe" && s.mapMetric === "change" && (
        <div className="control-group">
          <label className="control-label" htmlFor="basis">Measured in</label>
          <select
            id="basis"
            className="select"
            value={s.changeBasis}
            onChange={(e) => s.set("changeBasis", e.target.value as "share" | "people")}
          >
            <option value="share">Percentage points</option>
            <option value="people">People</option>
          </select>
          <label className="control-label" htmlFor="base">from</label>
          <select
            id="base"
            className="select baseline"
            value={s.baseYear}
            onChange={(e) => s.setBaseYear(Number(e.target.value))}
          >
            {/* Historical baselines too: comparing AD 0 against 2010 is the
                least interesting question the map can answer. */}
            {[0, 500, 1000, 1500, 1800, 1900, 1950, 2010, 2020, 2030, 2040].map((y) => (
              <option key={y} value={y}>{formatYear(y)}</option>
            ))}
          </select>
        </div>
      )}

      <div className="control-group grow">
        <span className="control-label">Religion</span>
        <div className="chips" role="group" aria-label="Religion shown on the map">
          {labels.map((l, i) => (
            <button
              key={l}
              className={`chip ${s.religion === i ? "active" : ""} ${s.visible[i] ? "" : "off"}`}
              onClick={() => { s.setReligion(i); if (!s.visible[i]) s.toggleReligion(i); }}
              onDoubleClick={() => s.soloReligion(i)}
              title={`${l} — click to map, double-click to isolate in the chart`}
              aria-pressed={s.religion === i}
            >
              <span className="dot" style={{ background: colors[i] }} />
              {l}
            </button>
          ))}
          <button className="chip ghost" onClick={s.showAllReligions}>Show all</button>
        </div>
      </div>

      <div className="control-group">
        <Toggle on={s.showDensity} onChange={(v) => s.set("showDensity", v)} label="Density" />
        <Toggle
          on={s.chartMode === "stack"}
          onChange={(v) => s.set("chartMode", v ? "stack" : "lines")}
          label="Stacked"
        />
        <Toggle on={s.showTable} onChange={(v) => s.set("showTable", v)} label="Table" />
        <Toggle on={s.dark} onChange={(v) => s.set("dark", v)} label="Dark" />
      </div>
    </div>
  );
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      className={`toggle ${on ? "on" : ""}`}
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
    >
      <span className="track"><span className="knob" /></span>
      {label}
    </button>
  );
}
