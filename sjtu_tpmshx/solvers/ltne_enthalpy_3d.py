"""Option B enthalpy-form 3D LTNE solver (Phase 2.2).

A self-contained conservative LTNE kernel that keeps specific enthalpy ``h`` as
the primary fluid unknown, so the convection telescopes the mass flux ṁ on h
(true enthalpy flux ṁ·h) instead of the legacy ṁ·cp·T. For a strongly
variable-cp fluid (sCO2 across the pseudocritical line) ṁ·cp·T conserves the
wrong quantity (off by ∫T·dcp → the 703 ~41% A/B imbalance); the enthalpy form
closes it. See the validated 1D PoC poc/poc_1d_ltne_enthalpy_optionB.py and the
plan vault reports/method/3d/2026-06-28-3d-ltne-enthalpy-conservative-rewrite-plan-CN.md.

Architecture (numba constraint): the inner Gauss-Seidel sweeps are @njit and
operate purely on precomputed arrays; ALL CoolProp work (the T = T(h,P) inverse
and the cp/k property fields) lives in the Python driver and is refreshed once
per outer (Picard) iteration. This is the separation the production port uses —
the njit kernel never calls CoolProp.

The production path consumes signed SIMPLE mass flow on every staggered face,
so mixed fluids, all six directions, offset porosity and local inlet/outlet
patches share the same first-order conservative formulation.
"""
from __future__ import annotations

import numpy as np
from numba import njit
from sjtu_tpmshx.domain.cancellation import CancelledError


_T_LO, _T_HI = 240.0, 420.0

# ── Per-fluid property accessors (#1 mixed kernel) ──────────────────────────
# The njit kernel is fluid-agnostic (it consumes cp / h / T* arrays). Only this
# driver layer needs to know the fluid, so the energy solve can mix a variable-cp
# sCO2 stream with a water (or air) stream — the real 703 precooler. Each fluid's
# h/T(h)/cp/k come from CoolProp at the side's pressure. For 'sco2' these are the
# SAME CO2 calls sco2_props makes → byte-identical to the sCO2-only path.
from CoolProp.CoolProp import PropsSI as _PropsSI  # noqa: E402
from sjtu_tpmshx.models.fluid_props import (  # noqa: E402
    WaterStateError, check_water_state, check_finite_temperatures,
)
from sjtu_tpmshx.models.sco2_props import _validate_state  # noqa: E402
_CP_NAME = {'sco2': 'CO2', 'water': 'Water', 'air': 'Air'}


def _check_sco2_state(fluid, T, P, *, where):
    if fluid == 'sco2':
        _validate_state(T, P, where=where)


def _prop_field(key, T, P, fluid):
    """Return one field, or contiguous fields for a sequence of output keys."""
    T = np.ascontiguousarray(T, dtype=np.float64)
    P = np.broadcast_to(np.asarray(P, dtype=np.float64), T.shape)
    _check_sco2_state(fluid, T, P, where='enthalpy property field')
    out = _PropsSI(key, "T", T.ravel(), "P", np.ascontiguousarray(P).ravel(),
                   _CP_NAME.get(fluid, fluid))
    out = np.asarray(out, dtype=np.float64)
    if isinstance(key, str):
        return out.reshape(T.shape)
    # CoolProp squeezes a single state; restore state/output axes before splitting.
    return np.ascontiguousarray(out.reshape(-1, len(key)).T).reshape(
        (len(key),) + T.shape)


def _T_of_h_field(h, P, fluid, *, where='enthalpy EOS return'):
    h = np.ascontiguousarray(h, dtype=np.float64)
    P = np.broadcast_to(np.asarray(P, dtype=np.float64), h.shape)
    try:
        out = _PropsSI("T", "H", h.ravel(), "P", np.ascontiguousarray(P).ravel(),
                       _CP_NAME.get(fluid, fluid))
    except ValueError as exc:
        if fluid == 'water':
            location = (f'index={tuple(0 for _ in h.shape)}' if h.size == 1
                        else f'failed index undetermined, input shape={h.shape}')
            raise WaterStateError(
                f'{where}: water EOS T(h,P) state unconfirmed; {location}; '
                f'input h={np.array2string(h, threshold=8)} J/kg, '
                f'P_abs={np.array2string(P, threshold=8)} Pa') from exc
        raise
    temperature = np.asarray(out, dtype=np.float64).reshape(h.shape)
    check_water_state(fluid, temperature, P, where=where)
    _check_sco2_state(fluid, temperature, P, where=where)
    return temperature


def _h_scalar(T, P, fluid):
    return float(_PropsSI("H", "T", float(T), "P", float(P), _CP_NAME.get(fluid, fluid)))


def face_mass_fluxes(uf, vf, wf, rho, eps_side, dx, dy, dz):
    """Convert real-coordinate staggered velocities to signed face mass flow."""
    rho_eps = (np.asarray(rho, dtype=np.float64)
               * np.asarray(eps_side, dtype=np.float64))
    Nx, Ny, Nz = rho_eps.shape
    dx = np.asarray(dx, dtype=np.float64)
    dy = np.asarray(dy, dtype=np.float64)
    dz = np.asarray(dz, dtype=np.float64)
    cx = np.empty((Nx + 1, Ny, Nz), dtype=np.float64)
    cy = np.empty((Nx, Ny + 1, Nz), dtype=np.float64)
    cz = np.empty((Nx, Ny, Nz + 1), dtype=np.float64)
    cx[1:-1] = 0.5 * (rho_eps[:-1] + rho_eps[1:])
    cx[0] = rho_eps[0]; cx[-1] = rho_eps[-1]
    cy[:, 1:-1] = 0.5 * (rho_eps[:, :-1] + rho_eps[:, 1:])
    cy[:, 0] = rho_eps[:, 0]; cy[:, -1] = rho_eps[:, -1]
    cz[:, :, 1:-1] = 0.5 * (rho_eps[:, :, :-1] + rho_eps[:, :, 1:])
    cz[:, :, 0] = rho_eps[:, :, 0]; cz[:, :, -1] = rho_eps[:, :, -1]
    Fx = cx * np.asarray(uf, dtype=np.float64) * dy[None, :, None] * dz[None, None, :]
    Fy = cy * np.asarray(vf, dtype=np.float64) * dx[:, None, None] * dz[None, None, :]
    Fz = cz * np.asarray(wf, dtype=np.float64) * dx[:, None, None] * dy[None, :, None]
    return tuple(np.ascontiguousarray(f) for f in (Fx, Fy, Fz))


def _uniform_face_mass_flux(shape, m_dot, direction):
    """Compatibility flux field for standalone uniform-flow kernel tests."""
    Nx, Ny, Nz = shape
    Fx = np.zeros((Nx + 1, Ny, Nz), dtype=np.float64)
    Fy = np.zeros((Nx, Ny + 1, Nz), dtype=np.float64)
    Fz = np.zeros((Nx, Ny, Nz + 1), dtype=np.float64)
    fluxes = (Fx, Fy, Fz)
    axis = int(direction) // 2
    sign = 1.0 if int(direction) % 2 == 0 else -1.0
    cross_cells = shape[(axis + 1) % 3] * shape[(axis + 2) % 3]
    fluxes[axis][...] = sign * abs(float(m_dot)) / cross_cells
    return fluxes


from sjtu_tpmshx.result_math import _boundary_enthalpy_duty  # noqa: F401 - existing public name


@njit(cache=True, fastmath=True)
def _harmonic(a, b):
    return 0.0 if a + b <= 0.0 else 2.0 * a * b / (a + b)


@njit(cache=True, fastmath=True)
def _fluid_enthalpy_sweep(h, T_star, Ts, cp, h_star, dh, hv, Fx, Fy, Fz,
                          h_in, dx, dy, dz, omega, h_lo, h_hi):
    """One conservative FVM sweep using signed SIMPLE face mass flows."""
    Nx, Ny, Nz = h.shape
    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                dxi = dx[i]; dyj = dy[j]; dzk = dz[k]
                Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                vol = dxi * dyj * dzk
                dW = (_harmonic(dh[i, j, k], dh[i - 1, j, k]) * Ax
                      / (0.5 * (dx[i - 1] + dxi))) if i > 0 else 0.0
                dE = (_harmonic(dh[i, j, k], dh[i + 1, j, k]) * Ax
                      / (0.5 * (dx[i + 1] + dxi))) if i + 1 < Nx else 0.0
                dS = (_harmonic(dh[i, j, k], dh[i, j - 1, k]) * Ay
                      / (0.5 * (dy[j - 1] + dyj))) if j > 0 else 0.0
                dN = (_harmonic(dh[i, j, k], dh[i, j + 1, k]) * Ay
                      / (0.5 * (dy[j + 1] + dyj))) if j + 1 < Ny else 0.0
                dB = (_harmonic(dh[i, j, k], dh[i, j, k - 1]) * Az
                      / (0.5 * (dz[k - 1] + dzk))) if k > 0 else 0.0
                dT = (_harmonic(dh[i, j, k], dh[i, j, k + 1]) * Az
                      / (0.5 * (dz[k + 1] + dzk))) if k + 1 < Nz else 0.0

                fw = Fx[i, j, k]; fe = Fx[i + 1, j, k]
                fs = Fy[i, j, k]; fn = Fy[i, j + 1, k]
                fb = Fz[i, j, k]; ft = Fz[i, j, k + 1]
                aW = dW + max(fw, 0.0)
                aE = dE + max(-fe, 0.0)
                aS = dS + max(fs, 0.0)
                aN = dN + max(-fn, 0.0)
                aB = dB + max(fb, 0.0)
                aT = dT + max(-ft, 0.0)
                cpi = max(cp[i, j, k], 1e-30)
                exchange = hv[i, j, k] * vol
                aP = (dW + dE + dS + dN + dB + dT + exchange / cpi
                      + max(-fw, 0.0) + max(fe, 0.0)
                      + max(-fs, 0.0) + max(fn, 0.0)
                      + max(-fb, 0.0) + max(ft, 0.0))
                rhs = exchange * (
                    Ts[i, j, k] - T_star[i, j, k]
                    + h_star[i, j, k] / cpi)
                if i > 0:
                    rhs += aW * h[i - 1, j, k]
                elif fw > 0.0:
                    rhs += fw * h_in
                if i + 1 < Nx:
                    rhs += aE * h[i + 1, j, k]
                elif fe < 0.0:
                    rhs += -fe * h_in
                if j > 0:
                    rhs += aS * h[i, j - 1, k]
                elif fs > 0.0:
                    rhs += fs * h_in
                if j + 1 < Ny:
                    rhs += aN * h[i, j + 1, k]
                elif fn < 0.0:
                    rhs += -fn * h_in
                if k > 0:
                    rhs += aB * h[i, j, k - 1]
                elif fb > 0.0:
                    rhs += fb * h_in
                if k + 1 < Nz:
                    rhs += aT * h[i, j, k + 1]
                elif ft < 0.0:
                    rhs += -ft * h_in
                if aP > 1e-30:
                    update = (1.0 - omega) * h[i, j, k] + omega * rhs / aP
                    h[i, j, k] = min(max(update, h_lo), h_hi)


@njit(cache=True, fastmath=True)
def _solid_temperature_sweep(Ts, hA, hB, cpA, cpB, TA_star, TB_star,
                             hA_star, hB_star, hvA, hvB, Kss,
                             dx, dy, dz, omega):
    Nx, Ny, Nz = Ts.shape
    for i in range(Nx):
        for j in range(Ny):
            for k in range(Nz):
                dxi = dx[i]; dyj = dy[j]; dzk = dz[k]
                Ax = dyj * dzk; Ay = dxi * dzk; Az = dxi * dyj
                vol = dxi * dyj * dzk
                dW = (_harmonic(Kss[i, j, k], Kss[i - 1, j, k]) * Ax
                      / (0.5 * (dx[i - 1] + dxi))) if i > 0 else 0.0
                dE = (_harmonic(Kss[i, j, k], Kss[i + 1, j, k]) * Ax
                      / (0.5 * (dx[i + 1] + dxi))) if i + 1 < Nx else 0.0
                dS = (_harmonic(Kss[i, j, k], Kss[i, j - 1, k]) * Ay
                      / (0.5 * (dy[j - 1] + dyj))) if j > 0 else 0.0
                dN = (_harmonic(Kss[i, j, k], Kss[i, j + 1, k]) * Ay
                      / (0.5 * (dy[j + 1] + dyj))) if j + 1 < Ny else 0.0
                dB = (_harmonic(Kss[i, j, k], Kss[i, j, k - 1]) * Az
                      / (0.5 * (dz[k - 1] + dzk))) if k > 0 else 0.0
                dT = (_harmonic(Kss[i, j, k], Kss[i, j, k + 1]) * Az
                      / (0.5 * (dz[k + 1] + dzk))) if k + 1 < Nz else 0.0
                ta = TA_star[i, j, k] + (
                    hA[i, j, k] - hA_star[i, j, k]) / max(cpA[i, j, k], 1e-30)
                tb = TB_star[i, j, k] + (
                    hB[i, j, k] - hB_star[i, j, k]) / max(cpB[i, j, k], 1e-30)
                eA = hvA[i, j, k] * vol
                eB = hvB[i, j, k] * vol
                aP = dW + dE + dS + dN + dB + dT + eA + eB
                rhs = eA * ta + eB * tb
                if i > 0: rhs += dW * Ts[i - 1, j, k]
                if i + 1 < Nx: rhs += dE * Ts[i + 1, j, k]
                if j > 0: rhs += dS * Ts[i, j - 1, k]
                if j + 1 < Ny: rhs += dN * Ts[i, j + 1, k]
                if k > 0: rhs += dB * Ts[i, j, k - 1]
                if k + 1 < Nz: rhs += dT * Ts[i, j, k + 1]
                if aP > 1e-30:
                    Ts[i, j, k] = (1.0 - omega) * Ts[i, j, k] + omega * rhs / aP


@njit(cache=True, fastmath=True)
def _gs_enthalpy_sweeps_3d(hA, hB, Ts, dhA, dhB, cpA, cpB,
                           TA_star, TB_star, hA_star, hB_star,
                           FxA, FyA, FzA, FxB, FyB, FzB,
                           hvA, hvB, Kss, dx, dy, dz, h_in_A, h_in_B,
                           n_sweep, omega, h_lo_A, h_hi_A, h_lo_B, h_hi_B):
    for _ in range(n_sweep):
        _fluid_enthalpy_sweep(
            hA, TA_star, Ts, cpA, hA_star, dhA, hvA, FxA, FyA, FzA,
            h_in_A, dx, dy, dz, omega, h_lo_A, h_hi_A)
        _fluid_enthalpy_sweep(
            hB, TB_star, Ts, cpB, hB_star, dhB, hvB, FxB, FyB, FzB,
            h_in_B, dx, dy, dz, omega, h_lo_B, h_hi_B)
        _solid_temperature_sweep(
            Ts, hA, hB, cpA, cpB, TA_star, TB_star, hA_star, hB_star,
            hvA, hvB, Kss, dx, dy, dz, omega)


_FL_TLO = {'sco2': 230.0, 'water': 274.0, 'air': 200.0}


def solve_ltne_enthalpy_3d(Nx, Ny, Nz, Lx, Ly, Lz, eps, k_s,
                           m_dot_A, m_dot_B, h_vA, h_vB,
                           T_inA, T_inB, P, P_B=None, dir_A=0, dir_B=1,
                           fluid_A='sco2', fluid_B='sco2',
                           eps_A_field=None, eps_B_field=None,
                           n_outer=3000, n_sweep=3, omega=0.6, tol=2e-5):
    """Python Picard driver around the njit enthalpy sweeps. CoolProp T(h,P)
    inverse + cp/k property fields refreshed once per outer iteration.

    Per-side pressure: ``P`` is fluid A's pressure, ``P_B`` fluid B's (defaults
    to ``P``). Per-side fluid (``fluid_A``/``fluid_B`` in {sco2,water,air}) lets
    the solve MIX a variable-cp sCO2 stream with water — the 703 precooler.
    The 703 recuperator runs sco2/sco2, hot ≈8 MPa / cold ≈18.5 MPa."""
    P_A = float(P)
    P_B = float(P_B) if P_B is not None else P_A
    check_water_state(fluid_A, T_inA, P_A, where='enthalpy inlet A')
    _check_sco2_state(fluid_A, T_inA, P_A, where='enthalpy inlet A')
    check_water_state(fluid_B, T_inB, P_B, where='enthalpy inlet B')
    _check_sco2_state(fluid_B, T_inB, P_B, where='enthalpy inlet B')
    dx = np.full(Nx, Lx / Nx, dtype=np.float64)
    dy = np.full(Ny, Ly / Ny, dtype=np.float64)
    dz = np.full(Nz, Lz / Nz, dtype=np.float64)
    shape = (Nx, Ny, Nz)
    # per-side single-channel void fraction. Default symmetric ε_A=ε_B=ε/2; an
    # offset-isosurface (δ≠0) design passes per-side fields (already split).
    epsA = (np.ascontiguousarray(eps_A_field, dtype=np.float64)
            if eps_A_field is not None else np.full(shape, 0.5 * eps))
    epsB = (np.ascontiguousarray(eps_B_field, dtype=np.float64)
            if eps_B_field is not None else np.full(shape, 0.5 * eps))
    flux_A = _uniform_face_mass_flux(shape, m_dot_A, dir_A)
    flux_B = _uniform_face_mass_flux(shape, m_dot_B, dir_B)
    hvA_fld = np.full(shape, float(h_vA))
    hvB_fld = np.full(shape, float(h_vB))
    Kss = (1.0 - epsA - epsB) * float(k_s)

    h_in_A = _h_scalar(T_inA, P_A, fluid_A)
    h_in_B = _h_scalar(T_inB, P_B, fluid_B)
    # clamp the iterate to a window around the inlets, floored per fluid (e.g.
    # water can't go sub-freezing for the CoolProp enthalpy call)
    T_span_lo = min(T_inA, T_inB) - 40.0
    T_span_hi = max(T_inA, T_inB) + 40.0
    h_lo_A = _h_scalar(max(T_span_lo, _FL_TLO.get(fluid_A, 230.0)), P_A, fluid_A)
    h_hi_A = _h_scalar(T_span_hi, P_A, fluid_A)
    h_lo_B = _h_scalar(max(T_span_lo, _FL_TLO.get(fluid_B, 230.0)), P_B, fluid_B)
    h_hi_B = _h_scalar(T_span_hi, P_B, fluid_B)

    hA = np.full(shape, h_in_A)
    hB = np.full(shape, h_in_B)
    Ts = np.full(shape, 0.5 * (T_inA + T_inB))

    n_done = 0
    for outer in range(n_outer):
        T_A = _T_of_h_field(hA, P_A, fluid_A, where='enthalpy iteration EOS return A')
        T_B = _T_of_h_field(hB, P_B, fluid_B, where='enthalpy iteration EOS return B')
        cpA, kA = _prop_field(("C", "L"), T_A, P_A, fluid_A)
        cpB, kB = _prop_field(("C", "L"), T_B, P_B, fluid_B)
        dhA = epsA * kA / np.maximum(cpA, 1e-30)   # h-space diffusivity
        dhB = epsB * kB / np.maximum(cpB, 1e-30)
        hA_star = hA.copy(); hB_star = hB.copy()

        _gs_enthalpy_sweeps_3d(
            hA, hB, Ts, dhA, dhB, cpA, cpB, T_A, T_B, hA_star, hB_star,
            *flux_A, *flux_B, hvA_fld, hvB_fld, Kss,
            dx, dy, dz, h_in_A, h_in_B,
            int(n_sweep), float(omega), h_lo_A, h_hi_A, h_lo_B, h_hi_B)

        n_done = outer + 1
        denom = max(abs(h_in_A - h_in_B), 1.0)
        if (max(np.max(np.abs(hA - hA_star)),
                np.max(np.abs(hB - hB_star))) / denom) < tol:
            break

    Ta = _T_of_h_field(hA, P_A, fluid_A, where='enthalpy final EOS return A')
    Tb = _T_of_h_field(hB, P_B, fluid_B, where='enthalpy final EOS return B')
    check_finite_temperatures(Ta, Tb, Ts, where='enthalpy final return')
    return dict(Ta=Ta, Tb=Tb,
                Ts=Ts, hA=hA, hB=hB, n_outer=n_done, P_A=P_A, P_B=P_B,
                fluid_A=fluid_A, fluid_B=fluid_B)


def _coupled_energy_balance(Ta, Tb, Ts, hvA, hvB, Kss, dx, dy, dz, q_A, q_B):
    """Adiabatic solid CV residuals at the final EOS state; W (W/m in 2D)."""
    widths = (dx, dy, dz)
    volume = dx[:, None, None] * dy[None, :, None] * dz[None, None, :]
    residual = (hvA * (Ta - Ts) + hvB * (Tb - Ts)) * volume
    for axis, width in enumerate(widths):
        lo = [slice(None)] * 3; hi = lo.copy()
        lo[axis] = slice(None, -1); hi[axis] = slice(1, None)
        lo, hi = tuple(lo), tuple(hi)
        kl, kh = Kss[lo], Kss[hi]
        harmonic = np.zeros_like(kl)
        np.divide(2 * kl * kh, kl + kh, out=harmonic, where=kl + kh > 0)
        shape = [1, 1, 1]; shape[axis] = -1
        distance = (0.5 * (width[:-1] + width[1:])).reshape(shape)
        area = volume / width.reshape(shape)
        flux = harmonic * area[lo] / distance * (Ts[hi] - Ts[lo])
        residual[lo] += flux; residual[hi] -= flux
    net = q_A + q_B
    solid_abs = float(np.abs(residual).sum())
    # Check each operand before max: max(finite, NaN) can hide NaN.
    if not np.all(np.isfinite((q_A, q_B, net, solid_abs))):
        raise FloatingPointError('Non-finite coupled energy budget')
    denominator = max(abs(q_A), abs(q_B), 1.0)
    numerator = max(abs(net), solid_abs)
    ratio = numerator / denominator
    if not np.all(np.isfinite((numerator, denominator, ratio))):
        raise FloatingPointError('Non-finite coupled energy ratio')
    return dict(net=float(net), solid_abs_sum=solid_abs,
                denominator=float(denominator), ratio=float(ratio))


def solve_ltne_enthalpy_3d_pipeline(Nx, Ny, Nz, dx, dy, dz, eps_arr, K_ss,
                                    h_vA_field, h_vB_field, m_dot_A, m_dot_B,
                                    T_inA, T_inB, P_A, P_B, dir_A, dir_B,
                                    fluid_A='sco2', fluid_B='sco2',
                                    eps_A_field=None, eps_B_field=None,
                                    pressure_A_field=None, pressure_B_field=None,
                                    mass_flux_A=None, mass_flux_B=None,
                                    Ta_init=None, Tb_init=None, Ts_init=None,
                                    n_outer=3000, n_sweep=5, omega=0.6, tol=2e-5,
                                    cancel_check=None, coupled_energy_tol=None):
    """Pipeline-facing true-enthalpy LTNE solve using SIMPLE face mass flow.

    Drives the njit enthalpy kernel from the production pipeline's fielded data
    (h_v fields, full porosity field, per-side SIMPLE face mass flow, per-
    side pressure, warm-start T fields). Returns ``(Ta, Tb, Ts, info)`` matching
    the ``solve_full_domain_3d(..., return_info=True)`` contract so it can drop
    into the Python backend's energy-solve call site in true-enthalpy mode.

    ``mass_flux_A/B`` are signed real-coordinate ``(Fx,Fy,Fz)`` arrays. Their
    boundary faces encode arbitrary inlet/outlet patches; zero faces are walls.
    Scalar ``m_dot`` remains only as a compatibility fallback for standalone
    uniform-flow tests. ``coupled_energy_tol`` adds an EOS solid/boundary
    balance gate; only the 2D adapter enables it (unit depth, W/m)."""
    if coupled_energy_tol is not None and (
            not np.isfinite(coupled_energy_tol) or coupled_energy_tol <= 0):
        raise ValueError('coupled_energy_tol must be finite and positive')
    check_water_state(fluid_A, T_inA, P_A, where='enthalpy inlet A')
    _check_sco2_state(fluid_A, T_inA, P_A, where='enthalpy inlet A')
    check_water_state(fluid_B, T_inB, P_B, where='enthalpy inlet B')
    _check_sco2_state(fluid_B, T_inB, P_B, where='enthalpy inlet B')
    shape = (Nx, Ny, Nz)
    dx = np.ascontiguousarray(dx, dtype=np.float64)
    dy = np.ascontiguousarray(dy, dtype=np.float64)
    dz = np.ascontiguousarray(dz, dtype=np.float64)
    # symmetric ε/2 by default; offset-isosurface (δ≠0) passes per-side fields.
    epsA = (np.ascontiguousarray(eps_A_field, dtype=np.float64)
            if eps_A_field is not None
            else 0.5 * np.ascontiguousarray(eps_arr, dtype=np.float64))
    epsB = (np.ascontiguousarray(eps_B_field, dtype=np.float64)
            if eps_B_field is not None else epsA.copy())
    hvA_fld = np.ascontiguousarray(h_vA_field, dtype=np.float64)
    hvB_fld = np.ascontiguousarray(h_vB_field, dtype=np.float64)
    Kss = np.broadcast_to(np.asarray(K_ss, dtype=np.float64), shape).copy()
    P_A_field = (np.full(shape, float(P_A)) if pressure_A_field is None
                 else np.ascontiguousarray(pressure_A_field, dtype=np.float64))
    P_B_field = (np.full(shape, float(P_B)) if pressure_B_field is None
                 else np.ascontiguousarray(pressure_B_field, dtype=np.float64))
    if P_A_field.shape != shape or P_B_field.shape != shape:
        raise ValueError("local pressure fields must match the 3D LTNE grid")
    flux_A = (_uniform_face_mass_flux(shape, m_dot_A, dir_A)
              if mass_flux_A is None else
              tuple(np.ascontiguousarray(f, dtype=np.float64)
                    for f in mass_flux_A))
    flux_B = (_uniform_face_mass_flux(shape, m_dot_B, dir_B)
              if mass_flux_B is None else
              tuple(np.ascontiguousarray(f, dtype=np.float64)
                    for f in mass_flux_B))
    expected_shapes = ((Nx + 1, Ny, Nz), (Nx, Ny + 1, Nz),
                       (Nx, Ny, Nz + 1))
    if tuple(f.shape for f in flux_A) != expected_shapes \
            or tuple(f.shape for f in flux_B) != expected_shapes:
        raise ValueError("face mass-flow arrays do not match the LTNE grid")

    h_in_A = _h_scalar(T_inA, P_A, fluid_A)
    h_in_B = _h_scalar(T_inB, P_B, fluid_B)
    T_span_lo = min(T_inA, T_inB) - 60.0
    T_span_hi = max(T_inA, T_inB) + 60.0
    h_lo_A = _h_scalar(max(T_span_lo, _FL_TLO.get(fluid_A, 230.0)), P_A, fluid_A)
    h_hi_A = _h_scalar(T_span_hi, P_A, fluid_A)
    h_lo_B = _h_scalar(max(T_span_lo, _FL_TLO.get(fluid_B, 230.0)), P_B, fluid_B)
    h_hi_B = _h_scalar(T_span_hi, P_B, fluid_B)

    # Validate actual initial states; the wider scalar h brackets are mathematical.
    _check_sco2_state(fluid_A, T_inA if Ta_init is None else Ta_init, P_A_field,
                      where='enthalpy warm start A')
    _check_sco2_state(fluid_B, T_inB if Tb_init is None else Tb_init, P_B_field,
                      where='enthalpy warm start B')
    if Ta_init is not None:
        check_water_state(fluid_A, Ta_init, P_A_field, where='enthalpy warm start A')
    if Tb_init is not None:
        check_water_state(fluid_B, Tb_init, P_B_field, where='enthalpy warm start B')
    check_finite_temperatures(
        Ta_init, Tb_init, Ts_init, where='enthalpy warm start')
    hA = (_prop_field("H", np.asarray(Ta_init, dtype=np.float64), P_A_field, fluid_A)
          if Ta_init is not None else np.full(shape, h_in_A))
    hB = (_prop_field("H", np.asarray(Tb_init, dtype=np.float64), P_B_field, fluid_B)
          if Tb_init is not None else np.full(shape, h_in_B))
    Ts = (np.ascontiguousarray(Ts_init, dtype=np.float64).copy()
          if Ts_init is not None else np.full(shape, 0.5 * (T_inA + T_inB)))
    hA = np.ascontiguousarray(hA, dtype=np.float64)
    hB = np.ascontiguousarray(hB, dtype=np.float64)

    n_done = 0
    resid = 0.0
    coupled = None
    converged = False
    next_temperatures = None
    for outer in range(n_outer):
        if cancel_check is not None and cancel_check():
            raise CancelledError("compute cancelled by user")
        if next_temperatures is None:
            T_A = _T_of_h_field(hA, P_A_field, fluid_A, where='enthalpy iteration EOS return A')
            T_B = _T_of_h_field(hB, P_B_field, fluid_B, where='enthalpy iteration EOS return B')
        else:
            T_A, T_B = next_temperatures
            next_temperatures = None
        cpA, kA = _prop_field(("C", "L"), T_A, P_A_field, fluid_A)
        cpB, kB = _prop_field(("C", "L"), T_B, P_B_field, fluid_B)
        dhA = epsA * kA / np.maximum(cpA, 1e-30)
        dhB = epsB * kB / np.maximum(cpB, 1e-30)
        hA_star = hA.copy(); hB_star = hB.copy()

        _gs_enthalpy_sweeps_3d(
            hA, hB, Ts, dhA, dhB, cpA, cpB, T_A, T_B, hA_star, hB_star,
            *flux_A, *flux_B, hvA_fld, hvB_fld, Kss,
            dx, dy, dz, h_in_A, h_in_B,
            int(n_sweep), float(omega), h_lo_A, h_hi_A, h_lo_B, h_hi_B)

        n_done = outer + 1
        if cancel_check is not None and cancel_check():
            raise CancelledError("compute cancelled by user")
        if coupled_energy_tol is not None and not all(
                np.all(np.isfinite(field)) for field in (hA, hB, Ts)):
            raise FloatingPointError('Non-finite coupled energy state')
        denom = max(abs(h_in_A - h_in_B), 1.0)
        resid = max(np.max(np.abs(hA - hA_star)),
                    np.max(np.abs(hB - hB_star))) / denom
        q_A = _boundary_enthalpy_duty(hA, h_in_A, flux_A)
        q_B = _boundary_enthalpy_duty(hB, h_in_B, flux_B)
        imbalance = abs(q_A + q_B) / max(abs(q_A), abs(q_B), 1e-30)
        converged = bool(resid < tol and imbalance < 0.05)
        if coupled_energy_tol is not None:
            if not np.all(np.isfinite((resid, q_A, q_B, imbalance))):
                raise FloatingPointError('Non-finite coupled energy convergence')
            if converged or n_done == n_outer:
                Ta = _T_of_h_field(hA, P_A_field, fluid_A, where='enthalpy final EOS return A')
                Tb = _T_of_h_field(hB, P_B_field, fluid_B, where='enthalpy final EOS return B')
                check_finite_temperatures(Ta, Tb, Ts, where='enthalpy final return')
                coupled = _coupled_energy_balance(
                    Ta, Tb, Ts, hvA_fld, hvB_fld, Kss, dx, dy, dz, q_A, q_B)
                converged = converged and coupled['ratio'] <= coupled_energy_tol
                if not converged and n_done < n_outer:
                    # Same h/P at the next chunk; consume once before its sweep.
                    next_temperatures = (Ta, Tb)
        if converged:
            break

    if coupled_energy_tol is None:
        Ta = _T_of_h_field(hA, P_A_field, fluid_A, where='enthalpy final EOS return A')
        Tb = _T_of_h_field(hB, P_B_field, fluid_B, where='enthalpy final EOS return B')
        check_finite_temperatures(Ta, Tb, Ts, where='enthalpy final return')
    info = dict(iterations=n_done,
                converged=bool(converged),
                residual=float(resid), enthalpy_mode=True,
                Q_A=float(q_A), Q_B=float(q_B),
                energy_imbalance_rel=float(imbalance))
    info['_native_state'] = dict(h_A=hA, h_B=hB, h_in_A=h_in_A, h_in_B=h_in_B,
                                 mass_flux_A=flux_A, mass_flux_B=flux_B)
    if coupled is not None:
        info['coupled_energy_balance'] = coupled
    return Ta, Tb, Ts, info


def enthalpy_metrics_3d(res, case):
    """Conservation metrics. Q_enth via TRUE enthalpy at the stream boundaries;
    Q_solid via the volumetric LTNE exchange."""
    Ta, Tb, Ts = res["Ta"], res["Tb"], res["Ts"]
    Nx, Ny, Nz = Ta.shape
    P_A = res.get("P_A", case["P"])
    P_B = res.get("P_B", case.get("P_B", P_A))
    fl_A = res.get("fluid_A", case.get("fluid_A", "sco2"))
    fl_B = res.get("fluid_B", case.get("fluid_B", "sco2"))
    Vc = (case["Lx"] / Nx) * (case["Ly"] / Ny) * (case["Lz"] / Nz)
    mA = abs(case["m_dot_A"]); mB = abs(case["m_dot_B"])
    hvA, hvB = case["h_vA"], case["h_vB"]
    dir_A, dir_B = case["dir_A"], case["dir_B"]

    outA = -1 if dir_A == 0 else 0
    outB = -1 if dir_B == 0 else 0
    hA_out = float(np.mean(_prop_field("H", Ta[outA, :, :], P_A, fl_A)))
    hB_out = float(np.mean(_prop_field("H", Tb[outB, :, :], P_B, fl_B)))
    h_in_A = _h_scalar(case["T_inA"], P_A, fl_A)
    h_in_B = _h_scalar(case["T_inB"], P_B, fl_B)

    Q_enth_A = mA * abs(hA_out - h_in_A)
    Q_enth_B = mB * abs(hB_out - h_in_B)
    Q_sA = float(np.sum(hvA * (Ts - Ta) * Vc))
    Q_sB = float(np.sum(hvB * (Ts - Tb) * Vc))

    AB_imbal = abs(Q_enth_A - Q_enth_B) / max(Q_enth_A, Q_enth_B, 1e-30)
    e_imb_LTNE = abs(Q_sA + Q_sB) / max(abs(Q_sA), abs(Q_sB), 1e-30)
    diff_A = abs(Q_enth_A - abs(Q_sA)) / max(Q_enth_A, 1e-30)
    diff_B = abs(Q_enth_B - abs(Q_sB)) / max(Q_enth_B, 1e-30)
    return dict(Q_enth_A=Q_enth_A, Q_enth_B=Q_enth_B, Q_sA=Q_sA, Q_sB=Q_sB,
                AB_imbal=AB_imbal, e_imb_LTNE=e_imb_LTNE,
                diff_A=diff_A, diff_B=diff_B)
