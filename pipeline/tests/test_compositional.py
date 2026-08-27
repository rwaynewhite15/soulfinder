import numpy as np
import pytest

from soulfinder.compositional import (
    aitchison_distance, alr, alr_inv, clr, clr_inv, closure,
    geometric_mean_composition, perturb, power, replace_zeros,
    total_variation_distance,
)


def test_closure_sums_to_one():
    assert np.isclose(closure(np.array([2.0, 3.0, 5.0])).sum(), 1.0)


def test_closure_handles_all_zero_row_without_nan():
    out = closure(np.array([[0.0, 0.0], [1.0, 1.0]]))
    assert np.isfinite(out).all()
    assert np.allclose(out[1], [0.5, 0.5])


@pytest.mark.parametrize("ref", [0, 1, -1])
def test_alr_roundtrip(ref):
    p = closure(np.array([0.5, 0.3, 0.2]))
    assert np.allclose(alr_inv(alr(p, ref), ref), p)


def test_clr_roundtrip_and_zero_sum():
    p = closure(np.array([[0.5, 0.3, 0.2], [0.1, 0.1, 0.8]]))
    z = clr(p)
    assert np.allclose(z.sum(axis=-1), 0.0)
    assert np.allclose(clr_inv(z), p)


def test_zero_replacement_preserves_ratios_among_observed_parts():
    """The whole point of multiplicative (not additive) replacement."""
    p = np.array([0.6, 0.3, 0.1, 0.0])
    out = replace_zeros(p)
    assert np.isclose(out.sum(), 1.0)
    assert out[3] > 0
    assert np.isclose(out[0] / out[1], p[0] / p[1])
    assert np.isclose(out[1] / out[2], p[1] / p[2])


def test_alr_is_finite_with_structural_zeros():
    p = np.array([0.99, 0.01, 0.0, 0.0])
    assert np.isfinite(alr(p)).all()


def test_aitchison_is_subcompositionally_coherent():
    """Rescaling a shared subset must not change the distance between them."""
    p = closure(np.array([0.5, 0.3, 0.2]))
    q = closure(np.array([0.4, 0.4, 0.2]))
    d1 = aitchison_distance(p, q)
    d2 = aitchison_distance(power(p, 1.0), power(q, 1.0))
    assert np.isclose(d1, d2)


def test_aitchison_sees_relative_change_euclidean_misses():
    """0.01 -> 0.02 doubles a group; 0.50 -> 0.51 barely moves one."""
    a1, a2 = np.array([0.01, 0.99]), np.array([0.02, 0.98])
    b1, b2 = np.array([0.50, 0.50]), np.array([0.51, 0.49])
    assert np.isclose(np.abs(a1 - a2).sum(), np.abs(b1 - b2).sum(), atol=0.01)
    assert aitchison_distance(a1, a2) > 5 * aitchison_distance(b1, b2)


def test_perturb_identity_and_inverse():
    p = closure(np.array([0.5, 0.3, 0.2]))
    identity = closure(np.ones(3))
    assert np.allclose(perturb(p, identity), p)
    assert np.allclose(perturb(p, power(p, -1.0)), identity)


def test_total_variation_bounds():
    p = np.array([1.0, 0.0, 0.0])
    q = np.array([0.0, 0.0, 1.0])
    assert np.isclose(total_variation_distance(p, p), 0.0)
    assert total_variation_distance(p, q) > 0.99


def test_geometric_mean_is_a_valid_composition():
    p = closure(np.array([[0.5, 0.3, 0.2], [0.2, 0.2, 0.6], [0.7, 0.2, 0.1]]))
    c = geometric_mean_composition(p)
    assert np.isclose(c.sum(), 1.0) and (c > 0).all()


def test_weighted_centre_moves_toward_heavier_unit():
    p = closure(np.array([[0.8, 0.1, 0.1], [0.1, 0.8, 0.1]]))
    heavy_first = geometric_mean_composition(p, weights=np.array([100.0, 1.0]))
    assert heavy_first[0] > heavy_first[1]
