"""
test_evaluator_sanity.py — End-to-end sanity for the continuous-field evaluator.

Marked ``slow`` because each test invokes a full SIMPLE × 2 + LTNE solve
(~5–10 s on default hardware). Run explicitly via::

    pytest tests/test_evaluator_sanity.py -v -m slow

or unconditionally::

    pytest tests/test_evaluator_sanity.py -v
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

warnings.filterwarnings('ignore', category=UserWarning)

from sjtu_tpmshx.models.continuous_field import (
    encode_decision_vector,
    uniform_field,
)
from sjtu_tpmshx.optimization.evaluator import evaluate_design


# Lighter solver settings so the test suite stays fast (~10 s total)
_FAST_CFG = {
    'max_iter_simple': 800,
    'tol_simple':      1e-3,
    'max_iter_energy': 1500,
    'tol_energy':      0.5,
    'n_rho_loops':     1,
}


pytestmark = pytest.mark.slow


# ─── Basic invariants on a single eval ──────────────────────────────


def test_uniform_field_returns_positive_q_and_dp():
    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0,
                        L_domain=0.10, H_domain=0.05)
    Q_neg, dP, mass = evaluate_design(x=None, cfg=_FAST_CFG, fc=fc)
    Q = -Q_neg
    # T_inA=350 > T_inB=300 → fluid A gives heat to fluid B → Q > 0
    assert Q > 0.0, f"expected Q > 0, got {Q}"
    assert dP > 0.0, f"expected dP > 0, got {dP}"
    assert mass > 0.0, f"expected mass > 0, got {mass}"
    # Sanity ranges (loose but catch obvious blowups)
    assert 1e2 < Q < 1e6, f"Q={Q} W/m outside 1e2..1e6"
    assert 1e2 < dP < 1e6, f"dP={dP} Pa outside 1e2..1e6"


def test_no_penalty_on_uniform_field():
    """Uniform L,t → manufacturability_penalty == 0 → dP unchanged by penalty."""
    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0,
                        L_domain=0.10, H_domain=0.05)
    cfg_with    = {**_FAST_CFG, 'penalty_enabled': True}
    cfg_without = {**_FAST_CFG, 'penalty_enabled': False}
    Q1, dP1, _ = evaluate_design(x=None, cfg=cfg_with, fc=fc)
    Q2, dP2, _ = evaluate_design(x=None, cfg=cfg_without, fc=fc)
    assert abs(Q1 - Q2) < 1e-6
    assert abs(dP1 - dP2) < 1e-6


# ─── Field actually drives the result ───────────────────────────────


def test_thicker_walls_increase_dP():
    """t=0.5 mm should produce larger dP than t=0.3 mm at the same L."""
    fc_thin  = uniform_field(6.0, 0.3, 'Diamond', 17.0, 0.10, 0.05)
    fc_thick = uniform_field(6.0, 0.5, 'Diamond', 17.0, 0.10, 0.05)
    _, dP_thin,  _ = evaluate_design(x=None, cfg=_FAST_CFG, fc=fc_thin)
    _, dP_thick, _ = evaluate_design(x=None, cfg=_FAST_CFG, fc=fc_thick)
    assert dP_thick > dP_thin, \
        f"thicker walls should raise dP: thin={dP_thin}, thick={dP_thick}"


def test_field_geometry_drives_outputs():
    """Different geometries should produce materially different (Q, dP).

    No sign assumption on Q vs t — at fixed *superficial* inlet velocity, the
    inlet open-area shrinks with thicker walls, so the actual mass flow and
    therefore Q can drop even as h_v rises locally. This test only asserts
    that the evaluator is sensitive to the input geometry (≥ 5 % delta on at
    least one objective) so we catch silent decoupling regressions.
    """
    fc_thin  = uniform_field(6.0, 0.3, 'Diamond', 17.0, 0.10, 0.05)
    fc_thick = uniform_field(6.0, 0.5, 'Diamond', 17.0, 0.10, 0.05)
    Q_thin_neg,  dP_thin,  _ = evaluate_design(x=None, cfg=_FAST_CFG, fc=fc_thin)
    Q_thick_neg, dP_thick, _ = evaluate_design(x=None, cfg=_FAST_CFG, fc=fc_thick)
    rel_dQ  = abs(Q_thick_neg - Q_thin_neg) / max(abs(Q_thin_neg),  1.0)
    rel_dP  = abs(dP_thick    - dP_thin)    / max(abs(dP_thin),     1.0)
    assert max(rel_dQ, rel_dP) > 0.05, \
        f"evaluator insensitive to t: rel_dQ={rel_dQ:.4f}, rel_dP={rel_dP:.4f}"


# ─── Decision-vector path matches direct fc path ────────────────────


def test_decision_vector_path_matches_direct_fc():
    """Encoding a uniform field to a 16-D decision vector and routing through
    evaluate_design(x=...) must reproduce the direct-fc result bit-for-bit
    (same SIMPLE seed and field)."""
    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0, 0.10, 0.05)
    x = encode_decision_vector(fc.L_ctrl, fc.t_ctrl, symmetric_y=True)

    cfg = {**_FAST_CFG,
           'tpms_type':  'Diamond',
           'k_s':         17.0,
           'L_domain':    0.10,
           'H_domain':    0.05,
           'n_ctrl_x':    4, 'n_ctrl_y': 4, 'symmetric_y': True}

    Q1_neg, dP1, m1 = evaluate_design(x=None, cfg=cfg, fc=fc)
    Q2_neg, dP2, m2 = evaluate_design(x=x,    cfg=cfg, fc=None)

    assert abs(Q1_neg - Q2_neg) < 1e-6, \
        f"Q differs: direct={Q1_neg}, via x={Q2_neg}"
    assert abs(dP1 - dP2) < 1e-6, \
        f"dP differs: direct={dP1}, via x={dP2}"
    assert abs(m1 - m2) < 1e-6


# ─── v2 hardening: dp_cap + log-dP + HV early stop ──────────────────


def test_dp_cap_caps_extreme_dp():
    """When dp_cap is set below the natural dP for the design, the evaluator
    must clamp the returned dP to the cap (rejected-design tag).

    Decoupled from SIMPLE convergence: forces ``reject_unconverged=False`` and
    sets ``dp_cap_pa`` to an absurdly low 100 Pa so the converged dP almost
    certainly exceeds it. Validates the post-solve guard, not the
    non-convergence branch.
    """
    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0, 0.10, 0.05)
    cfg = {**_FAST_CFG,
           'dp_cap_pa':           100.0,
           'reject_unconverged':  False}
    Q_neg, dP, _mass = evaluate_design(x=None, cfg=cfg, fc=fc)
    assert dP == 100.0, f"expected dP clamped to 100, got {dP}"
    assert abs(Q_neg) < 1.0, f"rejected design should report Q≈0, got Q_neg={Q_neg}"


def test_dp_cap_passthrough_when_below():
    """When dp_cap is comfortably above the natural dP, the evaluator must
    return the unmodified dP. Sanity that the cap doesn't fire on healthy
    designs."""
    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0, 0.10, 0.05)
    cfg_capped   = {**_FAST_CFG, 'dp_cap_pa': 1.0e7}   # 10 MPa cap (way above)
    cfg_uncapped = {**_FAST_CFG, 'dp_cap_pa': 1.0e9}
    _, dP_capped,   _ = evaluate_design(x=None, cfg=cfg_capped,   fc=fc)
    _, dP_uncapped, _ = evaluate_design(x=None, cfg=cfg_uncapped, fc=fc)
    assert abs(dP_capped - dP_uncapped) < 1e-6, \
        "natural dP should be unaffected by a non-binding cap"


# ─── HV-plateau helper (pure-numeric, fast) ─────────────────────────


@pytest.mark.fast
@pytest.mark.parametrize("hist,tol,window,expected", [
    # Flat tail: 3 trailing relative deltas all < 1 % → trigger
    ([1.00, 1.50, 1.51, 1.515, 1.518], 0.01, 3, True),
    # Steady rise: relative deltas way above 1 % → no trigger
    ([1.00, 1.50, 2.00, 3.00, 4.00],   0.01, 3, False),
    # Insufficient history (< window+1 entries) → never triggers
    ([1.00, 1.50],                     0.01, 3, False),
    # Disable via tol=0
    ([1.00, 1.00, 1.00, 1.00, 1.00],   0.0,  3, False),
    # Tighter tol fails on small-but-nonzero gain
    ([1.00, 1.10, 1.105, 1.110, 1.115], 0.001, 3, False),
])
def test_hv_plateau_detection(hist, tol, window, expected):
    from sjtu_tpmshx.optimization.optimizer_qnehvi import hv_plateau_detected
    assert hv_plateau_detected(hist, tol, window) is expected


@pytest.mark.fast
def test_log_dp_roundtrip_math():
    """Pure check of the log10 / 10**(-x) round-trip used by qnehvi to
    transform dP into the GP's MAX-form objective and back."""
    for dP in (1.0, 100.0, 12345.6, 1.0e6):
        log_form = -np.log10(dP)
        dP_back = 10.0 ** (-log_form)
        assert abs(dP_back - dP) / dP < 1e-12


# ─── Compressible outer-loop coupling (var-density ρ(T)) ────────────


def test_compressible_outer_loop_changes_dp():
    """n_rho_loops=3 must produce a materially different dP from
    n_rho_loops=1 on a heated case, proving the ρ(T) feedback into SIMPLE
    is wired and honors the project-level compressibility hard constraint
    (memory: feedback_compressible_required.md → wiring 弃压缩 ⇒ dP +21pp).

    Picks a deliberately large ΔT (T_inA=600 K, T_inB=300 K) so the
    compressibility shift is unambiguous (≥ 5 % relative dP delta).
    """
    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0, 0.10, 0.05)
    base = {**_FAST_CFG,
            'T_inA': 600.0, 'T_inB': 300.0,
            'reject_unconverged': False, 'penalty_enabled': False}
    Q1_neg, dP1, _ = evaluate_design(x=None, cfg={**base, 'n_rho_loops': 1}, fc=fc)
    Q3_neg, dP3, _ = evaluate_design(x=None, cfg={**base, 'n_rho_loops': 3}, fc=fc)
    rel_ddP = abs(dP3 - dP1) / dP1
    assert rel_ddP > 0.05, \
        f"compressibility coupling not wired: |ΔdP|/dP = {rel_ddP:.3%} (expected > 5 %)"


def test_compressible_outer_loop_isothermal_inlets_match_loop1():
    """When T_inA == T_inB (no temperature gradient at the inlets), and the
    energy solve produces a near-uniform field, the ρ(T) update should
    converge to the inlet ρ on the first iteration → drho_max < 1 % → break.
    Result should match n_rho_loops=1 within numerical noise.

    This is the consistency check: extra outer iterations should not move
    the solution when there's nothing to converge.
    """
    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0, 0.10, 0.05)
    base = {**_FAST_CFG,
            'T_inA': 300.0, 'T_inB': 300.0,    # zero ΔT
            'reject_unconverged': False, 'penalty_enabled': False}
    Q1_neg, dP1, _ = evaluate_design(x=None, cfg={**base, 'n_rho_loops': 1}, fc=fc)
    Q3_neg, dP3, _ = evaluate_design(x=None, cfg={**base, 'n_rho_loops': 3}, fc=fc)
    # Zero ΔT can still produce small Q/dP shifts due to iteration order; allow
    # 5 % slack to absorb that without losing the regression-detection signal.
    rel_dQ  = abs(Q3_neg - Q1_neg) / max(abs(Q1_neg), 1.0)
    rel_ddP = abs(dP3 - dP1)       / max(dP1, 1.0)
    assert rel_dQ  < 0.05, f"isothermal: ΔQ shift = {rel_dQ:.3%} > 5 %"
    assert rel_ddP < 0.05, f"isothermal: ΔdP shift = {rel_ddP:.3%} > 5 %"
