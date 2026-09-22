"""Uniform-flow x-axis reference retained for independent enthalpy tests only.

Production consumes prepared SIMPLE face mass fluxes through the pipeline driver.
"""
import numpy as np
from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent



def uniform_face_mass_flux(shape, m_dot, direction):
    """Prescribed uniform-flow fixture for independent kernel tests."""
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
    Inputs must satisfy the current property windows."""
    P_A = float(P)
    P_B = float(P_B) if P_B is not None else P_A
    ent.check_water_state(fluid_A, T_inA, P_A, where='enthalpy inlet A')
    ent._check_sco2_state(fluid_A, T_inA, P_A, where='enthalpy inlet A')
    ent.check_water_state(fluid_B, T_inB, P_B, where='enthalpy inlet B')
    ent._check_sco2_state(fluid_B, T_inB, P_B, where='enthalpy inlet B')
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
    flux_A = uniform_face_mass_flux(shape, m_dot_A, dir_A)
    flux_B = uniform_face_mass_flux(shape, m_dot_B, dir_B)
    hvA_fld = np.full(shape, float(h_vA))
    hvB_fld = np.full(shape, float(h_vB))
    Kss = (1.0 - epsA - epsB) * float(k_s)

    h_in_A = ent._h_scalar(T_inA, P_A, fluid_A)
    h_in_B = ent._h_scalar(T_inB, P_B, fluid_B)
    # clamp the iterate to a window around the inlets, floored per fluid (e.g.
    # water can't go sub-freezing for the CoolProp enthalpy call)
    T_span_lo = min(T_inA, T_inB) - 40.0
    T_span_hi = max(T_inA, T_inB) + 40.0
    h_lo_A = ent._h_scalar(max(T_span_lo, ent._FL_TLO.get(fluid_A, 230.0)), P_A, fluid_A)
    h_hi_A = ent._h_scalar(T_span_hi, P_A, fluid_A)
    h_lo_B = ent._h_scalar(max(T_span_lo, ent._FL_TLO.get(fluid_B, 230.0)), P_B, fluid_B)
    h_hi_B = ent._h_scalar(T_span_hi, P_B, fluid_B)

    hA = np.full(shape, h_in_A)
    hB = np.full(shape, h_in_B)
    Ts = np.full(shape, 0.5 * (T_inA + T_inB))

    n_done = 0
    clip_counts = np.zeros(2, dtype=np.int64)
    for outer in range(n_outer):
        T_A = ent._T_of_h_field(hA, P_A, fluid_A, where='enthalpy iteration EOS return A')
        T_B = ent._T_of_h_field(hB, P_B, fluid_B, where='enthalpy iteration EOS return B')
        cpA, kA = ent._prop_field(("C", "L"), T_A, P_A, fluid_A)
        cpB, kB = ent._prop_field(("C", "L"), T_B, P_B, fluid_B)
        dhA = epsA * kA / np.maximum(cpA, 1e-30)   # h-space diffusivity
        dhB = epsB * kB / np.maximum(cpB, 1e-30)
        hA_star = hA.copy(); hB_star = hB.copy()

        ent._gs_enthalpy_sweeps_3d(
            hA, hB, Ts, dhA, dhB, cpA, cpB, T_A, T_B, hA_star, hB_star,
            *flux_A, *flux_B, hvA_fld, hvB_fld, Kss,
            dx, dy, dz, h_in_A, h_in_B,
            int(n_sweep), float(omega), h_lo_A, h_hi_A, h_lo_B, h_hi_B,
            clip_counts)

        n_done = outer + 1
        denom = max(abs(h_in_A - h_in_B), 1.0)
        if (max(np.max(np.abs(hA - hA_star)),
                np.max(np.abs(hB - hB_star))) / denom) < tol:
            break

    Ta = ent._T_of_h_field(hA, P_A, fluid_A, where='enthalpy final EOS return A')
    Tb = ent._T_of_h_field(hB, P_B, fluid_B, where='enthalpy final EOS return B')
    ent.check_finite_temperatures(Ta, Tb, Ts, where='enthalpy final return')
    return dict(Ta=Ta, Tb=Tb,
                Ts=Ts, hA=hA, hB=hB, n_outer=n_done, P_A=P_A, P_B=P_B,
                fluid_A=fluid_A, fluid_B=fluid_B)


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
    hA_out = float(np.mean(ent._prop_field("H", Ta[outA, :, :], P_A, fl_A)))
    hB_out = float(np.mean(ent._prop_field("H", Tb[outB, :, :], P_B, fl_B)))
    h_in_A = ent._h_scalar(case["T_inA"], P_A, fl_A)
    h_in_B = ent._h_scalar(case["T_inB"], P_B, fl_B)

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

