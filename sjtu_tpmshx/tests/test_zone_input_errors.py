"""A requested zoned problem must fail instead of solving a uniform one."""
from unittest.mock import Mock

import pytest

from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D
from sjtu_tpmshx.domain.compute_config import ComputeConfig, ExtrapPolicy, GeometryConfig, SolverConfig, ZoneInputConfig
from sjtu_tpmshx.models.zone_config import Zone, ZoneConfig


@pytest.mark.parametrize('axis', ['x', 'y'])
def test_canonical_1d_json_restores_the_same_zone_fields(tmp_path, capsys, axis):
    import json
    from sjtu_tpmshx.cli import main
    from sjtu_tpmshx.preprocess.two_d.preparation import _parse_inputs_cfg

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
    expected = _parse_inputs_cfg(cfg)['za']
    parsed = _parse_inputs_cfg(loaded)
    assert isinstance(parsed['zone_config'], ZoneConfig)
    assert all(isinstance(zone, Zone) for zone in parsed['zone_config'].zones)
    restored = parsed['za']
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
    from sjtu_tpmshx.preprocess.two_d.preparation import _parse_inputs_cfg

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
    restored = _parse_inputs_cfg(loaded)['zone_config']
    assert source == original
    assert restored.zones[0].name == 'inlet'
    restored.zones[0].props_A['saved'] = [99]
    assert source == original


@pytest.mark.parametrize('invalid', ['gap', 'missing_field'])
def test_canonical_1d_json_does_not_swallow_invalid_zones(tmp_path, invalid):
    import json
    from sjtu_tpmshx.preprocess.two_d.preparation import _parse_inputs_cfg

    cfg = ComputeConfig(zones=ZoneInputConfig(enabled=True,
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
        _parse_inputs_cfg(loaded)


def test_valid_partial_grid_coverage_is_not_redefined():
    zones = ZoneInputConfig(enabled=True, axis='grid', grid=dict(
        cells=[dict(x0=0.25, x1=0.75, y0=0.2, y1=0.8, L=6, t=0.3)]))
    assert zones.validate() is zones


@pytest.mark.parametrize('dimension', [2, 3])
def test_direct_stage_parse_rejects_invalid_grid(dimension):
    from sjtu_tpmshx.preprocess.two_d.preparation import _parse_inputs_cfg
    from sjtu_tpmshx.preprocess.three_d.preparation import _parse_inputs_3d_cfg
    cfg = ComputeConfig(
        geometry=GeometryConfig(Lz_m=0.042), solver=SolverConfig(Nz=dimension - 1),
        extrap=ExtrapPolicy(allow=True), zones=ZoneInputConfig(
            enabled=True, axis='grid', grid=dict(
                cells=[dict(x0=1, x1=0, y0=0, y1=1, L=6, t=0.3)])))
    parse = _parse_inputs_cfg if dimension == 2 else _parse_inputs_3d_cfg
    with pytest.raises(ValueError, match='cell 1.*x'):
        parse(cfg)


@pytest.mark.parametrize('axis', ['x', 'y', 'grid'])
def test_supported_air_zones_build_fields(axis):
    from sjtu_tpmshx.preprocess.two_d.preparation import _parse_inputs_cfg
    grid = dict(cells=[dict(x0=0, x1=1, y0=0, y1=1, L=6, t=0.3)],
                tpms_type='Diamond', k_s=16)
    zones = ZoneInputConfig(enabled=True, axis=axis, grid=grid,
                            config=ZoneConfig.single_zone(6, 0.3, 'Diamond', 16))
    parsed = _parse_inputs_cfg(ComputeConfig(
        zones=zones, solver=SolverConfig(Nx=4, Ny=4),
        extrap=ExtrapPolicy(allow=True)))
    assert parsed['za']['eps_arr'].shape == (4, 4)
    assert parsed['zone_config'] is not None


def test_supported_3d_grid_is_consumed():
    from sjtu_tpmshx.preprocess.three_d.preparation import _parse_inputs_3d_cfg
    from sjtu_tpmshx.models.grid_3d import _build_zone_fields_3d
    cells = [dict(x0=0, x1=1, y0=0, y1=1, L=6, t=0.3)]
    cfg = ComputeConfig(geometry=GeometryConfig(Lz_m=0.042),
                        solver=SolverConfig(Nx=4, Ny=4, Nz=2),
                        zones=ZoneInputConfig(enabled=True, axis='grid', grid={'cells': cells}),
                        extrap=ExtrapPolicy(allow=True))
    parsed = _parse_inputs_3d_cfg(cfg)
    assert parsed['zone_grid_cells'] == cells
    lengths, thickness, eps = _build_zone_fields_3d(
        parsed['zone_grid_cells'], 4, 4, 2, 0.182, 0.042, 'Diamond', 16, 7, 0.6)
    assert lengths.shape == thickness.shape == eps.shape == (4, 4, 2)
    assert lengths == pytest.approx(6)
    assert thickness == pytest.approx(0.3)


@pytest.mark.parametrize('pipeline,axis,grid', [
    (Pipeline2D, 'y', None), (Pipeline2D, 'grid', None),
    (Pipeline2D, 'grid', {'cells': []}),
    (Pipeline3D, 'y', None), (Pipeline3D, 'grid', None),
    (Pipeline3D, 'grid', {'cells': []}),
])
def test_missing_zones_never_solve_or_finalize(pipeline, axis, grid, monkeypatch):
    cfg = ComputeConfig(
        geometry=GeometryConfig(Lz_m=0.042),
        solver=SolverConfig(Nz=2 if pipeline is Pipeline3D else 1),
        extrap=ExtrapPolicy(allow=True),
        zones=ZoneInputConfig(enabled=True, axis=axis, grid=grid))
    pipe = pipeline(cfg)
    solve, finalize = Mock(), Mock()
    monkeypatch.setattr(pipe, 'run_solvers', solve)
    monkeypatch.setattr(pipe, 'finalize', finalize)
    with pytest.raises((ValueError, NotImplementedError), match='[Zz]on|grid'):
        pipe.run()
    solve.assert_not_called()
    finalize.assert_not_called()


@pytest.mark.parametrize('builder', ['compute_properties', 'build_structured_arrays', 'build_grid_arrays'])
def test_zone_builder_error_propagates(builder, monkeypatch):
    zones = ZoneInputConfig(enabled=True,
                            config=ZoneConfig.single_zone(6, 0.3, 'Diamond', 16))
    if builder == 'build_grid_arrays':
        zones.axis = 'grid'
        zones.grid = dict(cells=[dict(x0=0, x1=1, y0=0, y1=1, L=6, t=0.3)],
                          tpms_type='Diamond', k_s=16)
    failure = RuntimeError('zone builder failed')
    monkeypatch.setattr(ZoneConfig, builder, Mock(side_effect=failure))
    if builder == 'build_structured_arrays':
        monkeypatch.setattr(ZoneConfig, 'compute_properties', lambda *a, **kw: None)
    pipe = Pipeline2D(ComputeConfig(zones=zones, extrap=ExtrapPolicy(allow=True)))
    solve, finalize = Mock(), Mock()
    monkeypatch.setattr(pipe, 'run_solvers', solve)
    monkeypatch.setattr(pipe, 'finalize', finalize)
    with pytest.raises(RuntimeError, match='zone builder failed') as caught:
        pipe.run()
    assert caught.value is failure
    solve.assert_not_called()
    finalize.assert_not_called()


@pytest.mark.parametrize('pipeline', [Pipeline2D, Pipeline3D])
@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('start,end', [
    (1, 0), (0.5, 0.5), (-0.1, 1), (0, 1.1),
    (float('nan'), 1), (0, float('inf')),
])
def test_invalid_grid_rectangle_never_solves(pipeline, axis, start, end, monkeypatch):
    cell = dict(x0=0, x1=1, y0=0, y1=1, L=6, t=0.3)
    cell[f'{axis}0'], cell[f'{axis}1'] = start, end
    cfg = ComputeConfig(
        geometry=GeometryConfig(Lz_m=0.042),
        solver=SolverConfig(Nz=2 if pipeline is Pipeline3D else 1),
        extrap=ExtrapPolicy(allow=True),
        zones=ZoneInputConfig(enabled=True, axis='grid', grid=dict(
            cells=[cell], tpms_type='Diamond', k_s=16)))
    pipe = pipeline(cfg)
    solve, finalize = Mock(), Mock()
    monkeypatch.setattr(pipe, 'run_solvers', solve)
    monkeypatch.setattr(pipe, 'finalize', finalize)
    with pytest.raises(ValueError, match=f'cell 1.*{axis}'):
        pipe.run()
    solve.assert_not_called()
    finalize.assert_not_called()
