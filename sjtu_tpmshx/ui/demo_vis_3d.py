"""demo_vis_3d.py — minimal 3D visualization demo for SJTU-TPMSHX.

Runs Shanghai case 8 (mid-Re) on a coarse uniform grid, then renders a 2×2
PyVista panel showing the four canonical 3D visualization modes.

Panel layout:
    (0,0) T_a slice planes     — 3 streamwise cuts, air temperature
    (0,1) Streamlines          — air velocity, coloured by |v|
    (1,0) T_a isosurface       — half-transparent mid-temperature shell
    (1,1) L-field volume render — zoning design field (fake 108-d vector
                                     applied to uniform Shanghai geometry)

Writes PNG to sjtu_tpmshx/ui/demo_vis_3d.png
Run from the repository root: python -u -m sjtu_tpmshx.ui.demo_vis_3d
"""

from __future__ import annotations
import sys, warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyvista as pv

ROOT = Path(__file__).resolve().parents[1]

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
warnings.filterwarnings('ignore')

from sjtu_tpmshx.models.tpms_calc import (
    geometry as tpms_geometry, air_density, air_viscosity,
    air_conductivity, air_cp, P_atm,
)
from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D
from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d, _inlet_transport_3d
from sjtu_tpmshx.solvers.sigmoid_field_3d import build_continuous_arrays_3d
from sjtu_tpmshx.models.sigmoid_field import get_geometry_lut
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF

R_AIR = 287.05

# ── Shanghai geometry ──
TPMS = 'Gyroid'; L_CELL = 7.0; T_WALL = 0.6; K_S = 16.0
g = tpms_geometry(TPMS, L_CELL, T_WALL, K_S)
EPS = g['epsilon']; D_H = g['D_h']; A0 = g['A_0']
L_DOM = 0.182; H_DOM = 0.042; LZ = 0.042

N_UNITS = 36
A_FLOW = N_UNITS * 18.0565e-6


def run_case_8_fields(Nx=30, Ny=15, Nz=5, max_outer=3):
    """Run Shanghai case 8 (mid-Re) and return solver + Ta for visualisation."""
    data_path = (ROOT.parent / 'data' / 'raw_data'
                 / 'experiments/water_air/water-air_G7-t0p6_shanghai_experiment_20260401.xlsx')
    if not data_path.exists():
        raise FileNotFoundError(f'required demo data not found: {data_path}')
    df = pd.read_excel(data_path, engine='openpyxl', sheet_name='Sheet1',
                       header=None, skiprows=2)

    ci = 7   # case 8 index
    m_air = float(df.iloc[ci, 5])
    T_Ain_K = float(df.iloc[ci, 28]) + 273.15
    P_Ain = P_atm + float(df.iloc[ci, 30])
    rho_A = air_density(T_Ain_K, P_Ain)
    mu_A = air_viscosity(T_Ain_K)
    cp_A = air_cp(T_Ain_K)
    u_A = m_air / (rho_A * A_FLOW)

    T_Bin_K = float(df.iloc[ci, 24]) + 273.15
    T_Bout_K = float(df.iloc[ci, 25]) + 273.15

    # Uniform grid
    dx = np.full(Nx, L_DOM / Nx)
    dy = np.full(Ny, H_DOM / Ny)
    dz = np.full(Nz, LZ / Nz)

    eps_arr = np.full((Nx, Ny, Nz), EPS)
    eps_A = 0.5 * EPS    # per-stream void fraction
    K_ffA = np.full((Nx, Ny, Nz), eps_A * air_conductivity(T_Ain_K))
    K_ffB = np.full((Nx, Ny, Nz), eps_A * 0.6)
    K_ss = np.full((Nx, Ny, Nz), (1.0 - EPS) * K_S)

    K_pred, cF_pred = predict_K_cF(TPMS, L_CELL, T_WALL, eps_A)
    K_A_arr = np.full((Nx, Nz), K_pred)
    cF_A_arr = np.full((Nx, Nz), cF_pred)

    h_vA0 = 1.0e5
    h_vA_field = np.full((Nx, Ny, Nz), h_vA0)
    h_vB_field = np.full((Nx, Ny, Nz), 1.0e10)
    rho_cp_A = rho_A * cp_A
    rho_cp_B = 998.0 * 4182.0

    # P_ref_abs seed
    G_A = m_air / A_FLOW
    C_est = mu_A * G_A / K_pred + cF_pred * G_A * G_A
    P_out_sq = P_Ain**2 - 2.0 * R_AIR * T_Ain_K * C_est * L_DOM
    P_ref_A = float(np.sqrt(max(P_out_sq, 1.0e4)))

    sA = SIMPLESolver3D(Lx=H_DOM, Ly=L_DOM, Lz=LZ,
                        Nx=Ny, Ny=Nx, Nz=Nz,
                        rho=rho_A, mu=mu_A, T_in=T_Ain_K, v_inlet=u_A,
                        eps=EPS, K_arr=K_A_arr, cF_arr=cF_A_arr,
                        P_ref_abs=P_ref_A, fluid_type='ideal_gas')
    sA.apply_outlet_taper(n_taper=8, min_frac=0.2)
    sA.solve(max_iter=400, tol=1e-3, verbose=False)

    # Frozen water
    ucB = vcB = wcB = np.zeros((Nx, Ny, Nz))
    y_centres = (np.arange(Ny) + 0.5) * (H_DOM / Ny)
    Tb_1d = T_Bout_K + (T_Bin_K - T_Bout_K) * (y_centres / H_DOM)
    Tb_presc = np.broadcast_to(Tb_1d[None, :, None], (Nx, Ny, Nz)).copy()

    Ta = Tb = Ts = None
    for outer in range(max_outer):
        vA_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])
        ucA = vA_cc.transpose(1, 0, 2).copy()
        vcA = np.zeros((Nx, Ny, Nz))
        wcA = np.zeros((Nx, Ny, Nz))

        # 2026-05-19 ε contract (Option A): pass FULL ε; kernel halves once.
        Ta, Tb, Ts = solve_full_domain_3d(
            L_DOM, H_DOM, LZ, Nx, Ny, Nz, T_Ain_K, T_Bin_K,
            K_ffA, K_ffB, K_ss, h_vA_field, h_vB_field,
            rho_cp_A, rho_cp_B, eps_arr,
            ucA, vcA, wcA, ucB, vcB, wcB,
            dir_A=0, dir_B=3,
            inlet_flux_A=_inlet_transport_3d(
                (sA.v.transpose(1, 0, 2), sA.u.transpose(1, 0, 2),
                 sA.w.transpose(1, 0, 2)),
                0.5*eps_arr, sA.rho_field.transpose(1, 0, 2), cp_A, dx, dy, dz, 0),
            dx_arr=dx, dy_arr=dy, dz_arr=dz,
            Tb_prescribed=Tb_presc, max_iter=20000, tol=1e-5,
            Ta_init=Ta, Tb_init=Tb, Ts_init=Ts, alpha_T=0.7)

        # Update SIMPLE A rho/mu
        # 2026-05-14 fix: propagate Ta into SIMPLE.T_field so inner
        # _update_density() uses real cell T instead of stale T_in.
        # Without this, the manual rho_field assignment below is
        # overwritten on the first inner iter → no T-ρ coupling.
        Ta_sA = Ta.transpose(1, 0, 2).copy()
        sA.update_T_field(Ta_sA)
        P_abs = sA.P_ref_abs + sA.P
        rho_new = P_abs / (R_AIR * Ta_sA)
        sA.rho_field = np.ascontiguousarray(
            0.6 * rho_new + 0.4 * sA.rho_field, dtype=np.float64)
        sA.mu_field = np.ascontiguousarray(air_viscosity(Ta_sA), dtype=np.float64)
        sA._mu_eff_field = np.ascontiguousarray(sA.mu_field / sA.eps, dtype=np.float64)
        sA.solve(max_iter=400, tol=1e-3, verbose=False)

    return sA, Ta, dx, dy, dz, Nx, Ny, Nz, u_A, T_Ain_K


def build_demo_zoning_field(Nx, Ny, Nz, dx, dy, dz):
    """Hand-crafted 108-d vector → varied L-field for visualisation demo.

    Zones 3×3×3 inlet + 3×3×3 outlet. Set non-uniform L to show spatial structure.
    """
    x = np.zeros(108)
    # Inlet L (zones 0-26): checker pattern low / high
    for i in range(27):
        x[i] = 0.3 if (i % 2 == 0) else 0.8
    # Inlet t (27-53)
    x[27:54] = 0.5
    # Outlet L (54-80): opposite pattern
    for i in range(27):
        x[54 + i] = 0.8 if (i % 2 == 0) else 0.3
    # Outlet t (81-107)
    x[81:108] = 0.5

    lut = get_geometry_lut(TPMS)
    # Nominal u, T (not used for L extraction, just API fillers)
    za = build_continuous_arrays_3d(
        x, L_CELL, T_WALL,
        0.2, 0.2, Nx, Ny, Nz, L_DOM, H_DOM, LZ,
        TPMS, K_S, 20.0, 1.0, 400.0, 300.0, lut,
        fix_L=False, fix_t=False,
        dx_arr=dx, dy_arr=dy, dz_arr=dz)
    return za['L_field']


def build_pv_grid(dx, dy, dz):
    """Build pyvista.RectilinearGrid from edge-coord 1D arrays."""
    x_edges = np.concatenate([[0.0], np.cumsum(dx)])
    y_edges = np.concatenate([[0.0], np.cumsum(dy)])
    z_edges = np.concatenate([[0.0], np.cumsum(dz)])
    grid = pv.RectilinearGrid(x_edges, y_edges, z_edges)
    return grid


def main():
    out_path = Path(__file__).parent / 'demo_vis_3d.png'
    print("[1/3] Running Shanghai case 8 on coarse grid…")
    sA, Ta, dx, dy, dz, Nx, Ny, Nz, u_A, T_Ain_K = run_case_8_fields(
        Nx=30, Ny=15, Nz=5, max_outer=3)
    print(f"      Grid: {Nx}×{Ny}×{Nz}  u_A={u_A:.1f} m/s  T_in={T_Ain_K:.1f} K")
    print(f"      T_a range: [{Ta.min():.1f}, {Ta.max():.1f}] K")

    print("[2/3] Building demo zoning field…")
    L_field = build_demo_zoning_field(Nx, Ny, Nz, dx, dy, dz)
    print(f"      L_field range: [{L_field.min():.2f}, {L_field.max():.2f}] mm")

    print(f"[3/3] Rendering 2×2 PyVista panel → {out_path.name}…")

    # Build PyVista grids — cell data attached
    grid_T = build_pv_grid(dx, dy, dz)
    grid_T.cell_data['Ta'] = Ta.flatten(order='F')

    # Velocity cell-centred: SIMPLE A internal is (Ny, Nx, Nz) streamwise y
    # Real coords: u_real = sA.v (streamwise, cell-centre by avg)
    vA_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])   # (Ny, Nx, Nz)
    uc_real = vA_cc.transpose(1, 0, 2).copy()          # (Nx, Ny, Nz)
    vel = np.zeros((Nx, Ny, Nz, 3))
    vel[..., 0] = uc_real
    vmag = np.linalg.norm(vel, axis=-1)

    grid_V = build_pv_grid(dx, dy, dz)
    grid_V.cell_data['velocity'] = vel.reshape(-1, 3, order='F')
    grid_V.cell_data['vmag'] = vmag.flatten(order='F')
    grid_Vp = grid_V.cell_data_to_point_data()

    grid_L = build_pv_grid(dx, dy, dz)
    grid_L.cell_data['L_mm'] = L_field.flatten(order='F')

    # ── PyVista 2×2 panel ──
    pv.set_plot_theme('document')
    p = pv.Plotter(shape=(2, 2), window_size=(1600, 1200), off_screen=True,
                   border=True, border_color='lightgray')

    # (0,0) T_a slices — 3 cuts along streamwise (y axis = real x / L_DOM)
    p.subplot(0, 0)
    centre = grid_T.center
    slices = grid_T.slice_orthogonal(x=centre[0], y=centre[1], z=centre[2])
    p.add_mesh(slices, scalars='Ta', cmap='hot',
               scalar_bar_args={'title': 'T_a [K]'})
    p.add_mesh(grid_T.outline(), color='black')
    p.add_text('(a) T_a orthogonal slices', font_size=10, position='upper_edge')
    p.view_isometric()

    # (0,1) Streamlines — seed at inlet (y=0), colour by |v|
    p.subplot(0, 1)
    try:
        seed = pv.Plane(center=(L_DOM * 0.02, H_DOM * 0.5, LZ * 0.5),
                        direction=(1, 0, 0),
                        i_size=H_DOM * 0.9, j_size=LZ * 0.9,
                        i_resolution=6, j_resolution=4)
        streams = grid_Vp.streamlines_from_source(
            seed, vectors='velocity', max_time=L_DOM * 2.0,
            integration_direction='forward', max_steps=200)
        if streams.n_points > 0:
            tubes = streams.tube(radius=L_DOM * 0.004)
            p.add_mesh(tubes, scalars='vmag', cmap='viridis',
                       scalar_bar_args={'title': '|v| [m/s]'})
    except Exception as e:
        print(f"      streamline skip: {e}")
    p.add_mesh(grid_T.outline(), color='black')
    p.add_text('(b) Streamlines from inlet', font_size=10, position='upper_edge')
    p.view_isometric()

    # (1,0) Isosurface — T_a at mid-temperature, half-transparent
    p.subplot(1, 0)
    T_iso = 0.5 * (Ta.min() + Ta.max())
    grid_Tp = grid_T.cell_data_to_point_data()
    try:
        iso = grid_Tp.contour(isosurfaces=[T_iso], scalars='Ta')
        if iso.n_points > 0:
            p.add_mesh(iso, color='orangered', opacity=0.6, show_edges=False)
    except Exception as e:
        print(f"      isosurface skip: {e}")
    p.add_mesh(grid_T.outline(), color='black')
    p.add_text(f'(c) T_a isosurface @ {T_iso:.0f} K', font_size=10,
               position='upper_edge')
    p.view_isometric()

    # (1,1) L-field volume render (design zoning)
    p.subplot(1, 1)
    slices_L = grid_L.slice_orthogonal(x=centre[0], y=centre[1], z=centre[2])
    p.add_mesh(slices_L, scalars='L_mm', cmap='viridis',
               scalar_bar_args={'title': 'L [mm]'})
    p.add_mesh(grid_L.outline(), color='black')
    p.add_text('(d) L-field design zoning', font_size=10, position='upper_edge')
    p.view_isometric()

    p.link_views()
    p.screenshot(str(out_path))
    print(f"      Saved: {out_path}")
    print("\nDONE.")


if __name__ == '__main__':
    sys.exit(main() or 0)
