"""MMS Phase B4 — observed order of the CONSERVATIVE face-shared HO kernel.

B-plan B4 certifies that the strict-conservation kernel branch
(cfg['conservative_ltne']=True → face-shared SOU deferred correction with the
(F_e-F_w) telescoping a_P) retains 2nd-order accuracy, i.e. conservation is
NOT bought at the cost of order. This drives run_mms(..., conservative=1) on
an h-refinement sweep and least-squares-fits the observed order p_obs from the
relative-L2 errors.

Note: for the MMS verification setup (uniform velocity + uniform material) the
per-cell mass divergence is identically zero and the face-shared SOU increment
coincides with the cell-local _sou_corr_* one, so conservative=1 reproduces the
already-V&V'd cell-local SOU path (Phase A.3) bit-for-bit — the order carries
over. The conservation gain itself lives in NON-uniform/reverse flow and is
certified separately by tests/test_conservation_3d_energy.py (T1-T6).

Run:  python -m sjtu_tpmshx.validation.cases.mms_phase_b4_order
Writes validation/mms_phase_b4_orders.csv (read by tests/test_mms_b4_conservative_order.py).
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

from sjtu_tpmshx.validation.cases.mms_3d_air_air import run_mms
from sjtu_tpmshx.validation.harness._order_fit import fit_order_loglog
from sjtu_tpmshx.validation.harness import _provenance as _prov

GRIDS = [10, 16, 24, 32]
OUT_CSV = ROOT / 'validation' / 'mms_phase_b4_orders.csv'


def main():
    from sjtu_tpmshx.validation.harness._mms_driver import run_grid_sequence
    rows_raw = run_grid_sequence(
        GRIDS,
        lambda N: run_mms('3d', Nx=N, Ny=N, Nz=N, max_outer=8000, inner=50,
                          tol=1e-10, alpha_f=0.7, alpha_s=1.0, verbose=False,
                          conservative=1),
        lambda N, r, dt: dict(h=1.0 / N, L2_A=r['L2_A'],
                              L2_B=r['L2_B'], L2_s=r['L2_s']),
        on_grid=lambda N, r, row, dt: print(
            f"N={N:>3}  L2_A={r['L2_A']:.4e}  L2_B={r['L2_B']:.4e}  "
            f"L2_s={r['L2_s']:.4e}"))
    hs = [row['h'] for row in rows_raw]
    errs = {m: [row[m] for row in rows_raw] for m in ('L2_A', 'L2_B', 'L2_s')}
    rows = []
    for m in ('L2_A', 'L2_B', 'L2_s'):
        _fit = fit_order_loglog(hs, errs[m])
        p, r2 = _fit.p, _fit.r2
        rows.append((m, p, r2, errs[m][-1]))
        print(f"  {m}: p_obs={p:.3f}  R2={r2:.5f}  val_gfine={errs[m][-1]:.3e}")
    # encoding='utf-8' is load-bearing: without it Windows writes the em-dash
    # below in the console codepage (GBK) and the utf-8 reader in
    # tests/test_mms_b4_conservative_order.py dies with UnicodeDecodeError
    # (found 2026-07-14). Provenance trio per the C.4 convention.
    with open(OUT_CSV, 'w', encoding='utf-8', newline='') as f:
        f.write("# MMS Phase B4 — conservative HO path observed order\n")
        f.write(f"# grids={GRIDS}  case=3d  conservative=1\n")
        f.write(f"# script: {_prov._normalise_script(__file__)}\n")
        f.write(f"# commit: {_prov._git_sha() or '<no-git>'}\n")
        f.write(f"# date:   {_prov._iso_now()}\n")
        f.write("case,metric,p_obs,R2,val_gfine\n")
        for m, p, r2, v in rows:
            f.write(f"3d,{m},{p:.4f},{r2:.5f},{v:.4e}\n")
    print(f"wrote {OUT_CSV}")


if __name__ == '__main__':
    main()
