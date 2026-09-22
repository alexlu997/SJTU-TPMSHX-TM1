"""Compressible validity checks for the SIMPLE/LTNE solvers.

The full solver qualifies actual cell absolute pressures and local Mach
numbers, together with physical inlet-pressure matching in the coupled loop.
A positive/subsonic field with the wrong inlet pressure is not a solution of
the requested operating point.

The 1D Forchheimer estimate describes straight, isothermal flow. Its failure
is not proof that a turning, non-isothermal coupled flow has no solution.
``check_compressible_envelope`` retains that limited 1D diagnostic; full 2D/3D
startup and bounded pressure updates live in ``solvers._solve_common``.
The final-field floor, nonfinite and Mach gates below remain unchanged.
"""
from __future__ import annotations

import math

import numpy as np
from numpy.typing import ArrayLike

R_AIR_DEFAULT = 287.05      # J/(kg K), dry air
GAMMA_AIR = 1.4

ENVELOPE_MODES = ('raise', 'warn', 'off')

# Mirrors the lower clip bound in SIMPLESolver{,3D}._update_density. The
# post-solve gate treats a converged field whose minimum absolute pressure sits
# at this floor as off-envelope: the clip only engages when the compressible
# solve could not hold a positive pressure on its own.
PRESSURE_FLOOR_PA = 1.0e3


class ChokedFlowError(RuntimeError):
    """A compressible validity check failed; the message identifies the check."""


def predict_outlet_p_sq(P_in: float, T_in: float, C_est: float, L: float,
                        *, R: float = R_AIR_DEFAULT) -> float:
    """1D compressible Forchheimer outlet pressure squared.

    ``P_out^2 = P_in^2 - 2 R T C_est L`` with ``C_est = mu*G/K + cF*G^2`` and
    ``G = rho*u`` (mass flux, constant along the pipe). Returns a float that is
    nonpositive when that isothermal 1D model has no positive outlet state.
    """
    return (float(P_in) ** 2
            - 2.0 * float(R) * float(T_in) * float(C_est) * float(L))


def check_compressible_envelope(P_out_sq: float, P_in: float, *,
                                mode: str = 'raise', context: str = '') -> str | None:
    """Validity diagnostic for the straight, isothermal 1D approximation.

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
        f"1D pressure-seed rejection: the Forchheimer approximation predicts a pressure "
        f"drop >= the inlet absolute pressure (P_in={float(P_in):.0f} Pa, "
        f"predicted outlet P^2={float(P_out_sq):.3e} < 0). No steady subsonic "
        f"solution exists within this isothermal 1D approximation; this does not prove physical choking. Reduce the inlet velocity, shorten the streamwise "
        f"domain, or raise the inlet pressure."
    )
    if context:
        msg += f" [{context}]"
    if mode == 'raise':
        raise ChokedFlowError(msg)
    if mode == 'warn':
        return msg
    return None      # mode == 'off'


def mach(vmax: float, T_ref: float, *, R: float = R_AIR_DEFAULT,
         gamma: float = GAMMA_AIR) -> float:
    """Mach number of speed ``vmax`` against the local sound speed at T_ref."""
    c = math.sqrt(float(gamma) * float(R) * float(T_ref))
    return float(vmax) / c


def mach_field_max(vmag: ArrayLike, T_field: ArrayLike, *, R: float = R_AIR_DEFAULT,
                   gamma: float = GAMMA_AIR) -> float:
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


def assess_solution_validity(P_abs_min: float, vmax: float, T_ref: float, *,
                             mach_limit: float = 1.0, R: float = R_AIR_DEFAULT,
                             gamma: float = GAMMA_AIR,
                             ma_max: float | None = None) -> tuple[bool, list[str]]:
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


def gate_solution(P_abs_min: float, vmax: float, T_ref: float, *,
                  mode: str = 'raise', dims: str = '3D', mach_limit: float = 1.0,
                  R: float = R_AIR_DEFAULT, gamma: float = GAMMA_AIR,
                  ma_max: float | None = None) -> tuple[bool, list[str]]:
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
