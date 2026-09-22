"""Historical 2D enthalpy references, used only by independent tests.

The production 2D adapter uses the shared face-mass-flow 3D enthalpy kernel.
This reference retains its original numerical operations and acceptance test.
"""
import numpy as np
from sjtu_tpmshx.models import sco2_props


_RELAX = 0.65


def scalar_pressure_duty(T_field, uc, vc, dir_code, dx_arr, dy_arr, *,
                         enthalpy_fn, rho_fn, P_ref, inlet_mask=None,
                         outlet_mask=None, eps_side=1.0, T_in=None):
    """Retired cell-velocity/scalar-pressure duty, not the current true-h path."""
    axis = 0 if dir_code < 2 else 1
    inlet, outlet = (0, -1) if dir_code in (0, 2) else (-1, 0)
    widths = np.asarray(dy_arr if axis == 0 else dx_arr)
    velocity = uc if axis == 0 else vc
    eps = np.broadcast_to(eps_side, T_field.shape)
    Ti = np.take(T_field, inlet, axis=axis) if T_in is None else np.asarray(T_in)
    To = np.take(T_field, outlet, axis=axis)
    wi = (np.take(eps, inlet, axis=axis) * rho_fn(Ti, P_ref)
          * np.abs(np.take(velocity, inlet, axis=axis)) * widths
          * (1.0 if inlet_mask is None else inlet_mask))
    wo = (np.take(eps, outlet, axis=axis) * rho_fn(To, P_ref)
          * np.abs(np.take(velocity, outlet, axis=axis)) * widths
          * (1.0 if outlet_mask is None else outlet_mask))
    mass_in = float(np.sum(wi))
    if mass_in < 1e-30:
        return 0.0
    hi, ho = enthalpy_fn(Ti, P_ref), enthalpy_fn(To, P_ref)
    hi_mean = float(np.sum(wi * hi)) / mass_in
    mass_out = float(np.sum(wo))
    ho_mean = (float(np.sum(wo * ho)) / mass_out
               if mass_out > 1e-30 else float(np.mean(ho)))
    return mass_in * (hi_mean - ho_mean)


def _field(value, shape, name):
    out = np.broadcast_to(np.asarray(value, dtype=np.float64), shape).copy()
    if not np.all(np.isfinite(out)):
        raise ValueError(f"{name} must be finite")
    return out


def _fluid_sweep(h, T, P, Ts, h_v, mass_rows, h_in_rows, dx, dy, direction):
    cp = np.asarray(sco2_props.sco2_prop("C", T, P), dtype=np.float64)
    h_old = h.copy()
    indices = range(h.shape[0]) if direction == 1 else range(h.shape[0] - 1, -1, -1)
    for i in indices:
        for j in range(h.shape[1]):
            exchange = h_v[i, j] * dx[i] * dy[j]
            diagonal = mass_rows[j] + exchange / cp[i, j]
            upstream = i - direction
            h_up = h[upstream, j] if 0 <= upstream < h.shape[0] else h_in_rows[j]
            rhs = (mass_rows[j] * h_up
                   + exchange * (Ts[i, j] - T[i, j] + h_old[i, j] / cp[i, j]))
            candidate = rhs / max(diagonal, np.finfo(np.float64).tiny)
            h[i, j] += _RELAX * (candidate - h[i, j])
    return h_old, cp


def _harmonic(a, b):
    total = a + b
    return 0.0 if total <= 0.0 else 2.0 * a * b / total


def _solid_sweep(Ts, Ta, Tb, k_s, h_vA, h_vB, dx, dy):
    nx, ny = Ts.shape
    for i in range(nx):
        for j in range(ny):
            volume = dx[i] * dy[j]
            exchange_A = h_vA[i, j] * volume
            exchange_B = h_vB[i, j] * volume
            diagonal = exchange_A + exchange_B
            rhs = exchange_A * Ta[i, j] + exchange_B * Tb[i, j]
            if i > 0:
                conductance = (_harmonic(k_s[i - 1, j], k_s[i, j]) * dy[j]
                               / (0.5 * (dx[i - 1] + dx[i])))
                diagonal += conductance
                rhs += conductance * Ts[i - 1, j]
            if i + 1 < nx:
                conductance = (_harmonic(k_s[i, j], k_s[i + 1, j]) * dy[j]
                               / (0.5 * (dx[i] + dx[i + 1])))
                diagonal += conductance
                rhs += conductance * Ts[i + 1, j]
            if j > 0:
                conductance = (_harmonic(k_s[i, j - 1], k_s[i, j]) * dx[i]
                               / (0.5 * (dy[j - 1] + dy[j])))
                diagonal += conductance
                rhs += conductance * Ts[i, j - 1]
            if j + 1 < ny:
                conductance = (_harmonic(k_s[i, j], k_s[i, j + 1]) * dx[i]
                               / (0.5 * (dy[j] + dy[j + 1])))
                diagonal += conductance
                rhs += conductance * Ts[i, j + 1]
            candidate = rhs / max(diagonal, np.finfo(np.float64).tiny)
            Ts[i, j] += _RELAX * (candidate - Ts[i, j])


def solve_sco2_enthalpy_2d(
    T_inA, T_inB, pressure_A, pressure_B, mass_flow_A_rows,
    mass_flow_B_rows, h_vA, h_vB, k_s, dx, dy, *, Ta_init=None,
    Tb_init=None, Ts_init=None, max_iter=5000, tol=0.5,
):
    """Solve full-face ``+x/-x`` paired sCO2 transport per metre depth."""
    dx = np.asarray(dx, dtype=np.float64)
    dy = np.asarray(dy, dtype=np.float64)
    shape = (dx.size, dy.size)
    if np.any(dx <= 0.0) or np.any(dy <= 0.0):
        raise ValueError("dx and dy must be positive")
    P_A = _field(pressure_A, shape, "pressure_A")
    P_B = _field(pressure_B, shape, "pressure_B")
    h_vA = _field(h_vA, shape, "h_vA")
    h_vB = _field(h_vB, shape, "h_vB")
    k_s = _field(k_s, shape, "k_s")
    mA = np.asarray(mass_flow_A_rows, dtype=np.float64)
    mB = np.asarray(mass_flow_B_rows, dtype=np.float64)
    if mA.shape != (shape[1],) or mB.shape != (shape[1],):
        raise ValueError("mass-flow rows must match the cross-stream grid")
    if np.any(mA <= 0.0) or np.any(mB <= 0.0):
        raise ValueError("full-face sCO2 mass flow must be positive on every row")

    Ta = _field(T_inA if Ta_init is None else Ta_init, shape, "Ta_init")
    Tb = _field(T_inB if Tb_init is None else Tb_init, shape, "Tb_init")
    Ts = _field(0.5 * (T_inA + T_inB) if Ts_init is None else Ts_init,
                shape, "Ts_init")
    hA = np.asarray(sco2_props.sco2_prop("H", Ta, P_A), dtype=np.float64)
    hB = np.asarray(sco2_props.sco2_prop("H", Tb, P_B), dtype=np.float64)
    h_inA = np.asarray(sco2_props.sco2_prop(
        "H", np.full(shape[1], T_inA), P_A[0, :]), dtype=np.float64)
    h_inB = np.asarray(sco2_props.sco2_prop(
        "H", np.full(shape[1], T_inB), P_B[-1, :]), dtype=np.float64)

    residual = float("inf")
    converged = False
    for iteration in range(1, int(max_iter) + 1):
        previous = (Ta.copy(), Tb.copy(), Ts.copy())
        hA_old, cpA = _fluid_sweep(
            hA, Ta, P_A, Ts, h_vA, mA, h_inA, dx, dy, 1)
        hB_old, cpB = _fluid_sweep(
            hB, Tb, P_B, Ts, h_vB, mB, h_inB, dx, dy, -1)
        Ta += (hA - hA_old) / cpA
        Tb += (hB - hB_old) / cpB
        # Direct CoolProp remains authoritative; the local dh/cp update avoids
        # two costly h->T EOS inversions on every Gauss--Seidel sweep.
        if iteration % 20 == 0:
            Ta = np.asarray(sco2_props.sco2_temperature_from_enthalpy(hA, P_A))
            Tb = np.asarray(sco2_props.sco2_temperature_from_enthalpy(hB, P_B))
        _solid_sweep(Ts, Ta, Tb, k_s, h_vA, h_vB, dx, dy)
        residual = max(float(np.max(np.abs(now - old)))
                       for now, old in zip((Ta, Tb, Ts), previous))
        q_A = float(np.sum(mA * (h_inA - hA[-1, :])))
        q_B = float(np.sum(mB * (h_inB - hB[0, :])))
        imbalance = abs(q_A + q_B) / max(abs(q_A), abs(q_B), 1e-30)
        if residual <= tol and imbalance < 0.05:
            converged = True
            break

    Ta = np.asarray(sco2_props.sco2_temperature_from_enthalpy(hA, P_A))
    Tb = np.asarray(sco2_props.sco2_temperature_from_enthalpy(hB, P_B))
    q_A = float(np.sum(mA * (h_inA - hA[-1, :])))
    q_B = float(np.sum(mB * (h_inB - hB[0, :])))
    imbalance = abs(q_A + q_B) / max(abs(q_A), abs(q_B), 1e-30)
    return Ta, Tb, Ts, {
        "converged": converged,
        "iterations": iteration,
        "residual": residual,
        "Q_A": q_A,
        "Q_B": q_B,
        "energy_imbalance_rel": imbalance,
        "enthalpy_mode": True,
    }
