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

# The year the historical layer hands off to the modern country panel.
HANDOFF_YEAR = 2010

YEAR_MIN = 0
YEAR_MAX = 2050


def _build_frames() -> list[int]:
    """The frame grid the app animates over: deliberately non-uniform.

    Annual frames only exist where annual data does. Going back, the grid
    coarsens to match what is actually knowable: a year-by-year claim about
    religious composition in 400 AD would be fiction dressed as precision, and
    41 frames per century of antiquity would inflate the payload by 20x to
    carry no additional information.

    Resolution is finest through 0-1000, where the two largest shifts in the
    whole series happen -- the Christianisation of the Mediterranean and the
    Islamic expansion after 622.
    """
    frames: list[int] = []
    frames += list(range(0, 1000, 50))       # antiquity -> early medieval
    frames += list(range(1000, 1500, 100))   # high medieval
    frames += list(range(1500, 1800, 50))    # early modern
    frames += list(range(1800, 1900, 25))    # industrial
    frames += list(range(1900, HANDOFF_YEAR, 10))
    frames += list(range(HANDOFF_YEAR, YEAR_MAX + 1, 1))
    return sorted(set(frames))


YEARS = _build_frames()
HISTORICAL_FRAMES = [y for y in YEARS if y < HANDOFF_YEAR]
MODERN_FRAMES = [y for y in YEARS if y >= HANDOFF_YEAR]

# Macro-regions carrying the historical layer. Modern borders are anachronistic
# before roughly 1900, so history is estimated for these and never per country.
MACRO_REGIONS = {
    "EUR": "Europe",
    "MENA": "Middle East, North Africa & Central Asia",
    "SSA": "Sub-Saharan Africa",
    "SAS": "South Asia",
    "EAS": "East Asia",
    "SEA": "Southeast Asia",
    "AMR": "Americas",
    "OCE": "Oceania",
}

# Religions that did not exist for part of the historical range. Log-ratio
# transforms cannot represent an exact zero, so structural zeros are carried as
# a small epsilon and reappear as ~0.06% after the round trip. Rendering
# "Muslim 0.1%" in year 0 would undercut the one thing the timelapse exists to
# show, so these are re-zeroed explicitly before the founding year.
# Dates are conventional: the traditional start of the Christian movement, and
# the Hijra.
RELIGION_FOUNDED = {"christian": 30, "muslim": 622}

# Multiplicative zero-replacement threshold. Shares below this are treated as
# "rounded to zero in the source", not as structural zeros, and are replaced so
# that log-ratio transforms stay finite. 0.0005 == 0.05 of a percentage point.
ZERO_REPLACEMENT = 0.0005

# Provenance levels, ordered from strongest to weakest evidence. The UI is
# required to visually distinguish these -- see docs/METHODOLOGY.md.
# `historical` is last for a reason: it is a regional reconstruction from
# fragmentary evidence, mapped onto modern borders that did not exist at the
# time. It is the weakest claim in the dataset by a wide margin.
PROVENANCE = ["observed", "interpolated", "modeled", "synthetic", "historical"]
