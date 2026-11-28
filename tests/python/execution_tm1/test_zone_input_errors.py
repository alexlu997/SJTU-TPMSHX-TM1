"""A requested zoned problem must fail instead of solving a uniform one."""
from unittest.mock import Mock

import pytest

from tm1.compute import compute
from tm1.data_types.compute_config import ComputeConfig, ExtrapPolicy, GeometryConfig, SolverConfig, ZoneInputConfig
from tm1.physical_models.zone_config import Zone, ZoneConfig


@pytest.mark.parametrize('axis', ['x', 'y'])
def test_canonical_1d_json_restores_the_same_zone_fields(tmp_path, capsys, axis):
    import json
    from tm1.applications.cli.main import main
    from tm1.preprocess.two_d.preparation import prepare_case

    cfg = ComputeConfig(
        geometry=GeometryConfig(tpms='Diamond'),
        solver=SolverConfig(Nx=8, Ny=6), extrap=ExtrapPolicy(allow=True),
        zones=ZoneInputConfig(enabled=True, axis=axis, config=ZoneConfig(
            zones=[Zone('inlet', 0, 0.5, 6, 0.3), Zone('outlet', 0.5, 1, 7, 0.5)],
            tpms_type='Diamond', k_s=16)))
    path = tmp_path / 'zoned.json'
    cfg.to_json(path)
    loaded = ComputeConfig.from_json(path)
    assert isinstance(loaded.zones.config, dict)
    from tm1.solvers.full_2d import _zone_objects
    from tests.python.native.stage_interception import saved_2d_inputs
    expected = prepare_case(cfg, case_id='original').design_fields
    case = prepare_case(loaded, case_id='loaded')
    parsed, _, _ = saved_2d_inputs(case)
    # The saved stage keeps a plain zone record or builds zone objects from it.
    zone = parsed['zone_config']
    zone = zone if isinstance(zone, ZoneConfig) else _zone_objects(zone)
    assert all(isinstance(item, Zone) for item in zone.zones)
    restored = case.design_fields
    assert restored['axis'] == axis
    for key in ('zone_id', 'eps_arr', 'K_ffA_arr', 'K_ffB_arr', 'h_vA_arr', 'h_vB_arr'):
        assert restored[key] == pytest.approx(expected[key])
    capsys.readouterr()
    assert main([str(path), '--dry-run', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['pipeline'] == 'Pipeline2D'


@pytest.mark.parametrize('enabled,axis', [(False, 'y'), (True, 'grid')])
def test_canonical_loader_keeps_unused_1d_config_semantics(enabled, axis):
    config = {'zones': [{'draft': True}]}
    loaded = ComputeConfig.from_dict({'solver': {'Nz': 1}, 'zones': {
        'enabled': enabled, 'axis': axis, 'config': config,
        'grid': {'cells': [dict(x0=0, x1=1, y0=0, y1=1, L=6, t=0.3)]}}})
    assert loaded.zones.config == config


def test_canonical_1d_stage_does_not_mutate_or_share_source_dict():
    from copy import deepcopy
    from dataclasses import asdict
    from tm1.preprocess.two_d.preparation import prepare_case

    cfg = ComputeConfig(geometry=GeometryConfig(tpms='Diamond'),
        solver=SolverConfig(Nx=8, Ny=6), extrap=ExtrapPolicy(allow=True),
        zones=ZoneInputConfig(enabled=True, config=ZoneConfig(
        zones=[Zone('outlet', 0.5, 1, 7, 0.5, props_A={'saved': [1]}),
               Zone('inlet', 0, 0.5, 6, 0.3, props_A={'saved': [2]})],
        tpms_type='Diamond', k_s=16)))
    source = asdict(cfg)
    original = deepcopy(source)
    loaded = ComputeConfig.from_dict(source)
    assert source == original
    from tests.python.native.stage_interception import saved_2d_inputs
    case = prepare_case(loaded, case_id='detached')
    restored = saved_2d_inputs(case)[0]['zone_config']
    assert source == original
    first = restored.zones[0] if isinstance(restored, ZoneConfig) else Zone(**restored['zones'][0])
    assert first.name == 'inlet'
    first.props_A['saved'] = [99]
    assert source == original


@pytest.mark.parametrize('invalid', ['gap', 'missing_field'])
def test_canonical_1d_json_does_not_swallow_invalid_zones(tmp_path, invalid):
    import json
    from tm1.preprocess.two_d.preparation import prepare_case

    cfg = ComputeConfig(geometry=GeometryConfig(tpms='Diamond'),
        zones=ZoneInputConfig(enabled=True,
        config=ZoneConfig.single_zone(6, 0.3, 'Diamond', 16)))
    path = tmp_path / 'invalid-zone.json'
    cfg.to_json(path)
    payload = json.loads(path.read_text())
    zone = payload['zones']['config']['zones'][0]
    if invalid == 'gap':
        zone['y_frac_start'] = 0.1
    else:
        del zone['L_mm']
    path.write_text(json.dumps(payload))
    loaded = ComputeConfig.from_json(path)
    with pytest.raises(ValueError if invalid == 'gap' else TypeError,
                       match='start at 0' if invalid == 'gap' else 'L_mm'):
        prepare_case(loaded, case_id='invalid-zone')


def test_valid_partial_grid_coverage_is_not_redefined():
    zones = ZoneInputConfig(enabled=True, axis='grid', grid=dict(
        cells=[dict(x0=0.25, x1=0.75, y0=0.2, y1=0.8, L=6, t=0.3)]))
    assert zones.validate() is zones


@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('source', ['object', 'yaml'])
@pytest.mark.parametrize('index,endpoint,value', [
    (0, 'y_frac_start', float('nan')),
    (0, 'y_frac_end', float('nan')),
    (1, 'y_frac_start', float('nan')),
    (1, 'y_frac_end', float('nan')),
    (0, 'y_frac_end', float('inf')),
    (1, 'y_frac_start', -float('inf')),
])
def test_nonfinite_stripe_endpoints_never_solve(tmp_path, axis, source, index, endpoint, value):
    import yaml
    from tm1.file_io.config_io import load_config

    zones = ZoneConfig([Zone('first', 0, .5, 6, .3),
                        Zone('last', .5, 1, 7, .5)], 'Diamond', 16)
    setattr(zones.zones[index], endpoint, value)
    cfg = ComputeConfig(
        geometry=GeometryConfig(tpms='Diamond'),
        solver=SolverConfig(Nx=8, Ny=6), extrap=ExtrapPolicy(allow=True),
        zones=ZoneInputConfig(enabled=True, axis=axis, config=zones))
    if source == 'yaml':
        path = tmp_path / 'invalid-zones.yaml'
        path.write_text(yaml.safe_dump(cfg.to_dict()), encoding='utf-8')
        cfg = load_config(path)
    solve = Mock(side_effect=AssertionError('Invalid zones reached the solver'))
    finalize = Mock()
    with pytest.raises(ValueError, match='Zone.*finite'):
        compute(cfg, solve=solve, evaluate=finalize)
    solve.assert_not_called()
    finalize.assert_not_called()


@pytest.mark.parametrize('axis', ['Y', 'typo', None])
@pytest.mark.parametrize('source', ['object', 'yaml'])
def test_unknown_active_zone_axis_never_solves(tmp_path, axis, source):
    import yaml
    from tm1.file_io.config_io import load_config

    cfg = ComputeConfig(
        solver=SolverConfig(Nx=8, Ny=6), extrap=ExtrapPolicy(allow=True),
        zones=ZoneInputConfig(enabled=True, axis=axis,
                             config=ZoneConfig.single_zone(6, .3, 'Diamond', 16)))
    solve = Mock(side_effect=AssertionError('Invalid axis reached the solver'))
    finalize = Mock()
    with pytest.raises(ValueError, match='[Zz]one axis'):
        if source == 'yaml':
            path = tmp_path / 'invalid-axis.yaml'
            path.write_text(yaml.safe_dump(cfg.to_dict()), encoding='utf-8')
            cfg = load_config(path)
        compute(cfg, solve=solve, evaluate=finalize)
    solve.assert_not_called()
    finalize.assert_not_called()


def test_disabled_zone_axis_remains_an_unchecked_draft():
    zones = ZoneInputConfig(enabled=False, axis='draft')
    assert zones.validate() is zones


@pytest.mark.parametrize('dimension', [2, 3])
def test_direct_stage_rejects_invalid_grid(dimension):
    from tm1.preprocess.api import prepare_case
    cfg = ComputeConfig(
        geometry=GeometryConfig(Lz_m=0.042), solver=SolverConfig(Nz=dimension - 1),
        extrap=ExtrapPolicy(allow=True), zones=ZoneInputConfig(
            enabled=True, axis='grid', grid=dict(
                cells=[dict(x0=1, x1=0, y0=0, y1=1, L=6, t=0.3)])))
    with pytest.raises(ValueError, match='cell 1.*x'):
        prepare_case(cfg, case_id='invalid-grid')


@pytest.mark.parametrize('axis', ['x', 'y', 'grid'])
def test_supported_air_zones_build_fields(axis):
    from tm1.preprocess.two_d.preparation import prepare_case
    grid = dict(cells=[dict(x0=0, x1=1, y0=0, y1=1, L=6, t=0.3)],
                tpms_type='Diamond', k_s=16)
    zones = ZoneInputConfig(enabled=True, axis=axis, grid=grid,
                            config=ZoneConfig.single_zone(6, 0.3, 'Diamond', 16))
    case = prepare_case(ComputeConfig(
        zones=zones, geometry=GeometryConfig(tpms='Diamond'), solver=SolverConfig(Nx=4, Ny=4),
        extrap=ExtrapPolicy(allow=True)), case_id='air-zones')
    assert case.design_fields['eps_arr'].shape == (len(case.grid['dx']), len(case.grid['dy']))
    assert case.parameters['zone_config'] is not None


def test_supported_3d_grid_is_consumed():
    from tm1.preprocess.api import prepare_case
    cells = [dict(x0=0, x1=1, y0=0, y1=1, L=6, t=0.3)]
    cfg = ComputeConfig(geometry=GeometryConfig(Lz_m=0.042),
                        solver=SolverConfig(Nx=4, Ny=4, Nz=2),
                        zones=ZoneInputConfig(enabled=True, axis='grid', grid={'cells': cells}),
                        extrap=ExtrapPolicy(allow=True))
    case = prepare_case(cfg, case_id='grid-consumed')
    assert case.parameters['zone_grid_cells'][0]['L_m'] == .006
    lengths, thickness, eps = (case.design_fields[key] for key in ('L_field_m', 't_field_m', 'eps_arr'))
    assert lengths.shape == thickness.shape == eps.shape == (4, 4, 2)
    assert lengths == pytest.approx(.006)
    assert thickness == pytest.approx(.0003)


@pytest.mark.parametrize('dimension,axis,grid', [
    (2, 'y', None), (2, 'grid', None),
    (2, 'grid', {'cells': []}),
    (3, 'y', None), (3, 'grid', None),
    (3, 'grid', {'cells': []}),
])
def test_missing_zones_never_solve_or_finalize(dimension, axis, grid, monkeypatch):
    cfg = ComputeConfig(
        geometry=GeometryConfig(Lz_m=0.042),
        solver=SolverConfig(Nz=2 if dimension == 3 else 1),
        extrap=ExtrapPolicy(allow=True),
        zones=ZoneInputConfig(enabled=True, axis=axis, grid=grid))
    solve, finalize = Mock(), Mock()
    with pytest.raises((ValueError, NotImplementedError), match='[Zz]on|grid'):
        compute(cfg, solve=solve, evaluate=finalize)
    solve.assert_not_called()
    finalize.assert_not_called()


@pytest.mark.parametrize('axis', ['x', 'y', 'grid'])
def test_native_zone_callback_error_propagates(axis, monkeypatch):
    from tm1.preprocess.preparation import PreparationObservers
    zones = ZoneInputConfig(enabled=True, axis=axis,
        config=ZoneConfig.single_zone(6, .3, 'Diamond', 16),
        grid=dict(cells=[dict(x0=0, x1=1, y0=0, y1=1, L=6, t=.3)],
                  tpms_type='Diamond', k_s=16))
    failure = RuntimeError('zone callback failed')
    monkeypatch.setattr(PreparationObservers, 'observe_range', Mock(side_effect=failure))
    cfg = ComputeConfig(geometry=GeometryConfig(tpms='Diamond'),
        solver=SolverConfig(Nx=4, Ny=4), zones=zones, extrap=ExtrapPolicy(allow=True))
    solve, finalize = Mock(), Mock()
    with pytest.raises(RuntimeError, match='zone callback failed') as caught:
        compute(cfg, solve=solve, evaluate=finalize)
    assert caught.value is failure
    solve.assert_not_called()
    finalize.assert_not_called()


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('start,end', [
    (1, 0), (0.5, 0.5), (-0.1, 1), (0, 1.1),
    (float('nan'), 1), (0, float('inf')),
])
def test_invalid_grid_rectangle_never_solves(dimension, axis, start, end, monkeypatch):
    cell = dict(x0=0, x1=1, y0=0, y1=1, L=6, t=0.3)
    cell[f'{axis}0'], cell[f'{axis}1'] = start, end
    cfg = ComputeConfig(
        geometry=GeometryConfig(Lz_m=0.042),
        solver=SolverConfig(Nz=2 if dimension == 3 else 1),
        extrap=ExtrapPolicy(allow=True),
        zones=ZoneInputConfig(enabled=True, axis='grid', grid=dict(
            cells=[cell], tpms_type='Diamond', k_s=16)))
    solve, finalize = Mock(), Mock()
    with pytest.raises(ValueError, match=f'cell 1.*{axis}'):
        compute(cfg, solve=solve, evaluate=finalize)
    solve.assert_not_called()
    finalize.assert_not_called()


@pytest.mark.parametrize('axis', ['x', 'y', 'grid'])
def test_native_zone_stage_error_never_solves_or_finalizes(monkeypatch, axis):
    from tm1.cpp_interface import preparation_host as native
    zones = ZoneInputConfig(enabled=True, axis=axis,
        config=ZoneConfig.single_zone(6, .3, 'Diamond', 16),
        grid=dict(cells=[dict(x0=0., x1=1., y0=0., y1=1., L=6., t=.3)],
                  tpms_type='Diamond', k_s=16.))
    cfg = ComputeConfig(geometry=GeometryConfig(tpms='Diamond'),
        zones=zones, extrap=ExtrapPolicy(allow=True))
    failure = RuntimeError('native zone stage failed')
    monkeypatch.setattr(native, 'operation', Mock(side_effect=failure))
    solve, finalize = Mock(), Mock()
    with pytest.raises(RuntimeError, match='native zone stage failed') as caught:
        compute(cfg, solve=solve, evaluate=finalize)
    assert caught.value is failure
    solve.assert_not_called()
    finalize.assert_not_called()
