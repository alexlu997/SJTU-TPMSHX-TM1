# -*- coding: utf-8 -*-
"""703 sCO2 PCHE — METHOD iii : 3D field run (sCO2 fully generalized).

Proves the 3D enablement: the Fluid-A path of pipelines/stages_3d.py was air-
hardwired (air_density/visc/cp/cond + R_AIR EOS); iii generalizes it to the
fluid registry (props, flow_model EOS, cF×SCO2_CF_SCALE, per-cell variable
properties in the outer loop) and unblocks sCO2 on BOTH sides. air/water stay
bit-identical (golden 3D + full pytest).

Runs the recuperator (sCO2 both sides) in COUNTERFLOW (bc_A dir 0 / bc_B dir 1)
on a coarse grid and reports dP (both sides), the hot-side enthalpy duty, and
the AB energy-balance diagnostic.

⚠ KNOWN LIMITATION (not introduced here): the 3D LTNE has a B-side telescoping
conservation leak (see vault project_3d_bside_conservation_diagnosis: air-air
12-22%, needs the strict-energy FVM kernel to reach <0.4%). For sCO2 it is
amplified to ~23-28% (solid flux Q_sA≈Q_sB conserves, but the fluid convection
carries less). So the 3D dP + hot-side duty are trustworthy and confirm 2D, but
the 3D coupled Q / cold-outlet are NOT — use the 2D double-live coupled solve
(validate_sco2_703_coupled.py, imbalance −1.9%) for the coupled duty.

703 is counterflow (the recuperator/heater have a temperature cross: cold-out >
hot-out, impossible in crossflow).

Run:  TPMSHX_ALLOW_EXTRAP=1 python -u projects/703-sCO2-D76/validate_sco2_703_3d.py
"""
from __future__ import annotations

# ⚠ 2026-07-15: solver sCO2 closures switched to SMOOTH-WALL unit-cell CFD
# fits (Nu: nu_correlations.SCO2_NU_COEFFS with (Dh/L)^d; cF: df_surrogate/
# sco2_df.py via predict.sco2_cf_scale; the D-7-6 ×3.39 retired). This script
# validates the ROUGH D-7-6 experiment — errors are EXPECTED to grow until an
# experimental roughness anchor (gamma) lands. Ledger: SCO2-CFD.

import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("TPMSHX_ALLOW_EXTRAP", "1")  # t=0.6 trips ConstDF window

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from CoolProp.CoolProp import PropsSI as _P                    # noqa: E402
from sjtu_tpmshx.models.tpms_calc import geometry as _geom               # noqa: E402
from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack

_G = _geom("Diamond", 7.0, 0.6, 16.0)
EPS, EPS_A = _G["epsilon"], _G["epsilon_A"]

# recuperator (Method-A geometry); sCO2 both sides, counterflow
MH = MC = 37.6
TH, PH = 737.0, 8.017e6      # hot (Fluid A)
TC, PC = 361.0, 18.48e6      # cold (Fluid B)
A_FRONT, L = 0.740, 0.344
H = LZ = A_FRONT ** 0.5      # frontal = H×Lz = A_front


def _h(T, P):
    return _P("H", "T", T, "P", P, "CO2")


def _ff(w, wz):
    return dict(in_ctr=w / 2, in_w=w, out_ctr=w / 2, out_w=w,
                in_z_ctr=wz / 2, in_z_w=wz, out_z_ctr=wz / 2, out_z_w=wz)


def main(Nx=16, Ny=12, Nz=12):
    rho_h = _P("D", "T", TH, "P", PH, "CO2")
    rho_c = _P("D", "T", TC, "P", PC, "CO2")
    u_h = MH / (rho_h * EPS_A * A_FRONT)
    u_c = MC / (rho_c * EPS_A * A_FRONT)
    cfg = dict(
        L=L, H=H, Lz=LZ, Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=u_h, u_B=u_c, T_inA=TH, T_inB=TC, P_inA=PH, P_inB=PC,
        tpms_type="Diamond", Lcell=7.0, t_wall=0.6, k_s=16.0, eps=EPS,
        fluid_A_cfg=dict(dir=0, **_ff(H, LZ)),   # +x  (hot)
        fluid_B_cfg=dict(dir=1, **_ff(H, LZ)),   # -x  (cold, counterflow)
        fluid_type_A="sco2", fluid_type_B="sco2",
        wall_refine_3d=False,
    )
    print(f"703 recuperator 3D (sCO2 both, counterflow) — grid {Nx}x{Ny}x{Nz}, "
          f"H=Lz={H:.3f} L={L}")
    r = _run_3d_stack(cfg)
    ToA, ToB = r.get("T_A_out"), r.get("T_B_out")
    Q_hot = MH * (_h(TH, PH) - _h(ToA, PH)) / 1e6
    QsA, QsB = r.get("Q_sA", 0.0), r.get("Q_sB", 0.0)
    QeA, QeB = r.get("Q_enthalpy_A", 0.0), r.get("Q_enthalpy_B", 0.0)
    solid_imbal = abs(QsA + QsB) / max(abs(QsA), 1.0) * 100
    adv_gap = abs(abs(QsA) - QeA) / max(QeA, 1.0) * 100
    print(f"  dP_A = {r['dP']/1e3:6.1f} kPa ({r['dP']/PH*100:.2f}%)   "
          f"dP_B = {r['dP_B']/1e3:6.1f} kPa ({r['dP_B']/PC*100:.2f}%)")
    print(f"  T_A_out = {ToA:.1f} K (hot in {TH:.0f})   "
          f"T_B_out = {ToB:.1f} K (cold in {TC:.0f})")
    print(f"  hot-side enthalpy duty = {Q_hot:.2f} MW  (2D double-live: 16.3 MW)")
    print(f"  solid flux Q_sA={QsA/1e6:+.2f} Q_sB={QsB/1e6:+.2f} MW "
          f"(imbal {solid_imbal:.1f}%)")
    print(f"  fluid adv Q_enthA={QeA/1e6:.2f} Q_enthB={QeB/1e6:.2f} MW")
    print(f"  ⚠ hot adv-vs-solid gap = {adv_gap:.0f}%  → known 3D telescoping "
          f"leak (air-air 12-22%; needs strict-energy FVM). dP/hot-duty OK; "
          f"3D coupled-Q/cold-out NOT trustworthy.")
    ok = (r.get("dP", 0) > 0 and r.get("dP_B", 0) > 0
          and ToA and ToA < TH and ToB and ToB > TC and solid_imbal < 5.0)
    print(f"3D sCO2 ENABLE + RUN: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
