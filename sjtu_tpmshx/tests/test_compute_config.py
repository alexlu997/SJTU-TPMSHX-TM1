"""Tests for the compute contracts (domain/compute_config.py) + the window adapter (ui/window_config.py).

Covers:
- Default construction
- ``is_3d`` derived property
- JSON round-trip (canonical schema)
- JSON load from legacy ``configs/shanghai_baseline.json`` layout
- ``config_from_window`` adapter with a minimal mock window
- Optional-widget tolerance (le_Lz / le_TsInit / combo_fluidB missing)
- K/°C toggle honoured via ``window._temp_to_K``
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig,
    FluidConfig,
    GeometryConfig,
    SolverConfig,
    PartialBCConfig,
    ZoneInputConfig,
    ExtrapPolicy,
    FeatureFlags,
)
from sjtu_tpmshx.ui.window_config import config_from_window


# ── helpers ──────────────────────────────────────────────────────────


class _StubLineEdit:
    """Tiny stand-in for QLineEdit that returns a fixed text value."""

    def __init__(self, text: str, hidden: bool = False):
        self._text = text
        self._hidden = hidden

    def text(self) -> str:
        return self._text

    def isHidden(self) -> bool:
        return self._hidden


class _StubComboBox:
    def __init__(self, text: str, index: int = 0):
        self._text = text
        self._index = index

    def currentText(self) -> str:
        return self._text

    def currentIndex(self) -> int:
        return self._index


class _StubCheckBox:
    def __init__(self, checked: bool = False):
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _StubWindow:
    """Build only the attributes that ``config_from_window`` reads."""

    def __init__(self, **fields):
        # geometry
        self.combo_tpms = _StubComboBox(fields.get('tpms', 'Diamond'))
        self.le_Lcell = _StubLineEdit(fields.get('Lcell', '8.0'))
        self.le_t = _StubLineEdit(fields.get('t', '0.5'))
        self.le_ks = _StubLineEdit(fields.get('ks', '20.0'))
        self.le_L = _StubLineEdit(fields.get('L', '0.20'))
        self.le_H = _StubLineEdit(fields.get('H', '0.05'))
        # le_Lz defaults to a numeric value so strict mode passes for
        # 3D runs unless the test explicitly drops it.
        self.le_Lz = _StubLineEdit(fields.get('Lz', '0.05'))
        # solver
        self.le_Nx = _StubLineEdit(fields.get('Nx', '40'))
        self.le_Ny = _StubLineEdit(fields.get('Ny', '80'))
        self.le_Nz = _StubLineEdit(fields.get('Nz', '5'))
        if 'TsInit' in fields:
            self.le_TsInit = _StubLineEdit(fields['TsInit'])
        # fluids
        self.combo_fluidA = _StubComboBox(fields.get('fluidA', 'Air'))
        if 'fluidB' in fields:
            self.combo_fluidB = _StubComboBox(fields['fluidB'])
        self.le_uA = _StubLineEdit(fields.get('uA', '10.0'))
        self.le_uB = _StubLineEdit(fields.get('uB', '2.0'))
        self.le_TinA = _StubLineEdit(fields.get('TinA', '400.0'))
        self.le_TinB = _StubLineEdit(fields.get('TinB', '300.0'))
        self.le_PinA = _StubLineEdit(fields.get('PinA', '200000.0'))
        self.le_PinB = _StubLineEdit(fields.get('PinB', '101325.0'))


# ── defaults ─────────────────────────────────────────────────────────


def test_default_compute_config_is_2d():
    cfg = ComputeConfig()
    assert cfg.solver.Nz == 1
    assert cfg.is_3d is False
    assert cfg.fluid_A.type == 'air'
    assert cfg.geometry.tpms == 'Gyroid'


def test_is_3d_triggers_at_nz_2():
    cfg = ComputeConfig()
    cfg.solver.Nz = 1
    assert not cfg.is_3d
    cfg.solver.Nz = 2
    assert cfg.is_3d
    cfg.solver.Nz = 20
    assert cfg.is_3d


# ── JSON round-trip ─────────────────────────────────────────────────


def test_json_roundtrip_canonical():
    cfg = ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=12.3, T_in_K=420.0,
                            P_in_Pa=2e5),
        fluid_B=FluidConfig(type='water', u_mps=0.15, T_in_K=305.0,
                            P_in_Pa=1.5e5),
        geometry=GeometryConfig(tpms='Diamond', L_cell_mm=8.0,
                                t_wall_mm=0.5, k_s_W_mK=18.0,
                                L_dom_m=0.20, H_dom_m=0.05, Lz_m=0.05),
        solver=SolverConfig(Nx=40, Ny=80, Nz=10, T_s_init_K=350.0),
    )
    with tempfile.NamedTemporaryFile('w', suffix='.json',
                                      delete=False) as f:
        path = f.name
    try:
        cfg.to_json(path)
        cfg2 = ComputeConfig.from_json(path)
    finally:
        Path(path).unlink()
    assert cfg2.fluid_A.u_mps == pytest.approx(12.3)
    assert cfg2.fluid_B.type == 'water'
    assert cfg2.geometry.tpms == 'Diamond'
    assert cfg2.geometry.Lz_m == pytest.approx(0.05)
    assert cfg2.solver.Nz == 10
    assert cfg2.solver.T_s_init_K == pytest.approx(350.0)
    assert cfg2.is_3d


def test_json_legacy_shanghai_baseline_layout():
    """``configs/shanghai_baseline.json`` ships with the audit AR8 layout
    (``_meta``/``geometry``/``domain``/``_excluded``).  ``from_json``
    must absorb it; fluids fall back to defaults because the Shanghai
    loop overwrites them per case."""
    legacy = {
        '_meta': {'case_name': 'unit test'},
        'geometry': {
            'tpms': 'Gyroid', 'L_cell_mm': 7.0,
            't_wall_mm': 0.6, 'k_s_W_mK': 16.0,
        },
        'domain': {
            'L_dom_m': 0.182, 'H_dom_m': 0.042, 'Lz_m': 0.042,
        },
    }
    with tempfile.NamedTemporaryFile('w', suffix='.json',
                                      delete=False) as f:
        path = f.name
    try:
        Path(path).write_text(json.dumps(legacy), encoding='utf-8')
        cfg = ComputeConfig.from_json(path)
    finally:
        Path(path).unlink()
    assert cfg.geometry.tpms == 'Gyroid'
    assert cfg.geometry.L_cell_mm == pytest.approx(7.0)
    assert cfg.geometry.L_dom_m == pytest.approx(0.182)
    assert cfg.geometry.Lz_m == pytest.approx(0.042)
    # fluid defaults preserved
    assert cfg.fluid_A.type == 'air'


def test_repo_shanghai_baseline_loads():
    """Sanity: the file checked into ``configs/`` parses cleanly."""
    repo_path = (Path(__file__).resolve().parents[1]
                 / 'configs' / 'shanghai_baseline.json')
    cfg = ComputeConfig.from_json(repo_path)
    assert cfg.geometry.tpms == 'Gyroid'
    assert cfg.geometry.L_cell_mm == pytest.approx(7.0)
    assert cfg.geometry.L_dom_m == pytest.approx(0.182)


# ── config_from_window adapter ─────────────────────────────────────────


def test_config_from_window_full_smoke():
    window = _StubWindow(
        tpms='Diamond', Lcell='8.0', t='0.5', ks='20.0',
        L='0.20', H='0.05', Lz='0.05',
        Nx='40', Ny='80', Nz='5',
        fluidA='Air', fluidB='Water',
        uA='10.0', uB='2.0',
        TinA='400.0', TinB='300.0',
        PinA='200000.0', PinB='101325.0',
        TsInit='350.0',
    )
    cfg = config_from_window(window)
    assert cfg.geometry.tpms == 'Diamond'
    assert cfg.geometry.L_cell_mm == pytest.approx(8.0)
    assert cfg.geometry.Lz_m == pytest.approx(0.05)
    assert cfg.solver.Nz == 5
    assert cfg.solver.T_s_init_K == pytest.approx(350.0)
    assert cfg.fluid_A.type == 'air'
    assert cfg.fluid_B.type == 'water'
    assert cfg.fluid_A.u_mps == pytest.approx(10.0)
    assert cfg.fluid_B.P_in_Pa == pytest.approx(101325.0)
    assert cfg.is_3d


def test_config_from_window_optional_widgets_missing():
    """No le_Lz, no le_TsInit, no combo_fluidB → falls back to defaults
    without raising."""
    window = _StubWindow(
        tpms='Gyroid', Nx='30', Ny='60', Nz='1',
        fluidA='Air',  # combo_fluidB intentionally absent
    )
    # Remove le_Lz / le_TsInit / combo_fluidB to simulate stripped-down UI
    if hasattr(window, 'le_Lz'):
        del window.le_Lz
    cfg = config_from_window(window)
    assert cfg.geometry.Lz_m is None
    assert cfg.solver.T_s_init_K is None
    assert cfg.solver.Nz == 1
    assert cfg.fluid_B.type == 'air'   # default
    assert not cfg.is_3d


def test_config_from_window_temp_to_K_hook_called():
    """The window's ``_temp_to_K`` hook converts °C → K. The adapter
    must use it instead of raw float()."""
    window = _StubWindow(TinA='100', TinB='50')   # °C if hook present

    def _temp_to_K(widget):
        return float(widget.text()) + 273.15

    window._temp_to_K = _temp_to_K
    cfg = config_from_window(window)
    assert cfg.fluid_A.T_in_K == pytest.approx(373.15)
    assert cfg.fluid_B.T_in_K == pytest.approx(323.15)


def test_config_from_window_blank_lineedit_uses_default():
    """An empty QLineEdit (user deleted the value) falls back to the
    dataclass default rather than raising."""
    window = _StubWindow(uA='', Nx='', TinA='')
    cfg = config_from_window(window)
    assert cfg.fluid_A.u_mps == 5.0   # FluidConfig default
    assert cfg.solver.Nx == 30        # SolverConfig default
    assert cfg.fluid_A.T_in_K == 300.0


# ── strict validation ───────────────────────────────────────────────


def test_config_from_window_strict_passes_on_full_window():
    """Strict mode is a no-op when every required widget is filled."""
    window = _StubWindow()   # all defaults non-empty
    cfg = config_from_window(window, strict=True)
    assert cfg.fluid_A.u_mps == pytest.approx(10.0)


def test_config_from_window_strict_flags_blank_required_field():
    """Blank Velocity A → strict raises ValueError naming the field."""
    window = _StubWindow(uA='', H='')
    with pytest.raises(ValueError) as exc:
        config_from_window(window, strict=True)
    msg = str(exc.value)
    assert 'Velocity A' in msg
    assert 'Domain Height' in msg


def test_config_from_window_strict_flags_non_numeric_grid():
    """Garbage in Nx → strict raises naming the grid field."""
    window = _StubWindow(Nx='abc')
    with pytest.raises(ValueError) as exc:
        config_from_window(window, strict=True)
    assert 'Grid Nx' in str(exc.value)


def test_config_from_window_strict_3d_requires_Lz_Nz():
    """force_3d=True checks le_Lz / le_Nz as well."""
    window = _StubWindow(Nz='5')
    if hasattr(window, 'le_Lz'):
        del window.le_Lz   # 3D run with missing Lz
    with pytest.raises(ValueError) as exc:
        config_from_window(window, strict=True, force_3d=True)
    assert 'Width Lz' in str(exc.value)


def test_config_from_window_strict_autodetects_3d():
    """Nz>=2 in the widget auto-triggers the 3D required set even when
    ``force_3d`` is left as the default ``None``."""
    window = _StubWindow(Nz='5')
    if hasattr(window, 'le_Lz'):
        del window.le_Lz
    with pytest.raises(ValueError) as exc:
        config_from_window(window, strict=True)
    assert 'Width Lz' in str(exc.value)


# ── audit C4: extended schema (PartialBC / Zone / Extrap / Flags) ───


def test_c4_new_dataclasses_have_safe_defaults():
    """Default-construct each new dataclass — must not raise and must
    return values that match the legacy ``window`` defaults (zero-width
    BC = full face; zones disabled; no extrap; wall_refine off; K)."""
    bc = PartialBCConfig()
    assert bc.dir == 0
    assert bc.in_w == 0.0 and bc.in_ctr == 0.0
    assert bc.in_z_ctr is None and bc.out_z_w is None
    zn = ZoneInputConfig()
    assert zn.enabled is False
    assert zn.axis == 'y'
    assert zn.grid is None
    assert zn.pareto_x_decision is None
    fl = FeatureFlags()
    assert fl.wall_refine_3d is False
    assert fl.variable_rho_cp is True   # default ON (local-P gas density)
    assert fl.temp_unit == 'K'
    ex = ExtrapPolicy()
    assert ex.allow is False


def test_read_feature_flags_use_current_gui_transport_policy():
    from types import SimpleNamespace
    from sjtu_tpmshx.ui.window_config import _read_feature_flags

    window = SimpleNamespace(combo_grid=SimpleNamespace(currentData=lambda: True))
    flags = _read_feature_flags(window)
    assert flags.variable_rho_cp and flags.port_wall_refine
    assert not flags.wall_refine_3d


def test_c4_compute_config_default_has_new_fields():
    """``ComputeConfig()`` must default-construct every new sub-cfg
    without the caller having to supply them."""
    cfg = ComputeConfig()
    assert isinstance(cfg.bc_A, PartialBCConfig)
    assert isinstance(cfg.bc_B, PartialBCConfig)
    assert isinstance(cfg.zones, ZoneInputConfig)
    assert isinstance(cfg.flags, FeatureFlags)
    assert isinstance(cfg.extrap, ExtrapPolicy)


def test_c4_config_from_window_reads_partial_bc_widgets():
    """The 2D partial-BC pipe widgets feed ``bc_A`` / ``bc_B``."""
    window = _StubWindow()
    window.combo_dirA = _StubComboBox('+x', index=0)
    window.combo_dirB = _StubComboBox('-y', index=3)
    window.le_pipeA_in_ctr = _StubLineEdit('0.021')
    window.le_pipeA_in_w = _StubLineEdit('0.020')
    window.le_pipeA_out_ctr = _StubLineEdit('0.021')
    window.le_pipeA_out_w = _StubLineEdit('0.020')
    window.le_pipeB_in_ctr = _StubLineEdit('0.091')
    window.le_pipeB_in_w = _StubLineEdit('0.080')
    window.le_pipeB_out_ctr = _StubLineEdit('0.091')
    window.le_pipeB_out_w = _StubLineEdit('0.080')
    cfg = config_from_window(window)
    assert cfg.bc_A.dir == 0
    assert cfg.bc_A.in_ctr == pytest.approx(0.021)
    assert cfg.bc_A.out_w == pytest.approx(0.020)
    assert cfg.bc_B.dir == 3
    assert cfg.bc_B.in_w == pytest.approx(0.080)
    assert cfg.bc_B.uniform_inlet_2d is True
    assert cfg.bc_A.uniform_inlet_2d is True
    # 3D z-fields absent → stay None
    assert cfg.bc_A.in_z_ctr is None
    assert cfg.bc_B.in_z_w is None


def test_c4_config_from_window_reads_partial_bc_z_when_visible():
    """``le_pipe<side>_in_z_*`` honoured when present and not hidden
    (3D mode)."""
    window = _StubWindow()
    window.combo_dirA = _StubComboBox('+x', index=0)
    window.le_pipeA_in_ctr = _StubLineEdit('0.02')
    window.le_pipeA_in_w = _StubLineEdit('0.02')
    window.le_pipeA_out_ctr = _StubLineEdit('0.02')
    window.le_pipeA_out_w = _StubLineEdit('0.02')
    # z-fields visible
    window.le_pipeA_in_z_ctr = _StubLineEdit('0.025', hidden=False)
    window.le_pipeA_in_z_w = _StubLineEdit('0.020', hidden=False)
    window.le_pipeA_out_z_ctr = _StubLineEdit('0.025', hidden=False)
    window.le_pipeA_out_z_w = _StubLineEdit('0.020', hidden=False)
    cfg = config_from_window(window)
    assert cfg.bc_A.in_z_ctr == pytest.approx(0.025)
    assert cfg.bc_A.out_z_w == pytest.approx(0.020)


def test_c4_config_from_window_skips_partial_bc_z_when_hidden():
    """Hidden z-widgets fall back to None (2D mode hides them)."""
    window = _StubWindow()
    window.combo_dirA = _StubComboBox('+x', index=0)
    window.le_pipeA_in_ctr = _StubLineEdit('0.02')
    window.le_pipeA_in_w = _StubLineEdit('0.02')
    window.le_pipeA_out_ctr = _StubLineEdit('0.02')
    window.le_pipeA_out_w = _StubLineEdit('0.02')
    window.le_pipeA_in_z_ctr = _StubLineEdit('0.025', hidden=True)
    window.le_pipeA_in_z_w = _StubLineEdit('0.020', hidden=True)
    window.le_pipeA_out_z_ctr = _StubLineEdit('0.025', hidden=True)
    window.le_pipeA_out_z_w = _StubLineEdit('0.020', hidden=True)
    cfg = config_from_window(window)
    assert cfg.bc_A.in_z_ctr is None
    assert cfg.bc_A.out_z_w is None


def test_c4_config_from_window_reads_zone_state():
    """``chk_zones`` + ``combo_zone_axis`` + ``_zone_grid`` snapshot
    into ``cfg.zones``. ``_pareto_*`` carried through unchanged."""
    window = _StubWindow()
    window.chk_zones = _StubCheckBox(checked=True)
    window.combo_zone_axis = _StubComboBox('grid', index=2)
    from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
    window.zone_table = QTableWidget(1, 6)
    for col, value in enumerate(('0', '100', '0', '100', '6', '0.3')):
        window.zone_table.setItem(0, col, QTableWidgetItem(value))
    window._pareto_x_decision = [0.1, 0.2, 0.3]
    window._pareto_y_trans_inlet = 0.15
    window._pareto_y_trans_outlet = 0.18
    cfg = config_from_window(window)
    assert cfg.zones.enabled is True
    assert cfg.zones.axis == 'grid'
    assert cfg.zones.grid is not None
    assert cfg.zones.grid['tpms_type'] == 'Diamond'
    assert cfg.zones.pareto_x_decision == [0.1, 0.2, 0.3]
    assert cfg.zones.pareto_y_trans_inlet == pytest.approx(0.15)
    window._zone_grid['cells'][0]['L'] = 8
    window._pareto_x_decision[0] = 9
    assert cfg.zones.grid['cells'][0]['L'] == 6
    assert cfg.zones.pareto_x_decision == [0.1, 0.2, 0.3]


@pytest.mark.parametrize('nz', ['1', '5'])
def test_headless_dimension_and_explicit_override(nz):
    window = _StubWindow(Nz=nz)
    assert config_from_window(window).is_3d == (nz == '5')
    assert not config_from_window(window, force_3d=False).is_3d
    assert window.le_Nz.text() == nz
    if nz == '1':
        with pytest.raises(ValueError, match='Nz'):
            config_from_window(window, force_3d=True)
    else:
        assert config_from_window(window, force_3d=True).is_3d


def test_headless_invalid_nz_is_not_silently_repaired():
    cfg = config_from_window(_StubWindow(Nz='0'))
    assert cfg.solver.Nz == 0
    with pytest.raises(ValueError, match='Nz'):
        cfg.validate()


def test_c4_config_from_window_zone_defaults_when_widgets_absent():
    """No zone widgets on window → zones default (disabled, axis='y')."""
    window = _StubWindow()
    cfg = config_from_window(window)
    assert cfg.zones.enabled is False
    assert cfg.zones.axis == 'y'
    assert cfg.zones.grid is None
    assert cfg.zones.pareto_x_decision is None


def test_c4_config_from_window_reads_extrap_policy():
    window = _StubWindow()
    window.chk_allow_extrap = _StubCheckBox(checked=True)
    cfg = config_from_window(window)
    assert cfg.extrap.allow is True


def test_c4_config_from_window_extrap_default_when_widget_absent():
    window = _StubWindow()
    cfg = config_from_window(window)
    assert cfg.extrap.allow is False


def test_c4_config_from_window_reads_feature_flags():
    window = _StubWindow()
    window._temp_unit = 'C'
    cfg = config_from_window(window)
    assert cfg.flags.wall_refine_3d is False
    assert cfg.flags.temp_unit == 'C'


def test_c4_feature_flags_default_when_widgets_absent():
    window = _StubWindow()
    cfg = config_from_window(window)
    assert cfg.flags.wall_refine_3d is False
    assert cfg.flags.temp_unit == 'K'


def test_c4_json_roundtrip_includes_new_fields():
    """JSON canonical layout round-trips every new sub-cfg."""
    cfg = ComputeConfig(
        bc_A=PartialBCConfig(dir=0, in_ctr=0.021, in_w=0.02,
                              out_ctr=0.021, out_w=0.02),
        bc_B=PartialBCConfig(dir=3, in_ctr=0.091, in_w=0.08,
                              out_ctr=0.091, out_w=0.08, uniform_inlet_2d=True),
        zones=ZoneInputConfig(enabled=True, axis='x',
                              pareto_y_trans_inlet=0.18),
        flags=FeatureFlags(wall_refine_3d=True, temp_unit='C'),
        extrap=ExtrapPolicy(allow=True),
    )
    with tempfile.NamedTemporaryFile('w', suffix='.json',
                                      delete=False) as f:
        path = f.name
    try:
        cfg.to_json(path)
        cfg2 = ComputeConfig.from_json(path)
    finally:
        Path(path).unlink()
    assert cfg2.bc_A.dir == 0
    assert cfg2.bc_A.in_ctr == pytest.approx(0.021)
    assert cfg2.bc_B.dir == 3
    assert cfg2.bc_B.uniform_inlet_2d is True
    assert cfg2.zones.enabled is True
    assert cfg2.zones.axis == 'x'
    assert cfg2.zones.pareto_y_trans_inlet == pytest.approx(0.18)
    assert cfg2.flags.wall_refine_3d is True
    assert cfg2.flags.temp_unit == 'C'
    assert cfg2.extrap.allow is True


def test_uniform_inlet_rejects_text_boolean():
    with pytest.raises(ValueError, match='uniform_inlet_2d must be boolean'):
        ComputeConfig(bc_B=PartialBCConfig(uniform_inlet_2d='false')).validate()


def test_c4_legacy_json_without_new_fields_keeps_defaults():
    """Old JSON files (no bc_A/zones/flags) load with default sub-cfgs."""
    legacy = {
        'fluid_A': {'type': 'air', 'u_mps': 5.0},
        'geometry': {'tpms': 'Gyroid', 'L_dom_m': 0.182},
        'solver': {'Nx': 30},
    }
    with tempfile.NamedTemporaryFile('w', suffix='.json',
                                      delete=False) as f:
        path = f.name
    try:
        Path(path).write_text(json.dumps(legacy), encoding='utf-8')
        cfg = ComputeConfig.from_json(path)
    finally:
        Path(path).unlink()
    assert cfg.bc_A.dir == 0
    assert cfg.zones.enabled is False
    assert cfg.flags.temp_unit == 'K'
    assert cfg.extrap.allow is False
