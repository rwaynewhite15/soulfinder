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

from soulfinder.config import RELIGIONS, WEB_DATA, YEARS


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
        # population is serialised as an integer, so it must reconcile exactly
        assert np.isclose(
            sum(s["population"][yi] for s in states), by_id["USA"]["population"][yi], rtol=1e-7
        )


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
    allowed = {"observed", "interpolated", "modeled", "synthetic"}
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
    regions, _ = artifacts
    by_id = {s["id"]: s for s in regions["series"]}
    for iso3 in ("NGA", "IND", "USA"):
        pop = np.array(by_id[iso3]["population"])
        assert (np.diff(pop) > 0).all(), iso3
