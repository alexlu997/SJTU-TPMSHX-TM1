"""Integrity of the frozen Shanghai 16-case evidence, not a current solver test.

The stored 2026-07-13 F2 pipeline table reported RMSRE_dP=4.88% and
RMSRE_Q=2.12%, with relative tolerances 5% and 10% respectively. These values
and thresholds remain historical. The current validation driver uses its
own 12% / 6% gates, convergence status and separately attributed output.

The former opt-in test launched a current module from the package directory
(instead of repository root), causing ModuleNotFoundError, and its output
path could overwrite the frozen table. Removing that invocation does not
claim that today's solver reproduces the historical scores.

The former lumped paper oracle was cross-flow Q_air RMSRE=1.71%, relative
tolerance 10% (2026-04-29). No frozen lumped CSV is tracked here; its old test
executed changing current physics and read a mutable data/ file. That number
is retained as a historical record, not a current executable acceptance.
The complete former test and chronology remain at Git 1f86da1.
"""
from pathlib import Path

import numpy as np
import pandas as pd


def test_shanghai_3d_historical_evidence():
    """Check recorded membership, arithmetic and original score bounds only."""
    path = Path(__file__).resolve().parents[1] / 'validation' / 'shanghai_3d_baseline.csv'
    df = pd.read_csv(path, comment='#')
    assert df['case'].tolist() == list(range(1, 17))
    assert df['pressure_state_valid'].eq(1).all()
    assert df['pressure_clip_hits'].eq(0).all()
    assert df['outer_converged'].all()
    for quantity in ('dP', 'Q'):
        values = df[[f'{quantity}_exp', f'{quantity}_sim', f'err_{quantity}%']].to_numpy()
        assert np.isfinite(values).all()
        np.testing.assert_allclose((values[:, 1] - values[:, 0]) / values[:, 0] * 100,
                                   values[:, 2], rtol=1e-12, atol=1e-12)
    rmsre_dP = float(np.sqrt(np.mean(df['err_dP%'].to_numpy() ** 2)))
    rmsre_Q = float(np.sqrt(np.mean(df['err_Q%'].to_numpy() ** 2)))
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
    BASELINE_DP, BASELINE_Q = 4.88, 2.12
    tol_dp, tol_q = .05, .10
    assert abs(rmsre_dP - BASELINE_DP) < BASELINE_DP * tol_dp
    assert abs(rmsre_Q - BASELINE_Q) < BASELINE_Q * tol_q
