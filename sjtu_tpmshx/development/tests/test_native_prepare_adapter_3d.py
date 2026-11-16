"""Compare complete 3D host preparation with its frozen public reference."""
from dataclasses import asdict
from itertools import product

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import preparation_api_reference as reference
from sjtu_tpmshx.development.tests import test_native_preparation_3d as uniform
from sjtu_tpmshx.development.tests import test_native_preparation_continuous_3d as continuous
from sjtu_tpmshx.development.tests import test_native_preparation_spatial_3d as spatial
from sjtu_tpmshx.development.tests.test_native_prepare_adapter import _capture, _same, _failure
from sjtu_tpmshx.preprocess import api


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch):
    for name in ('TPMSHX_CHI_S', 'TPMSHX_ALLOW_EXTRAP', 'TPMSHX_MAX_CELLS_3D'):
        monkeypatch.delenv(name, raising=False)
    yield
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    compute.cache_clear()
    compute_geometry.cache_clear()


def _configuration(mode, topology='Gyroid', pair=('air', 'water')):
    if mode in ('xy', 'xyz'):
        return continuous._configuration(topology, pair, nz=3 if mode == 'xyz' else None)
    if mode in ('grid', 'offset'):
        return spatial._configuration(topology, pair, spatial=mode == 'grid', delta=.12)
    return uniform._configuration(topology, pair)


@pytest.mark.parametrize('mode', ['uniform', 'xy', 'xyz'])
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(('air', 'water', 'sco2', 'co2'), repeat=2)))
def test_complete_case_matches_reference(monkeypatch, mode, topology, pair):
    config = _configuration(mode, topology, pair)
    before = asdict(config)
    expected = _capture(monkeypatch, reference, 'full', config)
    actual = _capture(monkeypatch, api, 'full', config)
    _same(actual, expected)
    _same(asdict(config), before, 'unchanged input')


@pytest.mark.parametrize('mode', ['uniform', 'xy', 'xyz', 'grid', 'offset'])
@pytest.mark.parametrize('operation', ['capacity', 'resolve', 'full'])
@pytest.mark.parametrize('explicit', [False, True])
def test_fixed_and_configured_flows(monkeypatch, mode, operation, explicit):
    config = _configuration(mode)
    targets = (.001, .01) if explicit else None
    config.fluid_A.u_mps, config.fluid_B.u_mps = -99., -88.
    if not explicit:
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .001, .01
    _same(_capture(monkeypatch, api, operation, config, targets),
          _capture(monkeypatch, reference, operation, config, targets))


@pytest.mark.parametrize('mode', ['uniform', 'xy', 'xyz', 'grid', 'offset'])
@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64, np.int16])
def test_typed_targets(monkeypatch, mode, dtype):
    config = _configuration(mode)
    targets = tuple(dtype(value) for value in ((1, 2) if dtype is np.int16 else (.001, .01)))
    for operation in ('capacity', 'resolve', 'full'):
        _same(_capture(monkeypatch, api, operation, config, targets),
              _capture(monkeypatch, reference, operation, config, targets))


@pytest.mark.parametrize('mode', ['uniform', 'xy', 'xyz', 'grid', 'offset'])
@pytest.mark.parametrize('selection', ['cap', 'cap-negative', 'roughness', 'chi', 'temperature-array'])
def test_host_failure_order(monkeypatch, mode, selection):
    config = _configuration(mode)
    if selection == 'cap':
        monkeypatch.setenv('TPMSHX_MAX_CELLS_3D', 'bad')
    elif selection == 'cap-negative':
        monkeypatch.setenv('TPMSHX_MAX_CELLS_3D', '-5')
    elif selection == 'roughness':
        monkeypatch.setenv('TPMSHX_ROUGH_EPS_UM', 'bad')
    elif selection == 'chi':
        monkeypatch.setenv('TPMSHX_CHI_S', 'bad')
    else:
        config.fluid_A.T_in_K = np.array(config.fluid_A.T_in_K)
    if selection == 'temperature-array' and mode in ('xy', 'xyz', 'grid'):
        _same(_capture(monkeypatch, api, 'full', config),
              _capture(monkeypatch, reference, 'full', config))
    else:
        assert _failure(monkeypatch, api, config) == _failure(monkeypatch, reference, config)


@pytest.mark.parametrize('mode', ['uniform', 'xy', 'xyz', 'grid', 'offset'])
def test_cold_warm_cache_order(monkeypatch, mode):
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    config = _configuration(mode, pair=('air', 'air'))
    outcomes = []
    for module in (reference, api):
        results = []
        for cold in (True, False, False):
            results.append((_capture(monkeypatch, module, 'full', config, clear_cache=cold),
                            tuple(compute.cache_info()), tuple(compute_geometry.cache_info())))
        outcomes.append(results)
    _same(outcomes[1], outcomes[0])


@pytest.mark.parametrize('mode', ['uniform', 'xyz', 'grid'])
@pytest.mark.parametrize('direction', range(6))
@pytest.mark.parametrize('refined', [False, True])
def test_physical_ports_and_refinement(monkeypatch, mode, direction, refined):
    from sjtu_tpmshx.shared.domain.compute_config import PartialBCConfig
    config = _configuration(mode)
    config.flags.port_wall_refine = refined
    if refined:
        config.solver.Nx = config.solver.Ny = config.solver.Nz = 30
    lengths = config.geometry.L_dom_m, config.geometry.H_dom_m, config.geometry.Lz_m
    for side, selected in (('A', direction), ('B', (direction + 3) % 6)):
        cross = lengths[1 if selected < 2 else 0]
        other = lengths[2 if selected < 4 else 1]
        setattr(config, 'bc_' + side, PartialBCConfig(dir=selected,
            in_ctr=.43 * cross, in_w=.47 * cross, out_ctr=.61 * cross, out_w=.37 * cross,
            in_z_ctr=.41 * other, in_z_w=.43 * other,
            out_z_ctr=.56 * other, out_z_w=.39 * other))
        if refined:
            port = getattr(config, "bc_" + side)
            port.in_ctr, port.in_w, port.out_ctr, port.out_w = .5 * cross, .5 * cross, .5 * cross, .5 * cross
            port.in_z_ctr, port.in_z_w = .5 * other, .5 * other
            port.out_z_ctr, port.out_z_w = .5 * other, .5 * other
    _same(_capture(monkeypatch, api, 'full', config, (.001, .01)),
          _capture(monkeypatch, reference, 'full', config, (.001, .01)))


@pytest.mark.parametrize('mode', ['uniform', 'xy', 'xyz', 'grid', 'offset'])
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('selection', ['geometry', 'grid', 'fluid'])
def test_scalar_kinds_keep_preparation_contract(monkeypatch, mode, dtype, selection):
    config = _configuration(mode)
    if selection == 'geometry':
        config.geometry.t_wall_mm = .5
        for name in ('L_cell_mm', 't_wall_mm', 'k_s_W_mK'):
            setattr(config.geometry, name, dtype(getattr(config.geometry, name)))
    elif selection == 'grid':
        for name in ('L_dom_m', 'H_dom_m', 'Lz_m'):
            setattr(config.geometry, name, dtype(getattr(config.geometry, name)))
    else:
        for side in 'AB':
            fluid = getattr(config, 'fluid_' + side)
            for name in ('u_mps', 'T_in_K', 'P_in_Pa'):
                value = getattr(fluid, name)
                setattr(fluid, name, dtype(value) if name != 'P_in_Pa' or dtype != np.float16 else np.float32(value))
    if selection == 'grid' and dtype in (np.float16, np.float32) and mode in ('xy', 'xyz'):
        assert _failure(monkeypatch, api, config) == _failure(monkeypatch, reference, config)
    else:
        _same(_capture(monkeypatch, api, 'full', config),
              _capture(monkeypatch, reference, 'full', config))


@pytest.mark.parametrize('name', ['TPMSHX_PHASE_A', 'TPMSHX_PHASE_B', 'TPMSHX_PHASE_C'])
@pytest.mark.parametrize('value', ['', '0', '1', '2', 'false'])
def test_environment_flag_values(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    config = _configuration('uniform')
    _same(_capture(monkeypatch, api, 'full', config),
          _capture(monkeypatch, reference, 'full', config))


@pytest.mark.parametrize('mode', ['uniform', 'xy', 'xyz', 'grid', 'offset'])
def test_saved_case_is_independent_of_native_owner(monkeypatch, tmp_path, mode):
    import gc
    from dataclasses import replace
    from sjtu_tpmshx.shared.io.case_io import save_case, load_case
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
    config = _configuration(mode)
    actual = _capture(monkeypatch, api, 'full', config)[0]
    expected = _capture(monkeypatch, reference, 'full', config)[0]
    gc.collect()
    path = tmp_path / 'native-case.yaml'
    save_case(actual, path)
    loaded = load_case(path)
    reference_path = tmp_path / 'reference-case.yaml'
    save_case(expected, reference_path)
    _same(loaded, load_case(reference_path))
    without_snapshot = replace(loaded, config_snapshot={})
    actual_input = build_execution_inputs(without_snapshot)
    expected_input = build_execution_inputs(replace(expected, config_snapshot={}))
    from sjtu_tpmshx.development.tests.native.test_cpp_full_3d import compare
    actual_models = actual_input[0].pop('_models')
    expected_models = expected_input[0].pop('_models')
    assert {key: type(value) for key, value in actual_models.items()} == {
        key: type(value) for key, value in expected_models.items()}
    compare(actual_input, expected_input)
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
    from sjtu_tpmshx.shared.models import _native_preparation_3d as binding
    from sjtu_tpmshx.shared.domain.run_warnings import warning_scope, current_warnings
    original = binding._Bindings
    released = []
    failure = ValueError('host port object failed')

    def bindings(path):
        value = original(path)
        for key, release in value.releases.items():
            def checked(pointer, release=release):
                released.append(True)
                release(pointer)
            value.releases[key] = checked
        return value

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(binding, '_bindings', bindings)
    monkeypatch.setattr(preparation, 'bc_to_dict', fail)
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
    import ctypes as ct
    from sjtu_tpmshx.preprocess.three_d import preparation
    from sjtu_tpmshx.shared.models import _native_preparation_3d as binding
    from sjtu_tpmshx.shared.models import _native_preparation_case as native
    from sjtu_tpmshx.shared.models import _native_preparation
    config = _configuration(mode).validate()
    source = preparation._input(config, None, 'prepare_flow_case')
    kind = binding._ContinuousCase if source.abi_version == 3 else binding._SpatialCase
    result = kind(source.abi_version, ct.sizeof(kind))
    options = native._Options(1, ct.sizeof(native._Options), 0, 1, 0.)
    failure, error = native._Failure(2, ct.sizeof(native._Failure)), ct.create_string_buffer(4096)
    bindings = binding._bindings(_native_preparation._library().path)
    call = bindings.operations[source.abi_version, 'prepare_flow_case']
    assert call(ct.byref(source), ct.byref(options), None, ct.byref(result),
                ct.byref(failure), error, len(error)) == 0
    try:
        field = native._array(result.prepared.cell_length)
        before = bytes(result), bytes(failure), bytes(error), field.copy()
        output_error = ct.cast(result.prepared.cell_length.data, ct.POINTER(ct.c_char)) if alias == 'error' else error
        output_failure = (ct.cast(result.prepared.cell_length.data, ct.POINTER(native._Failure))
                          if alias == 'failure' else ct.byref(failure))
        assert call(ct.byref(source), ct.byref(options), None, ct.byref(result),
                    output_failure, output_error, 8 if alias == 'error' else len(error)) == 1
        assert (bytes(result), bytes(failure), bytes(error)) == before[:3]
        np.testing.assert_array_equal(native._array(result.prepared.cell_length), before[3])
    finally:
        bindings.releases[kind](ct.byref(result))


@pytest.mark.parametrize('alias', ['error', 'failure'])
def test_cached_3d_evidence_cannot_alias_diagnostics(alias):
    import ctypes as ct
    from sjtu_tpmshx.preprocess.three_d import preparation
    from sjtu_tpmshx.shared.models import _native_preparation_3d as binding
    from sjtu_tpmshx.shared.models import _native_preparation_case as native
    from sjtu_tpmshx.shared.models import _native_preparation
    config = _configuration('uniform', pair=('air', 'air')).validate()
    source = preparation._input(config, None, 'prepare_flow_case')
    result = binding._SpatialCase(4, ct.sizeof(binding._SpatialCase))
    options = native._Options(1, ct.sizeof(native._Options), 0, 1, 0.)
    failure, error = native._Failure(2, ct.sizeof(native._Failure)), ct.create_string_buffer(b'unchanged', 4096)
    calls = []

    def inlet(action, key, value):
        calls.append(action)
        pointer = error if alias == 'error' else ct.byref(failure)
        value.evidence.warnings = ct.cast(pointer, ct.POINTER(native._Text))
        value.evidence.warning_count = 1
        return False

    callbacks, descriptor, errors = native._callback_bridge(lambda *args: None,
        geometry_cache_at=lambda *args: False, inlet_cache_at=inlet)
    before = bytes(result), bytes(failure), bytes(error)
    bindings = binding._bindings(_native_preparation._library().path)
    status = bindings.operations[4, 'prepare_flow_case'](ct.byref(source), ct.byref(options),
        ct.byref(descriptor), ct.byref(result), ct.byref(failure), error, len(error))
    assert status == 1 and calls == [0] and not errors
    assert (bytes(result), bytes(failure), bytes(error)) == before


@pytest.mark.parametrize('axis', ['Nx', 'Ny', 'Nz'])
@pytest.mark.parametrize('refined', [False, True])
@pytest.mark.parametrize('earlier', [None, 'chi', 'cap'])
def test_grid_count_transport_preserves_bounds_and_error_order(monkeypatch, axis, refined, earlier):
    import ctypes as ct
    config = _configuration('uniform')
    config.flags.port_wall_refine = refined
    setattr(config.solver, axis, 2 ** (ct.sizeof(ct.c_size_t) * 8) + 4)
    if earlier:
        monkeypatch.setenv('TPMSHX_CHI_S' if earlier == 'chi' else 'TPMSHX_MAX_CELLS_3D', 'bad')
    actual = _failure(monkeypatch, api, config)
    expected = _failure(monkeypatch, reference, config)
    assert actual == expected
    if earlier != 'chi' and (not refined or axis == 'Nx'):
        assert actual[0][0] == (ValueError, 'grid count must be within size_t')


@pytest.mark.parametrize('fault', ['missing-L', 'invalid-L', 'missing-t', 'invalid-t', 'field-order'])
@pytest.mark.parametrize('earlier', [None, 'cap', 'chi', 'water', 'roughness'])
def test_grid_cell_conversion_follows_physical_preparation(monkeypatch, fault, earlier):
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    config = _configuration('grid')
    rows = config.zones.grid['cells']
    if fault == 'field-order':
        rows[0]['t'] = 'invalid t'
        rows[-1].pop('L')
    else:
        action, key = fault.split('-')
        if action == 'missing':
            rows[0].pop(key)
        else:
            rows[0][key] = 'invalid cell value'
    if earlier == 'water':
        config.fluid_B.T_in_K = 1000.
    elif earlier:
        name = {'cap': 'TPMSHX_MAX_CELLS_3D', 'chi': 'TPMSHX_CHI_S',
                'roughness': 'TPMSHX_ROUGH_EPS_UM'}[earlier]
        monkeypatch.setenv(name, 'bad')
    expected = _failure(monkeypatch, reference, config)
    expected_cache = tuple(compute_geometry.cache_info())
    actual = _failure(monkeypatch, api, config)
    assert actual == expected
    assert tuple(compute_geometry.cache_info()) == expected_cache


@pytest.mark.parametrize('mode', ['uniform', 'xy', 'xyz', 'grid', 'offset'])
@pytest.mark.parametrize('dtype', [np.float16, np.float32])
def test_weak_scalar_bounds_keep_later_df_validation(monkeypatch, mode, dtype):
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    config = _configuration(mode)
    config.geometry.t_wall_mm = dtype(.6)
    if mode in ('uniform', 'offset'):
        expected = _failure(monkeypatch, reference, config)
        cache = tuple(compute_geometry.cache_info())
        assert _failure(monkeypatch, api, config) == expected
        assert tuple(compute_geometry.cache_info()) == cache
    else:
        _same(_capture(monkeypatch, api, 'full', config),
              _capture(monkeypatch, reference, 'full', config))


@pytest.mark.parametrize('mode', ['xy', 'xyz', 'grid'])
@pytest.mark.parametrize('targets', [None, (.001, .001)])
def test_air_field_observations_keep_original_bounded_sequence(monkeypatch, mode, targets):
    from sjtu_tpmshx.preprocess.native_preparation import PreparationCacheBridge
    from sjtu_tpmshx.shared.domain.run_warnings import _range_context
    from sjtu_tpmshx.shared.models import nu_correlations as nu
    from sjtu_tpmshx.shared.models import _native_preparation_case as native

    config = _configuration(mode, pair=('air', 'air'))
    config.solver.Nx, config.solver.Ny, config.solver.Nz = 30, 20, 10
    expected_calls, actual_calls = [], []
    original_notice, original_observe = nu._warn_extrap, PreparationCacheBridge.observe_range

    def notice(topology, minimum, maximum, value):
        side, stage, layout = _range_context.get()
        if stage == 'inlet' and layout == 'scalar-zoned-call':
            expected_calls.append((side, value))
        return original_notice(topology, minimum, maximum, value)

    def observe(self, value, bounds_list, cached, scalar):
        if (native._text(value.layout) == 'scalar-zoned-call'
                and [native._text(item) for item in value.source[:value.source_count]][:2] == ['nu', 'air']):
            actual_calls.append((native._text(value.side), scalar))
        return original_observe(self, value, bounds_list, cached, scalar)

    monkeypatch.setattr(nu, '_warn_extrap', notice)
    expected = _capture(monkeypatch, reference, 'full', config, targets)
    monkeypatch.setattr(PreparationCacheBridge, 'observe_range', observe)
    actual = _capture(monkeypatch, api, 'full', config, targets)
    _same(actual, expected)
    assert 2 <= len(expected_calls) <= 16
    assert actual_calls == expected_calls
