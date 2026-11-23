"""Verify Phase 3B float64 numeric normalization and caller immutability."""
from copy import deepcopy
from dataclasses import asdict

import numpy as np
import pytest

from sjtu_tpmshx.cpp_interface._native_values import grid_count, real_array, real_scalar
from sjtu_tpmshx.data_types.compute_config import (
    ComputeConfig, ExtrapPolicy, GeometryConfig, PartialBCConfig, SolverConfig,
)
from sjtu_tpmshx.preprocess import api
from tests.python import grid_source_reference as grid_reference


class _IndexCount:
    def __init__(self, value):
        self.value = value

    def __index__(self):
        return self.value


@pytest.mark.parametrize('value', [
    4, 4.5, np.int8(4), np.uint16(4), np.int32(4), np.int64(4),
    np.float16(4.5), np.float32(4.5), np.float64(4.5),
    np.asarray(4, dtype=np.int16), np.asarray(4.5, dtype=np.float32),
])
def test_real_scalar_promotes_real_inputs_to_float(value):
    result = real_scalar(value, name='sample')
    assert type(result) is float
    assert result == float(np.asarray(value))


@pytest.mark.parametrize('value', [True, False, np.bool_(True), 1 + 2j, np.complex128(3.0), '3.5', None, object()])
def test_real_scalar_rejects_non_real_types(value):
    with pytest.raises(TypeError):
        real_scalar(value, name='sample')


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), np.nan, np.inf, 10 ** 400])
def test_real_scalar_rejects_nonfinite_and_overflow_by_default(value):
    with pytest.raises((ValueError, OverflowError)):
        real_scalar(value, name='sample')


def test_real_scalar_allows_nonfinite_when_requested():
    assert np.isnan(real_scalar(float('nan'), allow_nonfinite=True))
    assert np.isinf(real_scalar(float('inf'), allow_nonfinite=True))


@pytest.mark.parametrize('value', [4, np.int16(4), np.uint32(4), _IndexCount(4)])
def test_grid_count_accepts_operator_index_integers(value):
    assert grid_count(value) == 4


@pytest.mark.parametrize('value', [True, False, np.bool_(True), 4.0, '4', 1 + 0j])
def test_grid_count_rejects_bool_and_non_index_types(value):
    with pytest.raises(TypeError):
        grid_count(value)


@pytest.mark.parametrize('value', [-1, 2 ** 80])
def test_grid_count_rejects_negative_and_size_t_overflow(value):
    with pytest.raises(ValueError):
        grid_count(value)


def test_real_array_promotes_numeric_arrays_and_rejects_bool_or_complex():
    for dtype in (np.int16, np.float16, np.float32, np.float64):
        out = real_array(np.array([[1, 2], [3, 4]], dtype=dtype), name='field')
        assert out.dtype == np.float64 and out.flags.c_contiguous
    for bad in (np.array([True, False]), np.array([1 + 2j]), np.array(['1.0'])):
        with pytest.raises(TypeError):
            real_array(bad, name='field')


@pytest.mark.parametrize('integer,floating', [(np.int8, np.float16), (np.int32, np.float32), (int, float)])
def test_prepare_case_2d_normalizes_to_float64_without_mutating_config(integer, floating):
    config = ComputeConfig(
        geometry=GeometryConfig(L_dom_m=integer(1), H_dom_m=np.int16(2), Lz_m=floating(.042)),
        solver=SolverConfig(Nx=12, Ny=12, Nz=1), extrap=ExtrapPolicy(allow=True),
        bc_A=PartialBCConfig(dir=0, in_ctr=integer(1), out_ctr=integer(1),
                             in_w=floating(.2), out_w=floating(.2), uniform_inlet_2d=True),
        bc_B=PartialBCConfig(dir=3, in_ctr=.5, out_ctr=.5,
                             in_w=1., out_w=1., uniform_inlet_2d=True))
    before = deepcopy(asdict(config))
    case = api.prepare_case(config, case_id='normalized-2d')
    assert asdict(config) == before
    assert type(config.geometry.L_dom_m) is integer
    assert type(config.bc_A.in_w) is floating

    port_a = dict(dir=0, in_ctr=1., out_ctr=1., in_w=float(floating(.2)), out_w=float(floating(.2)))
    port_b = dict(dir=3, in_ctr=.5, out_ctr=.5, in_w=1., out_w=1.)
    dx, dy, *_ = grid_reference.build_grid_2d(1., 2., 12, 12, (port_a, port_b))
    np.testing.assert_array_equal(case.grid['dx'], dx)
    np.testing.assert_array_equal(case.grid['dy'], dy)
    assert case.grid['dx'].dtype == np.float64 and case.grid['dy'].dtype == np.float64
    assert np.isclose(case.grid['dx'].sum(), 1.0, rtol=1e-12)
    assert np.isclose(case.grid['dy'].sum(), 2.0, rtol=1e-12)
    for field in ('eps_arr', 'K_ss_arr', 'L_field_m', 't_field_m'):
        assert case.design_fields[field].dtype == np.float64


@pytest.mark.parametrize('scalar_type', [np.float16, np.float32, np.float64])
def test_prepare_case_3d_normalizes_to_float64_without_mutating_config(scalar_type):
    config = ComputeConfig(
        geometry=GeometryConfig(
            L_dom_m=scalar_type(.08), H_dom_m=scalar_type(.06), Lz_m=scalar_type(.04),
            L_cell_mm=scalar_type(6.5), t_wall_mm=scalar_type(.45), k_s_W_mK=scalar_type(16.0)),
        solver=SolverConfig(Nx=4, Ny=4, Nz=3), extrap=ExtrapPolicy(allow=True))
    before = deepcopy(asdict(config))
    case = api.prepare_case(config, case_id='normalized-3d')
    assert asdict(config) == before
    assert type(config.geometry.L_dom_m) is scalar_type
    for axis, target in zip('xyz', (float(scalar_type(.08)), float(scalar_type(.06)), float(scalar_type(.04)))):
        assert case.grid['d' + axis].dtype == np.float64
        assert np.isclose(case.grid['d' + axis].sum(), target, rtol=1e-12)
    np.testing.assert_allclose(
        case.design_fields['eps_A'] + case.design_fields['eps_B'],
        case.design_fields['eps_arr'], rtol=1e-14, atol=1e-14)
    for field in ('eps_arr', 'eps_A', 'eps_B', 'K_m2', 'cF_per_m', 'K_ss'):
        assert case.design_fields[field].dtype == np.float64


def test_prepare_case_2d_rejects_bool_complex_and_string_scalars():
    for bad in (True, 1 + 2j, '0.1'):
        config = ComputeConfig(
            geometry=GeometryConfig(L_dom_m=bad),
            solver=SolverConfig(Nx=4, Ny=4, Nz=1), extrap=ExtrapPolicy(allow=True))
        with pytest.raises((TypeError, ValueError)):
            api.prepare_case(config, case_id='bad-scalar')
