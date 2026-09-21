"""Shanghai 16-case validation regression tests (opt-in, slow).

Two historical validation comparisons remain: the 3D driver and the
cross-flow lumped model. The retired 2D test placeholder is indexed in
``docs/history/retired-tools.md``. Historical reference numbers below retain
their original version and thresholds; they are not current accuracy claims.

These tests are SLOW (~6 min each) and OPT-IN. Default pytest run skips
them. To enable:

    # Shell (env var)
    TPMSHX_RUN_SHANGHAI_REGRESSION=1 python -m pytest sjtu_tpmshx/tests/test_shanghai_regression.py -v

    # PowerShell
    $env:TPMSHX_RUN_SHANGHAI_REGRESSION = '1'
    python -m pytest sjtu_tpmshx/tests/test_shanghai_regression.py -v

Baseline values are pinned per the audit report (vault/reports/engineering/
2026-05-28-validation-correctness-audit-CN.html §H3). If a deliberate
solver change shifts numbers, record a separately attributable comparison.
Do not overwrite these historical references to make the checks pass.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_DATA_ROOT = _ROOT.parent / 'data'

# Skip all tests in this module unless explicitly opted in.
_RUN_REG = os.environ.get(
    'TPMSHX_RUN_SHANGHAI_REGRESSION', '0').lower() in ('1', 'true', 'yes')

pytestmark = pytest.mark.skipif(
    not _RUN_REG,
    reason=("Slow Shanghai regression — set "
            "TPMSHX_RUN_SHANGHAI_REGRESSION=1 to enable"),
)


# ── Helpers ──────────────────────────────────────────────────────────

def _run_subprocess(module: str, *args, timeout: int = 1200) -> tuple:
    """Run module via subprocess, return (returncode, stdout, stderr)."""
    cmd = [sys.executable, '-u', '-m', module, *args]
    proc = subprocess.run(
        cmd, cwd=str(_ROOT), capture_output=True, text=True,
        timeout=timeout, encoding='utf-8', errors='replace',
    )
    return proc.returncode, proc.stdout, proc.stderr


def _rmsre_from_pct(arr) -> float:
    """RMSRE from a pre-computed percent-error array (sqrt(mean(e^2)))."""
    arr = np.asarray(arr, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    return float(np.sqrt(np.mean(arr ** 2)))


# ── 2. Production 3D Shanghai validation ─────────────────────────────

def test_shanghai_3d_baseline():
    """Production 3D Shanghai validation (Nz=3 default grid).

    Baselines (2026-05-29, post G-fix + RBF cubic/smoothing=0.1):
      RMSRE_dP = 17.32%
      RMSRE_Q  =  3.74%

    History:
      * pre G-fix (col 48 G, thin_plate s=0):   dP 97.11% / Q 2.51%
      * post G-fix (cols 12·13, thin_plate s=0): dP 29.58% / Q 3.06%
      * **post G-fix + cubic s=0.1**:           **dP 17.32% / Q 3.74%**
      * pre-incident memory baseline (Nz=3):    dP 41.19% / Q 2.85%
      * doc method spec 2D (lost xlsx):         dP 10.07%

    Two stacked surrogate fixes:

    1. **G convention** (commit f6146db): v3.1 xlsx col 48 G carries
       interstitial-throat mass flux (~20×ρv) that does not match the
       method spec
       (vault/reports/_archive/methodology/2026-04-16-surrogate-v3-dP-Q-method-CN.md
       §1.2-1.3). ``_build`` now reads ``G = col 12 (ρ) × col 13 (v)``.

    2. **RBF kernel + smoothing**: switched from thin_plate_spline,
       smoothing=0 (exact interp, prone to extrapolation wiggle) to
       ``cubic`` kernel with ``smoothing=0.1`` (Tikhonov reg). Sweep
       found smoothing < 0.01 collapses 6 high-Re cases into
       pressure-INVALID (c_F extrapolated too aggressive → P_out²≤0).
       0.1 is the safest production sweet spot — 12 pp better than
       thin_plate baseline, 16/16 valid, 6× margin to choke. See
       ``vault/reports/method/2026-05-29-surrogate-rbf-cubic-smoothing-CN.md``.

    Q tolerance ±10 % relative. dP tolerance ±5 %.

    Note: this test uses Nz=3 default for speed (each case ~25 s vs
    ~3 min on Nz=10). If you want Nz=10 in CI, pass ``--nz 10`` and
    update baselines.
    """
    import pandas as pd
    rc, stdout, stderr = _run_subprocess(
        'sjtu_tpmshx.validation.cases.validate_shanghai_3d_real',
        '--suffix', '_pytest_h3',
        timeout=1500)
    assert rc == 0, (
        f"validate_shanghai_3d_real failed (rc={rc}):\n"
        f"STDERR:\n{stderr[-2000:]}")

    csv_path = _ROOT / 'validation' / 'shanghai_3d_baseline_pytest_h3.csv'
    assert csv_path.exists(), f"output CSV not found: {csv_path}"
    df = pd.read_csv(csv_path)

    rmsre_dP = _rmsre_from_pct(df['err_dP%'])
    rmsre_Q = _rmsre_from_pct(df['err_Q%'])

    # 2026-06-04 — MASS-FLUX inlet BC fix. The Shanghai experiment fixes the
    # air MASS FLOW (m_air; u_A = m_air/(ρ_A·A_FLOW) is derived). The legacy
    # velocity-inlet held v constant but let ρ_inlet float, so at high-dP
    # compressible cases it injected the WRONG (systematically LOW) mass flow
    # (case 16: 0.84× the target) → systematically under-predicted dP. The
    # mass-flux inlet (hold ρ·v = m_air, SIMPLESolver3D.massflux_inlet, default
    # True for ideal_gas) injects the experimentally-correct mass flow → dP
    # RMSRE 17.43%→7.19%, Q 3.74%→3.22%. The residual is the true closure +
    # geometry floor (incl. the low-dP case-1 +16% regime). Verified: injected
    # ∑ρv·A is locked at the m_air ratio across all 16 cases (was drifting).
    # See vault 2026-06-04-reverse-dir-convention-fix-plan-CN.md §6 and
    # [[feedback_dp_gap_attribution]] (the "inlet convention" contributor is
    # now the identified+fixed part of the gap). Conservative kernel, Nz=3.
    # 2026-06-12 — DF surrogate default switched rbf -> gamma_df (user
    # decision; see df_surrogate/gamma_df.py). Full-chain Nz=3 measured:
    # dP 9.82% / Q 3.20% (rbf: 7.19% / 3.22%; the +2.6pp is entirely the
    # smooth-trend K — cF is gate-identical 534.8 by construction).
    # Traded for sane extrapolation outside the gate geometry (D7-class:
    # 454 vs rbf 745, end-to-end 67.4%). Old numbers reproducible with
    # TPMSHX_DF_METHOD=rbf.
    # 2026-06-30 — dP now extracted with the 2nd-order face-extrapolation
    # (SIMPLESolver3D.extract_dP_face_extrap): the cell-centre method sampled P
    # ~h/2 inside the inlet/outlet faces (O(h) offset → ~1st-order, and it
    # systematically UNDER-predicted dP, inflating the gap vs experiment).
    # Extrapolating P to the faces recovers the true model dP, which is closer
    # to experiment: Nz=3 RMSRE_dP 9.82% → 5.05% (Q unchanged — Q is a duty
    # integral, independent of the dP reduction). Verified 2nd-order in the
    # streamwise direction (tests/test_dp_face_extrap_order.py).
    # 2026-06-30 (#2) — gamma_df K re-baselined: SmoothDF Dh² trend → CFD-refit
    # surface (per-geometry water-CFD K, 2-stage extraction). c_F unchanged; the
    # cleaner/smaller K lifts the Darcy term, so Nz=3 RMSRE_dP 5.05% → 5.28%
    # (Q 3.20% → 3.21%). See gamma_df.py K UPDATE + openspec/df-coeffs-cfd-refit.
    # 2026-07-12 — GATE RUNNER SWITCHED: frozen-B kernel → production Pipeline3D
    # (the water side is now SOLVED, not prescribed). RMSRE_dP 5.28% → 4.93%,
    # RMSRE_Q 3.21% → 2.12%. Three reasons, fully written up in the
    # validate_shanghai_3d_real module docstring:
    #   (1) more accurate — Q error cut 34%, and 2.12% finally beats the 2D
    #       aligned kernel gate's Q RMSRE (2.51%; the ε-NTU LUMPED baseline is
    #       a different number, 1.71% — the two were conflated in early notes);
    #   (2) the frozen-B runner was fed part of the answer — Tb_prescribed is
    #       built from the MEASURED water outlet temperature, which already
    #       encodes the true duty through the water-side enthalpy balance
    #       (243.8 W vs the experimental air-side 248.4 W). A method given LESS
    #       information produces a BETTER answer;
    #   (3) the old gate validated a code path production never runs — the GUI,
    #       the optimizer and the server batches all drive Pipeline3D.
    # All 16 cases converge the outer coupling in 3 iterations, none truncated.
    # (The `A@init[stall]` on the high-u cases is a benign cold-start artifact;
    # every warm re-solve converges. See the module docstring.)
    # The old frozen-B numbers stay reproducible with `--runner kernel`.
    # 2026-07-13 — RE-BASELINED for the F2 pipeline default (ledger C6/C7):
    # the gate script inherits convergence_mode='f2' (RMSRE_dP 4.93% → 4.88%,
    # Q unchanged at 2.12%). The 4.93 value was still passing only by eating
    # half the ±5% drift budget — pin the number the default actually
    # produces, keep the budget for real drift.
    BASELINE_DP = 4.88
    BASELINE_Q = 2.12
    tol_dp = 0.05
    tol_q = 0.10
    assert abs(rmsre_dP - BASELINE_DP) < BASELINE_DP * tol_dp, (
        f"3D RMSRE_dP drift: {rmsre_dP:.2f}% vs baseline "
        f"{BASELINE_DP}% (tol ±{tol_dp*100:.0f}%)")
    assert abs(rmsre_Q - BASELINE_Q) < BASELINE_Q * tol_q, (
        f"3D RMSRE_Q drift: {rmsre_Q:.2f}% vs baseline "
        f"{BASELINE_Q}% (tol ±{tol_q*100:.0f}%)")


# ── 3. Paper baseline ε-NTU lumped ───────────────────────────────────

def test_shanghai_lumped_paper():
    """Paper baseline ε-NTU lumped Q_air prediction (cross-flow primary).

    Baseline (memory project_lumped_dual_nu_baseline, 2026-04-29):
      Q_air RMSRE cross-flow ≈ 1.71%

    Cross-flow is the primary Shanghai topology (air ⊥ water). The
    `err_air_xf` CSV column is the matching error per case.

    Tolerance: ±10% relative on RMSRE.
    """
    import pandas as pd
    rc, stdout, stderr = _run_subprocess(
        'sjtu_tpmshx.validation.cases.validate_shanghai_lumped_dual_nu', timeout=600)
    assert rc == 0, (
        f"validate_shanghai_lumped_dual_nu failed (rc={rc}):\n"
        f"STDERR:\n{stderr[-2000:]}")

    csv_path = _DATA_ROOT / 'shanghai_lumped_dual_nu.csv'
    assert csv_path.exists(), f"output CSV not found: {csv_path}"
    df = pd.read_csv(csv_path)

    assert 'err_air_xf' in df.columns, (
        f"Expected 'err_air_xf' column missing. Got: {list(df.columns)}")
    rmsre = _rmsre_from_pct(df['err_air_xf'])

    BASELINE = 1.71
    tol = 0.10
    assert abs(rmsre - BASELINE) < BASELINE * tol, (
        f"Lumped Q_air RMSRE drift: {rmsre:.2f}% vs baseline "
        f"{BASELINE}% (tol ±{tol*100:.0f}%)")
