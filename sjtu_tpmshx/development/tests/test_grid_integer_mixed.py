"""Keep NumPy integer and narrow-float promotion in physical grids.

Expected values use the frozen pre-port grid and port functions. The tests
use small ordinary domain values; they do not define a large-integer engine.
"""
import numpy as np
import pytest

from sjtu_tpmshx.development.tests import grid_ports_reference as ports_reference
from sjtu_tpmshx.development.tests import grid_source_reference as reference
from sjtu_tpmshx.shared.models import _native_grid as native
from sjtu_tpmshx.shared.models import grid


INTEGER_KINDS = (np.int8, np.uint8, np.int16, np.uint16,
                 np.int32, np.uint32, np.int64, np.uint64)
FLOAT_KINDS = (float, np.float16, np.float32, np.float64)


def _exact(actual, expected):
    actual, expected = np.asarray(actual), np.asarray(expected)
    assert actual.shape == expected.shape and actual.dtype == expected.dtype
    np.testing.assert_array_equal(actual, expected)


def _scalars(actual, expected):
    assert len(actual) == len(expected)
    for left, right in zip(actual, expected):
        assert type(left) is type(right)
        _exact(left, right)


def _port(integer_kind, float_kind):
    return dict(dir=0, in_ctr=integer_kind(1), out_ctr=integer_kind(1),
                in_w=float_kind(.2), out_w=float_kind(.3),
                in_z_ctr=integer_kind(1), out_z_ctr=integer_kind(1),
                in_z_w=float_kind(.25), out_z_w=float_kind(.375))


@pytest.mark.parametrize('integer_kind', INTEGER_KINDS)
@pytest.mark.parametrize('float_kind', FLOAT_KINDS)
def test_port_edges_keep_integer_center_and_floating_width_promotion(integer_kind, float_kind):
    config = _port(integer_kind, float_kind)
    # The frozen rectangle body has the same original first-cross-axis expression.
    expected = ports_reference._port_rectangles(config, integer_kind(2))
    first = [*expected['inlet_rect'][:2], *expected['outlet_rect'][:2]]
    second = [*expected['inlet_rect'][2:], *expected['outlet_rect'][2:]]
    lengths = (integer_kind(1), integer_kind(2), integer_kind(2))
    _scalars(native.port_edges(lengths, (config,), 1), first)
    _scalars(native.port_edges(lengths, (config,), 2), second)
    actual = list(grid._port_wall_axes(lengths, (config,)))
    old = list(reference._port_wall_axes(lengths, (config,)))
    for left, right in zip(actual, old):
        _scalars(left[0], right[0])
        assert left[1:] == right[1:]


@pytest.mark.parametrize('integer_kind', INTEGER_KINDS)
@pytest.mark.parametrize('float_kind', FLOAT_KINDS)
@pytest.mark.parametrize('port_wall_refine', [False, True])
def test_integer_domain_mixed_ports_keep_exact_2d_widths_and_breaks(integer_kind, float_kind, port_wall_refine):
    length, height = integer_kind(1), integer_kind(2)
    config = _port(integer_kind, float_kind)
    arguments = (length, height, 96, 96, (config,))
    actual = grid.build_grid_2d(*arguments, port_wall_refine=port_wall_refine)
    expected = reference.build_grid_2d(*arguments, port_wall_refine=port_wall_refine)
    _exact(actual[0], expected[0])
    _exact(actual[1], expected[1])
    _scalars(actual[2], expected[2])
    _scalars(actual[3], expected[3])
    assert actual[4] == expected[4]


@pytest.mark.parametrize('integer_kind', INTEGER_KINDS)
@pytest.mark.parametrize('float_kind', FLOAT_KINDS)
def test_integer_domain_and_narrow_breakpoints_keep_aligned_arithmetic(integer_kind, float_kind):
    length = integer_kind(2)
    points = [float_kind(.002), float_kind(.125), float_kind(.49),
              float_kind(1.75), float_kind(1.998)]
    epsilon = length * .001
    bounds = sorted(set([0.] + [point for point in points if epsilon < point < length - epsilon] + [length]))
    _scalars(native.aligned_bounds(length, points), bounds)
    _exact(grid._aligned_grid(37, length, points), reference._aligned_grid(37, length, points))


@pytest.mark.parametrize('integer_kind', INTEGER_KINDS)
@pytest.mark.parametrize('float_kind', FLOAT_KINDS)
def test_integer_port_centers_keep_3d_rectangles_and_partial_masks(integer_kind, float_kind):
    config = _port(integer_kind, float_kind)
    config['dir'] = 5
    actual = native.rectangles(config, integer_kind(2))
    expected = ports_reference._port_rectangles(config, integer_kind(2))
    for key in ('inlet_rect', 'outlet_rect'):
        _scalars(actual[key], expected[key])
    first = np.array([.2, .3, .4, .1, .25, .5, .25], dtype=np.float64)
    second = np.full(16, .125)
    actual_masks = native.partial_masks(config, first, second, len(second))
    expected_masks = ports_reference._build_partial_masks(config, first, second, len(second))
    for left, right in zip(actual_masks, expected_masks):
        _exact(left, right)
        for threshold in (0., .01, .5, .99):
            np.testing.assert_array_equal(left > threshold, right > threshold)


@pytest.mark.parametrize('integer_kind', INTEGER_KINDS)
def test_integer_endpoint_first_max_keeps_numpy_spacing_type(integer_kind):
    widths = np.full(1024, 2.**-10)
    lower, upper = integer_kind(0), integer_kind(1)
    _exact(grid._port_overlap_1d(widths, lower, upper),
           reference._port_overlap_1d(widths, lower, upper))


def test_public_prepare_keeps_valid_integer_center_and_half_width_contract():
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.shared.domain.compute_config import (
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
    port_a = dict(dir=0, in_ctr=center, out_ctr=center, in_w=width, out_w=width)
    port_b = dict(dir=3, in_ctr=.5, out_ctr=.5, in_w=1., out_w=1.)
    expected = reference.build_grid_2d(length, height, 12, 12, (port_a, port_b))
    rectangle = ports_reference._port_rectangles(port_a, 1.)['inlet_rect']
    assert type(rectangle[0]) is np.float16
    assert rectangle[0] == .89990234375 and rectangle[1] == 1.099609375
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
