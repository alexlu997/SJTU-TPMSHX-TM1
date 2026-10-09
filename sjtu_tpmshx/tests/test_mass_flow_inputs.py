"""Authoritative inlet flow survives geometry edits, files and GUI handoff."""
from dataclasses import asdict, replace

import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig, FluidConfig, GeometryConfig, SolverConfig
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.preprocess.api import (
    prepare_case, prepare_inlet_mass_capacities, prepare_fixed_mass_flow_case, resolve_inlet_flow_config,
)
from sjtu_tpmshx.preprocess.inlet_flow import total_inlet_mass_capacity
from sjtu_tpmshx.tests.gui_io_support import win as win


def _config():
    return ComputeConfig(geometry=GeometryConfig(Lz_m=.042),
        solver=SolverConfig(Nx=6, Ny=5, Nz=3),
        fluid_A=FluidConfig(type='air', u_mps=8., T_in_K=400., P_in_Pa=130000.),
        fluid_B=FluidConfig(type='water', u_mps=.05, T_in_K=300., P_in_Pa=150000.))


@pytest.mark.parametrize('side', ['A', 'B'])
def test_mixed_flow_input_resolves_before_speed_validation_and_replays(tmp_path, side):
    from sjtu_tpmshx.io.case_io import load_case, save_case

    cfg = _config()
    inlet = getattr(cfg, 'fluid_' + side)
    target = prepare_inlet_mass_capacities(cfg)[side] * inlet.u_mps
    cfg = replace(cfg, **{'fluid_' + side: replace(inlet, u_mps=-99., mass_flow_kg_s=target)})
    original = asdict(cfg)
    cfg.validate()
    with pytest.raises(ValueError, match='u_mps'):
        cfg.validate(resolved_inlet_speeds=True)
    for factor in (1., 2.):
        changed = replace(cfg, geometry=replace(cfg.geometry, Lz_m=.042*factor))
        case = prepare_case(changed, case_id=f'mixed-{side}-{factor}')
        saved = case.config_snapshot['fluid_' + side]
        assert saved['mass_flow_kg_s'] == target
        assert saved['u_mps'] == pytest.approx(inlet.u_mps/factor, rel=1e-14)
        other = 'B' if side == 'A' else 'A'
        assert case.config_snapshot['fluid_' + other]['u_mps'] == getattr(cfg, 'fluid_' + other).u_mps
        assert total_inlet_mass_capacity(case.design_fields, case.parameters, case.grid, side) * saved['u_mps'] == pytest.approx(target, rel=1e-14)
        path = tmp_path / f'case-{factor}.yaml'
        save_case(case, path)
        loaded = load_case(path)
        replay = ComputeConfig.from_dict(mutable_data(loaded.config_snapshot))
        assert replay.to_dict() == mutable_data(case.config_snapshot)
        assert resolve_inlet_flow_config(replay).to_dict() == replay.to_dict()
        assert loaded.parameters['inlet_inputs'][side]['mass_flow_kg_s'] == target
    assert asdict(cfg) == original


@pytest.mark.parametrize('bad', [0., -1., float('nan'), float('inf'), True, '0.01'])
def test_bad_target_rejected_before_geometry_preparation(monkeypatch, bad):
    from sjtu_tpmshx.preprocess.three_d import preparation
    monkeypatch.setattr(preparation, '_prepare_geometry_data', lambda *a: pytest.fail('bad target reached geometry'))
    cfg = _config()
    cfg.fluid_A = replace(cfg.fluid_A, mass_flow_kg_s=bad)
    with pytest.raises(ValueError, match='mass_flow_kg_s'):
        prepare_case(cfg, case_id='invalid')


def test_resolved_speed_still_enforces_experimental_calibration():
    cfg = _config()
    cfg.df_mode = 'experimental'
    cfg.fluid_A = replace(cfg.fluid_A, u_mps=-1., mass_flow_kg_s=1e-12)
    cfg.validate()  # The inactive cached speed does not define this inlet.
    with pytest.raises(ValueError, match='calibration'):
        prepare_case(cfg, case_id='outside-calibration')


def test_explicit_batch_flow_overrides_stored_input_without_mutating_it():
    cfg = _config()
    cfg.fluid_A = replace(cfg.fluid_A, mass_flow_kg_s=.02)
    before = asdict(cfg)
    case = prepare_fixed_mass_flow_case(cfg, mass_flow_A_kg_s=.003, mass_flow_B_kg_s=.03, case_id='batch')
    assert asdict(cfg) == before
    for side, target in [('A', .003), ('B', .03)]:
        fluid = case.config_snapshot['fluid_' + side]
        assert fluid['mass_flow_kg_s'] is None
        assert fluid['u_mps'] * total_inlet_mass_capacity(case.design_fields, case.parameters, case.grid, side) == pytest.approx(target, rel=1e-14)


@pytest.fixture
def mass_window(win):
    win._load_named_preset('Shanghai (3D Gyroid)')
    win._continuous_field_spec = None
    win.chk_zones.setChecked(False)
    win._opt_conditions = None
    win.le_Nx.setText('8'); win.le_Ny.setText('6'); win.le_Nz.setText('3')
    win.combo_grid.setCurrentIndex(win.combo_grid.findData(False))
    win.combo_df_mode.setCurrentIndex(win.combo_df_mode.findData('cfd_smooth'))
    for side in 'AB':
        getattr(win, 'combo_inlet_mode' + side).setCurrentIndex(0)
    return win


def test_gui_mass_mode_autofill_save_and_single_condition_keep_target(mass_window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from sjtu_tpmshx.ui.window_config import config_from_window
    from sjtu_tpmshx.ui import optimize_panel
    from sjtu_tpmshx.ui.mixins import fluid_input

    window = mass_window
    initial = config_from_window(window, strict=True)
    target = prepare_inlet_mass_capacities(initial)['A'] * initial.fluid_A.u_mps
    window.le_mass_flowA.setText(format(target, '.17g'))
    window.combo_inlet_modeA.setCurrentIndex(1)
    window.le_uA.setText('obsolete')
    cfg = config_from_window(window, strict=True)
    assert cfg.fluid_A.mass_flow_kg_s == target and cfg.fluid_B.mass_flow_kg_s is None
    assert window.le_uA.isReadOnly() and not window.le_uB.isReadOnly()
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: pytest.fail(str(args)))
    calls = []
    compute = fluid_input.tpms_compute
    def capture(*args, **kwargs):
        calls.append(args[3])
        return compute(*args, **kwargs)
    monkeypatch.setattr(fluid_input, 'tpms_compute', capture)
    window.auto_fill_fluid_a()
    assert calls[-1] == pytest.approx(initial.fluid_A.u_mps, rel=1e-14)
    assert float(window.le_uA.text()) == calls[-1]
    preset = window._capture_current_preset('mass input')
    window._validate_preset(preset, complete=True)
    window.combo_inlet_modeA.setCurrentIndex(0)
    window._apply_user_preset(preset, show_notice=False)
    restored = config_from_window(window, strict=True)
    assert restored.fluid_A.mass_flow_kg_s == target
    row = optimize_panel._condition_inputs(restored, None)[0]
    assert row[2] == pytest.approx(target, rel=1e-14)
    window.combo_dim.setCurrentIndex(0)
    assert config_from_window(window, strict=True).fluid_A.mass_flow_kg_s is None
    assert not window.le_uA.isReadOnly()


def test_imported_optimization_flows_override_window_mass_input(mass_window):
    from sjtu_tpmshx.ui.optimize_panel import _condition_inputs
    from sjtu_tpmshx.tests.test_optimize_panel_wiring import condition
    cfg = _config()
    cfg.fluid_A = replace(cfg.fluid_A, mass_flow_kg_s=.02)
    row = _condition_inputs(cfg, [condition()])[0]
    assert row[1].fluid_A.mass_flow_kg_s is None
    assert row[2:] == (.003, .015)
    assert cfg.fluid_A.mass_flow_kg_s == .02
