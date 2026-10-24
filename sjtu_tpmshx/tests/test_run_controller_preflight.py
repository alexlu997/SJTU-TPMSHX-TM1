"""GUI preflight, advice and launch use the same captured inputs."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QMessageBox
from sjtu_tpmshx.domain.compute_config import ComputeConfig, SolverConfig
from sjtu_tpmshx.tests.gui_worker_support import win as win
from sjtu_tpmshx.tests.window_stubs import _StubWindow
from sjtu_tpmshx.ui.mixins.run_controller import RunControllerMixin
from sjtu_tpmshx.ui.window_config import config_from_window


class _Status:
    def __init__(self): self.msgs = []
    def showMessage(self, *a, **k): self.msgs.append(a)


# ── U5: high-velocity notice — blank u_B inherits u_A ───────────────────────
def _win_uv(uA, uB):
    st = _Status()
    cfg = config_from_window(_StubWindow(uA=uA, uB=uB), force_3d=False)
    return SimpleNamespace(statusBar=lambda: st), cfg, st


def test_highvel_notice_blank_uB_inherits_uA():
    """uA=20 (high velocity), uB blank -> u_B inherits u_A -> notice must fire."""
    window, cfg, st = _win_uv("20", "")
    RunControllerMixin._maybe_highvel_notice(window, cfg)
    assert st.msgs, "blank u_B zeroed the high-velocity check (notice suppressed)"
    assert "请关注收敛与压降" in st.msgs[0][0]


def test_highvel_notice_below_threshold_silent():
    window, cfg, st = _win_uv("5", "")
    RunControllerMixin._maybe_highvel_notice(window, cfg)
    assert not st.msgs


def test_highvel_notice_both_blank_silent():
    window, cfg, st = _win_uv("", "")
    RunControllerMixin._maybe_highvel_notice(window, cfg)
    assert not st.msgs


def test_highvel_notice_high_uB_only():
    window, cfg, st = _win_uv("5", "20")
    RunControllerMixin._maybe_highvel_notice(window, cfg)
    assert st.msgs


@pytest.mark.parametrize('mass_sides', ['A', 'B', 'AB'])
def test_highvel_notice_excludes_mass_flow_speeds(mass_sides):
    window, cfg, st = _win_uv('20', '20')
    for side in mass_sides:
        getattr(cfg, 'fluid_' + side).mass_flow_kg_s = .003
    RunControllerMixin._maybe_highvel_notice(window, cfg)
    if mass_sides == 'AB':
        assert not st.msgs
    else:
        message = st.msgs[0][0]
        assert f'u_{mass_sides}=' not in message
        assert f'u_{"B" if mass_sides == "A" else "A"}=20.0' in message


def test_stored_high_speed_does_not_warn_for_low_prescribed_speed():
    window, cfg, st = _win_uv('20', '5')
    cfg.fluid_A.mass_flow_kg_s = .003
    RunControllerMixin._maybe_highvel_notice(window, cfg)
    assert not st.msgs


# ── U4: Large-grid confirm reflects the actual refine setting ───────────────
def _grid_config(nx, ny, nz):
    return ComputeConfig(solver=SolverConfig(Nx=nx, Ny=ny, Nz=nz))


def test_large_grid_no_confirm_when_refine_off():
    """40^3 = 64000 actual cells with refine OFF is below the 100k threshold ->
    no confirm dialog. Pre-fix the unconditional +16 inflated it to
    56^3 = 175616 and popped a spurious 'Large 3D Grid' confirm."""
    cfg = _grid_config(40, 40, 40)
    with patch.object(QMessageBox, 'question') as q, \
         patch.object(QMessageBox, 'warning'):
        proceed, est, label = RunControllerMixin._preflight_3d(None, cfg)
    q.assert_not_called()
    assert proceed is True
    assert est == 64000
    assert label == "40×40×40"


def test_large_grid_confirms_using_total_input_counts():
    cfg = _grid_config(50, 50, 50)
    with patch.object(QMessageBox, 'question',
                      return_value=QMessageBox.StandardButton.Yes) as q, \
         patch.object(QMessageBox, 'warning'):
        proceed, est, label = RunControllerMixin._preflight_3d(None, cfg)
    q.assert_called_once()
    assert proceed is True
    assert est == 50 ** 3
    assert label == "50×50×50"
    text = q.call_args.args[2]
    assert 'selected scheme' in text
    assert 'Nz=5' not in text and '~30 s' not in text


@pytest.mark.parametrize('answer', [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
def test_large_grid_keeps_confirmation_choice(answer):
    with patch.object(QMessageBox, 'question', return_value=answer):
        proceed, _, _ = RunControllerMixin._preflight_3d(None, _grid_config(50, 50, 50))
    assert proceed == (answer == QMessageBox.StandardButton.Yes)


def test_too_few_z_cells_reject_before_preflight_and_launch(win, monkeypatch):
    win.combo_dim.setCurrentIndex(1)
    win.le_Nz.setText('1')
    with patch.object(QMessageBox, 'warning') as warning, \
         patch.object(win, '_preflight_grid') as grid, \
         patch.object(win.compute, 'start') as start:
        win.run_calculation()
    assert 'Nz must be >= 2' in warning.call_args.args[2]
    grid.assert_not_called()
    start.assert_not_called()


@pytest.mark.parametrize('dimension', [0, 1])
def test_run_captures_once_for_preflight_advice_and_worker(win, monkeypatch, dimension):
    win.combo_dim.setCurrentIndex(dimension)
    win.le_Nz.setText('4')
    observed = []

    def grid(config):
        observed.append(config)
        return True

    def advice(config):
        observed.append(config)

    def grid_3d(config):
        observed.append(config)
        return True, 8, 'test'

    def start(mode, worker, *, cfg):
        assert mode == ('3d' if dimension else '2d')
        observed.append(cfg)
        return True

    monkeypatch.setattr(win, '_preflight_grid', grid)
    monkeypatch.setattr(win, '_preflight_3d', grid_3d)
    monkeypatch.setattr(win, '_maybe_highvel_notice', advice)
    monkeypatch.setattr(win.compute, 'start', start)
    with patch('sjtu_tpmshx.ui.window_config.config_from_window', wraps=config_from_window) as capture:
        win.run_calculation()
    capture.assert_called_once_with(win, strict=True, force_3d=bool(dimension))
    assert len(observed) == 3 + dimension
    assert all(config is observed[0] for config in observed)
    if dimension:
        win._compute_3d_watchdog.stop()


@pytest.mark.parametrize('dimension', [0, 1])
def test_grid_preflight_uses_captured_geometry_ports_and_temperatures(win, monkeypatch, dimension):
    from sjtu_tpmshx.main import Main_Menu
    from sjtu_tpmshx.ui.preflight import Preflight

    win.combo_dim.setCurrentIndex(dimension)
    win.le_Nz.setText('4')
    cfg = config_from_window(win, strict=True)
    cfg.fluid_A.T_in_K, cfg.fluid_B.T_in_K = 310., 330.
    cfg.bc_A.in_z_ctr, cfg.bc_A.in_z_w = (.02, .01) if dimension else (None, None)
    captured = []

    def preflight(**kwargs):
        captured.append(kwargs)
        return Preflight()

    monkeypatch.setattr('sjtu_tpmshx.ui.preflight.compute_preflight', preflight)
    assert Main_Menu._preflight_grid(SimpleNamespace(), cfg)
    inputs = captured[0]
    assert (inputs['L'], inputs['H'], inputs['Lz']) == (
        cfg.geometry.L_dom_m, cfg.geometry.H_dom_m, cfg.geometry.Lz_m)
    assert (inputs['Nx'], inputs['Ny'], inputs['Nz'], inputs['is_3d']) == (
        cfg.solver.Nx, cfg.solver.Ny, cfg.solver.Nz, bool(dimension))
    assert (inputs['T_inA'], inputs['T_inB']) == (310., 330.)
    assert inputs['port_wall_refine'] == cfg.flags.port_wall_refine
    for side in 'AB':
        port, bc = inputs['fluid_' + side], getattr(cfg, 'bc_' + side)
        for name in ('dir', 'in_ctr', 'in_w', 'out_ctr', 'out_w'):
            assert getattr(port, name) == getattr(bc, name)
        assert (port.z_in_ctr, port.z_in_w) == (bc.in_z_ctr, bc.in_z_w)


def test_captured_invalid_geometry_still_blocks_grid_checks(monkeypatch):
    from sjtu_tpmshx.main import Main_Menu
    cfg = ComputeConfig()
    cfg.geometry.L_dom_m = -1.
    with patch.object(QMessageBox, 'critical') as error, \
         patch('sjtu_tpmshx.ui.preflight.compute_preflight') as grid:
        assert not Main_Menu._preflight_grid(None, cfg)
    error.assert_called_once()
    grid.assert_not_called()
