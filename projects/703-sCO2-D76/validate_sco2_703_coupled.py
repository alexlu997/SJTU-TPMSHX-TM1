# -*- coding: utf-8 -*-
"""703 sCO2 PCHE — METHOD B' : BOTH-SIDES-LIVE coupled solve (task i).

Upgrades the prescribed-B field check (validate_sco2_703_field.py) to a fully
two-side-live coupled solve via the production Pipeline2D, at the Method-A sized
geometry, counterflow. This removes the prescribed-B caveat: BOTH outlet
temperatures are solved (energy-balanced), not imposed — so the duty Q is
physical, not frozen.

Conventions / why Q is computed externally:
  * 2D slice frontal = A_front (unit depth) so the domain volume = the core
    volume and dP is the real Forchheimer drop;
  * interstitial u = ṁ/(ρ·ε_A·A_front) per side;
  * counterflow = bc_A dir 0 (+x), bc_B dir 1 (-x);
  * Pipeline2D's internal Q_W uses a mass-flux convention that does not match
    this hand-built (u, H_dom) mapping, so Q is recomputed from the COUPLED
    outlet temps as ṁ·Δh (CoolProp), and the hot/cold imbalance is reported as
    the coupled-solve energy-conservation residual.

t=0.6 trips the ConstDF surrogate window → run needs allow-extrap (sCO2 uses its
own D-7-6 closure, not ConstDF, so it is not a true extrapolation).

Run:  python -u projects/703-sCO2-D76/validate_sco2_703_coupled.py
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

os.environ.setdefault("TPMSHX_ALLOW_EXTRAP", "1")

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from CoolProp.CoolProp import PropsSI as _P                    # noqa: E402
from sjtu_tpmshx.domain.compute_config import (ComputeConfig, FluidConfig,  # noqa: E402
    GeometryConfig, SolverConfig, PartialBCConfig, ExtrapPolicy)
from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D            # noqa: E402
from sjtu_tpmshx.models.tpms_calc import geometry as _geom               # noqa: E402

EPS_A = _geom("Diamond", 7.0, 0.6, 16.0)["epsilon_A"]


def _cp_name(fluid):
    return "CO2" if fluid == "sco2" else "Water"


def _rho(fluid, T, P):
    return _P("D", "T", T, "P", P, _cp_name(fluid))


def _h(fluid, T, P):
    return _P("H", "T", T, "P", P, _cp_name(fluid))


# Method-A sized picks (from size_sco2_703.py); hardcoded to skip re-sizing.
DEVS = [
    dict(name="主换热器 Heater",
         hot=("sco2", 25.0, 873.15, 12.7e6), cold=("sco2", 37.6, 654.0, 18.11e6),
         A_front=0.400, L=0.332, Q_target=6.46, Tc_out_A=794.8),
    dict(name="回热器 Recuperator",
         hot=("sco2", 37.6, 737.0, 8.017e6), cold=("sco2", 37.6, 361.0, 18.48e6),
         A_front=0.740, L=0.344, Q_target=15.98, Tc_out_A=655.0),
    dict(name="预冷器 Precooler",
         hot=("sco2", 37.6, 371.0, 7.857e6), cold=("water", 129.5, 297.15, 0.5e6),
         A_front=1.020, L=0.127, Q_target=5.41, Tc_out_A=307.15),
]


def run_device(dev, Nx=40, Ny=24):
    (fh, mh, Th, Ph) = dev["hot"]
    (fc, mc, Tc, Pc) = dev["cold"]
    A_front, L = dev["A_front"], dev["L"]
    H = A_front                       # 2D frontal = A_front (unit depth)
    rho_h = _rho(fh, Th, Ph)
    rho_c = _rho(fc, Tc, Pc)
    u_h = mh / (rho_h * EPS_A * A_front)
    u_c = mc / (rho_c * EPS_A * A_front)
    cfg = ComputeConfig(
        fluid_A=FluidConfig(type=fh, u_mps=u_h, T_in_K=Th, P_in_Pa=Ph),
        fluid_B=FluidConfig(type=fc, u_mps=u_c, T_in_K=Tc, P_in_Pa=Pc),
        geometry=GeometryConfig(tpms="Diamond", L_cell_mm=7.0, t_wall_mm=0.6,
                                k_s_W_mK=16.0, L_dom_m=L, H_dom_m=H),
        solver=SolverConfig(Nx=Nx, Ny=Ny),
        bc_A=PartialBCConfig(dir=0, in_ctr=H / 2, in_w=H, out_ctr=H / 2, out_w=H),
        bc_B=PartialBCConfig(dir=1, in_ctr=H / 2, in_w=H, out_ctr=H / 2, out_w=H),
        extrap=ExtrapPolicy(allow=True),
    )
    r = Pipeline2D(cfg).run()
    ToA, ToB = r.T_out_A_K, r.T_out_B_K
    Q_hot = mh * (_h(fh, Th, Ph) - _h(fh, ToA, Ph)) / 1e6
    Q_cold = mc * (_h(fc, ToB, Pc) - _h(fc, Tc, Pc)) / 1e6
    return dict(ToA=ToA, ToB=ToB, Q_hot=Q_hot, Q_cold=Q_cold,
                dPh=r.dP_A_Pa, dPc=r.dP_B_Pa, Ph=Ph, Pc=Pc,
                imbal=(Q_hot - Q_cold) / Q_hot * 100.0)


def main():
    print("703 sCO2 PCHE — METHOD B' (both-sides-LIVE coupled, counterflow, Method-A geometry)\n")
    print(f"{'device':>20} {'Q_hot':>6} {'Q_cold':>6} {'imbal%':>6} {'Qtgt':>6} "
          f"{'ToA K':>7} {'ToB K':>7} {'dPh%':>6} {'dPc%':>6}")
    for dev in DEVS:
        try:
            r = run_device(dev)
        except Exception as e:
            print(f"{dev['name']:>20}  FAILED: {type(e).__name__}: {str(e)[:60]}")
            continue
        print(f"{dev['name']:>20} {r['Q_hot']:>6.2f} {r['Q_cold']:>6.2f} "
              f"{r['imbal']:>+6.1f} {dev['Q_target']:>6.2f} "
              f"{r['ToA']:>7.1f} {r['ToB']:>7.1f} "
              f"{r['dPh']/r['Ph']*100:>6.2f} {r['dPc']/r['Pc']*100:>6.2f}")
    print("\n  Q = ṁ·Δh from COUPLED outlet temps (no prescribed-B); imbal = energy-conservation residual.")
    print("  dP both sides from the live coupled SIMPLE (cf_scale=3.39 for sCO2).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
