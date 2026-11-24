"""Verify 2D native preparation adapter contracts, invariants, caches and errors."""
from collections.abc import Mapping
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict, fields, is_dataclass, replace
from itertools import product
from pathlib import Path
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.preprocess import api
from sjtu_tpmshx.preprocess.two_d import preparation
from sjtu_tpmshx.physical_models import sigmoid_field, tpms_calc, tpms_geometry
from sjtu_tpmshx.run_control.run_warnings import (
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
    from sjtu_tpmshx.run_control.logutil import get_logger
    if clear_cache:
        tpms_calc.compute.cache_clear()
        tpms_geometry.compute_geometry.cache_clear()
    events = []
    with monkeypatch.context() as patch:
        logger = get_logger('sjtu_tpmshx.preprocess.two_d.preparation')
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
    from sjtu_tpmshx.run_control.logutil import get_logger
    events = []
    with monkeypatch.context() as patch, warnings.catch_warnings():
        warnings.simplefilter('always')
        patch.setattr(warnings, 'showwarning', lambda message, category, *args, **kwargs:
                      events.append((category.__name__, str(message))))
        patch.setattr(get_logger('sjtu_tpmshx.preprocess.two_d.preparation'), 'info',
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
    from sjtu_tpmshx.data_types.compute_config import ComputeConfig

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
    assert notices[0].lineno != notices[1].lineno


def test_nonzero_delta_uses_native_thermal_geometry(monkeypatch):
    from sjtu_tpmshx.cpp_interface import _native_geometry
    config = native_preparation_abi._configuration_mass_flow()
    config.geometry.delta_levelset = .1
    monkeypatch.setattr(_native_geometry, 'prepare_sides',
                        lambda *args, **kwargs: pytest.fail('native stage reentered Python thermal geometry'))
    case, _, _, _ = _capture(monkeypatch, api, 'full', config)
    assert case.parameters['thermal_geometry']['split_A'] > .5
    assert case.parameters['thermal_geometry']['side_geometry'] is not None


def test_callback_exception_restores_scope_and_releases_owner(monkeypatch):
    from sjtu_tpmshx.cpp_interface import preparation_host as binding
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


@pytest.mark.parametrize('entry', ['public', 'cached', 'unwrapped'])
@pytest.mark.parametrize('frozen', [False, True])
def test_property_cache_wrapper_keeps_warning_source(monkeypatch, entry, frozen):
    tpms_calc.compute.cache_clear()
    if frozen:
        from sjtu_tpmshx.physical_models import preparation_cache
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
