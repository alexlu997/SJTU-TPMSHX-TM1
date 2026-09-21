"""2D true-enthalpy adapter for mixed fluids and arbitrary x/y ports."""
from __future__ import annotations
import numpy as np


def solve_enthalpy_2d(
    T_inA, T_inB, pressure_A, pressure_B, mass_flux_A, mass_flux_B,
    h_vA, h_vB, k_s, eps_A, eps_B, dx, dy, *, P_inA, P_inB,
    fluid_A='sco2', fluid_B='sco2', Ta_init=None, Tb_init=None, Ts_init=None,
    max_iter=5000, tol=0.5, cancel_check=None, native_sweeps=None,
):
    """2D-per-metre adapter for the shared face-flux true-enthalpy kernel.

    P_inA/P_inB are inlet absolute pressures (Pa) for the inlet enthalpies;
    pressure_A/pressure_B remain local absolute pressure fields for properties.
    """
    from .ltne_enthalpy_3d import solve_ltne_enthalpy_3d_pipeline

    dx = np.asarray(dx, dtype=np.float64)
    dy = np.asarray(dy, dtype=np.float64)
    shape = (dx.size, dy.size)

    def cell3(value):
        return np.broadcast_to(np.asarray(value, dtype=np.float64), shape)[..., None]

    def flux3(value):
        fx, fy = value
        return (np.asarray(fx, dtype=np.float64)[..., None],
                np.asarray(fy, dtype=np.float64)[..., None],
                np.zeros((shape[0], shape[1], 2), dtype=np.float64))

    result = solve_ltne_enthalpy_3d_pipeline(
        shape[0], shape[1], 1, dx, dy, np.ones(1),
        cell3(eps_A) + cell3(eps_B), cell3(k_s),
        cell3(h_vA), cell3(h_vB), 0.0, 0.0,
        T_inA, T_inB, P_inA, P_inB,
        0, 0, fluid_A=fluid_A, fluid_B=fluid_B,
        eps_A_field=cell3(eps_A), eps_B_field=cell3(eps_B),
        pressure_A_field=cell3(pressure_A),
        pressure_B_field=cell3(pressure_B),
        mass_flux_A=flux3(mass_flux_A), mass_flux_B=flux3(mass_flux_B),
        Ta_init=None if Ta_init is None else cell3(Ta_init),
        Tb_init=None if Tb_init is None else cell3(Tb_init),
        Ts_init=None if Ts_init is None else cell3(Ts_init),
        n_outer=max_iter, n_sweep=3, tol=max(float(tol), 1e-8) / 100.0,
        cancel_check=cancel_check, coupled_energy_tol=0.001,
        equation_energy_tol=0.001, native_sweeps=native_sweeps,
    )
    Ta, Tb, Ts, info = result
    return Ta[..., 0], Tb[..., 0], Ts[..., 0], info
