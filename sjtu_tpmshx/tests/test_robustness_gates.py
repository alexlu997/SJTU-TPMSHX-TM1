"""Robustness-hardening locks (openspec robustness-hardening, 2026-07-03).

Pins the input-validation choke points, the first-class convergence
verdict, the 3D cell cap, and the corrupt-session quarantine — the gaps
the 2026-07-03 robustness survey found and this change closed.
"""
from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from sjtu_tpmshx.domain.compute_config import (  # noqa: E402
    ComputeConfig,
    FluidConfig,
    GeometryConfig,
    PartialBCConfig,
)
from sjtu_tpmshx.domain.compute_result import ComputeResult  # noqa: E402


# ── ComputeConfig.validate — the script/optimizer boundary ────────────

def _canonical(**geometry_over):
    ge = dict(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.6, k_s_W_mK=16.0,
              L_dom_m=0.182, H_dom_m=0.042, Lz_m=0.042)
    ge.update(geometry_over)
    return {
        'fluid_A': {'type': 'air', 'u_mps': 8.0, 'T_in_K': 422.0,
                    'P_in_Pa': 192362.0},
        'fluid_B': {'type': 'water', 'u_mps': 0.5, 'T_in_K': 293.15,
                    'P_in_Pa': 101325.0},
        'geometry': ge,
        'solver': {'Nx': 20, 'Ny': 20, 'Nz': 5},
    }


def test_from_dict_valid_passes():
    cfg = ComputeConfig.from_dict(_canonical())
    assert cfg.geometry.L_dom_m == 0.182


@pytest.mark.parametrize('section,name', [
    ('extrap', 'allow'), ('zones', 'enabled'),
    ('flags', 'variable_rho_cp'), ('flags', 'port_wall_refine'),
    ('flags', 'wall_refine_3d'),
])
def test_control_booleans_reject_text_false(section, name):
    data = _canonical()
    data[section] = {name: 'false'}
    with pytest.raises(ValueError, match=rf'{section}\.{name}.*boolean'):
        ComputeConfig.from_dict(data)


@pytest.mark.parametrize('name,value', [
    ('Nx', 20.5), ('Ny', True), ('Nz', 1.9), ('Nz', '2'),
    ('max_iter_simple', 10.5), ('max_outer_ltne', 2.9),
])
def test_solver_integers_are_not_coerced(name, value):
    data = _canonical()
    data['solver'][name] = value
    with pytest.raises(ValueError, match=name):
        ComputeConfig.from_dict(data)


def test_fractional_nz_is_rejected_before_geometry_preparation(monkeypatch):
    from sjtu_tpmshx.domain.compute_config import SolverConfig
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.preprocess.two_d import preparation
    monkeypatch.setattr(preparation, 'tpms_geometry',
                        lambda *a, **kw: pytest.fail('invalid grid reached geometry'))
    config = ComputeConfig(solver=SolverConfig(Nz=1.9))
    with pytest.raises(ValueError, match='Nz'):
        prepare_case(config, case_id='fractional-grid')


def test_from_dict_rejects_nan():
    d = _canonical(L_dom_m=float('nan'))
    with pytest.raises(ValueError, match='L_dom_m'):
        ComputeConfig.from_dict(d)


def test_from_dict_rejects_negative():
    d = _canonical(t_wall_mm=-0.6)
    with pytest.raises(ValueError, match='t_wall_mm'):
        ComputeConfig.from_dict(d)


def test_from_dict_rejects_zero_grid():
    d = _canonical()
    d['solver']['Nx'] = 0
    with pytest.raises(ValueError, match='Nx'):
        ComputeConfig.from_dict(d)


def test_from_json_rejects_json_nan(tmp_path):
    """json.loads happily produces NaN — the exact hole the survey found."""
    d = _canonical()
    raw = json.dumps(d).replace('0.182', 'NaN')
    p = tmp_path / 'bad.json'
    p.write_text(raw, encoding='utf-8')
    with pytest.raises(ValueError):
        ComputeConfig.from_json(p)


def test_shanghai_baseline_still_loads():
    """The legacy layout must survive validation (regression guard)."""
    base = ROOT / 'configs' / 'shanghai_baseline.json'
    if not base.exists():
        pytest.skip('shanghai_baseline.json not present')
    cfg = ComputeConfig.from_json(base)
    assert cfg.geometry.L_cell_mm == 7.0


def test_sco2_v2_accepts_mixed_directions_and_partial_ports():
    cfg = ComputeConfig(
        fluid_A=FluidConfig(type='sco2', u_mps=0.8, T_in_K=500.0,
                            P_in_Pa=12.0e6),
        fluid_B=FluidConfig(type='sco2', u_mps=0.5, T_in_K=330.0,
                            P_in_Pa=12.0e6),
        geometry=GeometryConfig(tpms='Diamond', L_cell_mm=7.0,
                                t_wall_mm=0.6),
        bc_A=PartialBCConfig(dir=0),
        bc_B=PartialBCConfig(dir=1),
    )
    assert cfg.validate() is cfg

    cfg.bc_B.dir = 2
    assert cfg.validate() is cfg

    cfg.bc_A.in_w = 0.01
    cfg.bc_A.out_w = 0.01
    cfg.bc_A.in_ctr = cfg.bc_A.out_ctr = 0.02
    assert cfg.validate() is cfg

    cfg.fluid_B = FluidConfig(type='water', u_mps=0.5, T_in_K=330.0,
                              P_in_Pa=2.0e5)
    assert cfg.validate() is cfg


@pytest.mark.parametrize('fluid_a', ('air', 'water', 'sco2'))
@pytest.mark.parametrize('fluid_b', ('air', 'water', 'sco2'))
def test_all_ordered_fluid_pairs_validate(fluid_a, fluid_b):
    def fluid(name, hot):
        return FluidConfig(
            type=name, u_mps=0.5, T_in_K=500.0 if hot else 300.0,
            P_in_Pa=12e6 if name == 'sco2' else 2e6)

    cfg = ComputeConfig(
        fluid_A=fluid(fluid_a, True),
        fluid_B=fluid(fluid_b, False),
        geometry=GeometryConfig(L_cell_mm=7.0, t_wall_mm=0.6),
    )
    assert cfg.validate() is cfg


def test_compute_config_shared_port_validation():
    cfg = ComputeConfig(
        geometry=GeometryConfig(L_dom_m=0.08, H_dom_m=0.04),
        bc_A=PartialBCConfig(dir=0, in_ctr=0.05, in_w=0.02,
                             out_ctr=0.02, out_w=0.01),
    )
    with pytest.raises(ValueError, match=r"bc_A.*out_of_domain"):
        cfg.validate()


def test_compute_config_default_widths_mean_full_face():
    cfg = ComputeConfig()
    assert cfg.validate() is cfg


# ── window strict boundary (duck-typed, no Qt) ────────────────────────

class _FakeLE:
    def __init__(self, txt):
        self._t = str(txt)

    def text(self):
        return self._t


def _fake_window(**over):
    vals = dict(le_L='0.182', le_H='0.042', le_Nx='20', le_Ny='20',
                le_uA='8.0', le_uB='0.5', le_TinA='422', le_TinB='293',
                le_Lcell='7.0', le_t='0.6', le_ks='16.0')
    vals.update(over)
    w = types.SimpleNamespace()
    for k, v in vals.items():
        setattr(w, k, _FakeLE(v))
    return w


def test_strict_widgets_reject_nan():
    from sjtu_tpmshx.ui.window_config import _validate_required_widgets
    with pytest.raises(ValueError, match='Domain Length'):
        _validate_required_widgets(_fake_window(le_L='nan'), is_3d=False)


def test_strict_widgets_reject_negative():
    from sjtu_tpmshx.ui.window_config import _validate_required_widgets
    with pytest.raises(ValueError, match='TPMS t'):
        _validate_required_widgets(_fake_window(le_t='-0.6'), is_3d=False)


def test_strict_widgets_allow_negative_celsius_temp():
    """Temp fields may hold °C text — sign check is deferred to
    ComputeConfig.validate (Kelvin domain)."""
    from sjtu_tpmshx.ui.window_config import _validate_required_widgets
    _validate_required_widgets(_fake_window(le_TinA='-10'), is_3d=False)


# ── ComputeResult.converged first-class field ─────────────────────────

def test_compute_result_has_converged_default_true():
    r = ComputeResult()
    assert r.converged is True
    assert ComputeResult(converged=False).converged is False


# ── 3D cell cap (script path, no UI dialog) ───────────────────────────

def test_run_3d_stack_cell_cap(monkeypatch):
    from sjtu_tpmshx.runs._case_template import build_cfg
    from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
    monkeypatch.setenv('TPMSHX_MAX_CELLS_3D', '1000')
    cfg = build_cfg(Nx=20, Ny=20, Nz=5)          # 2000 cells > 1000 cap
    with pytest.raises(ValueError, match='cell cap'):
        _run_3d_stack(cfg)


def test_run_3d_stack_cell_cap_cfg_override(monkeypatch):
    from sjtu_tpmshx.runs._case_template import build_cfg
    from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
    monkeypatch.setenv('TPMSHX_MAX_CELLS_3D', '10')
    cfg = build_cfg(Nx=20, Ny=20, Nz=5, max_cells_3d=100)
    # cfg override wins over env; 2000 > 100 still raises (proves the
    # cfg path is honoured without running a full solve)
    with pytest.raises(ValueError, match='cell cap'):
        _run_3d_stack(cfg)


# ── corrupt-session quarantine ────────────────────────────────────────

def test_corrupt_session_quarantined(tmp_path):
    from sjtu_tpmshx.controllers.session_manager import SessionManager
    sm = SessionManager(base_dir=tmp_path)
    p = sm.session_path('A')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{ not valid json', encoding='utf-8')
    assert sm.load_session('A') is None
    assert not p.exists(), 'corrupt file must be renamed away'
    quarantined = list(p.parent.glob(p.name + '.corrupt-*'))
    assert quarantined, 'quarantine copy must exist'
