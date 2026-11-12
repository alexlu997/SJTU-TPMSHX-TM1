"""Compare the spatial host with the independent public preparation contract."""
from copy import deepcopy
from dataclasses import asdict, replace

import numpy as np
import pytest

from sjtu_tpmshx.development.tests import preparation_api_reference as reference
from sjtu_tpmshx.development.tests import test_native_preparation_spatial_flow as raw
from sjtu_tpmshx.development.tests.test_native_prepare_adapter import _capture, _same, _cache_info, _failure, _observe_prepare
from sjtu_tpmshx.preprocess import api
from sjtu_tpmshx.shared.models import sigmoid_field, tpms_calc, tpms_geometry


@pytest.fixture(autouse=True)
def caches():
    tpms_calc.compute.cache_clear()
    tpms_geometry.compute_geometry.cache_clear()
    yield
    tpms_calc.compute.cache_clear()
    tpms_geometry.compute_geometry.cache_clear()


def configuration(monkeypatch, tmp_path, mode, topology='Gyroid'):
    config = raw._configuration(mode, topology)
    if mode == 'sigmoid':
        table = sigmoid_field.GeometryLUT(topology, n_L=2, n_t=2, N=16, cache_dir=tmp_path)
        monkeypatch.setattr(sigmoid_field, 'get_geometry_lut', lambda *args, **kwargs: table)
        monkeypatch.setitem(sigmoid_field._lut_cache, (topology,), table)
    return config


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
@pytest.mark.parametrize('operation,targets', [('full', None), ('capacity', None), ('resolve', None),
    ('resolve', (.001, .001)), ('full', (.001, .001)), ('configured', None)])
def test_complete_spatial_case_and_cache_counts(monkeypatch, tmp_path, mode, topology, operation, targets):
    config = configuration(monkeypatch, tmp_path, mode, topology)
    if operation == 'configured':
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .001, .001
        config.fluid_A.u_mps = config.fluid_B.u_mps = float('nan')
        operation = 'full'
    before = asdict(config)
    expected = _capture(monkeypatch, reference, operation, config, targets)
    counts = _cache_info(reference)
    actual = _capture(monkeypatch, api, operation, config, targets)
    _same(actual, expected)
    assert _cache_info() == counts
    _same(asdict(config), before, 'unchanged input')


@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
@pytest.mark.parametrize('nominal,spatial', [('Diamond', 'Gyroid'), ('Gyroid', 'Diamond')])
@pytest.mark.parametrize('targets', [None, (.001, .001)])
def test_conflicting_spatial_material_keeps_public_rejection(monkeypatch, tmp_path, mode, nominal, spatial, targets):
    config = configuration(monkeypatch, tmp_path, mode, nominal)
    config.geometry.k_s_W_mK = 15.
    config.zones.config.tpms_type, config.zones.config.k_s = spatial, np.float32(22.)
    config.zones.grid.update(tpms_type=spatial, k_s=np.float32(22.))
    expected = _failure(monkeypatch, reference, config, targets)
    counts = _cache_info(reference)
    actual = _failure(monkeypatch, api, config, targets)
    assert actual == expected
    assert _cache_info() == counts



@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
@pytest.mark.parametrize('warm', [False, True])
def test_spatial_equal_typed_cache_keys(monkeypatch, tmp_path, mode, dtype, warm):
    config = configuration(monkeypatch, tmp_path, mode)
    config.geometry.L_cell_mm = dtype(config.geometry.L_cell_mm)
    config.fluid_A.u_mps = dtype(config.fluid_A.u_mps)
    config.fluid_A.T_in_K = dtype(config.fluid_A.T_in_K)
    config.geometry.k_s_W_mK = dtype(config.geometry.k_s_W_mK)
    if mode in ('x', 'y'):
        for zone in config.zones.config.zones:
            zone.L_mm, zone.t_mm = dtype(zone.L_mm), dtype(zone.t_mm)
    elif mode == 'grid':
        for cell in config.zones.grid['cells']:
            cell['L'], cell['t'] = dtype(cell['L']), dtype(cell['t'])

    def sequence(module):
        first = _capture(monkeypatch, module, 'full', config)
        if warm:
            changed = deepcopy(config)
            changed.geometry.L_cell_mm = float(changed.geometry.L_cell_mm)
            changed.fluid_A.u_mps = float(changed.fluid_A.u_mps)
            changed.geometry.k_s_W_mK = 22.
            changed.zones.config.k_s = 22.
            changed.zones.grid['k_s'] = 22.
            first = _capture(monkeypatch, module, 'full', changed, clear_cache=False)
        return first, _cache_info(module)

    _same(sequence(api), sequence(reference))


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('failure', ['chi', 'unhashable-nominal', 'unhashable-inlet', 'preflight'])
def test_spatial_failure_keeps_completed_cache_entries(monkeypatch, tmp_path, mode, failure):
    config = configuration(monkeypatch, tmp_path, mode)
    if failure == 'chi':
        monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
    elif failure == 'unhashable-nominal':
        config.geometry.L_cell_mm = np.asarray(config.geometry.L_cell_mm)
    elif failure == 'unhashable-inlet':
        config.fluid_B.u_mps = np.asarray(config.fluid_B.u_mps)
    else:
        config.fluid_A.u_mps = 1.e-6
        config.extrap = replace(config.extrap, allow=False)
    expected = _failure(monkeypatch, reference, config)
    counts = _cache_info(reference)
    actual = _failure(monkeypatch, api, config)
    assert actual == expected
    assert _cache_info() == counts


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
def test_spatial_host_does_not_reenter_python_preparation(monkeypatch, tmp_path, mode):
    from sjtu_tpmshx.shared.models import _native_df, _native_geometry
    from sjtu_tpmshx.shared.models.zone_config import ZoneConfig
    config = configuration(monkeypatch, tmp_path, mode)
    expected = _capture(monkeypatch, reference, 'full', config)

    def forbidden(*args, **kwargs):
        pytest.fail('native host reentered a Python numerical workflow')

    monkeypatch.setattr(_native_df, 'project_rows', forbidden)
    monkeypatch.setattr(_native_geometry, 'prepare_sides', forbidden)
    for name in ('compute_properties', 'build_structured_arrays', 'build_structured_geometry',
                 'build_grid_arrays', 'build_grid_geometry'):
        monkeypatch.setattr(ZoneConfig, name, forbidden)
    for name in ('build_continuous_arrays', 'build_continuous_geometry', 'get_geometry_lut'):
        monkeypatch.setattr(sigmoid_field, name, forbidden)
    _same(_capture(monkeypatch, api, 'full', config), expected)


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
def test_capacity_ignores_unconsumed_experimental_drag(monkeypatch, tmp_path, mode):
    config = configuration(monkeypatch, tmp_path, mode)
    config.df_mode = 'experimental'
    _same(_capture(monkeypatch, api, 'capacity', config), _capture(monkeypatch, reference, 'capacity', config))


@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
def test_standalone_spatial_warning_origins(monkeypatch, tmp_path, mode):
    from sjtu_tpmshx.development.tests import preparation_case_reference
    from sjtu_tpmshx.preprocess.two_d import preparation as native_preparation
    config = configuration(monkeypatch, tmp_path, mode)
    config.fluid_A.u_mps = 1.e-6
    config.extrap = replace(config.extrap, allow=True)

    _same(_observe_prepare(monkeypatch, native_preparation, 'full', config, direct=True),
          _observe_prepare(monkeypatch, preparation_case_reference, 'full', config, direct=True))


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_default_lut_cold_memory_and_disk_paths(monkeypatch, tmp_path, topology):
    config = raw._configuration('sigmoid', topology)
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'reference'))
    monkeypatch.delitem(sigmoid_field._lut_cache, (topology,), raising=False)
    expected = _capture(monkeypatch, reference, 'full', config)
    original = sigmoid_field._lut_cache[topology,]
    monkeypatch.delitem(sigmoid_field._lut_cache, (topology,))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'native'))

    def forbidden(*args, **kwargs):
        pytest.fail('native cold LUT construction reentered Python geometry')

    monkeypatch.setattr(sigmoid_field.GeometryLUT, '_precompute', forbidden)
    monkeypatch.setattr(sigmoid_field, 'get_geometry_lut', forbidden)
    _same(_capture(monkeypatch, api, 'full', config), expected)
    created = sigmoid_field._lut_cache[topology,]
    for name in ('L_vals', 't_vals', 'eps_table', 'A0_table'):
        _same(getattr(created, name), getattr(original, name), name)
    _same(_capture(monkeypatch, api, 'full', config), expected)
    assert sigmoid_field._lut_cache[topology,] is created
    monkeypatch.delitem(sigmoid_field._lut_cache, (topology,))
    _same(_capture(monkeypatch, api, 'full', config), expected)
    restored = sigmoid_field._lut_cache[topology,]
    assert restored is not created
    for name in ('L_vals', 't_vals', 'eps_table', 'A0_table'):
        _same(getattr(restored, name), getattr(created, name), name)


@pytest.mark.parametrize('mode', ['x', 'grid', 'sigmoid'])
@pytest.mark.parametrize('direction', [0, 1, 2, 3])
@pytest.mark.parametrize('refined', [False, True])
def test_spatial_physical_ports_and_single_target(monkeypatch, tmp_path, mode, direction, refined):
    config = configuration(monkeypatch, tmp_path, mode)
    config.solver.Nx = config.solver.Ny = 64 if refined else 16
    config.flags = replace(config.flags, port_wall_refine=refined)
    for side in 'AB':
        port = getattr(config, 'bc_' + side)
        port.dir = direction if side == 'A' else 3-direction
        cross = config.geometry.H_dom_m if port.dir in (0, 1) else config.geometry.L_dom_m
        port.in_ctr, port.in_w, port.out_ctr, port.out_w = .4*cross, .4*cross, .6*cross, .4*cross
        port.uniform_inlet_2d = side == 'A'
    config.fluid_A.mass_flow_kg_s = .001
    config.fluid_A.u_mps = float('nan')
    expected = _capture(monkeypatch, reference, 'full', config)
    counts = _cache_info(reference)
    _same(_capture(monkeypatch, api, 'full', config), expected)
    assert _cache_info() == counts


@pytest.mark.parametrize('geometry_allow', [False, True])
@pytest.mark.parametrize('environment_allow', [False, True])
@pytest.mark.parametrize('targets', [None, (.001, .001)])
def test_sigmoid_geometry_extrapolation_policy_is_explicit(monkeypatch, tmp_path, geometry_allow, environment_allow, targets):
    config = configuration(monkeypatch, tmp_path, 'sigmoid')
    config.zones.pareto_x_decision = [value for _ in range(18) for value in (8.2, .62)]
    config.extrap = replace(config.extrap, allow=geometry_allow)
    monkeypatch.setenv('TPMSHX_ALLOW_EXTRAP', '1' if environment_allow else '0')
    _same(_observe_prepare(monkeypatch, api, 'full', config, targets),
          _observe_prepare(monkeypatch, reference, 'full', config, targets))


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('operation', ['resolve', 'full'])
def test_fixed_experimental_spatial_rejection_order(monkeypatch, tmp_path, mode, operation):
    config = configuration(monkeypatch, tmp_path, mode)
    config.df_mode = 'experimental'
    _same(_observe_prepare(monkeypatch, api, operation, config, (.001, .001)),
          _observe_prepare(monkeypatch, reference, operation, config, (.001, .001)))


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
@pytest.mark.parametrize('operation,targets', [('full', None), ('capacity', None), ('full', (.001, .001))])
def test_unsupported_spatial_fluid_keeps_original_failure(monkeypatch, tmp_path, mode, operation, targets):
    config = configuration(monkeypatch, tmp_path, mode)
    config.fluid_A.type, config.fluid_A.T_in_K = 'water', 330.
    _same(_observe_prepare(monkeypatch, api, operation, config, targets),
          _observe_prepare(monkeypatch, reference, operation, config, targets))


@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
def test_spatial_unhashable_region_keeps_first_error_and_cache(monkeypatch, tmp_path, mode):
    config = configuration(monkeypatch, tmp_path, mode)
    if mode == 'grid':
        config.zones.grid['cells'][1]['L'] = np.asarray(config.zones.grid['cells'][1]['L'])
    else:
        zone = config.zones.config.zones[1]
        zone.L_mm = np.asarray(zone.L_mm)
    expected = _failure(monkeypatch, reference, config)
    counts = _cache_info(reference)
    assert _failure(monkeypatch, api, config) == expected
    assert _cache_info() == counts


@pytest.mark.parametrize('mode', ['x', 'y', 'grid', 'sigmoid'])
def test_spatial_saved_case_keeps_complete_reference_contract(monkeypatch, tmp_path, mode):
    from sjtu_tpmshx.shared.io.case_io import load_case, save_case
    config = configuration(monkeypatch, tmp_path, mode)
    expected = _capture(monkeypatch, reference, 'full', config, (.001, .001))
    actual = _capture(monkeypatch, api, 'full', config, (.001, .001))
    _same(actual, expected)
    for name, result in (('reference', expected), ('native', actual)):
        save_case(result[0], tmp_path / (name + '.yaml'))
    _same(load_case(tmp_path / 'native.yaml'), load_case(tmp_path / 'reference.yaml'))


@pytest.mark.parametrize('mode', ['x', 'y'])
@pytest.mark.parametrize('operation,targets', [('full', None), ('capacity', None), ('full', (.001, .001))])
@pytest.mark.parametrize('earlier', [None, 'preflight', 'chi'])
def test_missing_stripe_config_keeps_error_order(monkeypatch, tmp_path, mode, operation, targets, earlier):
    config = configuration(monkeypatch, tmp_path, mode)
    config.zones.config = None
    if earlier == 'preflight':
        config.fluid_A.u_mps = 1.e-6
        config.extrap = replace(config.extrap, allow=False)
    elif earlier == 'chi':
        monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
    expected = _observe_prepare(monkeypatch, reference, operation, config, targets)
    counts = _cache_info(reference)
    _same(_observe_prepare(monkeypatch, api, operation, config, targets), expected)
    assert _cache_info() == counts


@pytest.mark.parametrize('mode', ['uniform', 'continuous', 'x', 'grid', 'sigmoid'])
@pytest.mark.parametrize('dtype', [np.float16, np.float32])
@pytest.mark.parametrize('wall', [.3, .6])
@pytest.mark.parametrize('operation', ['capacity', 'full'])
@pytest.mark.parametrize('allow', [False, True])
def test_typed_geometry_limits_keep_validation_and_cache_order(monkeypatch, tmp_path, mode, dtype, wall, operation, allow):
    if mode in ('uniform', 'continuous'):
        from sjtu_tpmshx.development.tests.test_native_prepare_adapter import uniform, continuous
        config = (uniform if mode == 'uniform' else continuous)._configuration(pair=('air', 'air'))
    else:
        config = configuration(monkeypatch, tmp_path, mode)
    config.geometry.t_wall_mm = dtype(wall)
    config.extrap = replace(config.extrap, allow=allow)
    expected = _observe_prepare(monkeypatch, reference, operation, config)
    counts = _cache_info(reference)
    _same(_observe_prepare(monkeypatch, api, operation, config), expected)
    assert _cache_info() == counts


@pytest.mark.parametrize('allow', [False, True])
def test_preflight_keeps_nu_and_geometry_reasons_separate(monkeypatch, tmp_path, allow):
    config = configuration(monkeypatch, tmp_path, 'x')
    config.geometry.t_wall_mm = np.float32(.6)
    config.fluid_A.u_mps = 1.e-6
    config.extrap = replace(config.extrap, allow=allow)
    _same(_observe_prepare(monkeypatch, api, 'full', config),
          _observe_prepare(monkeypatch, reference, 'full', config))


@pytest.mark.parametrize('mode', ['x', 'y'])
@pytest.mark.parametrize('fault', ['missing-cell', 'row-extra', 'config-extra', 'missing-zones', 'missing-topology', 'missing-conductivity'])
@pytest.mark.parametrize('operation,targets', [('full', None), ('capacity', None), ('full', (.001, .001))])
@pytest.mark.parametrize('earlier', [None, 'chi', 'preflight'])
def test_canonical_stripe_schema_keeps_error_order(monkeypatch, tmp_path, mode, fault, operation, targets, earlier):
    config = configuration(monkeypatch, tmp_path, mode)
    model = config.zones.config = asdict(config.zones.config)
    if fault == 'missing-cell':
        del model['zones'][0]['L_mm']
    elif fault == 'row-extra':
        model['zones'][0]['unexpected'] = 1
    elif fault == 'config-extra':
        model['unexpected'] = 1
    else:
        del model[{'missing-zones': 'zones', 'missing-topology': 'tpms_type', 'missing-conductivity': 'k_s'}[fault]]
    if earlier == 'chi':
        monkeypatch.setenv('TPMSHX_CHI_S', 'invalid')
    elif earlier == 'preflight':
        config.fluid_A.u_mps = 1.e-6
        config.extrap = replace(config.extrap, allow=False)
    _same(_observe_prepare(monkeypatch, api, operation, config, targets),
          _observe_prepare(monkeypatch, reference, operation, config, targets))


@pytest.mark.parametrize('operation,targets', [('full', None), ('capacity', None), ('full', (.001, .001)), ('resolve', (.001, .001))])
@pytest.mark.parametrize('unused', ['absent', 'invalid'])
def test_sigmoid_does_not_consume_discrete_material_fields(monkeypatch, tmp_path, operation, targets, unused):
    config = configuration(monkeypatch, tmp_path, 'sigmoid')
    for cell in config.zones.grid['cells']:
        for key in ('L', 't'):
            if unused == 'absent':
                del cell[key]
            else:
                cell[key] = 'unused'
    _same(_capture(monkeypatch, api, operation, config, targets),
          _capture(monkeypatch, reference, operation, config, targets))


@pytest.mark.parametrize('mode', ['x', 'y', 'grid'])
@pytest.mark.parametrize('dtype,other', [(np.float16, 16.0001), (np.float32, 16.0000001)])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('operation,targets', [('full', None), ('capacity', None), ('full', (.001, .001))])
def test_spatial_conductivity_keeps_value_after_weak_comparison(monkeypatch, tmp_path, mode, dtype, other, reverse, operation, targets):
    config = configuration(monkeypatch, tmp_path, mode)
    nominal, spatial = (other, dtype(16.)) if reverse else (dtype(16.), other)
    assert nominal == spatial and float(nominal) != float(spatial)
    config.geometry.k_s_W_mK = nominal
    if mode == 'grid':
        config.zones.grid['k_s'] = spatial
    else:
        config.zones.config.k_s = spatial
    _same(_capture(monkeypatch, api, operation, config, targets),
          _capture(monkeypatch, reference, operation, config, targets))


@pytest.mark.parametrize('operation,targets', [('full', None), ('capacity', None), ('full', (.001, .001))])
def test_geometry_cache_queries_receive_initialized_storage(monkeypatch, tmp_path, operation, targets):
    from sjtu_tpmshx.preprocess.native_preparation import PreparationCacheBridge
    original = PreparationCacheBridge.geometry_at
    lookups = []
    def observed(self, action, key, value):
        if not action:
            assert all(getattr(value, name) == 0. for name, _ in value._fields_)
            lookups.append((key.cell_length_mm, key.wall_thickness_mm))
        return original(self, action, key, value)
    config = configuration(monkeypatch, tmp_path, 'x')
    expected = _capture(monkeypatch, reference, operation, config, targets)
    monkeypatch.setattr(PreparationCacheBridge, 'geometry_at', observed)
    _same(_capture(monkeypatch, api, operation, config, targets), expected)
    assert lookups


@pytest.mark.parametrize('value', [0., -1., float('nan'), float('inf')])
def test_raw_spatial_model_rejects_invalid_conductivity(monkeypatch, tmp_path, value):
    from sjtu_tpmshx.preprocess.two_d import preparation as native_preparation
    config = configuration(monkeypatch, tmp_path, 'x')
    original = native_preparation._input
    def invalid(*args, **kwargs):
        source = original(*args, **kwargs)
        source.model.solid_conductivity_W_mK = value
        return source
    monkeypatch.setattr(native_preparation, '_input', invalid)
    with pytest.raises(ValueError, match='spatial.solid_conductivity_W_mK'):
        api.prepare_case(config, case_id='invalid-spatial-material')
