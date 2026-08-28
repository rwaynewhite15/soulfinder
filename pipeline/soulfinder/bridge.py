"""Regenerate the 2010 bridge row in the historical table.

    python -m soulfinder.bridge

The historical series is benchmarked onto its own handoff-year row, so that row
has to equal the modern country rollup. When it does not, the disagreement is
propagated backwards through two thousand years: an authored MENA Jewish share
2.2 points too high at 2010 halved the Jewish share of the world in year 0.
This makes that row derived rather than authored, so it cannot drift.

The table has no 2000 row on purpose: an authored knot ten years before a
derived one over-specifies the last decade and produced a 24pp step at the
handoff for Ghana. 1950 is the last authored knot.
"""
from __future__ import annotations

import re

from . import io as sio
from .build import apply_benchmark, load_admin1_frame
from .config import HANDOFF_YEAR, RELIGIONS, SOURCES
from .historical import load_macro_regions, region_anchor_compositions
from .interpolate import densify_national


def main() -> None:
    national = sio.load_national_religion()
    population = sio.resolve_row_residual(national, sio.load_population())
    dense = densify_national(national, population)
    admin1_df, _, comps_true = load_admin1_frame()
    dense = apply_benchmark(dense, "USA", comps_true, admin1_df["population"].to_numpy(float), {})

    region_of = dict(zip(*load_macro_regions()[["iso3", "region"]].to_numpy().T))
    anchors = region_anchor_compositions(dense, region_of)

    path = SOURCES / "historical_religion.csv"
    lines = path.read_text().splitlines()
    updated = 0
    out = []
    for line in lines:
        m = re.match(rf"^([A-Z]+),{HANDOFF_YEAR},", line)
        if m and m.group(1) in anchors:
            vals = anchors[m.group(1)] * 100
            out.append(f"{m.group(1)},{HANDOFF_YEAR}," + ",".join(f"{v:.2f}" for v in vals))
            updated += 1
        else:
            out.append(line)
    path.write_text("\n".join(out) + "\n")
    print(f"regenerated {updated} bridge rows at {HANDOFF_YEAR} in {path.name}")


if __name__ == "__main__":
    main()
