"""B2 2.4 — ComputeConfig field registry + round-trip guards.

CONFIG_FIELDS is the single source for scalar field wiring (dataclass slot
↔ widget ↔ parse kind ↔ required-validation membership). These tests pin:

  1. registry completeness — every non-special row maps onto a real
     dataclass field of its section (a renamed/removed field fails here
     instead of silently defaulting);
  2. validation membership/order == the retired _REQUIRED_* lists;
  3. round-trips: cfg → json → cfg equality (non-default values), and
     stub-window → cfg → json → cfg equality;
  4. 2D vs 3D required-set parity (Lz/Nz only demanded in 3D).
"""

import pytest

from sjtu_tpmshx.domain.compute_config import (ComputeConfig, FluidConfig,
                                    GeometryConfig, SolverConfig)
from sjtu_tpmshx.ui.window_config import (CONFIG_FIELDS, config_from_window,
                              _validate_required_widgets)
from sjtu_tpmshx.tests.window_stubs import _StubWindow

_SECTION_TYPES = {
    'geometry': GeometryConfig,
    'solver': SolverConfig,
    'fluid_A': FluidConfig,
    'fluid_B': FluidConfig,
}


def test_registry_rows_map_to_real_dataclass_fields():
    for fs in CONFIG_FIELDS:
        cls = _SECTION_TYPES[fs.section]
        assert fs.name in cls.__dataclass_fields__, (
            f"CONFIG_FIELDS row {fs.widget!r} names unknown field "
            f"{fs.section}.{fs.name}")
        assert fs.kind in ('float', 'int', 'temp')


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
    cfg.flags.wall_refine_3d = True
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


def test_fluid_b_velocity_cross_default():
    """fluid_B.u_mps defaults to fluid_A's value when its widget is absent
    (the registry marks it special for exactly this reason)."""
    window = _StubWindow(uA='7.25')
    delattr(window, 'le_uB')
    cfg = config_from_window(window)
    assert cfg.fluid_B.u_mps == cfg.fluid_A.u_mps == 7.25


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
    from sjtu_tpmshx.tests.window_stubs import _StubLineEdit
    window = _StubWindow()
    window.le_pipeA_in_w = _StubLineEdit('0,042')
    with pytest.raises(ValueError) as e:
        _validate_required_widgets(window, is_3d=False)
    assert "Pipe A in_w" in str(e.value)


def test_pipe_widget_zero_and_blank_stay_legal():
    from sjtu_tpmshx.tests.window_stubs import _StubLineEdit
    window = _StubWindow()
    window.le_pipeA_in_w = _StubLineEdit('0.0')
    window.le_pipeA_out_w = _StubLineEdit('')
    _validate_required_widgets(window, is_3d=False)   # must not raise
