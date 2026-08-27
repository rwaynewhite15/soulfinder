"""Shared configuration: category vocabulary, paths, model constants."""
from __future__ import annotations

from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
SOURCES = PIPELINE_ROOT / "sources"
GEO_SOURCES = SOURCES / "geo"
WEB_DATA = PIPELINE_ROOT.parent / "web" / "public" / "data"

# The eight-way vocabulary used by the major cross-national religion datasets
# (Pew's Global Religious Landscape and its 2010-2050 projections). Order is
# load-bearing: every composition vector in the pipeline is in this order.
RELIGIONS = [
    "christian",
    "muslim",
    "unaffiliated",
    "hindu",
    "buddhist",
    "folk",
    "other",
    "jewish",
]

RELIGION_LABELS = {
    "christian": "Christian",
    "muslim": "Muslim",
    "unaffiliated": "Religiously unaffiliated",
    "hindu": "Hindu",
    "buddhist": "Buddhist",
    "folk": "Folk religions",
    "other": "Other religions",
    "jewish": "Jewish",
}

N_RELIGIONS = len(RELIGIONS)

# Years rendered by the app. Source data is decadal; everything between the
# decadal knots is interpolated (and flagged as such).
YEAR_MIN = 2010
YEAR_MAX = 2050
YEAR_STEP = 1
YEARS = list(range(YEAR_MIN, YEAR_MAX + 1, YEAR_STEP))

# Multiplicative zero-replacement threshold. Shares below this are treated as
# "rounded to zero in the source", not as structural zeros, and are replaced so
# that log-ratio transforms stay finite. 0.0005 == 0.05 of a percentage point.
ZERO_REPLACEMENT = 0.0005

# Provenance levels, ordered from strongest to weakest evidence. The UI is
# required to visually distinguish these -- see docs/METHODOLOGY.md.
PROVENANCE = ["observed", "interpolated", "modeled", "synthetic"]
