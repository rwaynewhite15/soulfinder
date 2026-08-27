import { useStore } from "../state/store";
import { categorical } from "../lib/palette";
import { pct, people, pp, signedPeople } from "../lib/format";
import { change, peopleOf, shareOf, yearIndex } from "../lib/data";
import type { RegionSeries } from "../lib/types";

/**
 * The table view.
 *
 * Required, not optional: three of the light-mode categorical slots fall below
 * 3:1 contrast against the light surface, and the palette rule is that such a
 * chart owes its readers relief -- either visible direct labels or an exact
 * table. This app ships both. It also makes every figure copy-pasteable, which
 * is the first thing anyone actually wants to do with a chart like this.
 */
export default function DataTable({
  series, years, labels,
}: { series: RegionSeries; years: number[]; labels: string[] }) {
  const { year, baseYear, visible, changeBasis, dark } = useStore();
  const colors = categorical(dark);
  const yi = yearIndex(years, year);
  const bi = yearIndex(years, baseYear);
  const shown = labels.map((_, i) => i).filter((i) => visible[i]);

  return (
    <div className="table-wrap">
      <table className="data-table">
        <caption>
          {series.name} — {year} (baseline {baseYear}).
          Provenance: <span className={`prov prov-${series.provenance[yi]}`}>{series.provenance[yi]}</span>
          {series.lo && <span className="caption-note"> · “—” means measured, not modeled: no interval applies.</span>}
        </caption>
        <thead>
          <tr>
            <th scope="col">Religion</th>
            <th scope="col" className="num">Share</th>
            <th scope="col" className="num">People</th>
            <th scope="col" className="num">
              Change from {baseYear} ({changeBasis === "share" ? "pp" : "people"})
            </th>
            {series.lo && <th scope="col" className="num">90% interval</th>}
          </tr>
        </thead>
        <tbody>
          {shown.map((ri) => {
            const d = change(series, bi, yi, ri, changeBasis);
            return (
              <tr key={ri}>
                <th scope="row">
                  <span className="dot" style={{ background: colors[ri] }} />
                  {labels[ri]}
                </th>
                <td className="num">{pct(shareOf(series, yi, ri), 2)}</td>
                <td className="num">{people(peopleOf(series, yi, ri))}</td>
                <td className={`num ${d >= 0 ? "up" : "down"}`}>
                  {changeBasis === "share" ? pp(d, 2) : signedPeople(d)}
                </td>
                {series.lo && (
                  <td className="num muted">
                    {(() => {
                      const lo = series.lo?.[yi]?.[ri];
                      const hi = series.hi?.[yi]?.[ri];
                      // Measured units have no predictive interval; printing
                      // "49.4% - 49.4%" under a "90% interval" heading would
                      // manufacture a precision claim nobody made.
                      return lo !== undefined && hi !== undefined && hi - lo > 0.0005
                        ? `${pct(lo, 1)} – ${pct(hi, 1)}`
                        : "—";
                    })()}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
