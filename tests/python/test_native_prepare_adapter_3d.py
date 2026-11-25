"""Verify 3D native host preparation contracts, invariants, persistence and errors."""
from copy import deepcopy
import ctypes as ct
from dataclasses import asdict, replace
import gc
from itertools import product

import numpy as np
import pytest

from sjtu_tpmshx.cpp_interface._native_values import copy_array
from sjtu_tpmshx.data_types.compute_config import PartialBCConfig
from sjtu_tpmshx.file_io.case_io import load_case, save_case
from sjtu_tpmshx.physical_models.tpms_calc import compute
from sjtu_tpmshx.physical_models.tpms_geometry import compute_geometry
from sjtu_tpmshx.preprocess import api
from sjtu_tpmshx.solvers.full_3d import validate_saved_case
from tests.python import native_preparation_abi, property_reference as prop_ref
from tests.python.native_preparation_abi import _configuration_continuous_3d, _configuration_spatial_3d
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
        return _configuration_continuous_3d(topology, pair, nz=3 if mode == 'xyz' else None)
    if mode in ('grid', 'offset'):
        return _configuration_spatial_3d(topology, pair, spatial=mode == 'grid', delta=.12)
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
    shape, _, _, _ = validate_saved_case(without_snapshot)
    assert shape[0] == without_snapshot.parameters['prepared']['Nx'] == len(actual.grid['dx'])
    assert shape == without_snapshot.design_fields['eps_arr'].shape == actual.design_fields['eps_arr'].shape
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
    from sjtu_tpmshx.cpp_interface import _native_preparation_3d as binding
    from sjtu_tpmshx.cpp_interface import _native_preparation_case as native
    from sjtu_tpmshx.cpp_interface import preparation_host
    from sjtu_tpmshx.cpp_interface.stage_libraries import preparation_library
    config = _configuration(mode).validate()
    source, errors = binding.pack_input(config, None, lambda fluid: fluid.u_mps, 2_000_000)
    assert not errors
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
    from sjtu_tpmshx.cpp_interface import _native_preparation_3d as binding
    from sjtu_tpmshx.cpp_interface import _native_preparation_case as native
    from sjtu_tpmshx.cpp_interface import preparation_host
    from sjtu_tpmshx.cpp_interface.stage_libraries import preparation_library
    config = _configuration('uniform', pair=('air', 'air')).validate()
    source, errors = binding.pack_input(config, None, lambda fluid: fluid.u_mps, 2_000_000)
    assert not errors
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
    from sjtu_tpmshx.preprocess.preparation import PreparationCache
    config = _configuration(mode, pair=('air', 'air'))
    config.solver.Nx, config.solver.Ny, config.solver.Nz = 30, 20, 10
    actual_calls = []
    original_observe = PreparationCache.observe_range

    def observe(self, key, record, cached, scalar):
        if key[-1][2] == 'scalar-zoned-call' and key[:2] == ('nu', 'air'):
            actual_calls.append((key[-1][0], scalar))
        return original_observe(self, key, record, cached, scalar)

    monkeypatch.setattr(PreparationCache, 'observe_range', observe)
    _capture(monkeypatch, api, 'full', config, targets)
    assert 2 <= len(actual_calls) <= 16


@pytest.mark.parametrize('spatial', [False, True], ids=['offset', 'grid'])
@pytest.mark.parametrize('delta', [0., .12, -.12])
def test_offset_split_orders_side_porosities(spatial, delta):
    config = _configuration_spatial_3d(spatial=spatial, delta=delta)
    if delta < 0.:
        config.geometry.L_cell_mm, config.geometry.t_wall_mm = 6.25, .45
    case = api.prepare_case(config, case_id='offset-split')
    _check_3d_case_invariants(case, config)
    eps_A, eps_B = case.design_fields['eps_A'], case.design_fields['eps_B']
    eps_arr, thermal = case.design_fields['eps_arr'], case.parameters['thermal_geometry']
    if delta == 0.:
        assert thermal['split_A'] == .5 and thermal['side_geometry'] is None
        native_preparation_abi._same(eps_A, .5 * eps_arr, 'side A porosity')
        native_preparation_abi._same(eps_B, eps_A, 'side B porosity')
    elif delta > 0.:
        assert thermal['split_A'] > .5 and np.all(eps_A > eps_B)
    else:
        assert thermal['split_A'] < .5 and np.all(eps_A < eps_B)
    # Only grid zones produce local thermal geometry fields. A uniform core keeps scalar values.
    assert (thermal['fields'] is not None) == spatial
    for name in ('A_0', 'D_h', 'epsilon') if spatial else ():
        field = thermal['fields'][name]
        assert field.shape == eps_arr.shape and np.all(np.isfinite(field)) and np.all(field > 0.)


@pytest.mark.parametrize('spatial', [False, True], ids=['offset', 'grid'])
@pytest.mark.parametrize('delta', [-100., 100.])
def test_closed_side_offset_stops_at_the_capacity_boundary(spatial, delta):
    config = _configuration_spatial_3d(spatial=spatial, delta=delta)
    case = api.prepare_case(config, case_id='closed-side')
    assert case.parameters['thermal_geometry']['split_A'] == (1. if delta > 0. else 0.)
    closed = 'B' if delta > 0. else 'A'
    with pytest.raises(ValueError, match=f'side {closed}: inlet density times open pore area'):
        api.prepare_inlet_mass_capacities(config)


@pytest.mark.parametrize('selection', ['gaps', 'reverse-overlap', 'no-hit', 'overwritten-nan', 'overwritten-domain'])
def test_grid_rectangle_gaps_overlap_and_late_overwrite(selection):
    config = _configuration_spatial_3d(delta=0.)
    rows = config.zones.grid['cells']
    if selection == 'gaps':
        del rows[1:]
    elif selection == 'reverse-overlap':
        rows.reverse()
    elif selection == 'no-hit':
        rows.append(dict(x0=0., x1=.001, y0=0., y1=1., L=float('nan'), t=float('nan')))
    else:
        # The last rectangle that covers a point sets its value, so an earlier invalid value has no effect.
        value = float('nan') if selection == 'overwritten-nan' else 9.
        rows[:] = [dict(x0=0., x1=1., y0=0., y1=1., L=value, t=.4),
                   dict(x0=0., x1=1., y0=0., y1=1., L=6.25, t=.45)]
    case = api.prepare_case(config, case_id='grid-rectangles')
    _check_3d_case_invariants(case, config)
    if selection.startswith('overwritten-'):
        np.testing.assert_allclose(case.design_fields['L_field_m'], 6.25e-3, rtol=1e-15, atol=0.)
        np.testing.assert_allclose(case.design_fields['t_field_m'], .45e-3, rtol=1e-15, atol=0.)


def test_grid_smooths_local_values_before_cfd_lookup():
    config = _configuration_spatial_3d(delta=0.)
    # L = 9 mm is outside the CFD table. Smoothing must move it into the table before the lookup.
    config.zones.grid['cells'] = [dict(x0=0., x1=1., y0=0., y1=1., L=6., t=.4),
                                  dict(x0=0., x1=.1, y0=0., y1=.11, L=9., t=.4)]
    case = api.prepare_case(config, case_id='grid-smoothing')
    _check_3d_case_invariants(case, config)
    length = case.design_fields['L_field_m']
    assert np.all((length >= .004) & (length <= .008)) and np.ptp(length) > 0.


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('fluid', ['sco2', 'co2'])
@pytest.mark.parametrize('spatial', [True, False], ids=['grid', 'offset'])
def test_supercritical_and_co2_reject_grid_zones_and_offset(side, fluid, spatial):
    config = _configuration_spatial_3d(spatial=spatial, delta=.12)
    inlet = getattr(config, 'fluid_' + side)
    inlet.type, inlet.T_in_K, inlet.P_in_Pa = fluid, 400., 8e6
    match = 'discrete zones' if spatial else 'delta_levelset=0'
    with pytest.raises(ValueError, match=match):
        api.prepare_case(config, case_id='fluid-geometry')


def test_experimental_hx_capacity_precedes_offset_rejection():
    config = _configuration_spatial_3d(spatial=False, mode='experimental')
    capacities = api.prepare_inlet_mass_capacities(config)
    assert capacities['A'] > 0. and capacities['B'] > 0.
    targets = tuple(capacities[side] * getattr(config, 'fluid_' + side).u_mps for side in 'AB')
    with pytest.raises(ValueError, match='requires delta=0'):
        api.resolve_fixed_mass_flow_config(config, mass_flow_A_kg_s=targets[0], mass_flow_B_kg_s=targets[1])
    with pytest.raises(ValueError, match='requires delta=0'):
        api.prepare_case(config, case_id='experimental-offset')


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_experimental_air_core_keeps_nonzero_offset(topology):
    config = _configuration_spatial_3d(topology, ('air', 'air'), spatial=False, mode='experimental')
    config.geometry.L_cell_mm, config.geometry.t_wall_mm = 6.5, .4
    case = api.prepare_case(config, case_id='experimental-core')
    _check_3d_case_invariants(case, config)
    assert case.parameters['thermal_geometry']['split_A'] > .5


@pytest.mark.parametrize('layout', [
    (1, 1, None, False, 1), (1, 5, None, True, 3), (4, 1, None, False, 2),
    (4, 4, None, True, 2), (4, 5, None, False, 3),
    (4, 5, 1, True, 3), (1, 4, 3, False, 3), (4, 1, 3, True, 2),
    (1, 1, 1, True, 3), (4, 4, 2, True, 1), (4, 5, 3, False, 2),
])
def test_continuous_control_layouts_and_orders(layout):
    nx, ny, nz, mirror, order = layout
    config = _configuration_continuous_3d(nx=nx, ny=ny, nz=nz, mirror=mirror, order=order)
    case = api.prepare_case(config, case_id='continuous-layout')
    _check_3d_case_invariants(case, config)
    if nz is None:
        for name in ('L_field_m', 't_field_m', 'eps_arr'):
            field = case.design_fields[name]
            native_preparation_abi._same(field, np.repeat(field[:, :, :1], field.shape[2], axis=2), name + ' extrusion')


@pytest.mark.parametrize('pair', [('air', 'water'), ('co2', 'water')])
def test_continuous_co2_thermal_porosity_differs_from_common_porosity(pair):
    config = _configuration_continuous_3d(pair=pair, nx=3, ny=4, nz=3, mirror=False)
    case = api.prepare_case(config, case_id='continuous-thermal')
    total, thermal = case.design_fields['eps_arr'], case.parameters['thermal_geometry']['fields']['epsilon']
    if pair[0] == 'co2':
        assert np.any(total != thermal)
    else:
        np.testing.assert_allclose(total, thermal, rtol=1e-12, atol=1e-12)


@pytest.mark.parametrize('selection,match', [
    ('order', 'spline_order'), ('counts', 'controls per axis'), ('z-count', 'controls per axis'),
    ('L-bounds', 'L_bounds'), ('t-bounds', 't_bounds'), ('decision-length', 'x_decision'),
    ('control-domain', 'control values'), ('delta', 'delta_levelset=0'),
])
def test_continuous_rejects_invalid_controls_and_offset(selection, match):
    config = _configuration_continuous_3d(nz=3)
    spec = config.zones.config
    if selection == 'order':
        spec['spline_order'] = 0
    elif selection == 'counts':
        spec['n_ctrl_x'] = 0
    elif selection == 'z-count':
        spec['n_ctrl_z'] = 0
    elif selection == 'L-bounds':
        spec['L_bounds'] = [3., 9.]
    elif selection == 't-bounds':
        spec['t_bounds'] = [.2, .7]
    elif selection == 'decision-length':
        spec['x_decision'].pop()
    elif selection == 'control-domain':
        spec['x_decision'][0] = 3.
    else:
        config.geometry.delta_levelset = .1
    with pytest.raises(ValueError, match=match):
        api.prepare_case(config, case_id='continuous-error')


@pytest.mark.parametrize('mode', ['offset', 'xyz'])
@pytest.mark.parametrize('operation', ['capacity', 'resolve'])
def test_flow_queries_emit_out_of_range_observations(monkeypatch, mode, operation):
    config = _configuration(mode)
    config.fluid_A.T_in_K = 190.
    targets = (.001, .01) if operation == 'resolve' else None
    _, _, ranges, _ = _capture(monkeypatch, api, operation, config, targets)
    observed = {(row['source'], row['low']) for row in ranges if row.get('low')}
    assert observed >= {
        (('property', 'air_viscosity'), 1),
        (('property', 'air_cp'), 1),
        (('property', 'air_conductivity'), 1),
    }


def _bytes_owner(array):
    owner = array
    while type(owner) is np.ndarray:
        owner = owner.base
    return owner


@pytest.mark.parametrize('mode', ['uniform', 'xyz', 'grid', 'offset'])
def test_detached_case_survives_buffer_poison_and_second_call_with_single_copy(monkeypatch, mode):
    from contextlib import contextmanager
    from sjtu_tpmshx.cpp_interface import _native_preparation_3d as binding, preparation_host
    from sjtu_tpmshx.preprocess.three_d import preparation

    config = _configuration(mode)
    original_op, original_case = preparation_host.volume_operation, preparation._case
    released_owners, detached_records, model_names, live_buffers = [], [], [], []
    snapshots = []

    @contextmanager
    def poison_buffers(*args, **kwargs):
        with original_op(*args, **kwargs) as result:
            source = result.prepared
            model_names.append(ct.string_at(source.models[0].name.data, source.models[0].name.size).decode())
            views = [source.widths[0], source.edges[0], source.cell_length, source.side_porosity,
                     source.sides[0].inlet_opening, source.models[0].name]
            if isinstance(result, binding._SpatialCase):
                views.append(result.side_b_porosity)
            if result.area_density_per_m.size:
                views.append(result.area_density_per_m)
            replacements, raw_bytes = [], []
            for view in views:
                saved = type(view).from_buffer_copy(view)
                size = view.size * ct.sizeof(view.data._type_)
                raw = ct.string_at(view.data, size)
                raw_bytes.append(raw)
                storage = ct.create_string_buffer(raw, size)
                live_buffers.append(storage)
                view.data = ct.cast(storage, type(view.data))
                replacements.append((view, saved, storage))
            snapshots.append(raw_bytes)
            try:
                yield result
            finally:
                for view, saved, storage in replacements:
                    ct.memset(storage, 0, ct.sizeof(storage))
                    ct.memmove(ct.byref(view), ct.byref(saved), ct.sizeof(view))
        released_owners.append(result.owner)

    def capture_detached(detached, *args):
        # The native owner must already be released before CaseData assembly starts.
        assert len(released_owners) == len(detached_records) + 1
        assert released_owners[-1] is None
        detached_records.append(detached)
        return original_case(detached, *args)

    monkeypatch.setattr(preparation_host, 'volume_operation', poison_buffers)
    monkeypatch.setattr(preparation, '_case', capture_detached)
    first = api.prepare_case(config, case_id='first')
    config.solver.Nx += 1
    second = api.prepare_case(config, case_id='second')

    assert released_owners == [None, None]
    assert first.case_id == 'first' and len(first.grid['dx']) != len(second.grid['dx'])
    first_detached = detached_records[0]
    pairs = [
        (first_detached.widths[0], first.grid['dx']),
        (first_detached.edges[0], first.grid['x_edges']),
        (first_detached.cell_length, first.design_fields['L_field_m']),
        (first_detached.side_porosity, first.design_fields['eps_A']),
        (first_detached.sides[0].inlet_opening, first.parameters['prepared']['openings']['A']['inlet']),
    ]
    for index, (detached_arr, saved_arr) in enumerate(pairs):
        assert saved_arr.dtype == np.float64 and saved_arr.flags.c_contiguous and saved_arr.flags.aligned
        assert not saved_arr.flags.writeable
        assert saved_arr.tobytes() == snapshots[0][index]
        assert np.any(saved_arr != 0.)
        owner = _bytes_owner(detached_arr)
        assert type(owner) is bytes and _bytes_owner(saved_arr) is owner
    assert first.model_refs[0].name == model_names[0] and first.model_refs[0].name
    if mode == 'xyz':
        assert _bytes_owner(first.design_fields['eps_B']) is _bytes_owner(first.design_fields['eps_A'])
    else:
        assert _bytes_owner(first.design_fields['eps_B']) is _bytes_owner(first_detached.side_b_porosity)
    if first.parameters['thermal_geometry']['fields'] is not None:
        assert (_bytes_owner(first.parameters['thermal_geometry']['fields']['A_0'])
                is _bytes_owner(first_detached.thermal_fields.area_density_per_m))
    stream_axis = first.parameters['prepared']['axes']['A']['stream_real_axis']
    grid_key = 'd' + 'xyz'[stream_axis]
    assert _bytes_owner(first.parameters['prepared']['axes']['A']['dstream']) is _bytes_owner(first.grid[grid_key])
    assert not np.shares_memory(first.design_fields['L_field_m'], second.design_fields['L_field_m'])


@pytest.mark.parametrize('mode', ['uniform', 'xyz'])
@pytest.mark.parametrize('operation', ['capacity', 'resolve', 'prepare', 'fixed-flow'])
def test_all_3d_operations_release_owned_result_once(monkeypatch, mode, operation):
    from sjtu_tpmshx.cpp_interface import _native_preparation_3d as binding, preparation_host

    config = _configuration(mode)
    original = preparation_host._Bindings
    releases = []

    def bindings(path):
        owner = original(path, volume=True)
        for kind, release in owner.releases.items():
            def checked(pointer, kind=kind, release=release):
                view = ct.cast(pointer, ct.POINTER(kind)).contents
                previous = bool(view.owner)
                release(pointer)
                releases.append((kind, previous, bool(view.owner)))
            owner.releases[kind] = checked
        return owner

    monkeypatch.setattr(preparation_host, '_volume_bindings', bindings)
    if operation == 'capacity':
        api.prepare_inlet_mass_capacities(config)
    elif operation == 'resolve':
        api.resolve_fixed_mass_flow_config(config, mass_flow_A_kg_s=.001, mass_flow_B_kg_s=.01)
    elif operation == 'fixed-flow':
        api.prepare_fixed_mass_flow_case(config, mass_flow_A_kg_s=.001, mass_flow_B_kg_s=.01, case_id='rel-fixed')
    else:
        api.prepare_case(config, case_id='rel-case')

    expected_kind = (
        (binding._ContinuousFlow if operation in ('capacity', 'resolve') else binding._ContinuousCase)
        if mode == 'xyz'
        else (binding._SpatialFlow if operation in ('capacity', 'resolve') else binding._SpatialCase)
    )
    assert releases == [(expected_kind, True, False)]


@pytest.mark.parametrize('exc_cls', [StopIteration, LookupError, MemoryError])
@pytest.mark.parametrize('mode,fault', [
    (mode, fault)
    for mode in ('uniform', 'xyz')
    for fault in (
        'detach', 'geometry_scalars', 'fixed_record', 'drag_evidence', 'model_text', 'model_evidence',
        'cache_geometry', 'observe_range', 'host_stage_13',
    )
] + [('uniform', 'cache_inlet')])
def test_injected_read_and_callback_failures_keep_exception_and_release_once(monkeypatch, mode, exc_cls, fault):
    from contextlib import contextmanager
    from sjtu_tpmshx.cpp_interface import _native_preparation_3d as binding, preparation_host
    from sjtu_tpmshx.preprocess.preparation import PreparationCache
    from sjtu_tpmshx.preprocess.three_d import preparation
    from sjtu_tpmshx.run_control.run_warnings import current_warnings, warning_scope

    pair = ('co2', 'water') if fault == 'drag_evidence' else ('air', 'water')
    config = _configuration(mode, pair=pair)
    if fault == 'observe_range':
        config.fluid_A.T_in_K = 190.
    marker = exc_cls(f'{mode}-{fault}')
    original = preparation_host._Bindings
    releases = []

    def bindings(path):
        owner = original(path, volume=True)
        for kind, release in owner.releases.items():
            def checked(pointer, kind=kind, release=release):
                view = ct.cast(pointer, ct.POINTER(kind)).contents
                previous = bool(view.owner)
                release(pointer)
                releases.append((kind, previous, bool(view.owner)))
            owner.releases[kind] = checked
        return owner

    def fail(*args, **kwargs):
        raise marker

    monkeypatch.setattr(preparation_host, '_volume_bindings', bindings)
    callback_faults = {'cache_geometry', 'cache_inlet', 'observe_range', 'host_stage_13'}
    if fault == 'detach':
        monkeypatch.setattr(binding, '_detach_array', fail)
    elif fault == 'geometry_scalars':
        # Fault only the post-yield _copy_case read, not the cache publish callback.
        original_op = preparation_host.volume_operation

        @contextmanager
        def fail_on_case_geometry(*args, **kwargs):
            with original_op(*args, **kwargs) as result:
                with monkeypatch.context() as inner:
                    inner.setattr(preparation_host, 'geometry_scalars', fail)
                    yield result

        monkeypatch.setattr(preparation_host, 'volume_operation', fail_on_case_geometry)
    elif fault == 'fixed_record':
        monkeypatch.setattr(preparation_host, 'fixed_record', fail)
    elif fault == 'drag_evidence':
        monkeypatch.setattr(preparation_host, 'drag_evidence', fail)
    elif fault == 'model_text':
        monkeypatch.setattr(binding, 'read_text', fail)
    elif fault == 'model_evidence':
        monkeypatch.setattr(preparation_host, 'model_evidence', fail)
    elif fault == 'cache_geometry':
        monkeypatch.setattr(PreparationCache, 'geometry', fail)
    elif fault == 'cache_inlet':
        monkeypatch.setattr(PreparationCache, 'inlet', fail)
    elif fault == 'observe_range':
        monkeypatch.setattr(PreparationCache, 'observe_range', fail)
    else:
        monkeypatch.setattr(preparation, 'capture_environment', fail)

    parent = {('parent',): 'parent'}
    expected_kind = binding._ContinuousCase if mode == 'xyz' else binding._SpatialCase
    with warning_scope(parent):
        if fault in callback_faults and exc_cls is StopIteration:
            with pytest.raises(RuntimeError, match='^generator raised StopIteration$') as caught:
                api.prepare_case(config, case_id='fault')
            assert caught.value.__cause__ is marker
        else:
            with pytest.raises(exc_cls) as caught:
                api.prepare_case(config, case_id='fault')
            assert caught.value is marker and caught.value.__cause__ is None
        assert current_warnings() is parent and parent == {('parent',): 'parent'}

    assert len(releases) == 1
    kind, previous, after = releases[0]
    assert kind is expected_kind and after is False
    if fault not in callback_faults:
        assert previous is True


def test_detach_array_rejects_null_pointer_with_nonzero_size():
    from sjtu_tpmshx.cpp_interface import _native_preparation_3d as binding, _native_preparation_case as native

    empty = binding._detach_array(native._Array(None, 0))
    assert empty.dtype == np.float64 and empty.shape == (0,) and not empty.flags.writeable
    assert _bytes_owner(empty) == b''
    with pytest.raises(RuntimeError, match='null array pointer'):
        binding._detach_array(native._Array(None, 4))


@pytest.mark.parametrize('field', ['L_bounds', 't_bounds'])
def test_continuous_bounds_conversion_keeps_stop_iteration(field):
    from sjtu_tpmshx.preprocess.three_d import preparation

    marker = StopIteration(field)

    class BadFloat(float):
        def __float__(self):
            raise marker

    config = _configuration('xyz')
    config.zones.config[field][0] = BadFloat(config.zones.config[field][0])
    with pytest.raises(StopIteration) as caught:
        preparation._execute(config, 'prepare_flow_case', case_id='bounds-stop')
    assert caught.value is marker and caught.value.__cause__ is None


def test_3d_warning_sites_repeat_counts_and_scoped_metadata(monkeypatch):
    from pathlib import Path
    import warnings
    from sjtu_tpmshx.physical_models import nu_correlations, tpms_props
    from sjtu_tpmshx.preprocess import preparation as shared
    from sjtu_tpmshx.preprocess.three_d import preparation

    monkeypatch.setattr(tpms_props, '_range_warnings_emitted', set())
    monkeypatch.setattr(nu_correlations, '_EXTRAP_WARNED', set())
    monkeypatch.setattr(shared, '__warningregistry__', {}, raising=False)
    config = _configuration('uniform', 'Gyroid', ('air', 'air'))
    config.fluid_A.T_in_K, config.fluid_B.T_in_K = 190., 1100.
    config.fluid_A.u_mps = config.fluid_B.u_mps = .0001
    counts = []
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter('default')
        for _ in range(2):
            compute.cache_clear()
            compute_geometry.cache_clear()
            preparation.prepare_case(config, case_id='warn-direct')
            counts.append(len(recorded))

    assert counts == [9, 9]
    assert [entry.category for entry in recorded] == [UserWarning] * 9
    assert [str(entry.message).split(':', 1)[0] for entry in recorded] == [
        'air_viscosity', '[surrogate extrap] Fluid A', '[surrogate extrap] Fluid B',
        'air_cp', 'air_conductivity', 'air_cp', 'Gyroid', '[Nu extrap] Gyroid', 'Gyroid',
    ]
    assert {Path(entry.filename).resolve() for entry in recorded} == {Path(shared.__file__).resolve()}
    assert recorded[0].lineno == recorded[3].lineno == recorded[4].lineno == recorded[5].lineno == recorded[7].lineno
    assert recorded[1].lineno == recorded[2].lineno
    assert recorded[6].lineno == recorded[8].lineno
    assert len({recorded[0].lineno, recorded[1].lineno, recorded[6].lineno}) == 3

    compute.cache_clear()
    compute_geometry.cache_clear()
    with warnings.catch_warnings(record=True) as scoped_recorded:
        warnings.simplefilter('always')
        scoped = api.prepare_case(config, case_id='warn-scoped')
    assert [str(entry.message).split(':', 1)[0] for entry in scoped_recorded] == [
        '[surrogate extrap] Fluid A', '[surrogate extrap] Fluid B',
    ]
    assert {Path(entry.filename).resolve() for entry in scoped_recorded} == {Path(shared.__file__).resolve()}
    assert {entry.lineno for entry in scoped_recorded} == {recorded[1].lineno}
    assert scoped.metadata['warnings'] and scoped.metadata['applicability_inputs']


def test_3d_preparation_loads_only_preparation_library(monkeypatch, tmp_path):
    import json
    import subprocess
    import sys
    from sjtu_tpmshx.cpp_interface.stage_libraries import preparation_library

    for name in ('RESULT', 'GEOMETRY', 'NATIVE_SOLVER', 'SOLVER'):
        monkeypatch.setenv(f'TPMSHX_{name}_LIBRARY', str(tmp_path / 'absent'))
    fixtures = json.dumps([(mode, asdict(_configuration(mode)))
                           for mode in ('uniform', 'xy', 'xyz', 'grid', 'offset')])
    code = '''
from copy import deepcopy
import json
from pathlib import Path
import sys
images = []
def capture(event, args):
    if event == 'ctypes.dlopen' and args[0] and 'tpmshx_' in Path(args[0]).name.lower():
        images.append(Path(args[0]).resolve())
sys.addaudithook(capture)
from sjtu_tpmshx.data_types.compute_config import ComputeConfig
from sjtu_tpmshx.preprocess import api
for mode, payload in json.loads(sys.argv[2]):
    cfg = ComputeConfig.from_dict(payload)
    api.prepare_case(cfg, case_id='iso-' + mode)
    api.prepare_inlet_mass_capacities(cfg)
    if mode != 'offset':
        flow_cfg = deepcopy(cfg)
        flow_cfg.geometry.delta_levelset = 0.
        api.resolve_fixed_mass_flow_config(flow_cfg, mass_flow_A_kg_s=.001, mass_flow_B_kg_s=.01)
        api.prepare_fixed_mass_flow_case(flow_cfg, mass_flow_A_kg_s=.001, mass_flow_B_kg_s=.01, case_id='iso-f-' + mode)
forbidden = [name for name in sys.modules if name.startswith((
    'sjtu_tpmshx.solvers', 'sjtu_tpmshx.postprocess', 'PySide6', 'CoolProp',
))]
if forbidden:
    raise SystemExit(f'unexpected modules: {forbidden}')
if set(images) != {Path(sys.argv[1]).resolve()}:
    raise SystemExit(str(images))
'''
    subprocess.run([sys.executable, '-c', code, preparation_library.path(), fixtures], check=True, timeout=120)
