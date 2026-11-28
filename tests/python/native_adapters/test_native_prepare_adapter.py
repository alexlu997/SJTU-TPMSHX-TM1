"""Verify 2D native preparation adapter contracts, invariants, caches and errors."""
from collections.abc import Mapping
from contextlib import contextmanager, nullcontext
from copy import deepcopy
import ctypes as ct
from dataclasses import asdict, fields, is_dataclass, replace
from itertools import product
from pathlib import Path
import warnings

import numpy as np
import pytest

from tm1.cpp_interface import native_preparation, preparation_host
from tm1.preprocess import api, preparation as shared
from tm1.preprocess.two_d import preparation
from tm1.physical_models import nu_correlations, sigmoid_field, tpms_calc, tpms_geometry, tpms_props
from tm1.run_control.run_warnings import (
    current_warnings, range_observations, warning_scope,
)
from tests.python import native_preparation_abi, property_reference as prop_ref


@pytest.fixture(autouse=True)
def _release_test_cache_state():
    yield
    tpms_calc.compute.cache_clear()
    tpms_geometry.compute_geometry.cache_clear()


def _same(actual, expected, path='case'):
    if is_dataclass(expected):
        assert type(actual) is type(expected), path
        for field in fields(expected):
            _same(getattr(actual, field.name), getattr(expected, field.name), path + '.' + field.name)
    elif isinstance(expected, Mapping):
        assert set(actual) == set(expected), path
        for name in expected:
            _same(actual[name], expected[name], path + '.' + name)
    elif isinstance(expected, np.ndarray):
        assert isinstance(actual, np.ndarray) and actual.dtype == expected.dtype, path
        assert actual.shape == expected.shape, path
        np.testing.assert_array_equal(actual.reshape(-1).view(np.uint8),
                                      expected.reshape(-1).view(np.uint8), err_msg=path)
        assert actual.flags.writeable == expected.flags.writeable, path
    elif isinstance(expected, (list, tuple)):
        assert type(actual) is type(expected) and len(actual) == len(expected), path
        for index, value in enumerate(expected):
            _same(actual[index], value, path + f'[{index}]')
    elif isinstance(expected, float):
        assert type(actual) is type(expected), path
        assert actual.hex() == expected.hex(), path
    else:
        assert type(actual) is type(expected) and actual == expected, path


def _capture(monkeypatch, module, operation, config, targets=None, *, clear_cache=True):
    from tm1.run_control.logutil import get_logger
    if clear_cache:
        tpms_calc.compute.cache_clear()
        tpms_geometry.compute_geometry.cache_clear()
    events = []
    with monkeypatch.context() as patch:
        logger = get_logger('tm1.preprocess.two_d.preparation')
        patch.setattr(logger, 'info', lambda message: events.append(('log', message)))
        with warnings.catch_warnings():
            warnings.simplefilter('always')
            patch.setattr(warnings, 'showwarning', lambda message, category, *args, **kwargs:
                          events.append((category.__name__, str(message))))
            with warning_scope({}) as preliminary:
                if operation == 'capacity':
                    result = module.prepare_inlet_mass_capacities(config)
                elif operation == 'resolve':
                    result = (module.resolve_inlet_flow_config(config) if targets is None else
                              module.resolve_fixed_mass_flow_config(config,
                                  mass_flow_A_kg_s=targets[0], mass_flow_B_kg_s=targets[1]))
                else:
                    result = (module.prepare_case(config, case_id='adapter-reference') if targets is None else
                              module.prepare_fixed_mass_flow_case(config, mass_flow_A_kg_s=targets[0],
                                  mass_flow_B_kg_s=targets[1], case_id='adapter-reference'))
    return result, events, range_observations(preliminary), range_observations(preliminary, last=True)


def _failure(monkeypatch, module, config, targets=None):
    tpms_calc.compute.cache_clear()
    tpms_geometry.compute_geometry.cache_clear()
    from tm1.run_control.logutil import get_logger
    events = []
    with monkeypatch.context() as patch, warnings.catch_warnings():
        warnings.simplefilter('always')
        patch.setattr(warnings, 'showwarning', lambda message, category, *args, **kwargs:
                      events.append((category.__name__, str(message))))
        patch.setattr(get_logger('tm1.preprocess.two_d.preparation'), 'info',
                      lambda message: events.append(('log', message)))
        with pytest.raises(Exception) as caught:
            if targets is None:
                module.prepare_case(config, case_id='host-error')
            else:
                module.prepare_fixed_mass_flow_case(config, mass_flow_A_kg_s=targets[0],
                                                  mass_flow_B_kg_s=targets[1], case_id='host-error')
    error, chain = caught.value, []
    while error is not None:
        chain.append((type(error), str(error)))
        error = error.__cause__
    return chain, events


def _cache_info():
    return tuple(tpms_geometry.compute_geometry.cache_info()), tuple(tpms_calc.compute.cache_info())


def _check_2d_case_invariants(case, config):
    dx, dy = case.grid['dx'], case.grid['dy']
    assert dx.dtype == np.float64 and dy.dtype == np.float64
    assert np.all(dx > 0.) and np.all(dy > 0.)
    assert dx.sum() == pytest.approx(float(config.geometry.L_dom_m), rel=1e-12)
    assert dy.sum() == pytest.approx(float(config.geometry.H_dom_m), rel=1e-12)
    shape = (dx.size, dy.size)
    for key in ('eps_arr', 'K_ss_arr', 'L_field_m', 't_field_m'):
        field = case.design_fields[key]
        assert field.shape == shape and field.dtype == np.float64 and np.all(np.isfinite(field))
        assert not field.flags.writeable
    assert np.all((case.design_fields['eps_arr'] > 0.) & (case.design_fields['eps_arr'] < 1.))
    for side in 'AB':
        fluid = getattr(config, 'fluid_' + side)
        props = prop_ref.fluid_props(fluid.type, float(fluid.T_in_K), float(fluid.P_in_Pa))
        static = case.parameters['static_properties'][side]
        assert static['rho'] == pytest.approx(props.rho, rel=1e-12)
        assert static['mu'] == pytest.approx(props.mu, rel=1e-12)
        assert static['k_f'] == pytest.approx(props.k, rel=1e-12)


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(('air', 'water', 'sco2', 'co2'), repeat=2)))
def test_complete_case_satisfies_physical_invariants(monkeypatch, spatial, topology, pair):
    config = (native_preparation_abi._configuration_continuous if spatial else native_preparation_abi._configuration_mass_flow)(topology, pair)
    before = deepcopy(asdict(config))
    case, _, _, _ = _capture(monkeypatch, api, 'full', config)
    _check_2d_case_invariants(case, config)
    _same(asdict(config), before, 'unchanged input')


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('operation,targets', [('full', None), ('capacity', None),
    ('resolve', (.001, .001)), ('full', (.001, .001))])
def test_native_zoned_routes_complete_and_preserve_config(monkeypatch, tmp_path, mode, operation, targets):
    from tests.python.solver_tm1.test_prepared_zoned_thermal_2d import _config
    config = _config('grid' if mode == 'sigmoid' else mode)
    config.geometry.Lz_m = .042
    if mode == 'sigmoid':
        config.zones.pareto_x_decision = np.column_stack(
            (np.linspace(5., 8., 18), np.linspace(.3, .6, 18))).ravel().tolist()
        lut = sigmoid_field.GeometryLUT('Gyroid', n_L=2, n_t=2, N=16, cache_dir=tmp_path)
        monkeypatch.setattr(sigmoid_field, 'get_geometry_lut', lambda *args, **kwargs: lut)
        monkeypatch.setitem(sigmoid_field._lut_cache, (config.geometry.tpms,), lut)
    before = deepcopy(asdict(config))
    result, _, _, _ = _capture(monkeypatch, api, operation, config, targets)
    if operation == 'capacity':
        assert set(result) == {'A', 'B'} and all(v > 0. for v in result.values())
    elif operation == 'resolve':
        assert result.fluid_A.u_mps > 0. and result.fluid_B.u_mps > 0.
    else:
        _check_2d_case_invariants(result, config)
    _same(asdict(config), before, 'unchanged input')


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('explicit', [False, True])
def test_mass_routes_resolve_stale_speeds_consistently(monkeypatch, spatial, explicit):
    config = (native_preparation_abi._configuration_continuous if spatial else native_preparation_abi._configuration_mass_flow)()
    targets = (.003, .03) if explicit else None
    config.fluid_A.u_mps, config.fluid_B.u_mps = -99., -88.
    if not explicit:
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .003, .03
    caps, _, _, _ = _capture(monkeypatch, api, 'capacity', config)
    resolved, _, _, _ = _capture(monkeypatch, api, 'resolve', config, targets)
    case, _, _, _ = _capture(monkeypatch, api, 'full', config, targets)
    for side, target in zip('AB', (.003, .03)):
        expected_u = target / caps[side]
        assert getattr(resolved, 'fluid_' + side).u_mps == pytest.approx(expected_u, rel=1e-13)
        assert case.parameters['u_' + side] == pytest.approx(expected_u, rel=1e-13)


@pytest.mark.parametrize('spatial,topology,pair', [
    (False, topology, pair) for topology in ('Diamond', 'Gyroid')
    for pair in product(('air', 'water', 'sco2', 'co2'), repeat=2)
] + [(True, 'Gyroid', ('air', 'water')), (True, 'Diamond', ('co2', 'co2')), (True, 'Gyroid', ('co2', 'co2'))])
def test_existing_experimental_selection(monkeypatch, spatial, topology, pair):
    config = (native_preparation_abi._configuration_continuous if spatial else native_preparation_abi._configuration_mass_flow)(topology, pair, 'experimental')
    case, _, _, _ = _capture(monkeypatch, api, 'full', config)
    _check_2d_case_invariants(case, config)
    assert case.parameters['flow_inputs']['A']['metadata'] is not None


def test_no_target_resolution_keeps_identity_without_library(monkeypatch):
    config = native_preparation_abi._configuration_mass_flow()
    config.fluid_A.u_mps = -99.
    monkeypatch.setenv('TPMSHX_PREPARATION_LIBRARY', '/missing/preparation/library')
    assert api.resolve_inlet_flow_config(config) is config


def test_missing_library_is_reported(monkeypatch):
    config = native_preparation_abi._configuration_mass_flow()
    monkeypatch.setenv('TPMSHX_PREPARATION_LIBRARY', '/missing/preparation/library')
    with pytest.raises(FileNotFoundError, match='prebuilt native preparation library is missing'):
        api.prepare_case(config, case_id='missing')


def test_direct_2d_preparation_keeps_dimension_guard():
    config = native_preparation_abi._configuration_mass_flow()
    config.solver.Nz = 2
    with pytest.raises(ValueError, match='2D preparation requires solver.Nz == 1'):
        preparation.prepare_case(config, case_id='wrong-dimension')


@pytest.mark.parametrize('prepare, flow', [
    (api.prepare_case, {}),
    (preparation.prepare_case, {}),
    (api.prepare_fixed_mass_flow_case, {'mass_flow_A_kg_s': .01, 'mass_flow_B_kg_s': .02}),
    (preparation.prepare_mass_flow_case, {'targets': {'A': .01, 'B': .02}}),
], ids=['public', 'direct', 'public-fixed-flow', 'direct-fixed-flow'])
def test_nominal_grid_warns_once_per_axis(prepare, flow):
    from tm1.data_types.compute_config import ComputeConfig

    config = ComputeConfig()
    config.geometry.L_dom_m = config.geometry.H_dom_m = float(np.finfo(float).smallest_subnormal)
    config.geometry.Lz_m = .042
    config.solver.Nx = config.solver.Ny = 4
    outcome = pytest.raises(ValueError, match='side A: inlet density times open pore area') if flow else nullcontext()
    with warnings.catch_warnings(record=True) as notices, np.errstate(under='warn'):
        warnings.simplefilter('default')
        with outcome:
            prepare(config, case_id='nominal-grid', **flow)
    assert [(str(item.message), item.category, Path(item.filename)) for item in notices] == [
        ('underflow encountered in divide', RuntimeWarning, Path(preparation.__file__))] * 2
    assert [item.lineno for item in notices] == [14, 16]


def test_nonzero_delta_uses_native_thermal_geometry(monkeypatch):
    from tm1.cpp_interface import _native_geometry
    config = native_preparation_abi._configuration_mass_flow()
    config.geometry.delta_levelset = .1
    monkeypatch.setattr(_native_geometry, 'prepare_sides',
                        lambda *args, **kwargs: pytest.fail('native stage reentered Python thermal geometry'))
    case, _, _, _ = _capture(monkeypatch, api, 'full', config)
    assert case.parameters['thermal_geometry']['split_A'] > .5
    assert case.parameters['thermal_geometry']['side_geometry'] is not None


def test_callback_exception_restores_scope_and_releases_owner(monkeypatch):
    from tm1.cpp_interface import preparation_host as binding
    config = native_preparation_abi._configuration_mass_flow()
    actual = binding._Bindings
    released = []

    def bindings(path):
        value = actual(path)
        for key, release in value.releases.items():
            def checked(pointer, release=release):
                released.append(True)
                release(pointer)
            value.releases[key] = checked
        return value

    monkeypatch.setattr(binding, '_bindings', bindings)
    monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
    parent = {('parent',): 'parent'}
    with warning_scope(parent):
        with pytest.raises(ValueError, match='could not convert string to float'):
            api.prepare_case(config, case_id='release')
        assert current_warnings() is parent
        assert parent == {('parent',): 'parent'}
    assert released == [True]


@pytest.mark.parametrize('field', ['parameter_version', 'source', 'applicability'])
def test_saved_text_keeps_complete_utf8_bytes(monkeypatch, field):
    config = native_preparation_abi._configuration_mass_flow('Diamond', ('sco2', 'water'))
    config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.13, alpha_G=2.27,
                            parameter_version='saved-version', source='retained source', applicability='retained scope')
    config.sco2_nu = replace(config.sco2_nu, **{field: '前段\x00后段'})
    case, _, _, _ = _capture(monkeypatch, api, 'full', config)
    assert case.metadata['model_metadata']['sco2_nu'][field] == '前段\x00后段'


def test_public_cache_and_native_preparation_share_float64_entries(monkeypatch):
    config = native_preparation_abi._configuration_mass_flow()
    config.geometry.L_cell_mm = np.float32(7.)
    config.fluid_A.u_mps = np.float32(6.)
    _capture(monkeypatch, api, 'full', config)
    first_geom, first_inlet = _cache_info()
    assert first_geom[3] >= 1 and first_inlet[3] >= 2
    _capture(monkeypatch, api, 'full', config, clear_cache=False)
    second_geom, second_inlet = _cache_info()
    assert second_geom[0] > first_geom[0] and second_inlet[0] > first_inlet[0]


@pytest.mark.parametrize('fluid', ['air', 'co2'])
@pytest.mark.parametrize('warm', [False, True])
def test_invalid_chi_preserves_error_and_only_completed_geometry(monkeypatch, fluid, warm):
    from tm1.run_control import run_environment

    config = native_preparation_abi._configuration_mass_flow(pair=(fluid, 'water'))
    geometry = tpms_geometry.compute_geometry
    geometry.cache_clear()
    tpms_calc.compute.cache_clear()
    standard = fluid == 'air'
    if warm:
        geometry(config.geometry.tpms, config.geometry.L_cell_mm, config.geometry.t_wall_mm)
    monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
    resolve = run_environment._resolve_chi_s
    original = []

    def capture(*args, **kwargs):
        try:
            return resolve(*args, **kwargs)
        except ValueError as error:
            error.add_note('captured chi conversion')
            original.append(error)
            raise

    monkeypatch.setattr(run_environment, '_resolve_chi_s', capture)
    with pytest.raises(ValueError, match='could not convert string to float') as caught:
        api.prepare_case(config, case_id='chi-selection')
    assert original == [caught.value]
    assert caught.value.__notes__ == ['captured chi conversion']
    assert caught.value.diagnostic['code'] == 'material.invalid_chi'
    assert geometry.cache_info() == (int(standard and warm), int(standard or warm), 32768, int(standard or warm))
    assert tpms_calc.compute.cache_info() == (0, 0, 4096, 0)


def test_shared_geometry_applies_each_material_after_lookup(monkeypatch):
    from tm1.preprocess.quick_design import pressure_fractions
    from tests.python.native_adapters.test_native_quick_prepare import _args

    config = native_preparation_abi._configuration_mass_flow('Diamond', ('air', 'water'))
    geo = config.geometry
    scalar = tpms_geometry.compute_geometry
    scalar.cache_clear()
    nominal = scalar(geo.tpms, geo.L_cell_mm, geo.t_wall_mm)
    args = _args(topo=geo.tpms, l=geo.L_cell_mm, t=geo.t_wall_mm)
    pressure_fractions(**args)
    assert scalar.cache_info() == (1, 1, 32768, 1)
    for conductivity, chi in ((16., '.25'), (22., '.7')):
        geo.k_s_W_mK = conductivity
        monkeypatch.setenv('TPMSHX_CHI_S', chi)
        warm = api.prepare_case(config, case_id='shared-material')
        assert scalar.cache_info().misses == 1
        solid = tpms_props.geometry(geo.tpms, geo.L_cell_mm, geo.t_wall_mm, conductivity)
        assert solid['D_h'] == nominal['D_h']
        assert np.all(warm.design_fields['K_ss_arr'] == solid['K_ss'])
        scalar.cache_clear()
        tpms_calc.compute.cache_clear()
        cold = api.prepare_case(config, case_id='cold-material')
        _same(warm.design_fields, cold.design_fields)
        _same(warm.parameters['static_properties'], cold.parameters['static_properties'])


def test_warm_inlet_converts_each_field_before_reading_the_next():
    config = native_preparation_abi._configuration_mass_flow()
    shared.inlet_cache.clear()
    with warning_scope({}):
        api.prepare_case(config, case_id='warm')
        properties, _ = next(iter(shared.inlet_cache.values.values()))
        properties['epsilon'] = 'bad-real'
        del properties['rho']
        with pytest.raises(TypeError, match='^must be real number, not str$') as caught:
            api.prepare_case(config, case_id='warm')
    assert caught.value.__cause__ is None


@pytest.mark.parametrize('entry', ['public', 'cached', 'unwrapped'])
@pytest.mark.parametrize('frozen', [False, True])
def test_property_cache_wrapper_keeps_warning_source(monkeypatch, entry, frozen):
    tpms_calc.compute.cache_clear()
    if frozen:
        from tm1.physical_models import preparation_cache
        monkeypatch.setattr(tpms_calc._compute_cached, '__code__',
            tpms_calc._compute_cached.__code__.replace(co_filename='python/physical_models/preparation_cache.py'))
        monkeypatch.setattr(preparation_cache, '__file__', '/Applications/TM1.app/Contents/Frameworks/python/physical_models/preparation_cache.py')
    function = {'public': tpms_calc.compute, 'cached': tpms_calc._compute_cached,
                'unwrapped': tpms_calc._compute_cached.__wrapped__}[entry]
    args = ('Diamond', 7., .6, .001, 300., 101325.) + ((16.,) if entry == 'public' else ())
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter('always')
        function(*args)
    selected = [item for item in recorded if 'outside the validated range' in str(item.message)]
    assert len(selected) == 1
    assert selected[0].filename == (tpms_calc.__file__ if entry == 'public' else __file__)


def test_case_and_binding_values_survive_release_and_second_call(monkeypatch):
    config = native_preparation_abi._configuration_continuous()
    original, assemble = preparation_host.operation, preparation._case
    releases, evidence, model_names = [], [], []
    buffers = []

    @contextmanager
    def replace_buffers(*args, **kwargs):
        with original(*args, **kwargs) as result:
            source = result.prepared
            model_names.append(ct.string_at(source.models[0].name.data, source.models[0].name.size).decode())
            views = (source.dx, source.cell_length, source.sides[0].inlet_profile, source.models[0].name)
            replacements = []
            for view in views:
                saved = type(view).from_buffer_copy(view)
                size = view.size * ct.sizeof(view.data._type_)
                storage = ct.create_string_buffer(ct.string_at(view.data, size))
                # Keep these buffers live for the checks after release.
                buffers.append(storage)
                view.data = ct.cast(storage, type(view.data))
                replacements.append((view, saved, storage))
            try:
                yield result
            finally:
                for view, saved, storage in replacements:
                    ct.memset(storage, 0, ct.sizeof(storage))
                    ct.memmove(ct.byref(view), ct.byref(saved), ct.sizeof(view))
        releases.append(result.owner)

    def keep_copy(values, *args):
        evidence.append(values)
        return assemble(values, *args)

    monkeypatch.setattr(preparation_host, 'operation', replace_buffers)
    monkeypatch.setattr(preparation, '_case', keep_copy)
    with warning_scope({}):
        first = preparation.prepare_case(config, case_id='first')
        config.solver.Nx += 1
        preparation.prepare_case(config, case_id='second')
    assert releases == [None, None]
    assert first.case_id == 'first' and len(first.grid['dx']) != evidence[1].prepared.nx
    first_values = evidence[0].prepared
    for values, saved in ((first_values.dx, first.grid['dx']),
                          (first_values.cell_length, first.design_fields['L_field_m']),
                          (first_values.sides[0].inlet_profile, first.parameters['boundary_openings']['A']['in_profile_frac'])):
        assert np.any(values != 0.) and not saved.flags.writeable
        np.testing.assert_array_equal(values.view(np.uint64), saved.view(np.uint64))
    assert model_names[0] == first.model_refs[0].name and first.model_refs[0].name


def test_invalid_first_model_precedes_second_model_decode(monkeypatch):
    operation = preparation_host.operation

    @contextmanager
    def damaged_models(*args, **kwargs):
        with operation(*args, **kwargs) as result:
            first, second = result.prepared.models[0].name, result.prepared.models[1].name
            first_size, saved_second = first.size, type(second).from_buffer_copy(second)
            bad_name = ct.create_string_buffer(b'\xff')
            first.size = 0
            second.data, second.size = ct.cast(bad_name, type(second.data)), 1
            try:
                yield result
            finally:
                first.size = first_size
                ct.memmove(ct.byref(second), ct.byref(saved_second), ct.sizeof(second))

    monkeypatch.setattr(preparation_host, 'operation', damaged_models)
    with warning_scope({}), pytest.raises(ValueError, match='^ModelRef requires a name and a version$') as caught:
        api.prepare_case(native_preparation_abi._configuration_mass_flow(), case_id='invalid-models')
    assert caught.value.__cause__ is None


@pytest.mark.parametrize('fault', ['cache', 'copy', 'model'])
def test_fault_keeps_exception_and_releases_once(monkeypatch, fault):
    marker = StopIteration(fault)
    releases = []
    original = preparation_host._Bindings

    def bindings(path):
        owner = original(path)
        for kind, release in owner.releases.items():
            def checked(pointer, kind=kind, release=release):
                view = ct.cast(pointer, ct.POINTER(kind)).contents
                previous = bool(view.owner)
                release(pointer)
                releases.append((previous, bool(view.owner)))
            owner.releases[kind] = checked
        return owner

    def fail(*args):
        raise marker

    monkeypatch.setattr(preparation_host, '_bindings', bindings)
    if fault == 'copy':
        monkeypatch.setattr(native_preparation, 'copy_array', fail)
    elif fault == 'cache':
        monkeypatch.setattr(shared.PreparationCache, 'inlet', fail)
    else:
        read = native_preparation.read_text

        def read_model(value):
            text = read(value)
            if text == 'fluid':
                raise marker
            return text

        monkeypatch.setattr(native_preparation, 'read_text', read_model)
    with warning_scope({}):
        with pytest.raises(StopIteration if fault == 'copy' else RuntimeError) as caught:
            preparation.prepare_case(native_preparation_abi._configuration_mass_flow(), case_id=fault)
    if fault == 'copy':
        assert caught.value is marker and caught.value.__cause__ is None
    else:
        assert str(caught.value) == 'generator raised StopIteration' and caught.value.__cause__ is marker
    assert releases == [(fault != 'cache', False)]


def test_direct_preparation_replays_model_notices_at_the_stage(monkeypatch):
    monkeypatch.setattr(tpms_props, '_range_warnings_emitted', set())
    monkeypatch.setattr(nu_correlations, '_EXTRAP_WARNED', set())
    config = native_preparation_abi._configuration_mass_flow('Gyroid', ('air', 'air'))
    for fluid in (config.fluid_A, config.fluid_B):
        fluid.T_in_K, fluid.u_mps = 1100., .0001
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter('default')
        for _ in range(2):
            tpms_calc.compute.cache_clear()
            tpms_geometry.compute_geometry.cache_clear()
            preparation.prepare_case(config, case_id='warning-site')
    assert [entry.category for entry in recorded] == [UserWarning] * 5
    assert [str(entry.message).split(':', 1)[0] for entry in recorded] == [
        '[surrogate extrap] Fluid A', '[surrogate extrap] Fluid B', 'air_cp', 'Gyroid', '[Nu extrap] Gyroid']
    assert {Path(entry.filename) for entry in recorded} == {Path(shared.__file__)}
    assert recorded[0].lineno == recorded[1].lineno
    assert recorded[2].lineno == recorded[4].lineno
    assert len({recorded[i].lineno for i in (0, 2, 3)}) == 3


@pytest.mark.parametrize('field', ['port', 'zone'])
def test_input_conversion_keeps_the_original_cause(field):
    marker = StopIteration(field)

    class BadFloat(float):
        def __float__(self):
            raise marker

    config = native_preparation_abi._configuration_mass_flow()
    if field == 'port':
        config.bc_A.in_ctr = BadFloat(.5)
    else:
        config.zones.enabled, config.zones.axis = True, 'grid'
        config.zones.grid = dict(k_s=16., cells=[dict(x0=BadFloat(0.), x1=1., y0=0., y1=1., L=7., t=.6)])
    with pytest.raises(RuntimeError, match='^generator raised StopIteration$') as caught:
        preparation.prepare_case(config, case_id=field)
    assert caught.value.__cause__ is marker
