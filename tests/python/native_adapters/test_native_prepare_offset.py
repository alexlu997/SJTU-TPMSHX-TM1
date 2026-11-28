"""Verify 2D offset preparation invariants, float64 normalization, and C ABI guards."""
import ctypes as ct
from dataclasses import asdict, replace
from itertools import product

import numpy as np
import pytest

from tm1.cpp_interface import _native_preparation_case as native, preparation_host
from tm1.cpp_interface import native_preparation as binding
from tm1.preprocess.two_d import preparation
from tm1.physical_models.fluid_props import WaterStateError
from tm1.physical_models.tpms_calc import compute
from tm1.physical_models.tpms_geometry import compute_geometry
from tm1.preprocess import api
from tests.python import native_preparation_abi
from tests.python.native_adapters.test_native_prepare_adapter import _capture, _same
from tests.python.native_adapters.test_native_prepare_spatial_adapter import configuration


@pytest.fixture(autouse=True)
def clear_caches():
    compute.cache_clear()
    compute_geometry.cache_clear()
    yield
    compute.cache_clear()
    compute_geometry.cache_clear()


def _check_offset_case(case, delta):
    eps = case.design_fields['eps_arr']
    assert eps.dtype == np.float64 and np.all(np.isfinite(eps))
    thermal = case.parameters['thermal_geometry']
    uniform = thermal['uniform']
    assert uniform['epsilon_A'] + uniform['epsilon_B'] == pytest.approx(uniform['epsilon'], rel=1e-14)
    if delta > 0.:
        assert thermal['split_A'] > .5
    else:
        assert thermal['split_A'] < .5
    sides = thermal['side_geometry']
    assert set(sides) == {'A', 'B'}
    for side in 'AB':
        values = np.asarray(sides[side], dtype=np.float64)
        assert values.shape == (4,) and np.all(np.isfinite(values)) and np.all(values > 0.)


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(('air', 'water'), repeat=2)))
@pytest.mark.parametrize('delta', [-.2, .2])
@pytest.mark.parametrize('direction', [0, 1, 2, 3])
def test_uniform_offset_invariants(monkeypatch, topology, pair, delta, direction):
    config = native_preparation_abi._configuration_mass_flow(topology, pair)
    config.geometry.delta_levelset = delta
    config.bc_A = replace(config.bc_A, dir=direction, in_w=0., out_w=0.)
    config.bc_B = replace(config.bc_B, dir=(direction + 2) % 4, in_w=0., out_w=0.)
    before = asdict(config)
    case, _, _, _ = _capture(monkeypatch, api, 'full', config)
    _check_offset_case(case, delta)
    _same(asdict(config), before)


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('delta', [-.2, .2])
@pytest.mark.parametrize('direction', [0, 1, 2, 3])
def test_spatial_offset_invariants(monkeypatch, tmp_path, mode, topology, delta, direction):
    config = configuration(monkeypatch, tmp_path, mode, topology)
    config.geometry.delta_levelset = delta
    config.bc_A = replace(config.bc_A, dir=direction, in_w=0., out_w=0.)
    config.bc_B = replace(config.bc_B, dir=(direction + 2) % 4, in_w=0., out_w=0.)
    before = asdict(config)
    case, _, _, _ = _capture(monkeypatch, api, 'full', config)
    _check_offset_case(case, delta)
    _same(asdict(config), before)


@pytest.mark.parametrize('mode', ['uniform', 'x', 'grid', 'sigmoid'])
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_offset_normalizes_float_geometry_on_refined_grid(monkeypatch, tmp_path, mode, dtype):
    def make_config(cast):
        config = (native_preparation_abi._configuration_mass_flow('Gyroid', ('air', 'water')) if mode == 'uniform'
                  else configuration(monkeypatch, tmp_path, mode))
        config.geometry.delta_levelset = cast(.15)
        config.geometry.L_cell_mm = cast(6.8)
        config.geometry.t_wall_mm = cast(.45)
        config.geometry.k_s_W_mK = cast(config.geometry.k_s_W_mK)
        config.solver.Nx = config.solver.Ny = 64
        config.flags = replace(config.flags, port_wall_refine=True)
        config.bc_B = replace(config.bc_B, in_w=0., out_w=0.)
        span = config.geometry.H_dom_m
        config.bc_A = replace(config.bc_A, in_ctr=.5 * span, in_w=.5 * span, out_ctr=.5 * span, out_w=.5 * span)
        return config

    actual, actual_events, actual_r, actual_rl = _capture(monkeypatch, api, 'full', make_config(dtype))
    expected, expected_events, expected_r, expected_rl = _capture(
        monkeypatch, api, 'full', make_config(lambda value: float(dtype(value))))
    _same(actual.grid, expected.grid, 'grid')
    _same(actual.design_fields, expected.design_fields, 'design_fields')
    for key in ('L_cell_m', 't_wall_m', 'eps', 'r_h', 'thermal_geometry', 'flow_inputs', 'static_properties'):
        _same(actual.parameters[key], expected.parameters[key], 'parameters.' + key)
    assert actual_events == expected_events
    assert actual_r == expected_r and actual_rl == expected_rl


@pytest.mark.parametrize('mode', ['uniform', 'x', 'grid', 'sigmoid'])
@pytest.mark.parametrize('operation,targets', [('capacity', None), ('resolve', (.001, .002)),
    ('full', (.001, .002)), ('configured', None)])
@pytest.mark.parametrize('problem', ['offset', 'water', 'chi', 'depth', 'nonair'])
def test_rejected_offset_raises_expected_error(monkeypatch, tmp_path, mode, operation, targets, problem):
    config = (native_preparation_abi._configuration_mass_flow('Gyroid', ('air', 'water')) if mode == 'uniform'
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
    expected_error = ((WaterStateError, ValueError) if problem == 'water'
                      else (NotImplementedError, ValueError) if problem == 'nonair' else ValueError)
    with pytest.raises(expected_error):
        _capture(monkeypatch, api, operation, config, targets)


@pytest.mark.parametrize('mode', ['x', 'grid', 'sigmoid'])
@pytest.mark.parametrize('failure', ['air-guard', 'water-state', 'preflight', 'nominal-chi'])
def test_nonair_spatial_guard_reports_failure(monkeypatch, tmp_path, mode, failure):
    config = configuration(monkeypatch, tmp_path, mode)
    config.fluid_B.type = 'water'
    if failure == 'water-state':
        config.fluid_B.T_in_K = 200.
    elif failure == 'preflight':
        config.fluid_A.u_mps = 1.e-6
        config.extrap = replace(config.extrap, allow=False)
    elif failure == 'nominal-chi':
        monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
    expected_error = (WaterStateError if failure == 'water-state'
                      else NotImplementedError if failure == 'air-guard' else ValueError)
    with pytest.raises(expected_error):
        _capture(monkeypatch, api, 'full', config)


@pytest.mark.parametrize('mode', ['uniform', 'x', 'sigmoid'])
@pytest.mark.parametrize('destination', ['error', 'failure'])
@pytest.mark.parametrize('invalid', [None, 'source', 'result'])
def test_offset_owned_buffers_survive_diagnostic_aliases(monkeypatch, tmp_path, mode, destination, invalid):
    config = (native_preparation_abi._configuration_mass_flow('Gyroid', ('air', 'water')) if mode == 'uniform'
              else configuration(monkeypatch, tmp_path, mode))
    config.geometry.delta_levelset = .2
    source, problem = binding.pack_input(config, None, lambda fluid: fluid.u_mps, preparation._spatial_rows)
    assert problem is None
    if mode == 'sigmoid':
        lut_cache = binding._lut_cache(preparation._lut_cache())
        lut_cache(0, 1, 16, source.lut)
        source.model.load_default_lut = 0
    family = 'uniform' if mode == 'uniform' else 'sigmoid' if mode == 'sigmoid' else 'zoned'
    result_type = (native._UniformCase if mode == 'uniform' else
                   native._SigmoidCase if mode == 'sigmoid' else native._ZonedCase)
    result = result_type(1, ct.sizeof(result_type))
    bindings = preparation_host._bindings(preparation_host.preparation_library.path())
    call = bindings.operations[family, 'prepare_flow_case'].call
    options = native._Options(1, ct.sizeof(native._Options), 0, 1, 0.)
    failure, error = native._Failure(2, ct.sizeof(native._Failure)), ct.create_string_buffer(4096)
    assert call(ct.byref(source), ct.byref(options), None,
                ct.byref(result), ct.byref(failure), error, len(error)) == 0, error.value.decode()
    try:
        if invalid is not None:
            (source if invalid == 'source' else result).abi_version = 0
        def rejected(failure, error, capacity):
            return call(ct.byref(source), ct.byref(options), None,
                        ct.byref(result), ct.cast(failure, ct.POINTER(native._Failure)), error, capacity)
        assert native_preparation_abi._check_owned_aliases_spatial(rejected, result, destination)
    finally:
        bindings.releases[result_type](ct.byref(result))
        assert not result.owner


@pytest.mark.parametrize('dtype', [np.float16, np.float32])
def test_offset_narrow_endpoint_keeps_df_rejection(monkeypatch, dtype):
    config = native_preparation_abi._configuration_mass_flow('Gyroid', ('air', 'water'))
    config.geometry.delta_levelset = dtype(.15)
    config.geometry.t_wall_mm = dtype(.6)
    with pytest.raises(ValueError, match='V2 geometry must lie inside the CFD grid'):
        _capture(monkeypatch, api, 'full', config)


@pytest.mark.parametrize('mode', ['uniform', 'x', 'sigmoid'])
@pytest.mark.parametrize('field', ['abi_version', 'struct_size'])
def test_offset_nested_headers_preserve_result(monkeypatch, tmp_path, mode, field):
    config = (native_preparation_abi._configuration_mass_flow('Gyroid', ('air', 'water')) if mode == 'uniform'
              else configuration(monkeypatch, tmp_path, mode))
    config.geometry.delta_levelset = .2
    source, problem = binding.pack_input(config, None, lambda fluid: fluid.u_mps, preparation._spatial_rows)
    assert problem is None
    if mode == 'sigmoid':
        binding._lut_cache(preparation._lut_cache())(0, 1, 16, source.lut)
        source.model.load_default_lut = 0
    family = 'uniform' if mode == 'uniform' else 'sigmoid' if mode == 'sigmoid' else 'zoned'
    result_type = (native._UniformCase if mode == 'uniform' else
                   native._SigmoidCase if mode == 'sigmoid' else native._ZonedCase)
    result = result_type(1, ct.sizeof(result_type))
    bindings = preparation_host._bindings(preparation_host.preparation_library.path())
    call = bindings.operations[family, 'prepare_flow_case'].call
    options = native._Options(1, ct.sizeof(native._Options), 0, 1, 0.)
    failure, error = native._Failure(2, ct.sizeof(native._Failure)), ct.create_string_buffer(4096)
    targets = [source, source.input]
    for target in [*targets, result]:
        previous = getattr(target, field)
        setattr(target, field, 0)
        before = bytes(result)
        error.value = b''
        try:
            status = call(ct.byref(source), ct.byref(options), None,
                          ct.byref(result), ct.byref(failure), error, len(error))
            assert status == 1 and error.value and bytes(result) == before
        finally:
            setattr(target, field, previous)
            if result.owner:
                bindings.releases[result_type](ct.byref(result))
