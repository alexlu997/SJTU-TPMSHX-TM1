"""Regression tests for the reviewer-driven fixes applied in this session.

Covers:
  1. Domain unit firewall — `_parse_inputs` raises ValueError when L/H/Lz
     exceed 10 m (defensive guard against m vs mm slip).
  2. Air roughness-factor consistency between scalar and field closures.

Single-fluid zero coupling and actual GUI fluid options are covered through
production constructors in their dedicated regression modules.
"""
from sjtu_tpmshx.models.nu_correlations import NU_ROUGHNESS_FACTOR


import numpy as np
import pytest


# ── 1. Domain unit firewall ─────────────────────────────────────────────


def test_domain_firewall_blocks_meter_typed_as_mm():
    """The domain unit firewall (L > 10 m → ValueError, catching the
    classic mm-vs-m slip of typing 182 into a metre field) must guard the
    PRODUCTION parse boundary. Since B2 2.1c that boundary is
    ``_parse_inputs_3d_cfg`` (driven by Pipeline3D.build_fields); the
    window adapter the original test used was deleted with the legacy
    entrypoints.
    """
    from sjtu_tpmshx.domain.compute_config import ComputeConfig, GeometryConfig, SolverConfig
    from sjtu_tpmshx.preprocess.three_d.preparation import _parse_inputs_3d_cfg

    cc = ComputeConfig(
        geometry=GeometryConfig(L_dom_m=182.0,    # unit slip: meant 0.182
                                H_dom_m=0.042, Lz_m=0.042),
        solver=SolverConfig(Nx=30, Ny=20, Nz=5),
    )
    with pytest.raises(ValueError) as excinfo:
        _parse_inputs_3d_cfg(cc)
    assert "exceeds" in str(excinfo.value) or "unit" in str(excinfo.value).lower(), (
        f"Expected unit firewall message, got: {excinfo.value}")
    print("test_domain_firewall_blocks_meter_typed_as_mm PASS")


def test_nu_roughness_factor_locked_at_1p28():
    """The CFD-fitted Nu correlation is multiplied by a global roughness
    enhancement factor φ_rough = 1.28 to bridge smooth-wall CFD predictions
    to rough-wall (additively-manufactured) experimental specimens.
    Justification: φ_rough = mean over angles of Q_exp / Q_DB(Re).

    Locking the constant here prevents accidental drift back to 1.0
    (which would silently push every Shanghai bias by ~+10% relative).
    """
    from sjtu_tpmshx.models import tpms_calc
    assert abs(NU_ROUGHNESS_FACTOR - 1.28) < 1e-9, (
        f"NU_ROUGHNESS_FACTOR={NU_ROUGHNESS_FACTOR} != 1.28. "
        "If you intentionally re-tuned it, update this test with the new "
        "value AND the docstring rationale in tpms_calc.py.")

    # nu_from_Re must apply the factor — sanity check via direct call
    Re_test = 5000.0
    eps_f = 0.4   # ε_full / 2 ≈ 0.78 / 2
    L_mm = 7.0
    D_h_mm = 3.6
    Nu_with = tpms_calc.nu_from_Re('Gyroid', Re_test, eps_f, L_mm, D_h_mm)
    # Compute smooth-wall reference directly
    Pr = tpms_calc.Pr
    Nu_smooth = 0.126 * Pr ** (1/3) * Re_test ** 0.7898 * (D_h_mm / L_mm) ** 0.2409
    expected = 1.28 * Nu_smooth
    assert abs(Nu_with - expected) / expected < 1e-6, (
        f"nu_from_Re did not apply the ×1.28 factor: got {Nu_with:.4f} "
        f"vs expected {expected:.4f} (smooth-wall Nu={Nu_smooth:.4f}).")

    # sigmoid_field._nu_vec must use the same constant (single source of truth)
    from sjtu_tpmshx.models.sigmoid_field import _nu_vec
    Re_arr = np.array([[Re_test]])
    eps_arr = np.array([[eps_f * 2.0]])      # _nu_vec consumes ε_full
    L_arr = np.array([[L_mm]])
    Nu_vec = _nu_vec('Gyroid', Re_arr, eps_arr, L_arr, D_h_mm)
    assert abs(float(Nu_vec[0, 0]) - expected) / expected < 1e-6, (
        f"_nu_vec drift from nu_from_Re — single-source-of-truth broken. "
        f"Got {float(Nu_vec[0,0]):.4f} vs expected {expected:.4f}.")
    print("test_nu_roughness_factor_locked_at_1p28 PASS")


if __name__ == '__main__':
    test_domain_firewall_blocks_meter_typed_as_mm()
    test_nu_roughness_factor_locked_at_1p28()
    print("\nAll review-fix tests PASS")
