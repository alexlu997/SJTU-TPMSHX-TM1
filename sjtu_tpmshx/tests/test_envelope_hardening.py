"""Hardening of the post-solve validity gate (adversarial-audit follow-up,
2026-06-25).

Three audit findings fixed here:
- gate-mach-inlet-Tref-underestimate: the Mach check used the (hot) inlet T for
  the sound speed, under-estimating Ma at a colder cell where peak |v| sits.
  Now a per-cell conservative Mach (mach_field_max) is used.
- pressure-floor-masks-postsolve-gate: the `P_abs <= 0` branch was unreachable
  because _update_density floors the stored gauge to >= 1 kPa. The check now
  fires when the pressure is AT the floor (i.e. the clip engaged → off-envelope).
- ma_max override so the pipeline can pass the rigorous per-cell value.
"""

import numpy as np
import pytest

from sjtu_tpmshx.models.envelope import (
    assess_solution_validity, mach_field_max, gate_solution, ChokedFlowError,
    PRESSURE_FLOOR_PA,
)


# ── conservative per-cell Mach ─────────────────────────────────────────────
def test_mach_field_max_uses_local_cold_cell():
    # Uniform |v|=300 m/s. A cold cell (300 K, c~347) gives higher Ma than the
    # hot inlet T (800 K, c~567). The field max must reflect the cold cell.
    vmag = np.full((4, 4), 300.0)
    T = np.full((4, 4), 800.0)
    T[0, 0] = 300.0
    ma = mach_field_max(vmag, T)
    assert ma == pytest.approx(300.0 / np.sqrt(1.4 * 287.05 * 300.0), rel=1e-3)
    # strictly larger than the hot-inlet-T estimate
    assert ma > 300.0 / np.sqrt(1.4 * 287.05 * 800.0)


def test_mach_field_max_empty_is_zero():
    assert mach_field_max(np.array([]), np.array([])) == 0.0


# ── ma_max override ────────────────────────────────────────────────────────
def test_assess_uses_ma_max_when_provided():
    # Scalar vmax/T_ref would give Ma~0.035 (valid); the per-cell ma_max=1.2
    # override must win and flag supersonic.
    valid, reasons = assess_solution_validity(150e3, 20.0, 800.0, ma_max=1.2)
    assert valid is False
    assert any('supersonic' in r.lower() for r in reasons)


# ── floor-detect revives the masked pressure branch ────────────────────────
def test_assess_flags_pressure_at_floor():
    # A choked solve gets clipped to the 1 kPa floor; min abs P ~ floor -> invalid.
    valid, reasons = assess_solution_validity(PRESSURE_FLOOR_PA, 5.0, 800.0)
    assert valid is False
    assert any('pressure' in r.lower() or 'floor' in r.lower() for r in reasons)


def test_assess_clean_high_pressure_subsonic_valid():
    valid, reasons = assess_solution_validity(150e3, 8.5, 800.0, ma_max=0.02)
    assert valid is True and reasons == []


def test_gate_solution_raises_on_ma_max_override():
    with pytest.raises(ChokedFlowError):
        gate_solution(150e3, 20.0, 800.0, mode='raise', dims='3D-B', ma_max=1.5)


# ── envelope_mode reachable through ComputeConfig (audit: unreachable) ──────
def test_envelope_mode_field_and_from_dict():
    from sjtu_tpmshx.domain.compute_config import ComputeConfig
    assert ComputeConfig().envelope_mode == 'raise'              # default
    assert ComputeConfig(envelope_mode='warn').envelope_mode == 'warn'
    # canonical-layout dict (the asdict round-trip path) carries it
    assert ComputeConfig.from_dict(
        {'solver': {}, 'envelope_mode': 'off'}).envelope_mode == 'off'


def test_envelope_mode_propagates_into_3d_cfg():
    from dataclasses import replace
    from sjtu_tpmshx.domain.compute_config import ComputeConfig
    from sjtu_tpmshx.preprocess.three_d.preparation import _parse_inputs_3d_cfg
    base = ComputeConfig()
    cc = replace(base,
                 geometry=replace(base.geometry, t_wall_mm=0.5, Lz_m=0.042),
                 envelope_mode='warn')
    cfg = _parse_inputs_3d_cfg(cc)
    assert cfg['envelope_mode'] == 'warn'


# ── A1: NaN/inf fields must FAIL the validity gate (audit 2026-06-28) ───────
# A diverged solve can leave NaN in the pressure/velocity field. Every float
# comparison against NaN is False, so the floor/Mach branches silently skip and
# the gate used to report a NaN field as valid=True (the exact silent-garbage
# failure this guard exists to prevent, via NaN instead of finite |v|~2000).
def test_assess_flags_nan_pressure_invalid():
    valid, reasons = assess_solution_validity(np.nan, 5.0, 800.0, ma_max=0.02)
    assert valid is False
    assert any('non-finite' in r.lower() or 'diverg' in r.lower() for r in reasons)


def test_assess_flags_inf_pressure_invalid():
    valid, reasons = assess_solution_validity(np.inf, 5.0, 800.0, ma_max=0.02)
    assert valid is False


def test_assess_flags_nan_mach_invalid():
    # NaN velocity field -> mach_field_max returns NaN -> ma_max=nan.
    valid, reasons = assess_solution_validity(150e3, 5.0, 800.0, ma_max=np.nan)
    assert valid is False
    assert any('non-finite' in r.lower() or 'diverg' in r.lower() for r in reasons)


def test_gate_solution_raises_on_nan_field():
    with pytest.raises(ChokedFlowError):
        gate_solution(np.nan, 5.0, 800.0, mode='raise', dims='3D')


def test_assess_finite_clean_still_valid():
    # Guard must not regress the clean case.
    valid, reasons = assess_solution_validity(150e3, 8.5, 800.0, ma_max=0.02)
    assert valid is True and reasons == []


# ── A2: gate_solution must validate envelope_mode (audit 2026-06-28) ────────
# check_compressible_envelope rejects an unknown mode; gate_solution did not, so
# a typo'd mode ('raises'/'Raise') silently degraded a 'raise' intent into 'off'.
def test_gate_solution_rejects_unknown_mode():
    with pytest.raises(ValueError):
        gate_solution(150e3, 5.0, 800.0, mode='raises')  # typo of 'raise'


def test_gate_solution_rejects_wrong_case_mode():
    with pytest.raises(ValueError):
        gate_solution(150e3, 5.0, 800.0, mode='Raise')


def test_gate_solution_accepts_valid_modes():
    # The three canonical modes must not raise ValueError on a clean field.
    for m in ('raise', 'warn', 'off'):
        valid, _ = gate_solution(150e3, 8.5, 800.0, mode=m, ma_max=0.02)
        assert valid is True
