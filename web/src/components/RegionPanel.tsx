import { useMemo } from "react";
import { useStore } from "../state/store";
import { categorical } from "../lib/palette";
import { PROVENANCE_LABEL, PROVENANCE_NOTE, pct, people, pp, signedPeople } from "../lib/format";
import { change, peopleOf, shareOf, yearIndex } from "../lib/data";
import { formatYear } from "../lib/frames";
import type { AppData } from "../lib/data";

export default function RegionPanel({ data }: { data: AppData }) {
  const { selected, year, baseYear, religion, changeBasis, dark, select } = useStore();
  const years = data.bundle.years;
  const yi = yearIndex(years, year);
  const bi = yearIndex(years, baseYear);
  const colors = categorical(dark);
  const labels = data.bundle.religions.map((r) => data.bundle.labels[r]);

  const series = data.byId.get(selected) ?? data.byId.get("WLD")!;
  const prov = series.provenance[yi];

  const ranked = useMemo(
    () => labels.map((_, i) => i)
      .map((ri) => ({ ri, share: shareOf(series, yi, ri), n: peopleOf(series, yi, ri) }))
      .sort((a, b) => b.share - a.share),
    [series, yi, labels]
  );

  const parent = series.parent ? data.byId.get(series.parent) : null;
  const d = change(series, bi, yi, religion, changeBasis);
  // Observed units carry lo == hi: the value was measured, not modelled, so
  // there is no predictive interval to show. Rendering "84.7% - 84.7%" under a
  // "90% interval" label would imply a precision claim that was never made.
  const lo = series.lo?.[yi]?.[religion];
  const hi = series.hi?.[yi]?.[religion];
  const interval =
    lo !== undefined && hi !== undefined && hi - lo > 0.0005
      ? `${pct(lo, 1)} – ${pct(hi, 1)}`
      : null;

  const v = data.meta.diagnostics.validation;

  return (
    <aside className="panel">
      <nav className="crumbs" aria-label="Breadcrumb">
        <button className="crumb" onClick={() => select("WLD")}>World</button>
        {parent && (
          <>
            <span className="sep">/</span>
            <button className="crumb" onClick={() => select(parent.id)}>{parent.name}</button>
          </>
        )}
        {series.id !== "WLD" && (
          <>
            <span className="sep">/</span>
            <span className="crumb current">{series.name}</span>
          </>
        )}
      </nav>

      <h2 className="panel-title">{series.name}</h2>
      <div className="hero">
        <div className="hero-value">{people(series.population[yi] ?? 0)}</div>
        <div className="hero-label">people, {formatYear(year)}</div>
      </div>

      <div className="stat-row">
        <div className="stat">
          <div className="stat-label">
            <span className="dot" style={{ background: colors[religion] }} />
            {labels[religion]}
          </div>
          <div className="stat-value">{pct(shareOf(series, yi, religion))}</div>
          {interval && <div className="stat-sub">90% interval {interval}</div>}
        </div>
        <div className="stat">
          <div className="stat-label">Change from {formatYear(baseYear)}</div>
          <div className={`stat-value ${d >= 0 ? "up" : "down"}`}>
            {changeBasis === "share" ? pp(d) : signedPeople(d)}
          </div>
          <div className="stat-sub">
            {signedPeople(change(series, bi, yi, religion, "people"))} adherents
          </div>
        </div>
      </div>

      <h3 className="section-head">Composition, {formatYear(year)}</h3>
      <ul className="bars">
        {ranked.map(({ ri, share, n }) => (
          <li key={ri}>
            <button className="bar-row" onClick={() => useStore.getState().setReligion(ri)}>
              <span className="bar-label">
                <span className="dot" style={{ background: colors[ri] }} />
                {labels[ri]}
              </span>
              <span className="bar-track">
                {/* 4px rounded data-end, anchored to the baseline */}
                <span
                  className="bar-fill"
                  style={{ width: `${Math.max(share * 100, share > 0 ? 0.6 : 0)}%`, background: colors[ri] }}
                />
              </span>
              <span className="bar-value">{pct(share)}</span>
              <span className="bar-people">{people(n)}</span>
            </button>
          </li>
        ))}
      </ul>

      <h3 className="section-head">Where this number comes from</h3>
      <div className={`prov-card prov-${prov}`}>
        <div className="prov-head">
          <span className={`prov prov-${prov}`}>{PROVENANCE_LABEL[prov]}</span>
        </div>
        <p className="prov-note">{PROVENANCE_NOTE[prov]}</p>
        {(prov === "synthetic" || prov === "modeled") && (
          <p className="prov-note">
            Cross-validated against held-out states: this synthesis misassigns{" "}
            <b>{pct(v.tvd_model, 1)}</b> of people on average, against{" "}
            <b>{pct(v.tvd_baseline, 1)}</b> for assuming every state matches the
            national average — {(v.tvd_skill * 100).toFixed(0)}% of that error removed.
            Largest single-category error: {pct(Math.max(...Object.values(v.per_religion_mae)), 1)}.
          </p>
        )}
      </div>

      {series.level === "country" && series.id === "USA" && (
        <p className="hint">
          Zoom in to drill down to states. State figures below the national
          level are modeled — see the provenance flag on each.
        </p>
      )}
    </aside>
  );
}
