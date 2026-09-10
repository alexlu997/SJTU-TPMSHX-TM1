"""Pure data-only math shared by online diagnostics and offline evaluation."""
import numpy as np


def _enthalpy_balance_2d(T_field, uc, vc, rho_cp_field, dir_code,
                          dx_arr, dy_arr, inlet_mask=None, outlet_mask=None,
                          enthalpy_fn=None, rho_fn=None, P_ref=None,
                          eps_side=None, T_in=None):
    """Mass-conserving enthalpy balance Q = ṁ_in · (T_in_avg − T_out_avg).

    Uses the inlet plane ρ·|u|·A·mask as ṁ·cp reference so the returned Q
    is robust to partial SIMPLE mass-conservation convergence (B-1 refactor
    2026-04-24). The earlier H_in − H_out form gave spurious non-zero Q
    when ṁ_inlet ≠ ṁ_outlet, which in fast-mode NSGA-II inflated Q by 3×.

    Positive = fluid gives up heat (T_in > T_out).
    Optional 1D masks (length = cross-axis) gate the integral to partial
    inlet / outlet pipes; missing masks default to full face.
    ``T_in`` supplies the physical inlet temperature when the first stored
    row is a real control volume. Omit it for independent boundary-field data.

    ``eps_side`` (N1 fix, 2026-07-07): the PER-SIDE void fraction (scalar or
    2D field). Velocities are interstitial, so the physical face mass flux is
    ε_side·ρ·|u|·A — without it the duty over-reads by 1/ε_side (verified
    2.7086 vs 1/ε_A = 2.7147 against the independent Σh_vB·(Ts−Tb)·dA
    integral on the golden air-air case). None keeps the legacy ε-less
    arithmetic for callers that pre-scale externally.

    True-enthalpy mode (sCO2, audit 2026-06-28 D1): when ``enthalpy_fn`` /
    ``rho_fn`` / ``P_ref`` are supplied the duty is the physically correct
    Q = ṁ·(⟨h_in⟩ − ⟨h_out⟩) with mass-flux-weighted mean enthalpy ⟨h(T)⟩ on
    each face (not ρcp(T_in)·ΔT, and not h(⟨T⟩) — both bias Q by tens-to-
    hundreds of percent for sCO2 across the pseudocritical cp spike). The mass
    flux weight is ρ·|u|·A (true mass flow), NOT ρcp. Air/water pass these as
    None and keep the legacy ρcp·ΔT arithmetic exactly (constant cp ⇒ value-
    identical, golden-safe).
    """
    if dir_code in (0, 1):
        i_in, i_out = (0, -1) if dir_code == 0 else (-1, 0)
        A_cell = dy_arr
        n_cross = T_field.shape[1]
        m_in_arr  = (np.asarray(inlet_mask,  dtype=np.float64)
                     if inlet_mask  is not None else np.ones(n_cross))
        m_out_arr = (np.asarray(outlet_mask, dtype=np.float64)
                     if outlet_mask is not None else np.ones(n_cross))
        u_in_face, u_out_face = np.abs(uc[i_in, :]), np.abs(uc[i_out, :])
        rho_cp_in, rho_cp_out = rho_cp_field[i_in, :], rho_cp_field[i_out, :]
        T_in_face, T_out_face = T_field[i_in, :], T_field[i_out, :]
        if eps_side is None:
            eps_in = eps_out = 1.0
        elif np.ndim(eps_side) == 0:
            eps_in = eps_out = float(eps_side)
        else:
            eps_in, eps_out = eps_side[i_in, :], eps_side[i_out, :]
    else:
        j_in, j_out = (0, -1) if dir_code == 2 else (-1, 0)
        A_cell = dx_arr
        n_cross = T_field.shape[0]
        m_in_arr  = (np.asarray(inlet_mask,  dtype=np.float64)
                     if inlet_mask  is not None else np.ones(n_cross))
        m_out_arr = (np.asarray(outlet_mask, dtype=np.float64)
                     if outlet_mask is not None else np.ones(n_cross))
        u_in_face, u_out_face = np.abs(vc[:, j_in]), np.abs(vc[:, j_out])
        rho_cp_in, rho_cp_out = rho_cp_field[:, j_in], rho_cp_field[:, j_out]
        T_in_face, T_out_face = T_field[:, j_in], T_field[:, j_out]
        if eps_side is None:
            eps_in = eps_out = 1.0
        elif np.ndim(eps_side) == 0:
            eps_in = eps_out = float(eps_side)
        else:
            eps_in, eps_out = eps_side[:, j_in], eps_side[:, j_out]

    if T_in is not None:
        T_in_face = np.asarray(T_in, dtype=np.float64)

    if enthalpy_fn is not None and rho_fn is not None and P_ref is not None:
        # True-enthalpy duty for strongly variable-cp fluids (sCO2).
        rho_in  = np.asarray(rho_fn(T_in_face,  P_ref), dtype=np.float64)
        rho_out = np.asarray(rho_fn(T_out_face, P_ref), dtype=np.float64)
        w_in  = eps_in  * rho_in  * u_in_face  * A_cell * m_in_arr
        w_out = eps_out * rho_out * u_out_face * A_cell * m_out_arr
        m_dot = float(np.sum(w_in))
        if m_dot < 1e-30:
            return 0.0
        h_in  = np.asarray(enthalpy_fn(T_in_face,  P_ref), dtype=np.float64)
        h_out = np.asarray(enthalpy_fn(T_out_face, P_ref), dtype=np.float64)
        h_in_avg = float(np.sum(w_in * h_in)) / m_dot
        m_out_tot = float(np.sum(w_out))
        h_out_avg = (float(np.sum(w_out * h_out)) / m_out_tot
                     if m_out_tot > 1e-30 else float(np.mean(h_out)))
        return m_dot * (h_in_avg - h_out_avg)

    m_in_w  = eps_in  * rho_cp_in  * u_in_face  * A_cell * m_in_arr
    m_out_w = eps_out * rho_cp_out * u_out_face * A_cell * m_out_arr
    m_dot_cp = float(np.sum(m_in_w))
    if m_dot_cp < 1e-30:
        return 0.0
    T_in_avg = float(np.sum(m_in_w * T_in_face)) / m_dot_cp
    m_out_total = float(np.sum(m_out_w))
    T_out_avg = (float(np.sum(m_out_w * T_out_face)) / m_out_total
                 if m_out_total > 1e-30 else float(np.mean(T_out_face)))
    return m_dot_cp * (T_in_avg - T_out_avg)


def _pipe_weighted(P_row, w):
    """Open-fraction-weighted boundary-row mean (module-level so the C8
    shooting reseed can measure dP with EXACTLY the reporting convention —
    see `_pipe_dp_2d`). Was nested in `_compute_pressure_2d`; moved verbatim."""
    s = float(w.sum())
    return float((P_row * w).sum() / s) if s > 1e-12 else float(P_row.mean())


def _outlet_temperature_2d(temperature, mass_flux, direction, outlet_fraction):
    """Raw outlet-cell T weighted by positive outward mass, in K.

    Outlet zero-gradient uses the adjacent cell T. Face mass already includes
    area; geometry only selects the real opening. Keep signed inputs intact
    for the separate full-boundary mass and energy checks.
    """
    mx, my = mass_flux
    if direction == 0:
        face_T, outward = temperature[-1, :], mx[-1, :]
    elif direction == 1:
        face_T, outward = temperature[0, :], -mx[0, :]
    elif direction == 2:
        face_T, outward = temperature[:, -1], my[:, -1]
    else:
        face_T, outward = temperature[:, 0], -my[:, 0]
    opening = np.asarray(outlet_fraction) > 0.0
    weights = np.maximum(outward[opening], 0.0)
    total = float(weights.sum())
    if not np.isfinite(total) or total <= 0.0:
        raise ValueError('2D outlet temperature requires finite positive outward mass flow')
    flowing = weights > 0.0
    value = float(np.sum(weights[flowing] * face_T[opening][flowing]) / total)
    if not np.isfinite(value):
        raise ValueError('2D outlet temperature is non-finite')
    return value


def _boundary_enthalpy_duty(h, h_in, mass_flux):
    """Heat lost by a stream from its six boundary-face enthalpy flows."""
    Fx, Fy, Fz = mass_flux
    net_out = 0.0
    for outward, adjacent in (
        (-Fx[0], h[0]), (Fx[-1], h[-1]),
        (-Fy[:, 0], h[:, 0]), (Fy[:, -1], h[:, -1]),
        (-Fz[:, :, 0], h[:, :, 0]), (Fz[:, :, -1], h[:, :, -1]),
    ):
        net_out += float(np.sum(np.where(outward > 0.0, outward * adjacent,
                                         outward * h_in)))
    return -net_out
