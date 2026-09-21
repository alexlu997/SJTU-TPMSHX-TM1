"""mms_phase_a4_boundary.py — Phase A.4: Boundary-stencil MMS verification.

Standard Tier ASME V&V 20 — Phase A.4. Boundary-aware decomposition of
the MMS error: separates L2/Linf per region (inlet, outlet, lateral walls,
interior) to verify each BC stencil's discretization consistency.

Background:
- Phase A.3 showed L2 ~ 2.1 order globally with manufactured cosines that
  trivially satisfy Neumann zero-grad at all walls (sin(pi)=0).
- A.4 extracts per-region error so we can confirm:
  * Inlet (Dirichlet pin)  → L2 ~ machine-eps (cell-center exactly pinned)
  * Outlet (Neumann via copy-neighbor) → L2 ~ 1st-order (one-sided stencil)
  * Lateral walls (adiabatic via same-cell fallback) → L2 matches interior
  * Interior → ~2nd-order (matches A.3 global)

The Phase A.3 driver returns full Ta/Tb/Ts arrays; this module runs the
same MMS-3D problem at 3 grids (20, 30, 40) and slices the result into
boundary-stratified L2/Linf metrics.

Hard gates:
- Inlet L2 < 1e-12 (Dirichlet exactness, dimensionless)
- Outlet L2 order_obs >= 0.8 (one-sided 1st-order stencil; allow modest)
- Lateral L2 order_obs >= 1.5 (cosine BC compatible with adiabatic)
- Interior L2 order_obs >= 1.8 (matches global A.3)
- All L2 (g30) < 1.0%

Each run writes mms_phase_a4_boundary.csv and mms_phase_a4_orders.csv in a
new .cache/validation/mms_phase_a4-*/ directory (or --out-dir). Explicit file
paths use the working directory; the recorded validation tables are read-only.
"""
from __future__ import annotations
import argparse
import sys
import warnings

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
warnings.filterwarnings('ignore')

from sjtu_tpmshx.validation.cases.mms_3d_air_air import run_mms, L_DOM
from sjtu_tpmshx.validation.harness._provenance import (
    write_csv_with_provenance, output_directory, output_path,
)
from sjtu_tpmshx.validation.harness._order_fit import fit_order_loglog
from sjtu_tpmshx.validation.harness._mms_driver import run_grid_sequence

_SCRIPT_REL = 'sjtu_tpmshx/validation/cases/mms_phase_a4_boundary.py'


def _region_masks(Nx, Ny, Nz):
    """Build boolean masks for boundary regions and interior."""
    inlet_A   = np.zeros((Nx, Ny, Nz), dtype=bool); inlet_A[0,  :, :]    = True
    outlet_A  = np.zeros((Nx, Ny, Nz), dtype=bool); outlet_A[-1, :, :]   = True
    inlet_B   = np.zeros((Nx, Ny, Nz), dtype=bool); inlet_B[:, 0,  :]    = True
    outlet_B  = np.zeros((Nx, Ny, Nz), dtype=bool); outlet_B[:, -1, :]   = True
    # Lateral walls (z = 0, Nz-1; y for A also lateral; x for B also lateral)
    lat_z     = np.zeros((Nx, Ny, Nz), dtype=bool)
    lat_z[:, :, 0]  = True
    lat_z[:, :, -1] = True
    # Interior — exclude all boundaries (any face)
    interior = np.ones((Nx, Ny, Nz), dtype=bool)
    interior[0,  :, :] = False
    interior[-1, :, :] = False
    interior[:, 0,  :] = False
    interior[:, -1, :] = False
    interior[:, :, 0]  = False
    interior[:, :, -1] = False
    return dict(
        inlet_A=inlet_A, outlet_A=outlet_A,
        inlet_B=inlet_B, outlet_B=outlet_B,
        lat_z=lat_z, interior=interior,
    )


def _l2_linf_masked(num, exact, mask):
    """rel L2 + Linf over a masked region (or full, if mask all-True)."""
    if mask.sum() == 0:
        return float('nan'), float('nan')
    diff = (num - exact)[mask]
    ref  = exact[mask]
    l2 = float(np.sqrt(np.mean(diff**2)) / (np.sqrt(np.mean(ref**2)) + 1e-30))
    linf = float(np.max(np.abs(diff)))
    return l2, linf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', default='3d', choices=['1d', '2d', '3d'])
    ap.add_argument('--grids', default='20,30,40')
    ap.add_argument('--max_outer', type=int, default=2500)
    ap.add_argument('--inner', type=int, default=100)
    ap.add_argument('--alpha_f', type=float, default=0.7)
    ap.add_argument('--out-dir', help='Output directory (default: new .cache/validation/mms_phase_a4-*/).')
    ap.add_argument('--out_csv', help='Raw CSV path; relative paths use the working directory.')
    ap.add_argument('--orders_csv', help='Order CSV path; reference tables cannot be overwritten.')
    args = ap.parse_args()
    try:
        for path in (args.out_csv, args.orders_csv):
            if path is not None:
                output_path(path)
        out_dir = output_directory('mms_phase_a4', args.out_dir)
        args.out_csv = output_path(args.out_csv or out_dir / 'mms_phase_a4_boundary.csv')
        args.orders_csv = output_path(args.orders_csv or out_dir / 'mms_phase_a4_orders.csv')
    except ValueError as exc:
        ap.error(str(exc))
    print(f'Output directory: {out_dir}')

    grids = [int(g) for g in args.grids.split(',')]

    print(f"{'='*72}")
    print("  MMS Phase A.4 — boundary-stratified order verification")
    print(f"{'='*72}")
    print(f"  Case: MMS-{args.case}  Grids: {grids}")
    print("  Regions: inlet_A, outlet_A, inlet_B, outlet_B, lat_z, interior\n")

    def _row(g, r, dt):
        masks = _region_masks(g, g, g)
        result = dict(N=g, h=L_DOM/g, elapsed=dt,
                      outer_iters=r['outer_iters'], last_chg=r['last_chg'])
        for region, mask in masks.items():
            for phase, num, exact in [
                ('A', r['Ta_num'], r['Ta_exact']),
                ('B', r['Tb_num'], r['Tb_exact']),
                ('s', r['Ts_num'], r['Ts_exact'])]:
                l2, linf = _l2_linf_masked(num, exact, mask)
                result[f'L2_{phase}_{region}']   = l2
                result[f'Linf_{phase}_{region}'] = linf
        return result

    _REGIONS = ['inlet_A', 'outlet_A', 'inlet_B', 'outlet_B',
                'lat_z', 'interior']   # == _region_masks key order

    def _progress(g, r, result, dt):
        print(f"  N={g:>3d}  [{dt:.0f}s]")
        for region in _REGIONS:
            print(f"    {region:<10}  "
                  f"L2_A={result[f'L2_A_{region}']:.3e}  "
                  f"L2_B={result[f'L2_B_{region}']:.3e}  "
                  f"L2_s={result[f'L2_s_{region}']:.3e}  "
                  f"Linf_A={result[f'Linf_A_{region}']:.3e}")

    rows = run_grid_sequence(
        grids,
        lambda g: run_mms(args.case, Nx=g, Ny=g, Nz=g,
                          max_outer=args.max_outer, inner=args.inner,
                          alpha_f=args.alpha_f, verbose=False),
        _row, on_grid=_progress)

    df = pd.DataFrame(rows)
    out_csv = args.out_csv
    write_csv_with_provenance(df, out_csv, _SCRIPT_REL)
    print(f"\nRaw written: {out_csv}")

    # Order fit per region per phase (L2)
    print(f"\n{'='*72}")
    print("  Per-region observed order (L2, log-log fit, full grid set)")
    print(f"{'='*72}")
    order_rows = []
    print(f"  {'region':<11} {'phase':<6} {'p_obs':>8} {'R^2':>7} "
          f"{'L2(g_max)':>11}")
    for region in ['inlet_A', 'outlet_A', 'inlet_B', 'outlet_B',
                   'lat_z', 'interior']:
        for phase in ['A', 'B', 's']:
            col = f'L2_{phase}_{region}'
            err = df[col].values
            _fit = fit_order_loglog(df['h'].values, err)
            p, r2 = _fit.p, _fit.r2
            l2_max = err[-1]
            order_rows.append(dict(
                region=region, phase=phase, p_obs=p, R2=r2, L2_g_max=l2_max))
            print(f"  {region:<11} {phase:<6} {p:>7.3f} {r2:>7.4f} "
                  f"{l2_max:>11.3e}")
    order_df = pd.DataFrame(order_rows)
    orders_csv = args.orders_csv
    write_csv_with_provenance(order_df, orders_csv, _SCRIPT_REL)
    print(f"\nOrders written: {orders_csv}")

    # Hard gates
    print(f"\n{'='*72}")
    print("  Hard gates")
    print(f"{'='*72}")
    fail = []

    # Inlet machine-eps check (use last grid)
    last = df.iloc[-1]
    for ph in ['A', 'B']:
        col = f'L2_{ph}_inlet_{ph}'
        v = float(last[col])
        ok = (v < 1e-12)
        print(f"  inlet_{ph} L2_{ph} (g={int(last['N'])}): {v:.3e}  "
              f"{'PASS' if ok else 'FAIL'}  (gate <1e-12)")
        if not ok:
            fail.append(f"inlet_{ph}_machine_eps")

    # Outlet order >= 0.8
    for ph in ['A', 'B']:
        sub = order_df[(order_df['region'] == f'outlet_{ph}') &
                       (order_df['phase'] == ph)]
        if len(sub):
            p = sub['p_obs'].iloc[0]
            ok = (p >= 0.8)
            print(f"  outlet_{ph} L2_{ph} order_obs: {p:.3f}  "
                  f"{'PASS' if ok else 'FAIL'}  (gate >=0.8)")
            if not ok:
                fail.append(f"outlet_{ph}_order")

    # Lateral wall L2_s order >= 1.5
    sub = order_df[(order_df['region'] == 'lat_z') &
                   (order_df['phase'] == 's')]
    if len(sub):
        p = sub['p_obs'].iloc[0]
        ok = (p >= 1.5)
        print(f"  lat_z L2_s order_obs: {p:.3f}  "
              f"{'PASS' if ok else 'FAIL'}  (gate >=1.5)")
        if not ok:
            fail.append("lat_z_order")

    # Interior order >= 1.8 each phase
    for ph in ['A', 'B', 's']:
        sub = order_df[(order_df['region'] == 'interior') &
                       (order_df['phase'] == ph)]
        if len(sub):
            p = sub['p_obs'].iloc[0]
            l2max = sub['L2_g_max'].iloc[0]
            ok_o = (p >= 1.8)
            ok_l = (l2max < 0.010)
            print(f"  interior L2_{ph} order_obs: {p:.3f}  "
                  f"L2_max: {l2max:.3e}  "
                  f"{'PASS' if (ok_o and ok_l) else 'FAIL'}  "
                  f"(gate order>=1.8, L2<1%)")
            if not (ok_o and ok_l):
                fail.append(f"interior_{ph}")

    print(f"\n  {'PASS' if not fail else 'FAILED'}: {fail}\n")
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
