"""Measure F2 tolerance cost on the historical full-face pricing workload.

Run as a module with --mom-tol 1e-3,1e-4,1e-5 --cases 1,8,16.
The retired legacy comparison remains in Git history at ec1c73e; its original
reports/f2_pricing_3d.csv is indexed in docs/history/retired-tools.md.
The full-face ports and velocity convention intentionally retain the pricing
workload; they differ from the confirmed Shanghai validation ports. These
errors are workload comparisons, not current specimen accuracy acceptance.
New runs default to separate .cache/validation/f2_pricing-*/ CSVs.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

from sjtu_tpmshx.domain.compute_config import (ComputeConfig, FluidConfig,   # noqa: E402
                                   GeometryConfig, SolverConfig,
                                   PartialBCConfig, ExtrapPolicy)
from sjtu_tpmshx.controllers.compute_pipeline import Pipeline3D              # noqa: E402
from sjtu_tpmshx.models.tpms_calc import (air_density, water_density,       # noqa: E402
                               P_atm)
from sjtu_tpmshx.validation.harness._case_sets import shanghai_spec, SHANGHAI_XLSX  # noqa: E402
from sjtu_tpmshx.validation.harness._harness import load_cases_df            # noqa: E402

from sjtu_tpmshx.validation.harness._provenance import (
    output_directory, output_path, write_csv_with_provenance,
)

SPEC = shanghai_spec()


def _build_cfg(ci, df, Nx, Ny, Nz, *, mom_tol, mass_local_tol,
               mass_global_tol, max_outer=None):
    m_air = float(df.iloc[ci, 5])
    T_Ain_K = float(df.iloc[ci, 28]) + 273.15
    P_Ain = P_atm + float(df.iloc[ci, 30])
    m_water = float(df.iloc[ci, 7])
    T_Bin_K = float(df.iloc[ci, 24]) + 273.15

    rho_A = air_density(T_Ain_K, P_Ain)
    u_A = m_air / (rho_A * SPEC.a_flow_m2)
    u_B = m_water / (water_density(T_Bin_K) * SPEC.a_flow_m2)
    L, H, Lz = SPEC.L_dom_m, SPEC.H_dom_m, SPEC.Lz_m

    solver = SolverConfig(
        Nx=Nx, Ny=Ny, Nz=Nz,
        max_outer_ltne=(None if max_outer is None else int(max_outer)),
        convergence_mode='f2', mom_tol=mom_tol,
        mass_local_tol=mass_local_tol, mass_global_tol=mass_global_tol)

    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=u_A, T_in_K=T_Ain_K,
                            P_in_Pa=P_Ain),
        fluid_B=FluidConfig(type='water', u_mps=u_B, T_in_K=T_Bin_K,
                            P_in_Pa=float(df['water_P_in_abs_Pa'].iloc[ci])),
        geometry=GeometryConfig(tpms=SPEC.tpms, L_cell_mm=SPEC.L_cell_mm,
                                t_wall_mm=SPEC.t_wall_mm,
                                k_s_W_mK=SPEC.k_s_W_mK,
                                L_dom_m=L, H_dom_m=H, Lz_m=Lz),
        solver=solver,
        bc_A=PartialBCConfig(dir=0, in_ctr=H / 2, in_w=H,
                             out_ctr=H / 2, out_w=H,
                             in_z_ctr=Lz / 2, in_z_w=Lz,
                             out_z_ctr=Lz / 2, out_z_w=Lz),
        bc_B=PartialBCConfig(dir=3, in_ctr=L / 2, in_w=L,
                             out_ctr=L / 2, out_w=L,
                             in_z_ctr=Lz / 2, in_z_w=Lz,
                             out_z_ctr=Lz / 2, out_z_w=Lz),
        extrap=ExtrapPolicy(allow=True),
    )


def _run(ci, df, Nx, Ny, Nz, **kw):
    dP_exp = float(df.iloc[ci, 30]) - float(df.iloc[ci, 31])
    Q_exp = float(df.iloc[ci, 33])
    cc = _build_cfg(ci, df, Nx, Ny, Nz, **kw)
    t0 = time.perf_counter()
    res = Pipeline3D(cc).run()
    wall = time.perf_counter() - t0

    d = res.diagnostics or {}
    cd = d.get('convergence_detail') or {}
    sa = cd.get('simple_A') or {}
    return {
        'case': ci + 1,
        'dP_sim': res.dP_A_Pa, 'dP_exp': dP_exp,
        'err_dP%': (res.dP_A_Pa - dP_exp) / dP_exp * 100 if dP_exp else np.nan,
        'Q_sim': res.Q_W, 'Q_exp': Q_exp,
        'err_Q%': (res.Q_W - Q_exp) / Q_exp * 100 if Q_exp else np.nan,
        'wall_s': wall,
        'exit_A': cd.get('simple_exit_A'),
        'simple_iters_A': sa.get('iterations'),
        'outer_iters': cd.get('outer_iters'),
        'converged': bool(d.get('solver_converged', False)),
        'res_mass_legacy': sa.get('final_res'),
        'res_mom': sa.get('final_res_mom'),
        'res_mass_local': sa.get('final_res_mass_local'),
        'res_mass_global': sa.get('final_res_mass_global'),
        'backflow_frac': sa.get('outlet_backflow_frac'),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--grid', default='20,10,3')
    ap.add_argument('--cases', default=','.join(str(i) for i in range(1, 17)))
    ap.add_argument('--mom-tol', default='1e-3,1e-4,1e-5',
                    help='momentum-residual tolerances to sweep (f2 only)')
    ap.add_argument('--mass-local-tol', type=float, default=1e-6)
    ap.add_argument('--mass-global-tol', type=float, default=1e-6)
    ap.add_argument('--max-outer', type=int, default=None)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    try:
        dest = (output_path(args.out) if args.out else
                output_directory('f2_pricing') / 'f2_pricing_3d_v2.csv')
    except ValueError as exc:
        ap.error(str(exc))

    if os.environ.get('PYTHONHASHSEED') != '0':
        print("[WARN] PYTHONHASHSEED != 0 — the 3D pipeline is hash-seed "
              "sensitive; these numbers are not reproducible. Re-run with "
              "PYTHONHASHSEED=0.", file=sys.stderr)

    Nx, Ny, Nz = (int(x) for x in args.grid.split(','))
    cases = [int(c) for c in args.cases.split(',')]
    mom_tols = [float(t) for t in args.mom_tol.split(',')]
    df = load_cases_df(SHANGHAI_XLSX)

    runs = []
    for mt in mom_tols:
        label = f"f2@{mt:g}"
        print(f"\n=== {label} ===", flush=True)
        for c in cases:
            r = _run(c - 1, df, Nx, Ny, Nz, mom_tol=mt,
                     mass_local_tol=args.mass_local_tol,
                     mass_global_tol=args.mass_global_tol,
                     max_outer=args.max_outer)
            r['mode'] = label
            r['mom_tol'] = mt
            runs.append(r)
            print(f"  case {r['case']:2d}  exit={str(r['exit_A']):>8s} "
                  f"iters={r['simple_iters_A']!s:>5s} "
                  f"{r['wall_s']:6.1f}s  "
                  f"dP={r['dP_sim']:10.1f} ({r['err_dP%']:+6.2f}%)  "
                  f"Q={r['Q_sim']:8.1f} ({r['err_Q%']:+6.2f}%)",
                  flush=True)

    out = pd.DataFrame(runs)
    write_csv_with_provenance(out, dest, __file__)

    print("\n" + "=" * 96)
    print(f"{'mode':10s} {'RMSRE dP%':>10s} {'RMSRE Q%':>9s} "
          f"{'SIMPLE iters':>13s} {'wall/case':>10s} {'exit':>10s} "
          f"{'res_mom':>10s}")
    print("-" * 96)
    base_it = None
    for label, g in out.groupby('mode', sort=False):
        rms = lambda a: float(np.sqrt(np.nanmean(np.asarray(a, float) ** 2)))  # noqa: E731
        it = float(np.nanmean(pd.to_numeric(g['simple_iters_A'], errors='coerce')))
        if base_it is None:
            base_it = it
        exits = ','.join(sorted(set(str(x) for x in g['exit_A'])))
        rm = pd.to_numeric(g['res_mom'], errors='coerce')
        print(f"{label:10s} {rms(g['err_dP%']):10.2f} {rms(g['err_Q%']):9.2f} "
              f"{it:8.0f} ({it / base_it:4.2f}x) {g['wall_s'].mean():9.1f}s "
              f"{exits:>10s} "
              f"{(np.nanmax(rm) if rm.notna().any() else np.nan):10.2e}")
    print("=" * 96)
    print(f"\nwrote {dest}")


if __name__ == '__main__':
    main()
