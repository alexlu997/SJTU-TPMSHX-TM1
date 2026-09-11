"""Compressible validity-envelope guards for the SIMPLE/LTNE solvers.

The steady, low-Mach, pressure-based SIMPLE solver is valid only while the
Forchheimer pressure drop stays well below the inlet *absolute* pressure. Once
the predicted dP approaches P_in the 1D outlet pressure goes to zero/negative
(P_out^2 < 0): there is no steady subsonic solution — the real flow chokes /
goes supersonic, and the discrete solver responds by driving rho = P/(R T)
toward zero while the mass-flux inlet holds rho*v fixed, so v explodes. The
mass residual stays self-consistent through all of this, so the solver used to
return ``converged=True`` with physically-meaningless fields (negative absolute
pressure, |v| ~ 2000 m/s) and no warning.

These helpers make that failure mode explicit:

* :func:`predict_outlet_p_sq` / :func:`check_compressible_envelope` — a cheap
  *pre-solve* gate from the same 1D Forchheimer seed the pipeline already
  computes. ``P_out_sq <= 0`` means choked; raise (default), warn, or ignore.
* :func:`assess_solution_validity` — a *post-solve* gate on the actual fields
  (positive absolute pressure everywhere, sub-sonic). Catches dynamic choking
  the 1D seed missed.

Nothing here changes an in-envelope solve; the gate is a no-op when
``P_out_sq > 0`` and the validity check only reports.
"""
from __future__ import annotations

import math

import numpy as np

R_AIR_DEFAULT = 287.05      # J/(kg K), dry air
GAMMA_AIR = 1.4

ENVELOPE_MODES = ('raise', 'warn', 'off')

# Mirrors the lower clip bound in SIMPLESolver{,3D}._update_density. The
# post-solve gate treats a converged field whose minimum absolute pressure sits
# at this floor as off-envelope: the clip only engages when the compressible
# solve could not hold a positive pressure on its own.
PRESSURE_FLOOR_PA = 1.0e3


class ChokedFlowError(RuntimeError):
    """The compressible 1D drag predicts dP >= inlet absolute pressure.

    The outlet pressure would have to be <= 0 (vacuum), so no steady subsonic
    solution exists — the flow is choked / supersonic. Subclasses RuntimeError
    so callers that only catch RuntimeError still handle it.
    """


def predict_outlet_p_sq(P_in, T_in, C_est, L, *, R=R_AIR_DEFAULT):
    """1D compressible Forchheimer outlet pressure squared.

    ``P_out^2 = P_in^2 - 2 R T C_est L`` with ``C_est = mu*G/K + cF*G^2`` and
    ``G = rho*u`` (mass flux, constant along the pipe). Returns a float that is
    negative when the predicted dP exceeds P_in (choked).
    """
    return (float(P_in) ** 2
            - 2.0 * float(R) * float(T_in) * float(C_est) * float(L))


def check_compressible_envelope(P_out_sq, P_in, *, mode='raise', context=''):
    """Pre-solve choke gate.

    ``P_out_sq > 0`` → in envelope → return ``None`` (never raises). Otherwise
    the 1D drag predicts dP >= P_in (outlet vacuum): with ``mode='raise'``
    raise :class:`ChokedFlowError`; ``'warn'`` return the message string for the
    caller to surface; ``'off'`` return ``None``.
    """
    if mode not in ENVELOPE_MODES:
        raise ValueError(f"unknown envelope mode {mode!r}; "
                         f"expected one of {ENVELOPE_MODES}")
    if P_out_sq > 0.0:
        return None
    msg = (
        f"Choked/supersonic flow: the 1D Forchheimer drag predicts a pressure "
        f"drop >= the inlet absolute pressure (P_in={float(P_in):.0f} Pa, "
        f"predicted outlet P^2={float(P_out_sq):.3e} < 0). No steady subsonic "
        f"solution exists. Reduce the inlet velocity, shorten the streamwise "
        f"domain, or raise the inlet pressure."
    )
    if context:
        msg += f" [{context}]"
    if mode == 'raise':
        raise ChokedFlowError(msg)
    if mode == 'warn':
        return msg
    return None      # mode == 'off'


def mach(vmax, T_ref, *, R=R_AIR_DEFAULT, gamma=GAMMA_AIR):
    """Mach number of speed ``vmax`` against the local sound speed at T_ref."""
    c = math.sqrt(float(gamma) * float(R) * float(T_ref))
    return float(vmax) / c


def mach_field_max(vmag, T_field, *, R=R_AIR_DEFAULT, gamma=GAMMA_AIR):
    """Conservative peak Mach over a field: max over cells of
    ``|v|_cell / sqrt(gamma R T_cell)``.

    Using each cell's LOCAL temperature (not the hot inlet T) matters because
    the peak |v| sits at the low-density / low-pressure end where the gas can be
    colder than the inlet — a colder cell has a lower sound speed and thus a
    HIGHER Mach, which a single hot-inlet sound speed would under-estimate.
    """
    v = np.asarray(vmag, dtype=np.float64)
    if v.size == 0:
        return 0.0
    T = np.maximum(np.asarray(T_field, dtype=np.float64), 1.0)
    c = np.sqrt(float(gamma) * float(R) * T)
    return float(np.max(v / c))


def assess_solution_validity(P_abs_min, vmax, T_ref, *, mach_limit=1.0,
                             R=R_AIR_DEFAULT, gamma=GAMMA_AIR, ma_max=None):
    """Post-solve physical-validity check on the converged fields.

    Returns ``(valid, reasons)``. ``valid`` is False when the minimum absolute
    pressure is at/below the clip floor (the compressible solve could not hold a
    positive pressure → off-envelope) or the peak Mach is sonic/supersonic.
    ``ma_max`` — if given (the rigorous per-cell value from
    :func:`mach_field_max`) — is used directly; otherwise a single ``vmax`` /
    ``T_ref`` Mach is computed (back-compat / scalar callers).
    """
    reasons = []
    # A diverged solve can leave NaN/inf in the pressure/velocity field. Every
    # float comparison against NaN is False, so the floor/Mach branches below
    # would silently skip and report a NaN field as valid — the same silent
    # garbage this gate exists to catch, just via NaN instead of finite |v|.
    # Treat non-finite inputs as off-envelope explicitly (audit 2026-06-28).
    if not np.isfinite(P_abs_min):
        reasons.append(
            f"non-finite absolute pressure (min P = {P_abs_min}) — the solver "
            "diverged (NaN/inf field)")
    elif P_abs_min <= PRESSURE_FLOOR_PA * (1.0 + 1.0e-6):
        reasons.append(
            f"pressure clipped to the {PRESSURE_FLOOR_PA:.0f} Pa floor "
            f"(min absolute P = {float(P_abs_min):.1f} Pa) — the solve left "
            "the compressible envelope")
    Ma = float(ma_max) if ma_max is not None else mach(vmax, T_ref, R=R,
                                                       gamma=gamma)
    if not np.isfinite(Ma):
        reasons.append(
            f"non-finite Mach (Ma = {Ma}) — the solver diverged "
            "(NaN/inf velocity or temperature field)")
    elif Ma >= mach_limit:
        reasons.append(
            f"supersonic: Ma_max = {Ma:.2f} >= {float(mach_limit):g}")
    return (len(reasons) == 0, reasons)


def gate_solution(P_abs_min, vmax, T_ref, *, mode='raise', dims='3D',
                  mach_limit=1.0, R=R_AIR_DEFAULT, gamma=GAMMA_AIR, ma_max=None):
    """Post-solve gate shared by the 2D and 3D pipelines.

    Runs :func:`assess_solution_validity`; with ``mode='raise'`` raise
    :class:`ChokedFlowError` (labelled by ``dims``) when the converged field is
    non-physical, otherwise just return ``(valid, reasons)``. ``'warn'`` /
    ``'off'`` never raise.

    ``mode`` is validated against :data:`ENVELOPE_MODES` (like the pre-solve
    :func:`check_compressible_envelope`), so a typo'd / mis-configured mode fails
    loudly instead of silently degrading a ``'raise'`` intent into ``'off'``
    (audit 2026-06-28).
    """
    if mode not in ENVELOPE_MODES:
        raise ValueError(f"unknown envelope mode {mode!r}; "
                         f"expected one of {ENVELOPE_MODES}")
    valid, reasons = assess_solution_validity(
        P_abs_min, vmax, T_ref, mach_limit=mach_limit, R=R, gamma=gamma,
        ma_max=ma_max)
    if mode == 'raise' and not valid:
        raise ChokedFlowError(
            f"{dims} solver returned a non-physical field (caught post-solve): "
            + "; ".join(reasons)
            + ". Reduce the inlet velocity, shorten the streamwise domain, or "
              "raise the inlet pressure.")
    return valid, reasons
