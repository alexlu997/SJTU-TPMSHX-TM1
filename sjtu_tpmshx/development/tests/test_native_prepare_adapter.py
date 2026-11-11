"""Qualify the production adapter against the independent preparation reference."""
from collections.abc import Mapping
from contextlib import nullcontext
from dataclasses import asdict, fields, is_dataclass, replace
from itertools import product
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import preparation_api_reference as reference
from sjtu_tpmshx.development.tests import test_native_preparation_continuous as continuous
from sjtu_tpmshx.development.tests import test_native_preparation_mass_flow as uniform
from sjtu_tpmshx.preprocess import api
from sjtu_tpmshx.preprocess.two_d import native_preparation
from sjtu_tpmshx.shared.domain.run_warnings import range_observations, warning_scope


@pytest.fixture(autouse=True)
def _release_test_cache_state():
    yield
    # Warm-order cases must not prewarm unrelated independent stage tests.
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    compute.cache_clear()
    compute_geometry.cache_clear()


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
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    from sjtu_tpmshx.shared.logutil import get_logger
    if clear_cache:
        compute.cache_clear()
        compute_geometry.cache_clear()
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


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('pair', list(product(('air', 'water', 'sco2', 'co2'), repeat=2)))
def test_complete_case_matches_reference(monkeypatch, spatial, topology, pair):
    config = (continuous._configuration if spatial else uniform._configuration)(topology, pair)
    before = asdict(config)
    expected = _capture(monkeypatch, reference, 'full', config)
    actual = _capture(monkeypatch, api, 'full', config)
    _same(actual, expected)
    _same(asdict(config), before, 'unchanged input')


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('operation', ['capacity', 'resolve', 'full'])
@pytest.mark.parametrize('explicit', [False, True])
def test_mass_routes_and_stale_speed(monkeypatch, spatial, operation, explicit):
    config = (continuous._configuration if spatial else uniform._configuration)()
    targets = (.003, .03) if explicit else None
    config.fluid_A.u_mps, config.fluid_B.u_mps = -99., -88.
    if not explicit:
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .003, .03
    expected = _capture(monkeypatch, reference, operation, config, targets)
    actual = _capture(monkeypatch, api, operation, config, targets)
    _same(actual, expected)


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('dtype', [float, np.float16, np.float32, np.float64, np.int16])
@pytest.mark.parametrize('array', [False, True])
def test_typed_capacity_and_resolved_values(monkeypatch, spatial, dtype, array):
    config = (continuous._configuration if spatial else uniform._configuration)()
    depth = dtype(1) if dtype is np.int16 else dtype(.042)
    config.geometry.Lz_m = np.asarray(depth) if array else depth
    targets = tuple(np.asarray(dtype(value)) if array else dtype(value)
                    for value in ((1, 2) if dtype is np.int16 else (.003, .03)))
    for operation in ('capacity', 'resolve', 'full'):
        _same(_capture(monkeypatch, api, operation, config, targets),
              _capture(monkeypatch, reference, operation, config, targets))


@pytest.mark.parametrize('spatial,topology,pair', [
    (False, topology, pair) for topology in ('Diamond', 'Gyroid')
    for pair in product(('air', 'water', 'sco2', 'co2'), repeat=2)
] + [(True, 'Gyroid', ('air', 'water')), (True, 'Diamond', ('co2', 'co2')), (True, 'Gyroid', ('co2', 'co2'))])
def test_existing_experimental_selection(monkeypatch, spatial, topology, pair):
    config = (continuous._configuration if spatial else uniform._configuration)(topology, pair, 'experimental')
    _same(_capture(monkeypatch, api, 'full', config), _capture(monkeypatch, reference, 'full', config))


def _failure(monkeypatch, module, config, targets=None):
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    compute.cache_clear()
    compute_geometry.cache_clear()
    from sjtu_tpmshx.shared.logutil import get_logger
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


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('kind', ['speed', 'temperature', 'pressure', 'earlier-water', 'target-replaces-speed'])
def test_host_object_error_order(monkeypatch, side, spatial, kind):
    config = (continuous._configuration if spatial else uniform._configuration)('Diamond', ('air', 'water'))
    fluid = getattr(config, 'fluid_' + side)
    name = {'temperature': 'T_in_K', 'pressure': 'P_in_Pa'}.get(kind, 'u_mps')
    setattr(fluid, name, np.asarray(getattr(fluid, name), dtype=np.float64))
    if kind == 'earlier-water':
        config.fluid_B.T_in_K = 450.
    if kind == 'target-replaces-speed':
        targets = (.003, .03)
        _same(_capture(monkeypatch, api, 'full', config, targets),
              _capture(monkeypatch, reference, 'full', config, targets))
    else:
        assert _failure(monkeypatch, api, config) == _failure(monkeypatch, reference, config)


def test_no_target_resolution_keeps_identity_without_library(monkeypatch):
    config = uniform._configuration()
    config.fluid_A.u_mps = -99.
    monkeypatch.setenv('TPMSHX_PREPARATION_LIBRARY', '/missing/preparation/library')
    assert api.resolve_inlet_flow_config(config) is config


def test_missing_library_does_not_call_old_physical_route(monkeypatch):
    from sjtu_tpmshx.preprocess.two_d import preparation
    config = uniform._configuration()
    monkeypatch.setenv('TPMSHX_PREPARATION_LIBRARY', '/missing/preparation/library')
    monkeypatch.setattr(preparation, '_prepare_case', lambda *args, **kwargs: pytest.fail('old route executed'))
    with pytest.raises(FileNotFoundError, match='prebuilt native preparation library is missing'):
        api.prepare_case(config, case_id='missing')


def test_nonzero_delta_keeps_explicit_original_route(monkeypatch):
    config = uniform._configuration()
    config.geometry.delta_levelset = .1
    monkeypatch.setattr(native_preparation, '_execute', lambda *args, **kwargs: pytest.fail('native symmetric route executed'))
    _same(_capture(monkeypatch, api, 'full', config), _capture(monkeypatch, reference, 'full', config))


def test_callback_exception_restores_scope_and_releases_owner(monkeypatch):
    from sjtu_tpmshx.shared.domain.run_warnings import current_warnings
    from sjtu_tpmshx.shared.models import _native_preparation_case as binding
    config = uniform._configuration()
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
    config.fluid_B.u_mps = np.array(config.fluid_B.u_mps)
    parent = {('parent',): 'parent'}
    with warning_scope(parent):
        with pytest.raises(TypeError, match='unhashable'):
            api.prepare_case(config, case_id='release')
        assert current_warnings() is parent
        assert parent == {('parent',): 'parent'}
    assert released == [True]


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64, np.int16])
@pytest.mark.parametrize('array', [False, True])
def test_material_scalar_and_array_types(monkeypatch, spatial, dtype, array):
    config = (continuous._configuration if spatial else uniform._configuration)()
    value = dtype(14.37)
    config.geometry.k_s_W_mK = np.asarray(value) if array else value
    _same(_capture(monkeypatch, api, 'full', config), _capture(monkeypatch, reference, 'full', config))


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('side', ['A', 'B'])
def test_single_target_keeps_other_speed_and_snapshot(monkeypatch, spatial, side):
    config = (continuous._configuration if spatial else uniform._configuration)()
    selected = getattr(config, 'fluid_' + side)
    selected.mass_flow_kg_s = .003 if side == 'A' else .03
    selected.u_mps = np.array(-99.)
    for operation in ('resolve', 'full'):
        _same(_capture(monkeypatch, api, operation, config),
              _capture(monkeypatch, reference, operation, config))


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('field', ['L_cell_mm', 't_wall_mm'])
def test_geometry_object_error_precedes_later_properties(monkeypatch, spatial, field):
    config = (continuous._configuration if spatial else uniform._configuration)()
    setattr(config.geometry, field, np.asarray(getattr(config.geometry, field)))
    config.fluid_B.u_mps = np.asarray(config.fluid_B.u_mps)
    assert _failure(monkeypatch, api, config) == _failure(monkeypatch, reference, config)


@pytest.mark.parametrize('refine', [False, True])
@pytest.mark.parametrize('side', ['A', 'B'])
def test_host_error_does_not_depend_on_grid_log(monkeypatch, refine, side):
    config = uniform._configuration()
    config.flags.port_wall_refine = refine
    if refine:
        config.solver.Nx, config.solver.Ny = 22, 24
    getattr(config, 'fluid_' + side).u_mps = np.array(1.)
    assert _failure(monkeypatch, api, config) == _failure(monkeypatch, reference, config)


@pytest.mark.parametrize('host_failure', [False, True])
def test_floating_failure_keeps_host_precedence(monkeypatch, host_failure):
    config = uniform._configuration('Diamond', ('air', 'sco2'))
    config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.e308, alpha_G=1.e308,
                            parameter_version='overflow-boundary', source='regression', applicability='test only')
    if host_failure:
        config.fluid_A.u_mps = np.asarray(config.fluid_A.u_mps)
    with np.errstate(over='raise', invalid='raise'):
        assert _failure(monkeypatch, api, config) == _failure(monkeypatch, reference, config)


@pytest.mark.parametrize('field', ['parameter_version', 'source', 'applicability'])
def test_saved_text_keeps_complete_utf8_bytes(monkeypatch, field):
    config = uniform._configuration('Diamond', ('sco2', 'water'))
    config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.13, alpha_G=2.27,
                            parameter_version='saved-version', source='retained source', applicability='retained scope')
    config.sco2_nu = replace(config.sco2_nu, **{field: '前段\x00后段'})
    _same(_capture(monkeypatch, api, 'full', config), _capture(monkeypatch, reference, 'full', config))


@pytest.mark.parametrize('field', ['u_mps', 'L_cell_mm'])
@pytest.mark.parametrize('first_strong', [False, True])
def test_equal_values_keep_existing_cache_order(monkeypatch, field, first_strong):
    first = uniform._configuration()
    second = uniform._configuration()
    owner_first = first.geometry if field == 'L_cell_mm' else first.fluid_A
    owner_second = second.geometry if field == 'L_cell_mm' else second.fluid_A
    value = 7. if field == 'L_cell_mm' else 6.
    setattr(owner_first, field, np.float32(value) if first_strong else value)
    setattr(owner_second, field, value if first_strong else np.float32(value))
    _capture(monkeypatch, reference, 'full', first)
    expected = _capture(monkeypatch, reference, 'full', second, clear_cache=False)
    _capture(monkeypatch, api, 'full', first)
    actual = _capture(monkeypatch, api, 'full', second, clear_cache=False)
    _same(actual, expected)


def _cache_info():
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    return compute_geometry.cache_info(), compute.cache_info()


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('operation', ['capacity', 'resolve', 'full'])
@pytest.mark.parametrize('targets', [None, (.003, .03)])
def test_native_entry_keeps_shared_cache_counts(monkeypatch, spatial, operation, targets):
    config = (continuous._configuration if spatial else uniform._configuration)()
    expected = _capture(monkeypatch, reference, operation, config, targets)
    counts = _cache_info()
    actual = _capture(monkeypatch, api, operation, config, targets)
    _same(actual, expected)
    assert _cache_info() == counts


@pytest.mark.parametrize('entry', ['geometry', 'properties'])
@pytest.mark.parametrize('direction', ['public-first', 'prepare-first'])
def test_public_cache_and_native_preparation_share_values(monkeypatch, entry, direction):
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    config = uniform._configuration()
    config.geometry.L_cell_mm = np.float32(7.)
    config.fluid_A.u_mps = np.float32(6.)

    def public():
        if entry == 'geometry':
            return compute_geometry(config.geometry.tpms, 7., config.geometry.t_wall_mm)
        fluid = config.fluid_A
        return compute(config.geometry.tpms, 7., config.geometry.t_wall_mm, 6., fluid.T_in_K,
                       fluid.P_in_Pa, config.geometry.k_s_W_mK, fluid.type,
                       sco2_nu=config.sco2_nu, co2_geometry=False)

    def sequence(module):
        compute.cache_clear()
        compute_geometry.cache_clear()
        if direction == 'public-first':
            public()
            result = _capture(monkeypatch, module, 'full', config, clear_cache=False)
        else:
            _capture(monkeypatch, module, 'full', config, clear_cache=False)
            result = public()
        return result, _cache_info()

    expected = sequence(reference)
    actual = sequence(api)
    _same(actual, expected)


@pytest.mark.parametrize('failure', ['second-side', 'chi', 'preflight'])
def test_failed_preparation_keeps_only_completed_cache_entries(monkeypatch, failure):
    config = uniform._configuration()
    if failure == 'second-side':
        config.fluid_B.u_mps = np.asarray(config.fluid_B.u_mps)
    elif failure == 'chi':
        monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
    else:
        config.fluid_A.u_mps = .000001
        config.extrap = replace(config.extrap, allow=False)
    expected = _failure(monkeypatch, reference, config)
    counts = _cache_info()
    actual = _failure(monkeypatch, api, config)
    assert actual == expected
    assert _cache_info() == counts


@pytest.mark.parametrize('cleared', ['geometry', 'properties'])
def test_independent_cache_clear_preserves_other_cache_values(monkeypatch, cleared):
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    first, second = uniform._configuration(), uniform._configuration()
    first.geometry.L_cell_mm = np.float32(7.)
    second.geometry.L_cell_mm = 7.

    def sequence(module):
        _capture(monkeypatch, module, 'full', first)
        (compute_geometry if cleared == 'geometry' else compute).cache_clear()
        return _capture(monkeypatch, module, 'full', second, clear_cache=False), _cache_info()

    _same(sequence(api), sequence(reference))


def test_warm_property_values_do_not_repeat_floating_operations(monkeypatch):
    config = uniform._configuration('Diamond', ('air', 'sco2'))
    config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.e308, alpha_G=1.e308,
                            parameter_version='overflow-warm', source='regression', applicability='test only')

    def sequence(module):
        with np.errstate(over='ignore', invalid='ignore'):
            _capture(monkeypatch, module, 'full', config)
        with np.errstate(over='raise', invalid='raise'):
            return _capture(monkeypatch, module, 'full', config, clear_cache=False), _cache_info()

    _same(sequence(api), sequence(reference))


@pytest.mark.parametrize('entry', ['public', 'cached', 'unwrapped'])
@pytest.mark.parametrize('frozen', [False, True])
def test_property_cache_wrapper_keeps_warning_source(monkeypatch, entry, frozen):
    from sjtu_tpmshx.shared.models import tpms_calc
    tpms_calc.compute.cache_clear()
    if frozen:
        from sjtu_tpmshx.shared.models import preparation_cache
        monkeypatch.setattr(tpms_calc._compute_cached, '__code__',
            tpms_calc._compute_cached.__code__.replace(co_filename='sjtu_tpmshx/shared/models/preparation_cache.py'))
        monkeypatch.setattr(preparation_cache, '__file__', '/Applications/TM1.app/Contents/Frameworks/sjtu_tpmshx/shared/models/preparation_cache.py')
    function = {'public': tpms_calc.compute, 'cached': tpms_calc._compute_cached,
                'unwrapped': tpms_calc._compute_cached.__wrapped__}[entry]
    args = ('Diamond', 7., .6, .001, 300., 101325.) + ((16.,) if entry == 'public' else ())
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter('always')
        function(*args)
    selected = [item for item in recorded if 'outside the validated range' in str(item.message)]
    assert len(selected) == 1
    assert selected[0].filename == (tpms_calc.__file__ if entry == 'public' else __file__)



def _observe_prepare(monkeypatch, module, operation, config, targets=None, *, scoped=False,
                     direct=False, warning_action='always', warning_message='', repeat=1):
    """Observe public warning filters and partial failure effects independently."""
    from sjtu_tpmshx.shared.domain.run_warnings import range_context
    from sjtu_tpmshx.shared.models import tpms_props, nu_correlations
    from sjtu_tpmshx.shared.models.tpms_calc import compute
    from sjtu_tpmshx.shared.models.tpms_geometry import compute_geometry
    from sjtu_tpmshx.shared.logutil import get_logger
    compute.cache_clear()
    compute_geometry.cache_clear()
    records, observations = {}, []
    with monkeypatch.context() as patch:
        patch.setattr(tpms_props, '_range_warnings_emitted', set())
        for name in ('_EXTRAP_WARNED', '_WATER_NU_WARNED', '_SCO2_NU_WARNED'):
            patch.setattr(nu_correlations, name, set())
        patch.setattr(get_logger('sjtu_tpmshx.preprocess.two_d.preparation'), 'info',
                      lambda message: observations.append(('log', message)))
        with warnings.catch_warnings():
            warnings.simplefilter('always')
            warnings.filterwarnings(warning_action, message=warning_message, category=UserWarning)
            patch.setattr(warnings, 'showwarning', lambda message, category, filename, lineno, *args, **kwargs:
                          observations.append((category.__name__, str(message), filename, lineno)))
            with warning_scope(records) if scoped else nullcontext():
                with range_context(side='parent', stage='caller', layout='scalar'):
                    results, errors = [], []
                    for _ in range(repeat):
                        try:
                            if operation == 'capacity':
                                result = module.prepare_inlet_mass_capacities(config)
                            elif operation == 'resolve':
                                result = module.resolve_fixed_mass_flow_config(config,
                                    mass_flow_A_kg_s=targets[0], mass_flow_B_kg_s=targets[1])
                            elif targets is None or direct:
                                result = module.prepare_case(config, case_id='warning-reference')
                            else:
                                result = module.prepare_fixed_mass_flow_case(config,
                                    mass_flow_A_kg_s=targets[0], mass_flow_B_kg_s=targets[1],
                                    case_id='warning-reference')
                            results.append(result)
                        except Exception as error:
                            chain = []
                            while error is not None:
                                chain.append((type(error).__name__, str(error)))
                                error = error.__cause__
                            errors.append(chain)
        registries = tuple(sorted(value) for value in (tpms_props._range_warnings_emitted,
            nu_correlations._EXTRAP_WARNED, nu_correlations._WATER_NU_WARNED,
            nu_correlations._SCO2_NU_WARNED))
    return (results, errors, observations, range_observations(records),
            range_observations(records, last=True), _cache_info(), registries)


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('operation', ['capacity', 'resolve', 'full'])
@pytest.mark.parametrize('warning_action', ['always', 'error'])
def test_unscoped_preliminary_notices_and_warning_errors(monkeypatch, spatial, operation, warning_action):
    config = (continuous._configuration if spatial else uniform._configuration)('Diamond', ('air', 'water'))
    config.fluid_B.T_in_K, config.fluid_B.P_in_Pa = 370., 101325.
    args = (operation, config, (.003, .03))
    kwargs = dict(warning_action=warning_action, repeat=2)
    expected = _observe_prepare(monkeypatch, reference, *args, **kwargs)
    actual = _observe_prepare(monkeypatch, api, *args, **kwargs)
    _same(actual, expected)
    assert any('water_density' in str(value) for value in expected[1:3])


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('direct', [False, True])
def test_failure_keeps_completed_range_observations(monkeypatch, spatial, direct):
    config = (continuous._configuration if spatial else uniform._configuration)('Diamond', ('air', 'water'))
    config.fluid_B.T_in_K, config.fluid_B.P_in_Pa = 370., 101325.
    old, new, targets = reference, api, (1.e-12, .03)
    if direct:
        from sjtu_tpmshx.development.tests import preparation_case_reference as old
        from sjtu_tpmshx.preprocess.two_d import preparation as new
        config.fluid_A.T_in_K = 1001.
        config.fluid_B.u_mps = np.asarray(config.fluid_B.u_mps)
        targets = None
    else:
        config.extrap = replace(config.extrap, allow=False)
    expected = _observe_prepare(monkeypatch, old, 'full', config, targets, scoped=True, direct=direct)
    actual = _observe_prepare(monkeypatch, new, 'full', config, targets, scoped=True, direct=direct)
    _same(actual, expected)
    assert expected[1] and expected[3]


@pytest.mark.parametrize('spatial', [False, True])
@pytest.mark.parametrize('fluid,experimental', [('air', False), ('water', False),
    ('sco2', False), ('sco2', True), ('co2', False)])
@pytest.mark.parametrize('warning_error', [False, True])
def test_direct_preparation_preserves_standalone_notice_order(monkeypatch, spatial, fluid, experimental, warning_error):
    from sjtu_tpmshx.development.tests import preparation_case_reference as old
    from sjtu_tpmshx.preprocess.two_d import preparation as new
    config = (continuous._configuration if spatial else uniform._configuration)('Diamond', (fluid, fluid))
    config.fluid_A.u_mps = config.fluid_B.u_mps = 1.e-6
    if experimental:
        config.sco2_nu = replace(config.sco2_nu, mode='experimental', alpha_D=1.13, alpha_G=2.27,
            parameter_version='notice-regression', source='regression', applicability='test only')
    options = dict(direct=True, repeat=2, warning_action='error' if warning_error else 'always',
        warning_message=(r'.*outside the validated range' if fluid == 'air' else
                         r'CO2 .* outside CFD calibration' if fluid == 'co2' else r'.*Nu extrap.*'))
    expected = _observe_prepare(monkeypatch, old, 'full', config, **options)
    actual = _observe_prepare(monkeypatch, new, 'full', config, **options)
    _same(actual, expected)
    assert bool(expected[1]) == warning_error
    assert expected[2]
