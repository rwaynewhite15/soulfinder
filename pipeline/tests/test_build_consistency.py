"""End-to-end invariants on the built artifacts.

These are the properties a reader of the app is entitled to assume: that
drilling from the world into a country and then into a state never crosses a
seam where the numbers stop adding up. They are easy to break -- benchmarking
one level and not another does it silently -- so they are asserted, not trusted.
"""
import json
import subprocess
import sys

import numpy as np
import pytest

from soulfinder.config import MODERN_FRAMES, RELIGIONS, WEB_DATA, YEARS


@pytest.fixture(scope="module")
def artifacts():
    subprocess.run(
        [sys.executable, "-m", "soulfinder.build", "--skip-density"],
        check=True, capture_output=True,
    )
    with open(WEB_DATA / "regions.json") as fh:
        regions = json.load(fh)
    with open(WEB_DATA / "meta.json") as fh:
        meta = json.load(fh)
    return regions, meta


# Shares are serialised at 5 decimal places (0.001 of a percentage point --
# far finer than the underlying data's real precision). Reconstructing counts
# from rounded shares therefore carries up to ~4e-5 relative error once summed
# over 8 categories, so that, not float epsilon, is the tolerance these
# rollups can be held to.
ROUNDING_RTOL = 1e-4


def counts(series, yi):
    return np.array(series["shares"][yi]) * series["population"][yi]


def test_every_series_is_a_valid_composition(artifacts):
    regions, _ = artifacts
    for s in regions["series"]:
        arr = np.array(s["shares"])
        assert arr.shape == (len(YEARS), len(RELIGIONS)), s["id"]
        assert np.allclose(arr.sum(axis=1), 1.0, atol=1e-4), s["id"]
        assert (arr >= 0).all(), s["id"]


def test_states_sum_to_their_country(artifacts):
    regions, _ = artifacts
    by_id = {s["id"]: s for s in regions["series"]}
    states = [s for s in regions["series"] if s.get("parent") == "USA"]
    assert len(states) == 51
    for yi in range(0, len(YEARS), 8):
        nat = counts(by_id["USA"], yi)
        st = sum(counts(s, yi) for s in states)
        assert np.allclose(st / st.sum(), nat / nat.sum(), atol=1e-4)
        assert np.isclose(st.sum(), nat.sum(), rtol=ROUNDING_RTOL)
        # Population is serialised as integers, so summing N children carries up
        # to N/2 people of rounding. That absolute bound is the right assertion;
        # a relative one fails on small historical populations, where 1 person
        # out of 3.9M already exceeds a 1e-7 tolerance.
        assert abs(
            sum(s["population"][yi] for s in states) - by_id["USA"]["population"][yi]
        ) <= len(states)


def test_countries_sum_to_the_world(artifacts):
    regions, _ = artifacts
    by_id = {s["id"]: s for s in regions["series"]}
    countries = [s for s in regions["series"] if s["level"] == "country"]
    for yi in range(0, len(YEARS), 8):
        tot = sum(counts(s, yi) for s in countries)
        assert np.allclose(tot / tot.sum(), np.array(by_id["WLD"]["shares"][yi]), atol=1e-4)
        assert np.isclose(tot.sum(), by_id["WLD"]["population"][yi], rtol=ROUNDING_RTOL)


def test_every_cell_carries_a_provenance_flag(artifacts):
    regions, _ = artifacts
    allowed = {"observed", "interpolated", "modeled", "synthetic", "historical"}
    for s in regions["series"]:
        assert len(s["provenance"]) == len(YEARS), s["id"]
        assert set(s["provenance"]) <= allowed, s["id"]


def test_admin1_intervals_bracket_the_estimate(artifacts):
    regions, _ = artifacts
    for s in regions["series"]:
        if s["level"] != "admin1":
            continue
        lo, hi = np.array(s["lo"]), np.array(s["hi"])
        assert (lo <= hi + 1e-9).all(), s["id"]
        assert (lo >= 0).all() and (hi <= 1 + 1e-9).all(), s["id"]


def test_synthesis_beats_the_naive_baseline(artifacts):
    """A negative-skill model must fail the build, not ship quietly."""
    _, meta = artifacts
    v = meta["diagnostics"]["validation"]
    assert v["tvd_model"] < v["tvd_baseline"]
    assert v["tvd_skill"] > 0.10


def test_ipf_reached_its_marginals(artifacts):
    _, meta = artifacts
    assert meta["diagnostics"]["ipf_diagnostics"]["max_marginal_error"] < 1e-6


def test_world_rollup_tracks_published_figures(artifacts):
    _, meta = artifacts
    assert meta["diagnostics"]["world_rollup_check"]["within_tolerance"]


def test_population_is_monotone_where_the_source_says_it_grows(artifacts):
    """Scoped to the modern frames on purpose.

    Over the historical range populations legitimately fall -- plague, and the
    collapse of the Americas after 1500 -- so monotone growth is the wrong
    assertion there, not a bug to fix.
    """
    regions, _ = artifacts
    by_id = {s["id"]: s for s in regions["series"]}
    start = regions["years"].index(MODERN_FRAMES[0])
    for iso3 in ("NGA", "IND", "USA"):
        pop = np.array(by_id[iso3]["population"][start:])
        assert (np.diff(pop) > 0).all(), iso3


def test_the_historical_layer_spans_year_zero_to_the_handoff(artifacts):
    regions, meta = artifacts
    assert regions["years"][0] == 0
    handoff = regions["handoffYear"]
    world = next(s for s in regions["series"] if s["id"] == "WLD")
    hist = [p for y, p in zip(regions["years"], world["provenance"]) if y < handoff]
    assert hist and set(hist) == {"historical"}
    assert meta["counts"]["regions"] == 8


def test_religions_are_exactly_zero_before_they_existed(artifacts):
    """Islam showing 0.06% in year 0 would undercut the whole timelapse."""
    regions, _ = artifacts
    founded = {"christian": 30, "muslim": 622}
    for religion, year in founded.items():
        j = regions["religions"].index(religion)
        for s in regions["series"]:
            for y, row in zip(regions["years"], s["shares"]):
                if y < year:
                    assert row[j] == 0.0, f"{s['id']} {religion} at {y}"


def test_frame_grid_is_finest_where_the_data_is(artifacts):
    regions, _ = artifacts
    years = regions["years"]
    handoff = regions["handoffYear"]
    modern = [y for y in years if y >= handoff]
    assert modern == list(range(handoff, 2051))
    ancient = [y for y in years if y < 1000]
    assert all(b - a == 50 for a, b in zip(ancient, ancient[1:]))
