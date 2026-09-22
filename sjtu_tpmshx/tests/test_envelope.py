"""Compressible validity-envelope guards (robustness pass, 2026-06-25).

The steady low-Mach SIMPLE solver has no valid solution once the Forchheimer
dP approaches the inlet absolute pressure (outlet -> vacuum -> rho<0 ->
mass-flux inlet drives v supersonic). These guards turn that silent blow-up
(which used to return converged=True with garbage fields) into either a clear
ChokedFlowError (pre-solve) or a flagged-invalid result (post-solve).
"""

import pytest

from sjtu_tpmshx.models.envelope import (
    ChokedFlowError, predict_outlet_p_sq, check_compressible_envelope,
    mach, assess_solution_validity, gate_solution,
)


# ── 1D outlet-pressure prediction ─────────────────────────────────────────
def test_predict_outlet_p_sq_matches_closed_form():
    P_in, T, C, L, R = 192362.0, 800.0, 5.0e4, 0.182, 287.05
    expected = P_in ** 2 - 2.0 * R * T * C * L
    assert predict_outlet_p_sq(P_in, T, C, L, R=R) == pytest.approx(expected)


def test_predict_outlet_p_sq_goes_negative_when_overdriven():
    # Huge drag over a long domain -> dP > P_in -> P_out^2 < 0.
    assert predict_outlet_p_sq(192362.0, 800.0, C_est=1.0e6, L=0.7) < 0.0


# ── pre-solve envelope check ───────────────────────────────────────────────
def test_check_envelope_passes_in_envelope():
    # P_out_sq > 0 -> in envelope -> returns None, never raises.
    assert check_compressible_envelope(9.0e9, 192362.0, mode='raise') is None


def test_check_envelope_raises_when_choked():
    with pytest.raises(ChokedFlowError):
        check_compressible_envelope(-2.0e10, 192362.0, mode='raise')


def test_check_envelope_warn_returns_message_no_raise():
    msg = check_compressible_envelope(-2.0e10, 192362.0, mode='warn')
    assert isinstance(msg, str) and 'pressure-seed rejection' in msg.lower()


def test_check_envelope_off_returns_none_no_raise():
    assert check_compressible_envelope(-2.0e10, 192362.0, mode='off') is None


def test_choked_error_is_runtimeerror_subclass():
    assert issubclass(ChokedFlowError, RuntimeError)


def test_check_envelope_message_names_the_fixes():
    msg = check_compressible_envelope(-1.0, 192362.0, mode='warn')
    low = msg.lower()
    assert 'velocity' in low and ('shorten' in low or 'domain' in low)


# ── Mach + post-solve validity ─────────────────────────────────────────────
def test_mach_air_800K():
    # c = sqrt(1.4*287.05*800) ~ 567 m/s -> 20 m/s ~ Ma 0.035
    assert mach(20.0, 800.0) == pytest.approx(0.0353, abs=2e-3)


def test_assess_validity_clean_case_passes():
    valid, reasons = assess_solution_validity(P_abs_min=173.4e3, vmax=8.5,
                                              T_ref=800.0)
    assert valid is True and reasons == []


def test_assess_validity_flags_negative_pressure():
    valid, reasons = assess_solution_validity(P_abs_min=-12.8e3, vmax=8.0,
                                              T_ref=800.0)
    assert valid is False
    assert any('pressure' in r.lower() for r in reasons)


def test_assess_validity_flags_supersonic():
    # 1964 m/s at 800K -> Ma ~ 3.5 -> supersonic.
    valid, reasons = assess_solution_validity(P_abs_min=150e3, vmax=1964.0,
                                              T_ref=800.0)
    assert valid is False
    assert any('supersonic' in r.lower() or 'ma' in r.lower() for r in reasons)


# ── shared post-solve gate (used by both 2D and 3D pipelines) ──────────────
def test_gate_solution_clean_returns_valid_no_raise():
    valid, reasons = gate_solution(173.4e3, 8.5, 800.0, mode='raise', dims='2D')
    assert valid is True and reasons == []


def test_gate_solution_raises_on_blowup_in_raise_mode():
    with pytest.raises(ChokedFlowError):
        gate_solution(150e3, 1964.0, 800.0, mode='raise', dims='3D')


def test_gate_solution_warn_mode_returns_invalid_no_raise():
    valid, reasons = gate_solution(150e3, 1964.0, 800.0, mode='warn', dims='2D')
    assert valid is False and reasons


def test_gate_solution_message_carries_dims_label():
    try:
        gate_solution(150e3, 1964.0, 800.0, mode='raise', dims='2D')
    except ChokedFlowError as e:
        assert '2D' in str(e)
    else:
        pytest.fail("expected ChokedFlowError")
