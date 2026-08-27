import numpy as np

from soulfinder.dasymetric import (
    _safe_bbox, allocate_unit, build_surface, density_at, points_in_rings,
    sigma_for_population,
)

SQUARE = [np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]])]


def test_point_in_polygon_on_a_known_square():
    pts = np.array([[5.0, 5.0], [-1.0, 5.0], [5.0, 11.0], [9.9, 0.1]])
    assert list(points_in_rings(pts, SQUARE)) == [True, False, False, True]


def test_point_in_polygon_handles_concave_shapes():
    """An L-shape: the notch must read as outside."""
    l_shape = [np.array([[0, 0], [10, 0], [10, 4], [4, 4], [4, 10], [0, 10], [0, 0]], dtype=float)]
    pts = np.array([[2.0, 2.0], [8.0, 8.0], [8.0, 2.0], [2.0, 8.0]])
    assert list(points_in_rings(pts, l_shape)) == [True, False, True, True]


def test_multiple_rings_are_unioned():
    second = np.array([[20.0, 20.0], [30.0, 20.0], [30.0, 30.0], [20.0, 30.0], [20.0, 20.0]])
    pts = np.array([[5.0, 5.0], [25.0, 25.0], [15.0, 15.0]])
    assert list(points_in_rings(pts, SQUARE + [second])) == [True, True, False]


def test_antimeridian_bbox_is_split_not_wrapped():
    """Alaska-shaped input: a naive bbox spans the globe and kills sampling."""
    rings = [np.array([[-179.0, 55.0], [-140.0, 55.0], [-140.0, 70.0], [179.0, 52.0], [-179.0, 55.0]])]
    min_lon, _, max_lon, _ = _safe_bbox(rings, centroid_lon=-152.0)
    assert max_lon - min_lon < 180
    assert min_lon < 0 and max_lon < 0


def test_normal_bbox_is_untouched():
    assert _safe_bbox(SQUARE, centroid_lon=5.0) == (0.0, 0.0, 10.0, 10.0)


def test_density_peaks_at_cities_and_has_a_rural_floor():
    cities = np.array([[5.0, 5.0]])
    pop = np.array([5e6])
    sigma = sigma_for_population(pop)
    near = density_at(np.array([[5.0, 5.0]]), cities, pop, sigma)[0]
    far = density_at(np.array([[9.9, 9.9]]), cities, pop, sigma)[0]
    assert near > far > 0  # rural areas keep a non-zero share


def test_bigger_cities_sprawl_further():
    assert sigma_for_population(np.array([2e7]))[0] > sigma_for_population(np.array([2e5]))[0]


def test_allocated_points_are_inside_the_polygon_and_weights_close():
    rng = np.random.default_rng(0)
    pts, w = allocate_unit(
        SQUARE, (5.0, 5.0), np.array([[3.0, 3.0]]), np.array([2e6]), 60, rng
    )
    assert points_in_rings(pts, SQUARE).all()
    assert np.isclose(w.sum(), 1.0)
    assert len(pts) == 60


def test_allocation_concentrates_near_the_city():
    rng = np.random.default_rng(1)
    pts, w = allocate_unit(
        SQUARE, (5.0, 5.0), np.array([[2.0, 2.0]]), np.array([1e7]), 300, rng
    )
    centre_of_mass = (pts * w[:, None]).sum(axis=0)
    assert centre_of_mass[0] < 5.0 and centre_of_mass[1] < 5.0


def test_surface_weights_sum_to_one_per_unit():
    second = [np.array([[20.0, 20.0], [30.0, 20.0], [30.0, 30.0], [20.0, 30.0], [20.0, 20.0]])]
    pts = build_surface(
        polygons={"a": SQUARE, "b": second},
        centroids={"a": (5.0, 5.0), "b": (25.0, 25.0)},
        cities_by_unit={"a": (np.array([[5.0, 5.0]]), np.array([1e6]))},
        populations={"a": 4e6, "b": 1e6},
        total_points=200,
    )
    for unit in ("a", "b"):
        assert np.isclose(sum(p["w"] for p in pts if p["u"] == unit), 1.0, atol=1e-3)


def test_larger_units_get_more_anchors():
    second = [np.array([[20.0, 20.0], [30.0, 20.0], [30.0, 30.0], [20.0, 30.0], [20.0, 20.0]])]
    pts = build_surface(
        polygons={"a": SQUARE, "b": second},
        centroids={"a": (5.0, 5.0), "b": (25.0, 25.0)},
        cities_by_unit={},
        populations={"a": 1e8, "b": 1e5},
        total_points=400, min_points=5,
    )
    assert sum(1 for p in pts if p["u"] == "a") > sum(1 for p in pts if p["u"] == "b")


def test_units_without_population_are_skipped():
    pts = build_surface(
        polygons={"a": SQUARE}, centroids={"a": (5.0, 5.0)},
        cities_by_unit={}, populations={"a": 0.0}, total_points=100,
    )
    assert pts == []
