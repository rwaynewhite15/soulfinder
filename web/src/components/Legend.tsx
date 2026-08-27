import { useStore } from "../state/store";
import { DIVERGING, divergingAt } from "../lib/palette";
import { pct, pp, signedPeople } from "../lib/format";

/** Map legend. Always present -- the map's colour is never the only cue, but it is the primary one. */
export default function Legend({ label, maxShare, maxDelta, ramp }: {
  label: string; maxShare: number; maxDelta: number; ramp: string[];
}) {
  const { mapMetric, changeBasis, baseYear, dark } = useStore();

  if (mapMetric === "share") {
    return (
      <div className="legend">
        <div className="legend-title">{label} — share of population</div>
        <div className="ramp">
          {ramp.map((c, i) => <span key={i} style={{ background: c }} />)}
        </div>
        <div className="ramp-labels"><span>0%</span><span>{pct(maxShare, 0)}</span></div>
      </div>
    );
  }

  const fmt = (v: number) => (changeBasis === "share" ? pp(v, 0) : signedPeople(v));
  const steps = DIVERGING.negative.length * 2 + 1;
  return (
    <div className="legend">
      <div className="legend-title">
        Change since {baseYear} — {label}
      </div>
      <div className="ramp">
        {Array.from({ length: steps }, (_, i) => {
          const t = (i / (steps - 1)) * 2 - 1;
          return <span key={i} style={{ background: divergingAt(t, dark) }} />;
        })}
      </div>
      <div className="ramp-labels">
        <span>{fmt(-maxDelta)}</span><span>0</span><span>{fmt(maxDelta)}</span>
      </div>
    </div>
  );
}
