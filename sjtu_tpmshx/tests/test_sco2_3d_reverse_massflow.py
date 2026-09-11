"""Regression: the reverse-dir density-frame fix for sCO2 (stages_3d, 2026-06-28).

For a reverse-dir (counterflow) B fluid the velocity transforms apply the
stream-axis flip but the T->SIMPLE-density transform did not, mirroring the
SIMPLE density field: the hot real-OUTLET temperature landed on the solver
injection face, so rho_in = rho(T_out) instead of rho(T_in). For air/water
(weak rho(T)) the effect is within the accepted reverse-dir residual
(test_3d_reverse_mirror), but for rho(T)-sensitive sCO2 it under-read the
B-side mass flow ~2.4x (15.5 vs 37.6 kg/s on the 703 recuperator) and inflated
the A/B enthalpy-duty imbalance to ~76%.

The fix (gated to sCO2 reverse-dir B) flips the density frame to match the
velocity frame. This test asserts the B-side implied mass flow recovers to the
physical value and the A/B imbalance drops out of the bug regime.

skipped if CoolProp is unavailable.
"""

import pytest

# NOTE: TPMSHX_ALLOW_EXTRAP is set test-locally via monkeypatch inside the test
# (NOT at module level) — a module-level os.environ.setdefault leaks the env
# process-wide and breaks later-collected out-of-window surrogate-domain tests.
PropsSI = pytest.importorskip("CoolProp.CoolProp").PropsSI

from sjtu_tpmshx.models.tpms_calc import geometry as _geom          # noqa: E402
import sjtu_tpmshx.pipelines.stages_3d as R                           # noqa: E402

_G = _geom("Diamond", 7.0, 0.6, 16.0)
EPS, EPS_A = _G["epsilon"], _G["epsilon_A"]


def _ff(w, wz):
    return dict(in_ctr=w / 2, in_w=w, out_ctr=w / 2, out_w=w,
                in_z_ctr=wz / 2, in_z_w=wz, out_z_ctr=wz / 2, out_z_w=wz)


def test_reverse_dir_sco2_massflow_recovered(monkeypatch):
    monkeypatch.setenv("TPMSHX_ALLOW_EXTRAP", "1")  # test-local; auto-restored
    # 703 recuperator: sCO2 both sides, counterflow (A dir 0 +x, B dir 1 -x).
    MH = MC = 37.6
    TH, PH = 650.0, 8.5e6            # hot  (A, forward)
    TC, PC = 350.0, 15.0e6           # cold (B, reverse) — dense, strong rho(T)
    A_FRONT, L = 0.740, 0.344
    H = LZ = A_FRONT ** 0.5
    rho_h = PropsSI("D", "T", TH, "P", PH, "CO2")
    rho_c = PropsSI("D", "T", TC, "P", PC, "CO2")
    u_h = MH / (rho_h * EPS_A * A_FRONT)
    u_c = MC / (rho_c * EPS_A * A_FRONT)
    cfg = dict(
        L=L, H=H, Lz=LZ, Nx=16, Ny=12, Nz=12, u_A=u_h, u_B=u_c,
        T_inA=TH, T_inB=TC, P_inA=PH, P_inB=PC, tpms_type="Diamond",
        Lcell=7.0, t_wall=0.6, k_s=16.0, eps=EPS,
        fluid_A_cfg=dict(dir=0, **_ff(H, LZ)),
        fluid_B_cfg=dict(dir=1, **_ff(H, LZ)),     # reverse-dir B
        fluid_type_A="sco2", fluid_type_B="sco2", wall_refine_3d=False,
    )
    r = R._run_3d_stack(cfg)

    # B-side implied mass flow from the coupled duty: Q_B = m_B * dh_B.
    ToB = r["T_B_out"]
    QeB = r.get("Q_enthalpy_B", 0.0)
    dhB = abs(PropsSI("H", "T", ToB, "P", PC, "CO2")
              - PropsSI("H", "T", TC, "P", PC, "CO2"))
    assert dhB > 1.0e3, "degenerate: no B-side enthalpy change to compare"
    m_B_implied = QeB / dhB

    # With the bug the SIMPLE-B inlet density was rho(T_out)~207 not rho(T_in)
    # ~503 -> m_B_implied ~15.5 kg/s (41% of physical). The fix recovers the
    # physical 37.6 kg/s. Gate at 30 kg/s sits well above the bug regime and
    # below the physical value (coarse-grid + duty leak give a few % slack).
    assert m_B_implied > 30.0, (
        f"reverse-dir sCO2 B mass flow not recovered: m_B_implied="
        f"{m_B_implied:.2f} kg/s (physical 37.6; bug regime ~15.5). The "
        f"T->SIMPLE-density frame flip for reverse-dir sCO2 B is missing."
    )

    # The A/B enthalpy-duty imbalance must drop out of the bug regime (~76%).
    imbal = r.get("Q_AB_imbalance_rel", float("nan"))
    assert imbal == imbal, "Q_AB_imbalance_rel not populated for sCO2 3D"
    assert imbal < 0.55, (
        f"A/B imbalance {imbal*100:.0f}% still in the bug regime (~76%); "
        f"reverse-dir density-frame fix regressed. Residual ~41% is the "
        f"known enthalpy-vs-(cp*T) kernel limit."
    )
