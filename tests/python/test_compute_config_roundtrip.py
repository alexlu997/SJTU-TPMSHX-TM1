"""Check coverage of desktop case inputs, submit order and archive round trips."""
import json
from dataclasses import asdict, fields, is_dataclass
import warnings as _warnings

import pytest

from sjtu_tpmshx.data_types.compute_config import ComputeConfig, OptimizerConfig, SolverConfig
from sjtu_tpmshx.applications.gui.ui.window_config import (CONFIG_FIELDS, LINE_EDITS, config_from_window,
                              _validate_required_widgets)
from tests.python.gui_io_support import win as win
from tests.python.window_stubs import _StubWindow

def test_registry_covers_case_leaves_and_live_editors(win):
    config = ComputeConfig(optimizer=OptimizerConfig())
    leaves = set()
    for root in fields(config):
        section = getattr(config, root.name)
        if is_dataclass(section):
            leaves.update(f'{root.name}.{leaf.name}' for leaf in fields(section))
        else:
            leaves.add(root.name)
    paths = [spec.path for spec in CONFIG_FIELDS]
    assert set(paths) == leaves
    assert len(paths) == len(leaves)
    for spec in CONFIG_FIELDS:
        assert spec.disposition in ('edited', 'derived', 'api-only', 'archive')
        if spec.disposition == 'edited':
            assert spec.widget and hasattr(win, spec.widget), spec.path
        if spec.family:
            meta = spec.definition.metadata
            assert meta['symbol'] and meta['unit'] and meta['range_ref'], spec.path
            assert meta['dimensions'] in ((2, 3), (3,)), spec.path
    # Inspect the case form independently of its save and validation lists.
    assert set(LINE_EDITS) == {name for name in vars(win) if name.startswith('le_')}


def test_validation_membership_and_order_preserved():
    """Message order must match the retired _REQUIRED_2D/_3D_EXTRA lists."""
    class _Empty:
        pass
    with pytest.raises(ValueError) as e2:
        _validate_required_widgets(_Empty(), is_3d=False)
    msg2 = str(e2.value)
    expect_2d = ("Domain Length (L), Domain Height (H), Grid Nx, Grid Ny, "
                 "Velocity A (u_A), Velocity B (u_B), Inlet Temp A (T_inA), "
                 "Inlet Temp B (T_inB), TPMS L_cell, TPMS t, TPMS k_s")
    assert msg2 == f"Invalid input in: {expect_2d}"
    with pytest.raises(ValueError) as e3:
        _validate_required_widgets(_Empty(), is_3d=True)
    assert str(e3.value) == \
        f"Invalid input in: {expect_2d}, Width Lz, Grid Nz"


def test_cfg_json_roundtrip_non_defaults(tmp_path):
    cfg = ComputeConfig()
    cfg.geometry.tpms = 'Diamond'
    cfg.geometry.L_cell_mm = 5.5
    cfg.geometry.Lz_m = 0.084
    cfg.solver.Nx = 22
    cfg.solver.Nz = 7
    cfg.fluid_A.u_mps = 12.5
    cfg.fluid_A.T_in_K = 422.0
    cfg.fluid_B.type = 'water'
    cfg.fluid_B.P_in_Pa = 101973.0
    cfg.flags.port_wall_refine = True
    p = tmp_path / 'cfg.json'
    cfg.to_json(p)
    back = ComputeConfig.from_json(p)
    assert back == cfg
    assert back.is_3d is True


def test_window_to_json_roundtrip(tmp_path):
    window = _StubWindow(L='0.2', H='0.05', Nx='18', Ny='12', Nz='4',
                         uA='9.5', uB='0.2', TinA='400', TinB='305',
                         Lcell='6.5', t='0.4', ks='15')
    cfg = config_from_window(window)
    p = tmp_path / 'cfg.json'
    cfg.to_json(p)
    back = ComputeConfig.from_json(p)
    assert back == cfg
    # spot-check the table-driven reads landed
    assert cfg.geometry.L_dom_m == 0.2
    assert cfg.solver.Nx == 18 and cfg.solver.Nz == 4
    assert cfg.fluid_A.u_mps == 9.5 and cfg.fluid_B.u_mps == 0.2


@pytest.mark.parametrize('absent', [True, False])
def test_fluid_b_velocity_cross_default(absent):
    """Partial capture uses side A's speed for a missing B speed."""
    window = _StubWindow(uA='7.25', uB='')
    if absent:
        delattr(window, 'le_uB')
    cfg = config_from_window(window)
    assert cfg.fluid_B.u_mps == cfg.fluid_A.u_mps == 7.25
    with pytest.raises(ValueError, match='Velocity B'):
        config_from_window(window, strict=True)


def test_required_set_2d_vs_3d_parity():
    """Lz/Nz blank: 2D validation passes, 3D validation flags exactly them."""
    window = _StubWindow(Lz='', Nz='')
    _validate_required_widgets(window, is_3d=False)   # must not raise
    with pytest.raises(ValueError) as e:
        _validate_required_widgets(window, is_3d=True)
    assert str(e.value) == "Invalid input in: Width Lz, Grid Nz"


# ── W2 (2026-07-07): non-empty unparseable optional fields must raise ──


def test_optional_pin_garbage_raises():
    """Typo'd P_in ("3e5 Pa") must raise instead of silently running the
    whole case at the 101325 Pa default (blind-spot audit W2)."""
    window = _StubWindow(PinA='3e5 Pa')
    with pytest.raises(ValueError) as e:
        _validate_required_widgets(window, is_3d=False)
    assert "P_inA" in str(e.value)


def test_optional_pin_comma_decimal_raises():
    window = _StubWindow(PinB='1,5e5')
    with pytest.raises(ValueError) as e:
        _validate_required_widgets(window, is_3d=False)
    assert "P_inB" in str(e.value)


def test_optional_pin_blank_keeps_default():
    """Blank optional field stays legal — it means 'keep the default'."""
    window = _StubWindow(PinA='')
    _validate_required_widgets(window, is_3d=False)   # must not raise
    cfg = config_from_window(window)
    assert cfg.fluid_A.P_in_Pa == 101325.0


def test_pipe_widget_garbage_raises():
    """Malformed partial-BC width used to silently zero the pipe geometry
    (bc degraded to full-face). Non-empty must parse."""
    from tests.python.window_stubs import _StubLineEdit
    window = _StubWindow()
    window.le_pipeA_in_w = _StubLineEdit('0,042')
    with pytest.raises(ValueError) as e:
        _validate_required_widgets(window, is_3d=False)
    assert "Pipe A in_w" in str(e.value)


def test_pipe_widget_zero_and_blank_stay_legal():
    from tests.python.window_stubs import _StubLineEdit
    window = _StubWindow()
    window.le_pipeA_in_w = _StubLineEdit('0.0')
    window.le_pipeA_out_w = _StubLineEdit('')
    _validate_required_widgets(window, is_3d=False)   # must not raise


def test_solver_knobs_default_to_auto():
    s = SolverConfig()
    assert s.max_iter_simple is None
    assert s.max_outer_ltne is None
    assert s.outer_tol_K is None
    assert not hasattr(s, 'alpha_T')
    assert not hasattr(s, 'rough_mode')


def test_archived_optimizer_budget_keeps_its_original_defaults():
    """Loading old files must not reinterpret their retired settings."""
    o = ComputeConfig.from_dict({'optimizer': {}}).optimizer
    assert o is not None
    assert o.max_outer_ltne == 4
    assert o.outer_tol_K == 0.5
    assert o.max_iter_simple == 800
    assert o.alpha_T == 0.7


def test_legacy_json_with_retired_keys_loads(tmp_path):
    """Archived configs carry solver.alpha_T / rough_mode — must load."""
    blob = {
        'fluid_A': {'type': 'air', 'u_mps': 5.0},
        'solver': {'Nx': 12, 'Ny': 10, 'alpha_T': 0.7,
                   'rough_mode': 'norris_1a', 'tol_simple': 1e-5},
        'optimizer': {'tol_simple': 1e-2, 'max_iter_simple': 512},
    }
    p = tmp_path / 'legacy.json'
    p.write_text(json.dumps(blob), encoding='utf-8')
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter('always')
        cfg = ComputeConfig.from_json(p)
    assert cfg.solver.Nx == 12
    assert any('retired' in str(w.message) for w in caught)
    assert any("budgets use 'solver'" in str(w.message) for w in caught)
    assert any("'optimizer' is archive-only" in str(w.message) for w in caught)
    assert any('optimizer.tol_simple' in str(w.message) for w in caught)
    assert cfg.optimizer.max_iter_simple == 512
    assert 'tol_simple' not in asdict(cfg)['solver']
    assert 'tol_simple' not in asdict(cfg)['optimizer']


def test_roundtrip_carries_optimizer_section(tmp_path):
    cfg = ComputeConfig(optimizer=OptimizerConfig(
        max_iter_simple=512, max_outer_ltne=7, outer_tol_K=0.25, alpha_T=0.6))
    cfg.solver.mom_tol = 3e-6
    p = tmp_path / 'cfg.json'
    cfg.to_json(p)
    back = ComputeConfig.from_json(p)
    assert back.optimizer.max_iter_simple == 512
    assert back.solver.mom_tol == 3e-6
    assert back == cfg


@pytest.mark.parametrize('data', [{}, {'optimizer': None}])
def test_new_config_roundtrip_omits_retired_optimizer(tmp_path, data):
    assert ComputeConfig().optimizer is None
    cfg = ComputeConfig.from_dict(data)
    p = tmp_path / 'cfg.json'
    for _ in range(2):
        cfg.to_json(p)
        saved = json.loads(p.read_text(encoding='utf-8'))
        assert 'optimizer' not in saved
        cfg = ComputeConfig.from_json(p)
        assert cfg.optimizer is None
