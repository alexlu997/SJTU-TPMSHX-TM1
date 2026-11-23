"""Verify 3D native host preparation contracts, invariants, persistence and errors."""
from copy import deepcopy
import ctypes as ct
from dataclasses import asdict, replace
import gc
from itertools import product

import numpy as np
import pytest

from sjtu_tpmshx.cpp_interface._native_values import copy_array, read_text
from sjtu_tpmshx.data_types.compute_config import PartialBCConfig
from sjtu_tpmshx.file_io.case_io import load_case, save_case
from sjtu_tpmshx.physical_models.tpms_calc import compute
from sjtu_tpmshx.physical_models.tpms_geometry import compute_geometry
from sjtu_tpmshx.preprocess import api
from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
from tests.python import native_preparation_abi, property_reference as prop_ref
from tests.python import test_native_preparation_continuous_3d as continuous
from tests.python import test_native_preparation_spatial_3d as spatial
from tests.python.test_native_prepare_adapter import _capture, _same


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch):
    for name in ('TPMSHX_CHI_S', 'TPMSHX_ALLOW_EXTRAP', 'TPMSHX_MAX_CELLS_3D'):
        monkeypatch.delenv(name, raising=False)
    yield
    compute.cache_clear()
    compute_geometry.cache_clear()


def _configuration(mode, topology='Gyroid', pair=('air', 'water')):
    if mode in ('xy', 'xyz'):
        return continuous._configuration(topology, pair, nz=3 if mode == 'xyz' else None)
    if mode in ('grid', 'offset'):
        return spatial._configuration(topology, pair, spatial=mode == 'grid', delta=.12)
    return native_preparation_abi._configuration_3d(topology, pair)


def _check_3d_case_invariants(case, config):
    lengths = (float(config.geometry.L_dom_m), float(config.geometry.H_dom_m), float(config.geometry.Lz_m))
    shape = tuple(len(case.grid['d' + axis]) for axis in 'xyz')
    for axis, target in zip('xyz', lengths):
        widths = case.grid['d' + axis]
        assert widths.dtype == np.float64 and np.all(widths > 0.)
        assert widths.sum() == pytest.approx(target, rel=1e-12)
    for key in ('L_field_m', 't_field_m', 'eps_arr', 'eps_A', 'eps_B', 'K_m2', 'cF_per_m', 'K_ss'):
        field = case.design_fields[key]
        assert field.shape == shape and field.dtype == np.float64 and np.all(np.isfinite(field))
        assert not field.flags.writeable
    np.testing.assert_allclose(
        case.design_fields['eps_A'] + case.design_fields['eps_B'],
        case.design_fields['eps_arr'], rtol=1e-14, atol=1e-14)
    for side in 'AB':
        fluid = getattr(config, 'fluid_' + side)
        props = prop_ref.fluid_props(fluid.type, float(fluid.T_in_K), float(fluid.P_in_Pa))
        recorded = case.parameters['prepared']['properties'][side]
        assert recorded['rho'] == pytest.approx(props.rho, rel=1e-12)
        assert recorded['mu'] == pytest.approx(props.mu, rel=1e-12)
        assert recorded['k'] == pytest.approx(props.k, rel=1e-12)


@pytest.mark.parametrize('mode', ['uniform', 'xy', 'xyz'])
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(('air', 'water', 'sco2', 'co2'), repeat=2)))
def test_complete_case_satisfies_physical_invariants(monkeypatch, mode, topology, pair):
    config = _configuration(mode, topology, pair)
    before = deepcopy(asdict(config))
    case, _, _, _ = _capture(monkeypatch, api, 'full', config)
    _check_3d_case_invariants(case, config)
    _same(asdict(config), before, 'unchanged input')


@pytest.mark.parametrize('mode', ['uniform', 'xy', 'xyz', 'grid', 'offset'])
@pytest.mark.parametrize('explicit', [False, True])
def test_fixed_and_configured_flows_agree_with_capacities(monkeypatch, mode, explicit):
    config = _configuration(mode)
    targets = (.001, .01) if explicit else None
    config.fluid_A.u_mps, config.fluid_B.u_mps = -99., -88.
    if not explicit:
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .001, .01
    caps, _, _, _ = _capture(monkeypatch, api, 'capacity', config)
    resolved, _, _, _ = _capture(monkeypatch, api, 'resolve', config, targets)
    case, _, _, _ = _capture(monkeypatch, api, 'full', config, targets)
    for side, target in zip('AB', (.001, .01)):
        expected_u = target / caps[side]
        assert getattr(resolved, 'fluid_' + side).u_mps == pytest.approx(expected_u, rel=1e-13)
        assert case.parameters['u_' + side] == pytest.approx(expected_u, rel=1e-13)


@pytest.mark.parametrize('mode', ['uniform', 'xy', 'xyz', 'grid', 'offset'])
@pytest.mark.parametrize('selection', ['cap', 'cap-negative', 'roughness', 'chi'])
def test_host_environment_errors_are_reported(monkeypatch, mode, selection):
    config = _configuration(mode)
    if selection == 'cap':
        monkeypatch.setenv('TPMSHX_MAX_CELLS_3D', 'bad')
    elif selection == 'cap-negative':
        monkeypatch.setenv('TPMSHX_MAX_CELLS_3D', '-5')
    elif selection == 'roughness':
        monkeypatch.setenv('TPMSHX_ROUGH_EPS_UM', 'bad')
    else:
        monkeypatch.setenv('TPMSHX_CHI_S', 'bad')
    with pytest.raises(ValueError):
        api.prepare_case(config, case_id='env-error')


@pytest.mark.parametrize('mode', ['uniform', 'xy', 'xyz', 'grid', 'offset'])
def test_cold_warm_cache_order(monkeypatch, mode):
    config = _configuration(mode, pair=('air', 'air'))
    _capture(monkeypatch, api, 'full', config, clear_cache=True)
    cold_info = tuple(compute.cache_info()), tuple(compute_geometry.cache_info())
    _capture(monkeypatch, api, 'full', config, clear_cache=False)
    warm_info = tuple(compute.cache_info()), tuple(compute_geometry.cache_info())
    assert warm_info[0][0] > cold_info[0][0] or warm_info[1][0] > cold_info[1][0]


@pytest.mark.parametrize('mode', ['uniform', 'xyz', 'grid'])
@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('refined', [False, True])
def test_physical_ports_and_refinement(monkeypatch, mode, direction, refined):
    config = _configuration(mode)
    config.flags.port_wall_refine = refined
    if refined:
        config.solver.Nx = config.solver.Ny = config.solver.Nz = 30
    lengths = config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m
    for side, selected in (('A', direction), ('B', (direction + 3) % 6)):
        cross = lengths[1 if selected < 2 else 0]
        other = lengths[2 if selected < 4 else 1]
        setattr(config, 'bc_' + side, PartialBCConfig(dir=selected,
            in_ctr=.5 * cross if refined else .43 * cross,
            in_w=.5 * cross if refined else .47 * cross,
            out_ctr=.5 * cross if refined else .61 * cross,
            out_w=.5 * cross if refined else .37 * cross,
            in_z_ctr=.5 * other if refined else .41 * other,
            in_z_w=.5 * other if refined else .43 * other,
            out_z_ctr=.5 * other if refined else .56 * other,
            out_z_w=.5 * other if refined else .39 * other))
    case, _, _, _ = _capture(monkeypatch, api, 'full', config, (.001, .01))
    _check_3d_case_invariants(case, config)


@pytest.mark.parametrize('mode', ['uniform', 'xy', 'xyz', 'grid', 'offset'])
def test_saved_case_is_independent_of_native_owner(monkeypatch, tmp_path, mode):
    config = _configuration(mode)
    actual, _, _, _ = _capture(monkeypatch, api, 'full', config)
    gc.collect()
    path = tmp_path / 'native-case.yaml'
    save_case(actual, path)
    loaded = load_case(path)
    _same(loaded.grid, actual.grid)
    _same(loaded.design_fields, actual.design_fields)
    without_snapshot = replace(loaded, config_snapshot={})
    params, prepared = build_execution_inputs(without_snapshot)
    assert params['Nx'] == len(actual.grid['dx'])
    assert prepared['design']['eps_arr'].shape == actual.design_fields['eps_arr'].shape
    for value in actual.design_fields.values():
        assert not value.flags.writeable
        with pytest.raises(ValueError):
            value.setflags(write=True)


def test_missing_preparation_library_stops_3d_dispatch(monkeypatch):
    monkeypatch.setenv('TPMSHX_PREPARATION_LIBRARY', '/missing/preparation/library')
    with pytest.raises(FileNotFoundError, match='prebuilt native preparation library is missing'):
        api.prepare_case(_configuration('uniform'), case_id='missing')


def test_host_exception_keeps_identity_and_releases_owner(monkeypatch):
    from sjtu_tpmshx.preprocess.three_d import preparation
    from sjtu_tpmshx.cpp_interface import preparation_host as binding
    from sjtu_tpmshx.run_control.run_warnings import warning_scope, current_warnings
    original = binding._Bindings
    released = []
    failure = ValueError('host environment capture failed')

    def bindings(path):
        value = original(path, volume=True)
        for key, release in value.releases.items():
            def checked(pointer, release=release):
                released.append(True)
                release(pointer)
            value.releases[key] = checked
        return value

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(binding, '_volume_bindings', bindings)
    monkeypatch.setattr(preparation, 'capture_environment', fail)
    parent = {('parent',): 'parent'}
    with warning_scope(parent):
        with pytest.raises(ValueError) as caught:
            api.prepare_case(_configuration('uniform'), case_id='host-error')
        assert caught.value is failure
        assert current_warnings() is parent
    assert released == [True]


@pytest.mark.parametrize('mode', ['uniform', 'xyz', 'grid'])
@pytest.mark.parametrize('alias', ['error', 'failure'])
def test_owned_3d_views_cannot_be_diagnostic_outputs(mode, alias):
    from sjtu_tpmshx.preprocess.three_d import preparation
    from sjtu_tpmshx.cpp_interface import _native_preparation_3d as binding
    from sjtu_tpmshx.cpp_interface import _native_preparation_case as native
    from sjtu_tpmshx.cpp_interface import preparation_host
    from sjtu_tpmshx.cpp_interface.stage_libraries import preparation_library
    config = _configuration(mode).validate()
    source = preparation._input(config, None, 'prepare_flow_case')
    kind = binding._ContinuousCase if isinstance(source, binding._ContinuousInput) else binding._SpatialCase
    result = kind(1, ct.sizeof(kind))
    options = native._Options(1, ct.sizeof(native._Options), 0, 1, 0.)
    failure, error = native._Failure(2, ct.sizeof(native._Failure)), ct.create_string_buffer(4096)
    bindings = preparation_host._volume_bindings(preparation_library.get().path)
    call = bindings.operations[type(source), 'prepare_flow_case'].call
    assert call(ct.byref(source), ct.byref(options), None, ct.byref(result),
                ct.byref(failure), error, len(error)) == 0
    try:
        field = copy_array(result.prepared.cell_length)
        before = bytes(result), bytes(failure), bytes(error), field.copy()
        output_error = ct.cast(result.prepared.cell_length.data, ct.POINTER(ct.c_char)) if alias == 'error' else error
        output_failure = (ct.cast(result.prepared.cell_length.data, ct.POINTER(native._Failure))
                          if alias == 'failure' else ct.byref(failure))
        assert call(ct.byref(source), ct.byref(options), None, ct.byref(result),
                    output_failure, output_error, 8 if alias == 'error' else len(error)) == 1
        assert (bytes(result), bytes(failure), bytes(error)) == before[:3]
        np.testing.assert_array_equal(copy_array(result.prepared.cell_length), before[3])
    finally:
        bindings.releases[kind](ct.byref(result))


@pytest.mark.parametrize('alias', ['error', 'failure'])
def test_cached_3d_evidence_cannot_alias_diagnostics(alias):
    from sjtu_tpmshx.preprocess.three_d import preparation
    from sjtu_tpmshx.cpp_interface import _native_preparation_3d as binding
    from sjtu_tpmshx.cpp_interface import _native_preparation_case as native
    from sjtu_tpmshx.cpp_interface import preparation_host
    from sjtu_tpmshx.cpp_interface.stage_libraries import preparation_library
    config = _configuration('uniform', pair=('air', 'air')).validate()
    source = preparation._input(config, None, 'prepare_flow_case')
    result = binding._SpatialCase(1, ct.sizeof(binding._SpatialCase))
    options = native._Options(1, ct.sizeof(native._Options), 0, 1, 0.)
    failure, error = native._Failure(2, ct.sizeof(native._Failure)), ct.create_string_buffer(b'unchanged', 4096)
    calls = []

    def inlet(action, key, value):
        calls.append(action)
        pointer = error if alias == 'error' else ct.byref(failure)
        value.evidence.warnings = ct.cast(pointer, ct.POINTER(native._Text))
        value.evidence.warning_count = 1
        return False

    callbacks, errors = preparation_host._callback_bridge(lambda *args: None,
        geometry_cache_at=lambda *args: False, inlet_cache_at=inlet)
    before = bytes(result), bytes(failure), bytes(error)
    bindings = preparation_host._volume_bindings(preparation_library.get().path)
    status = bindings.operations[binding._SpatialInput, 'prepare_flow_case'].call(ct.byref(source), ct.byref(options),
        ct.byref(callbacks), ct.byref(result), ct.byref(failure), error, len(error))
    assert status == 1 and calls == [0] and not errors
    assert (bytes(result), bytes(failure), bytes(error)) == before


@pytest.mark.parametrize('mode', ['xy', 'xyz', 'grid'])
@pytest.mark.parametrize('targets', [None, (.001, .001)])
def test_air_field_observations_stay_bounded(monkeypatch, mode, targets):
    from sjtu_tpmshx.cpp_interface.preparation_host import PreparationCacheBridge
    config = _configuration(mode, pair=('air', 'air'))
    config.solver.Nx, config.solver.Ny, config.solver.Nz = 30, 20, 10
    actual_calls = []
    original_observe = PreparationCacheBridge.observe_range

    def observe(self, value, bounds_list, cached, scalar):
        if (read_text(value.layout) == 'scalar-zoned-call'
                and [read_text(item) for item in value.source[:value.source_count]][:2] == ['nu', 'air']):
            actual_calls.append((read_text(value.side), scalar))
        return original_observe(self, value, bounds_list, cached, scalar)

    monkeypatch.setattr(PreparationCacheBridge, 'observe_range', observe)
    _capture(monkeypatch, api, 'full', config, targets)
    assert 2 <= len(actual_calls) <= 16
