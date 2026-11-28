"""Verify float64 promotion of NumPy integers and narrow floats in physical grids."""
import numpy as np
import pytest

from tests.python import grid_ports_reference as ports_reference
from tests.python import grid_source_reference as reference
from tm1.cpp_interface import _native_grid as native
from tm1.physical_models import grid


# Each pair covers a different integer width and floating kind. The native
# boundary converts every pair to float64, so a full product adds no case.
MIXED_KINDS = [(np.int8, np.float16), (np.int64, np.float32), (np.uint64, float)]


def _exact(actual, expected):
    actual, expected = np.asarray(actual), np.asarray(expected)
    assert actual.shape == expected.shape and actual.dtype == expected.dtype
    np.testing.assert_array_equal(actual, expected)


def _scalars(actual, expected):
    assert len(actual) == len(expected)
    for left, right in zip(actual, expected):
        assert type(left) is float and type(right) is float
        _exact(left, right)


def _port(integer_kind, float_kind):
    return dict(dir=0, in_ctr=integer_kind(1), out_ctr=integer_kind(1),
                in_w=float_kind(.2), out_w=float_kind(.3),
                in_z_ctr=integer_kind(1), out_z_ctr=integer_kind(1),
                in_z_w=float_kind(.25), out_z_w=float_kind(.375))


def _f64_port(port):
    return {key: (value if key == 'dir' else float(value)) for key, value in port.items()}


@pytest.mark.parametrize('integer_kind,float_kind', MIXED_KINDS)
def test_port_edges_promote_integer_center_and_floating_width_to_float64(integer_kind, float_kind):
    config = _port(integer_kind, float_kind)
    ref_config = _f64_port(config)
    expected = ports_reference._port_rectangles(ref_config, 2.)
    first = [float(v) for v in (*expected['inlet_rect'][:2], *expected['outlet_rect'][:2])]
    second = [float(v) for v in (*expected['inlet_rect'][2:], *expected['outlet_rect'][2:])]
    lengths = (integer_kind(1), integer_kind(2), integer_kind(2))
    _scalars(native.port_edges(lengths, (config,), 1), first)
    _scalars(native.port_edges(lengths, (config,), 2), second)
    actual = list(grid._port_wall_axes(lengths, (config,)))
    old = list(reference._port_wall_axes((1., 2., 2.), (ref_config,)))
    for left, right in zip(actual, old):
        _scalars(left[0], [float(v) for v in right[0]])
        assert left[1:] == right[1:]


@pytest.mark.parametrize('integer_kind,float_kind', MIXED_KINDS)
@pytest.mark.parametrize('port_wall_refine', [False, True])
def test_integer_domain_mixed_ports_promote_to_float64_2d_widths_and_breaks(integer_kind, float_kind, port_wall_refine):
    length, height = integer_kind(1), integer_kind(2)
    config = _port(integer_kind, float_kind)
    actual = grid.build_grid_2d(length, height, 96, 96, (config,), port_wall_refine=port_wall_refine)
    expected = reference.build_grid_2d(float(length), float(height), 96, 96, (_f64_port(config),),
                                       port_wall_refine=port_wall_refine)
    _exact(actual[0], expected[0])
    _exact(actual[1], expected[1])
    _scalars(actual[2], [float(v) for v in expected[2]])
    _scalars(actual[3], [float(v) for v in expected[3]])
    assert actual[4] == expected[4]


@pytest.mark.parametrize('integer_kind,float_kind', MIXED_KINDS)
def test_integer_domain_and_narrow_breakpoints_promote_to_float64_aligned(integer_kind, float_kind):
    length = integer_kind(2)
    points = [float_kind(.002), float_kind(.125), float_kind(.49),
              float_kind(1.75), float_kind(1.998)]
    f64_length = float(length)
    f64_points = [float(p) for p in points]
    epsilon = f64_length * .001
    bounds = sorted(set([0.] + [point for point in f64_points if epsilon < point < f64_length - epsilon] + [f64_length]))
    _scalars(native.aligned_bounds(length, points), bounds)
    _exact(grid._aligned_grid(37, length, points), reference._aligned_grid(37, f64_length, f64_points))


@pytest.mark.parametrize('integer_kind,float_kind', MIXED_KINDS)
def test_integer_port_centers_promote_3d_rectangles_and_partial_masks(integer_kind, float_kind):
    config = _port(integer_kind, float_kind)
    config['dir'] = 5
    ref_config = _f64_port(config)
    actual = native.rectangles(config, integer_kind(2))
    expected = ports_reference._port_rectangles(ref_config, 2.)
    for key in ('inlet_rect', 'outlet_rect'):
        _scalars(actual[key], [float(v) for v in expected[key]])
    first = np.array([.2, .3, .4, .1, .25, .5, .25], dtype=np.float64)
    second = np.full(16, .125)
    actual_masks = native.partial_masks(config, first, second, len(second))
    expected_masks = ports_reference._build_partial_masks(ref_config, first, second, len(second))
    for left, right in zip(actual_masks, expected_masks):
        _exact(left, right)
        for threshold in (0., .01, .5, .99):
            np.testing.assert_array_equal(left > threshold, right > threshold)


@pytest.mark.parametrize('integer_kind', [np.int8, np.uint64])
def test_integer_endpoint_first_max_promotes_to_float64(integer_kind):
    widths = np.full(1024, 2.**-10)
    lower, upper = integer_kind(0), integer_kind(1)
    _exact(grid._port_overlap_1d(widths, lower, upper),
           reference._port_overlap_1d(widths, float(lower), float(upper)))


def test_public_prepare_promotes_integer_center_and_half_width_without_mutating_config():
    from tm1.preprocess.api import prepare_case
    from tm1.data_types.compute_config import (
        ComputeConfig, ExtrapPolicy, GeometryConfig, PartialBCConfig, SolverConfig,
    )

    length, height = np.int8(1), np.int16(2)
    center, width = np.int8(1), np.float16(.2)
    config = ComputeConfig(
        geometry=GeometryConfig(L_dom_m=length, H_dom_m=height),
        solver=SolverConfig(Nx=12, Ny=12, Nz=1), extrap=ExtrapPolicy(allow=True),
        bc_A=PartialBCConfig(dir=0, in_ctr=center, out_ctr=center,
                             in_w=width, out_w=width, uniform_inlet_2d=True),
        bc_B=PartialBCConfig(dir=3, in_ctr=.5, out_ctr=.5,
                             in_w=1., out_w=1., uniform_inlet_2d=True))
    config.validate()
    assert type(config.geometry.L_dom_m) is np.int8
    assert type(config.geometry.H_dom_m) is np.int16
    assert type(config.bc_A.in_ctr) is np.int8
    assert type(config.bc_A.in_w) is np.float16
    port_a = dict(dir=0, in_ctr=float(center), out_ctr=float(center), in_w=float(width), out_w=float(width))
    port_b = dict(dir=3, in_ctr=.5, out_ctr=.5, in_w=1., out_w=1.)
    expected = reference.build_grid_2d(float(length), float(height), 12, 12, (port_a, port_b))
    rectangle = ports_reference._port_rectangles(port_a, 1.)['inlet_rect']
    case = prepare_case(config, case_id='integer-center-half-width')
    _exact(case.grid['dx'], expected[0])
    _exact(case.grid['dy'], expected[1])
    np.testing.assert_array_equal(case.grid['y_breaks'], expected[3])
    openings = case.parameters['boundary_openings']['A']
    raw, profile = reference._port_fractions_1d(
        expected[1], rectangle[0], rectangle[1], uniform=True)
    _exact(openings['in_geom_frac'], raw)
    _exact(openings['in_profile_frac'], profile)
    # Preparation must not rewrite the caller's retained configuration values.
    assert type(config.bc_A.in_ctr) is np.int8 and type(config.bc_A.in_w) is np.float16
