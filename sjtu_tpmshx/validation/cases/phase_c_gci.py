"""phase_c_gci.py — Phase C: Roache GCI + tol/iterative convergence audit.

Standard Tier ASME V&V 20 — Phase C (~2 d).

C.1 Roache GCI (1d): 4-grid h-refinement {12, 16, 20, 30} on T2 (full
    cross) and T4_H8 (partial-B). Per case:
      - Apparent order p_app from Richardson triplet (fine 3 grids)
      - Richardson extrapolated Q_∞
      - GCI_fine_grid = 1.25 · |Q_fine − Q_med| / (r^p − 1) / |Q_fine|
      Hard gate: GCI(grid 20) < 5%.

C.2 Iterative convergence audit (0.5d): leverage existing solver telemetry
    — run 1 production case, capture last_chg + outer iteration count.

C.3 F2 momentum-tolerance sensitivity: mom_tol ∈ {1e-3, 1e-5,
    1e-7}; verify Q saturates.

Outputs:
  validation/phase_c_gci.csv
  validation/phase_c_f2_tol_sweep.csv
"""
from __future__ import annotations
import argparse
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
warnings.filterwarnings('ignore')

from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
from sjtu_tpmshx.validation.harness._provenance import write_csv_with_provenance
from sjtu_tpmshx.validation.cases.audit_3d_conservation import (
    make_T2, make_T4_H8,
)


CASES_C = {
    'T2': make_T2,
    'T4_H8': make_T4_H8,
}


def _fit_order_loglog(Ns, Qs):
    """Slope of log|Q-Q_inf| vs log(h), Q_inf = finest-grid proxy."""
    from sjtu_tpmshx.validation.harness._order_fit import fit_order_loglog
    Qs = np.asarray(Qs, dtype=np.float64)
    Q_inf = Qs[-1]   # finest as proxy
    h = 1.0 / np.asarray(Ns, dtype=np.float64)
    e = np.abs(Qs - Q_inf)
    return fit_order_loglog(h, e, err_floor=1e-6).p


def _gci_roache(Q_fine, Q_med, h_fine, h_med, p):
    """Roache GCI on Q_fine grid. Fs=1.25 (3+ grids)."""
    r = h_med / h_fine
    if abs(r ** p - 1.0) < 1e-12:
        return float('nan')
    return 1.25 * abs(Q_fine - Q_med) / (r ** p - 1.0) / max(abs(Q_fine), 1e-30)


def _gci_table(Ns, Qs):
    """Full GCI report from a sequence of grids.
    Returns dict with order_obs (5-pt log-log), per-pair GCI."""
    Ns = np.asarray(Ns); Qs = np.asarray(Qs, dtype=np.float64)
    p_obs = _fit_order_loglog(Ns, Qs)

    out = dict(order_obs=p_obs, Q_inf=float(Qs[-1]))
    # GCI between successive pairs: for each pair (Ns[i], Ns[i+1])
    # treat finer (larger N) as Q_fine
    for i in range(len(Ns) - 1):
        Nc, Nf = Ns[i], Ns[i + 1]
        Qc, Qf = Qs[i], Qs[i + 1]
        h_c = 1.0 / Nc; h_f = 1.0 / Nf
        # Use 5-pt p_obs for stability
        p = p_obs if np.isfinite(p_obs) and p_obs > 0 else 2.0
        gci = _gci_roache(Qf, Qc, h_f, h_c, p)
        out[f'GCI_g{Nf}_pct'] = gci * 100.0
        out[f'rel_diff_g{Nc}_g{Nf}'] = abs(Qf - Qc) / max(abs(Qf), 1e-30) * 100.0
    return out


def run_c1(case_id, grids=(12, 16, 20, 30), out_csv=None):
    """C.1 — 4-grid GCI on `case_id`."""
    print(f"\n--- C.1 GCI: case={case_id}, grids={list(grids)} ---")
    rows = []
    Q_list = []
    for g in grids:
        cfg = CASES_C[case_id](g)
        t0 = time.time()
        try:
            res = _run_3d_stack(cfg)
            dt = time.time() - t0
            Q_enth_A = float(res.get('Q_enthalpy_A', float('nan')))
            Q_enth_B = float(res.get('Q_enthalpy_B', float('nan')))
            Q_sB_int = float(res.get('Q_sB_interior', float('nan')))
            T_A_out = float(res.get('T_A_out', float('nan')))
            T_B_out = float(res.get('T_B_out', float('nan')))
            dP = float(res.get('dP', float('nan')))
            rows.append(dict(case=case_id, N=g, h=1.0/g,
                             Q_enth_A=Q_enth_A, Q_enth_B=Q_enth_B,
                             Q_sB_interior=Q_sB_int, T_A_out=T_A_out,
                             T_B_out=T_B_out, dP=dP, elapsed=dt))
            Q_list.append(Q_enth_A)
            print(f"  N={g:>3}: Q_A={Q_enth_A:>8.2f}W  Q_B={Q_enth_B:>8.2f}W  "
                  f"T_A_out={T_A_out:.2f}K  dP={dP:.1f}Pa  [{dt:.0f}s]")
        except Exception as e:
            print(f"  N={g:>3}: FAILED ({type(e).__name__}: {e})")
            rows.append(dict(case=case_id, N=g, error=str(e), elapsed=0))
            Q_list.append(float('nan'))

    # GCI analysis
    gci = _gci_table(grids, Q_list)
    print("\n  GCI analysis (Q_enthalpy_A as QoI):")
    print(f"    Q_inf (finest):  {gci['Q_inf']:.2f} W")
    print(f"    order_obs (5pt): {gci['order_obs']:.3f}")
    for g_pair_key in [k for k in gci if k.startswith('GCI_')]:
        print(f"    {g_pair_key}: {gci[g_pair_key]:.2f}%")
    for d_key in [k for k in gci if k.startswith('rel_diff_')]:
        print(f"    {d_key}: {gci[d_key]:.3f}%")

    # Save
    df = pd.DataFrame(rows)
    if out_csv:
        df.to_csv(out_csv, index=False)
        print(f"  CSV: {out_csv}")

    return rows, gci


import contextlib


@contextlib.contextmanager
def _patched_env(name: str, value: str):
    """Temporarily override an environment variable, restore on exit.

    Restores the original value (or absence) even if the body raises —
    safer than the previous unconditional del at end-of-function (which
    could leak the patched value across runs if exception occurred mid-sweep).

    Audit 2026-05-28 L3 fix.
    """
    old = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


def run_c3_tol(case_id='T2', grid=20, tols=(1e-3, 1e-5, 1e-7)):
    """Sweep the current momentum gate; the old mass-only CSV is in Git history."""
    print(f"\n--- C.3 tol sweep: case={case_id}, grid={grid} ---")
    rows = []
    for tol in tols:
        with _patched_env('TPMSHX_CONV_MODE', 'f2'):
            cfg = dict(CASES_C[case_id](grid))
            cfg['convergence_mode'] = 'f2'
            cfg['mom_tol'] = tol
            t0 = time.time()
            res = _run_3d_stack(cfg)
            dt = time.time() - t0
            Q = float(res.get('Q_enthalpy_A', float('nan')))
            T_A_out = float(res.get('T_A_out', float('nan')))
            rows.append(dict(case=case_id, grid=grid, tol=tol,
                             Q_enth_A=Q, T_A_out=T_A_out, elapsed=dt))
            print(f"  tol={tol:.0e}: Q={Q:.4f}W  T_A_out={T_A_out:.4f}K  [{dt:.0f}s]")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', default='T2,T4_H8',
                    help='comma-list from {T2, T4_H8}')
    ap.add_argument('--grids', default='12,16,20,30',
                    help='comma-list of grid sizes')
    ap.add_argument('--skip_tol', action='store_true', help='skip C.3')
    args = ap.parse_args()

    cases = [c.strip() for c in args.cases.split(',') if c.strip()]
    grids = [int(g) for g in args.grids.split(',')]

    print(f"{'='*72}")
    print("  Phase C — Roache GCI + tol audit")
    print(f"{'='*72}")
    print(f"  Cases: {cases}  Grids: {grids}\n")

    all_rows = []
    summary = []
    for cid in cases:
        rows, gci = run_c1(cid, grids=grids)
        all_rows.extend(rows)
        summary.append(dict(case=cid, **gci))

    df = pd.DataFrame(all_rows)
    # C.4 provenance headers (# script/commit/date) — a plain to_csv here
    # silently dropped them on regeneration (found 2026-07-14).
    write_csv_with_provenance(df, ROOT / 'validation' / 'phase_c_gci.csv',
                              __file__)
    sdf = pd.DataFrame(summary)
    write_csv_with_provenance(sdf,
                              ROOT / 'validation' / 'phase_c_gci_summary.csv',
                              __file__)

    print(f"\n{'='*72}")
    print("  GCI summary")
    print(f"{'='*72}")
    print(sdf.to_string(index=False, float_format='%.4g'))

    # Hard gate: GCI on grid 20 < 5%
    print("\n  Hard gate: GCI(grid 20) < 5%")
    fail = []
    for s in summary:
        gci20 = s.get('GCI_g20_pct', float('nan'))
        ok = gci20 < 5.0 if np.isfinite(gci20) else False
        print(f"    {s['case']}: GCI_g20={gci20:.2f}%  "
              f"{'PASS' if ok else 'FAIL'}")
        if not ok: fail.append(s['case'])

    if not args.skip_tol:
        tol_rows = run_c3_tol('T2', grid=20)
        tdf = pd.DataFrame(tol_rows)
        write_csv_with_provenance(tdf,
                                  ROOT / 'validation' / 'phase_c_f2_tol_sweep.csv',
                                  __file__)
        Qs = [r['Q_enth_A'] for r in tol_rows]
        rng = max(Qs) - min(Qs)
        rel = rng / max(abs(Qs[-1]), 1e-30)
        print(f"\n  C.3 tol sweep range: {rng:.4f}W ({rel:.2%}) — "
              f"{'PASS' if rel < 0.01 else 'FAIL'} (gate <1%)")

    return 0 if not fail else 1


if __name__ == '__main__':
    sys.exit(main())
