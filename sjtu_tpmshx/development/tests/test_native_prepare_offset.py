"""Preserve the existing 2D offset preparation and its rejection sequence."""
import ctypes as ct
from dataclasses import asdict, replace
from itertools import product

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import preparation_api_reference as reference
from sjtu_tpmshx.development.tests import test_native_preparation_spatial_flow as raw
from sjtu_tpmshx.development.tests.test_native_prepare_adapter import (
    _capture, _same, _cache_info, _observe_prepare, uniform,
)
from sjtu_tpmshx.development.tests.test_native_prepare_spatial_adapter import configuration
from sjtu_tpmshx.preprocess import api
from sjtu_tpmshx.preprocess.two_d import preparation as host
from sjtu_tpmshx.shared.models import _native_preparation_case as native
from sjtu_tpmshx.shared.models.tpms_calc import compute
from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry


@pytest.fixture(autouse=True)
def clear_caches():
    compute.cache_clear()
    compute_geometry.cache_clear()
    yield
    compute.cache_clear()
    compute_geometry.cache_clear()


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(('air', 'water'), repeat=2)))
@pytest.mark.parametrize('delta', [-.2, .2])
@pytest.mark.parametrize('direction', [0, 1, 2, 3])
def test_uniform_offset_exact_contract(monkeypatch, topology, pair, delta, direction):
    config = uniform._configuration(topology, pair)
    config.geometry.delta_levelset = delta
    config.bc_A = replace(config.bc_A, dir=direction, in_w=0., out_w=0.)
    config.bc_B = replace(config.bc_B, dir=(direction + 2) % 4, in_w=0., out_w=0.)
    before = asdict(config)
    expected = _capture(monkeypatch, reference, 'full', config)
    counts = _cache_info(reference)
    _same(_capture(monkeypatch, api, 'full', config), expected)
    assert _cache_info() == counts
    _same(asdict(config), before)


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('delta', [-.2, .2])
@pytest.mark.parametrize('direction', [0, 1, 2, 3])
def test_spatial_offset_exact_contract(monkeypatch, tmp_path, mode, topology, delta, direction):
    config = configuration(monkeypatch, tmp_path, mode, topology)
    config.geometry.delta_levelset = delta
    config.bc_A = replace(config.bc_A, dir=direction, in_w=0., out_w=0.)
    config.bc_B = replace(config.bc_B, dir=(direction + 2) % 4, in_w=0., out_w=0.)
    before = asdict(config)
    expected = _capture(monkeypatch, reference, 'full', config)
    counts = _cache_info(reference)
    _same(_capture(monkeypatch, api, 'full', config), expected)
    assert _cache_info() == counts
    _same(asdict(config), before)


@pytest.mark.parametrize('mode', ['uniform', 'x', 'grid', 'sigmoid'])
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_offset_keeps_explicit_float_geometry_on_refined_grid(monkeypatch, tmp_path, mode, dtype):
    config = (uniform._configuration('Gyroid', ('air', 'water')) if mode == 'uniform'
              else configuration(monkeypatch, tmp_path, mode))
    config.geometry.delta_levelset = dtype(.15)
    config.geometry.L_cell_mm = dtype(6.8)
    config.geometry.t_wall_mm = dtype(.45)
    config.geometry.k_s_W_mK = dtype(config.geometry.k_s_W_mK)
    config.solver.Nx = config.solver.Ny = 64
    config.flags = replace(config.flags, port_wall_refine=True)
    config.bc_B = replace(config.bc_B, in_w=0., out_w=0.)
    span = config.geometry.H_dom_m
    config.bc_A = replace(config.bc_A, in_ctr=.5*span, in_w=.5*span, out_ctr=.5*span, out_w=.5*span)
    _same(_capture(monkeypatch, api, 'full', config), _capture(monkeypatch, reference, 'full', config))


@pytest.mark.parametrize('mode', ['uniform', 'x', 'grid', 'sigmoid'])
@pytest.mark.parametrize('operation,targets', [('capacity', None), ('resolve', (.001, .002)),
    ('full', (.001, .002)), ('configured', None)])
@pytest.mark.parametrize('problem', ['offset', 'water', 'chi', 'depth', 'nonair'])
def test_rejected_offset_preserves_first_error_and_observations(monkeypatch, tmp_path, mode, operation, targets, problem):
    config = (uniform._configuration('Gyroid', ('air', 'water')) if mode == 'uniform'
              else configuration(monkeypatch, tmp_path, mode))
    config.geometry.delta_levelset = .2
    config.fluid_A.u_mps = float('nan')
    if operation == 'configured':
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .001, .002
        operation = 'full'
    if problem == 'water':
        config.fluid_B.type, config.fluid_B.T_in_K = 'water', 200.
    elif problem == 'chi':
        monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
    elif problem == 'depth':
        config.geometry.Lz_m = None
    elif problem == 'nonair' and mode != 'uniform':
        config.fluid_B.type = 'water'
    expected = _observe_prepare(monkeypatch, reference, operation, config, targets, scoped=True)
    counts = _cache_info(reference)
    actual = _observe_prepare(monkeypatch, api, operation, config, targets, scoped=True)
    _same(actual, expected)
    assert _cache_info() == counts


@pytest.mark.parametrize('mode', ['x', 'grid', 'sigmoid'])
@pytest.mark.parametrize('failure', ['air-guard', 'water-state', 'preflight', 'nominal-chi'])
def test_nonair_spatial_guard_keeps_earlier_work(monkeypatch, tmp_path, mode, failure):
    config = configuration(monkeypatch, tmp_path, mode)
    config.fluid_B.type = 'water'
    if failure == 'water-state':
        config.fluid_B.T_in_K = 200.
    elif failure == 'preflight':
        config.fluid_A.u_mps = 1.e-6
        config.extrap = replace(config.extrap, allow=False)
    elif failure == 'nominal-chi':
        monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
    expected = _observe_prepare(monkeypatch, reference, 'full', config, scoped=True)
    counts = _cache_info(reference)
    _same(_observe_prepare(monkeypatch, api, 'full', config, scoped=True), expected)
    assert _cache_info() == counts


@pytest.mark.parametrize('mode', ['uniform', 'x', 'sigmoid'])
@pytest.mark.parametrize('destination', ['error', 'failure'])
@pytest.mark.parametrize('invalid', [None, 'source', 'result'])
def test_offset_owned_buffers_survive_diagnostic_aliases(monkeypatch, tmp_path, mode, destination, invalid):
    config = (uniform._configuration('Gyroid', ('air', 'water')) if mode == 'uniform'
              else configuration(monkeypatch, tmp_path, mode))
    config.geometry.delta_levelset = .2
    source = host._input(config, None, 'prepare_flow_case')
    if mode == 'sigmoid':
        lut_cache = host._lut_cache()
        lut_cache(0, 1, 16, source.values.values.lut)
        source.model.load_default_lut = 0
    result_type = (native._OffsetFlowCase if mode == 'uniform' else
                   native._OffsetSigmoidCase if mode == 'sigmoid' else native._OffsetZonedCase)
    result = result_type(10, ct.sizeof(result_type))
    bindings = native._bindings(native._native_preparation._library().path)
    call = bindings.operations[10, type(source), 'prepare_flow_case']
    options = native._Options(1, ct.sizeof(native._Options), 0, 1, 0.)
    failure, error = native._Failure(2, ct.sizeof(native._Failure)), ct.create_string_buffer(4096)
    assert call(ct.byref(source), ct.byref(source._grid_kinds), ct.byref(options), None,
                ct.byref(result), ct.byref(failure), error, len(error)) == 0, error.value.decode()
    try:
        if invalid is not None:
            (source if invalid == 'source' else result).abi_version = 0
        def rejected(failure, error, capacity):
            return call(ct.byref(source), ct.byref(source._grid_kinds), ct.byref(options), None,
                        ct.byref(result), ct.cast(failure, ct.POINTER(native._Failure)), error, capacity)
        assert raw._check_owned_aliases(rejected, result, destination)
    finally:
        bindings.releases[result_type](ct.byref(result))
        assert not result.owner


@pytest.mark.parametrize('dtype', [np.float16, np.float32])
def test_offset_narrow_endpoint_keeps_original_df_rejection(monkeypatch, dtype):
    config = uniform._configuration('Gyroid', ('air', 'water'))
    config.geometry.delta_levelset = dtype(.15)
    config.geometry.t_wall_mm = dtype(.6)
    expected = _observe_prepare(monkeypatch, reference, 'full', config, scoped=True)
    assert expected[1] and 'fixed sCO2 CFD grid' in str(expected[1])
    _same(_observe_prepare(monkeypatch, api, 'full', config, scoped=True), expected)
