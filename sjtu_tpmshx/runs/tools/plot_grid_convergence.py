"""Regenerate the historical grid-convergence figure in reports/figs/.

A1 grid-convergence study, post-A2 convergence criteria (2026-07-06):
all-axis r=2 refinement 16x8x4 -> 32x16x8 -> 64x32x16 -> 128x64x32 on the
Shanghai 16-case set (gamma_df backend, kernel runner, 2nd-order
face-extracted dP). Reads the per-grid CSVs written by

    python -u validation/cases/validate_shanghai_3d_real.py \
        --nx {N} --ny {N//2} --nz {N//4} --suffix _a1_{N}x{N//2}x{N//4}

plus the validation-gate grid CSV (shanghai_3d_baseline.csv, 20x10x3).

Outputs reports/figs/grid-convergence.png (dpi=300, PNG only per repo figure
conventions). The predecessor script was lost to scratch cleanup — this one
is versioned so the figure stays regenerable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]          # sjtu_tpmshx/
REPO = ROOT.parent                                   # repo root
VAL = ROOT / 'validation'
OUT = REPO / 'reports' / 'figs' / 'grid-convergence.png'

GRIDS = [16, 32, 64, 128]                            # streamwise Nx (r=2)
SUFFIX = {N: f"a1_{N}x{N // 2}x{N // 4}" for N in GRIDS}
GATE_CSV = VAL / 'shanghai_3d_baseline.csv'          # 20x10x3 gate grid
GATE_NX = 20

ORANGE = '#E8820C'
BLUE = '#2E75C9'


def _rms(a):
    return float(np.sqrt(np.mean(np.square(np.asarray(a, dtype=float)))))


def _load(N):
    return pd.read_csv(VAL / f'shanghai_3d_baseline_{SUFFIX[N]}.csv')


def _percase_floor(dfs, col_sim, col_exp):
    """Per-case Richardson on the finest available triplet (r=2); RMSRE of
    the extrapolated values vs experiment. Non-contracting cases keep the
    finest-grid value. Returns (rmsre_inf, median_p, n_extrapolable)."""
    d1, d2, d3 = dfs[-3], dfs[-2], dfs[-1]
    errs, ps = [], []
    for i in range(len(d3)):
        q1, q2, q3 = (d[col_sim][i] for d in (d1, d2, d3))
        exp = d3[col_exp][i]
        e12, e23 = q2 - q1, q3 - q2
        if e12 * e23 > 0 and abs(e23) > 1e-12 and abs(e12) > abs(e23):
            p = np.log2(abs(e12) / abs(e23))
            qi = q3 + e23 / (2 ** p - 1)
            ps.append(p)
        else:
            qi = q3
        errs.append((qi - exp) / exp * 100.0)
    med_p = float(np.median(ps)) if ps else float('nan')
    return _rms(errs), med_p, len(ps)


def main():
    dfs, dp_rms, q_rms, grids = [], [], [], []
    for N in GRIDS:
        try:
            d = _load(N)
        except FileNotFoundError:
            print(f"[skip] grid Nx={N}: CSV missing")
            continue
        dfs.append(d); grids.append(N)
        dp_rms.append(_rms(d['err_dP%']))
        q_rms.append(_rms(d['err_Q%']))
        print(f"Nx={N:4d}: RMSRE_dP {dp_rms[-1]:5.2f}%  RMSRE_Q {q_rms[-1]:4.2f}%")

    if len(dfs) < 3:
        sys.exit("need >=3 grids for the Richardson floor")

    dp_floor, dp_p, dp_n = _percase_floor(dfs, 'dP_sim', 'dP_exp')
    q_floor, q_p, _ = _percase_floor(dfs, 'Q_sim', 'Q_exp')
    print(f"per-case Richardson (finest triplet): dP floor {dp_floor:.2f}% "
          f"(median p {dp_p:.2f}, {dp_n}/16 extrapolable) | "
          f"Q floor {q_floor:.2f}% (median p {q_p:.2f})")

    gate = pd.read_csv(GATE_CSV)
    gate_dp, gate_q = _rms(gate['err_dP%']), _rms(gate['err_Q%'])
    print(f"gate grid 20x10x3: dP {gate_dp:.2f}%  Q {gate_q:.2f}%")

    # ── figure (style matches the 2026-06-30 original) ──
    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    ax2 = ax.twinx()

    ax.plot(grids, dp_rms, 'o-', color=ORANGE, lw=3, ms=11, zorder=3,
            label='Δp RMSRE (refinement)')
    ax.axhline(dp_floor, color=ORANGE, ls='--', lw=2.2,
               label=f'Δp per-case Richardson floor ≈ {dp_floor:.0f} %')
    ax2.plot(grids, q_rms, 's-', color=BLUE, lw=3, ms=10, zorder=3,
             label='Q RMSRE (refinement)')
    ax.plot([GATE_NX], [gate_dp], marker='*', ms=26, mfc='none',
            mec=ORANGE, mew=2.5, ls='none', zorder=4,
            label='validation-gate grid (20×10×3)')
    ax2.plot([GATE_NX], [gate_q], marker='*', ms=26, mfc='none',
             mec=BLUE, mew=2.5, ls='none', zorder=4)

    ax.annotate(f'grid-converged ≈ {dp_floor:.0f} %\n(geometry / closure floor)',
                xy=(grids[1], dp_floor), xytext=(grids[1] * 0.86, dp_floor + 0.6),
                color=ORANGE, fontsize=15, fontweight='bold')
    ax.annotate(f'gate grid 20×10×3\nunder-resolved (≈ {gate_dp:.0f} %)',
                xy=(GATE_NX, gate_dp), xytext=(GATE_NX * 0.82, gate_dp - 3.2),
                color=ORANGE, fontsize=13,
                arrowprops=dict(arrowstyle='-', color=ORANGE, lw=1.4))
    ax2.annotate(f'Q clean-converges → ≈ {q_floor:.0f} %',
                 xy=(grids[-1], q_rms[-1]), xytext=(grids[-2] * 0.75, q_rms[-1] + 1.2),
                 color=BLUE, fontsize=15, fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=BLUE, lw=1.6))

    ax.set_xscale('log', base=2)
    ax.set_xticks(grids + [GATE_NX])
    ax.set_xticklabels([str(g) for g in grids] + [str(GATE_NX)])
    ax.set_xlabel('streamwise cells  $N_x$  (∝ 1/h, all axes refined together)',
                  fontsize=15)
    ax.set_ylabel('3D Δp RMSRE  [%]', color=ORANGE, fontsize=16)
    ax2.set_ylabel('3D Q RMSRE  [%]', color=BLUE, fontsize=16)
    ymax = max(dp_floor, max(dp_rms)) + 2.5
    ax.set_ylim(0, ymax); ax2.set_ylim(0, ymax)
    ax.tick_params(axis='y', colors=ORANGE, labelsize=13)
    ax2.tick_params(axis='y', colors=BLUE, labelsize=13)
    ax.tick_params(axis='x', labelsize=13)
    ax.grid(True, ls=':', alpha=0.45)
    ax.set_title('3D grid convergence — Shanghai 16-case '
                 '(gamma_df, A2 normalized-residual criteria)', fontsize=16)

    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc='center right', fontsize=12.5,
              framealpha=0.95)

    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=300)
    print(f"saved {OUT}")


if __name__ == '__main__':
    main()
