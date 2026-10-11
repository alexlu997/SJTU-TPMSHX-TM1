"""demo_3d_air_air.py — fixed air/air demonstration workload.

Uses prepare_case, run_case and evaluate without Qt. Plots keep the display
fields; public boundary metrics and backend diagnostics are reported separately.

Fixed demonstration inputs:
    Geometry: L=0.182 m, H=0.042 m, Lz=0.042 m, Nx=30, Ny=20, Nz=5
    TPMS    : Gyroid, L_cell=7 mm, t=0.5 mm
    Solid   : k_s = 16 W/(m·K)
    Fluid A : Air, u_A=20 m/s, T_inA=422 K, P_inA=192362 Pa, +x stream
    Fluid B : Air, u_B=10 m/s, T_inB=293.15 K, P_inB=101325 Pa, -y stream
"""
import os
from pathlib import Path
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, PartialBCConfig, SolverConfig,
)
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate


def build_cfg(*, L=0.182, H=0.042, Lz=0.042, Nx=30, Ny=20, Nz=5):
    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=20.0, T_in_K=422.0, P_in_Pa=192362.0),
        fluid_B=FluidConfig(type='air', u_mps=10.0, T_in_K=293.15, P_in_Pa=101325.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.5,
            k_s_W_mK=16.0, L_dom_m=L, H_dom_m=H, Lz_m=Lz),
        solver=SolverConfig(Nx=Nx, Ny=Ny, Nz=Nz),
        bc_A=PartialBCConfig(dir=0, in_ctr=H / 2, in_w=H, out_ctr=H / 2, out_w=H),
        bc_B=PartialBCConfig(dir=3, in_ctr=L / 2, in_w=L, out_ctr=L / 2, out_w=L),
    )


def print_metrics(res, performance, cfg):
    geometry = res.metadata['parameters']['prepared']['geometry']
    diagnostics = res.metadata['diagnostics']
    print("=" * 70)
    print(f" 3D AIR-AIR DEMO — {cfg.geometry.L_dom_m:g}×"
          f"{cfg.geometry.H_dom_m:g}×{cfg.geometry.Lz_m:g} m")
    print("=" * 70)
    print(f"  Driving ΔT     : {cfg.fluid_A.T_in_K - cfg.fluid_B.T_in_K:.1f} K")
    print(f"  u_A / u_B      : {cfg.fluid_A.u_mps:.1f} / {cfg.fluid_B.u_mps:.1f} m/s")
    print(f"  ε / D_h        : {geometry['epsilon']:.4f} / {geometry['D_h']*1000:.3f} mm")
    print(f"  Execution      : {res.run_status['execution']}")
    print(f"  Converged      : {res.run_status['converged']}")
    passed = res.run_status['execution'] == 'completed' and bool(res.run_status['converged'])
    print("\n  PUBLIC METRICS")
    print("    Q = |Q_A|; Q_A/Q_B are signed native boundary heat losses.")
    print("    Heat gain is negative. T_out uses outward native thermal mass flux.")
    print("    dP uses physical port faces from the final SIMPLE pressure field.")
    for name in ('Q', 'Q_A', 'Q_B', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B',
                 'mass_flow_A', 'mass_flow_B', 'mass_imbalance_rel_A',
                 'mass_imbalance_rel_B', 'energy_imbalance_rel'):
        metric = performance.metrics[name]
        if metric.status == 'available':
            print(f"    {name:<24}: {metric.value:.6g} {metric.spec.unit}")
        else:
            print(f"    {name:<24}: {metric.status} — {metric.reason}")
            passed = False
    print("\n  BACKEND DIAGNOSTICS — original definitions and recorded values")
    print("    Q_enthalpy_A/B are magnitudes; Q_sA/Q_sB and Q_net are volume terms.")
    print("    Q_interior and AB_interior exclude the boundary-cell layer.")
    for name, unit in (
        ('Q', 'W'), ('Q_enthalpy_A', 'W'), ('Q_enthalpy_B', 'W'),
        ('Q_solid_B', 'W'), ('Q_sA', 'W'), ('Q_sB', 'W'), ('Q_net', 'W'),
        ('Q_interior', 'W'), ('AB_interior', '1'), ('energy_imbalance_rel', '1'),
        ('mass_imbalance_rel_A', '1'), ('mass_imbalance_rel_B', '1'),
        ('T_A_out', 'K'), ('T_B_out', 'K'), ('dP', 'Pa'), ('dP_B', 'Pa'),
    ):
        if name in diagnostics:
            print(f"    {name:<24}: {diagnostics[name]:.6g} {unit}")
        else:
            print(f"    {name:<24}: not recorded")
    print()
    print("  DISPLAY FIELD STATS (mid-z slice)")
    f = res.fields
    Nz = f['Ta_display'].shape[2]
    k_mid = Nz // 2
    Ta = f['Ta_display'][:, :, k_mid]
    Tb = f['Tb_display'][:, :, k_mid]
    Ts = f['Ts_display'][:, :, k_mid]
    vmag = f['vmag_A'][:, :, k_mid]
    P_kPa = f['P_fA_display'][:, :, k_mid] / 1000.0
    print(f"    Ta  range   : [{Ta.min():.2f}, {Ta.max():.2f}] K")
    print(f"    Tb  range   : [{Tb.min():.2f}, {Tb.max():.2f}] K")
    print(f"    Ts  range   : [{Ts.min():.2f}, {Ts.max():.2f}] K")
    print(f"    |v|_A range : [{vmag.min():.4f}, {vmag.max():.3f}] m/s")
    print(f"    P_A range   : [{P_kPa.min():.2f}, {P_kPa.max():.2f}] kPa")
    print()
    if not passed:
        print("Run or required metrics failed acceptance; plots are diagnostic outputs.")
    return passed


def plot_clouds(res, outdir):
    os.makedirs(outdir, exist_ok=True)
    f = res.fields
    Nx, Ny, Nz = f['Ta_display'].shape
    k_mid = Nz // 2
    dx = res.grid['dx']; dy = res.grid['dy']
    xc = (np.cumsum(dx) - dx / 2) * 1000.0   # mm
    yc = (np.cumsum(dy) - dy / 2) * 1000.0
    Y, X = np.meshgrid(yc, xc)

    Ta = f['Ta_display'][:, :, k_mid]; Tb = f['Tb_display'][:, :, k_mid]
    Ts = f['Ts_display'][:, :, k_mid]
    vmag_A = f['vmag_A'][:, :, k_mid]
    vmag_B = f.get('vmag_B')
    if vmag_B is not None:
        vmag_B = vmag_B[:, :, k_mid]
    P_A = f['P_fA_display'][:, :, k_mid] / 1000.0
    P_B = None
    if f.get('P_fB_display') is not None:
        P_B = f['P_fB_display'][:, :, k_mid] / 1000.0

    # ── Temperature 3-panel (shared clim) ──
    # NOTE: matplotlib's contourf with `levels=int` auto-bins per data array
    # and IGNORES vmin/vmax for the colorbar mapping. We pass an explicit
    # `levels = np.linspace(vmin, vmax, n)` array so all 3 panels share the
    # same colour normalisation.
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    vmin_t = float(min(Ta.min(), Tb.min(), Ts.min()))
    vmax_t = float(max(Ta.max(), Tb.max(), Ts.max()))
    levels_t = np.linspace(vmin_t, vmax_t, 80)
    for ax, (field, title) in zip(axes, [
        (Ta, 'Ta — Fluid A (hot, +x)'),
        (Tb, 'Tb — Fluid B (cold, -y)'),
        (Ts, 'Ts — Solid'),
    ]):
        cf = ax.contourf(X, Y, field, levels=levels_t, cmap='turbo',
                          vmin=vmin_t, vmax=vmax_t, extend='both')
        cb = fig.colorbar(cf, ax=ax, format='%.1f', label='[K]')
        cb.mappable.set_clim(vmin_t, vmax_t)
        ax.set_title(title, fontweight='bold')
        ax.set_xlabel('x [mm]'); ax.set_ylabel('y [mm]')
        ax.set_aspect('equal')
    fig.suptitle(f'Temperature mid-z slice  (k={k_mid}/{Nz})', y=1.0)
    fig.tight_layout()
    p1 = os.path.join(outdir, '3d_air_air_temperature.png')
    fig.savefig(p1, dpi=120, bbox_inches='tight')
    plt.close(fig)

    # ── Velocity 2-panel (shared vmax) ──
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    vmax_v = float(max(vmag_A.max(), vmag_B.max() if vmag_B is not None else 0.0))
    levels_v = np.linspace(0.0, vmax_v, 80)
    for ax, (field, title) in zip(axes, [
        (vmag_A, '|v|_A — Fluid A (hot, +x)'),
        (vmag_B, '|v|_B — Fluid B (cold, -y)'),
    ]):
        if field is None:
            ax.set_visible(False); continue
        cf = ax.contourf(X, Y, field, levels=levels_v, cmap='turbo',
                          vmin=0.0, vmax=vmax_v, extend='both')
        cb = fig.colorbar(cf, ax=ax, format='%.2f', label='[m/s]')
        cb.mappable.set_clim(0.0, vmax_v)
        ax.set_title(title, fontweight='bold')
        ax.set_xlabel('x [mm]'); ax.set_ylabel('y [mm]')
        ax.set_aspect('equal')
    fig.suptitle('Velocity magnitude mid-z slice (interstitial)', y=1.0)
    fig.tight_layout()
    p2 = os.path.join(outdir, '3d_air_air_velocity.png')
    fig.savefig(p2, dpi=120, bbox_inches='tight')
    plt.close(fig)

    # ── Pressure 2-panel (shared clim) ──
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    p_min = float(P_A.min()); p_max = float(P_A.max())
    if P_B is not None:
        p_min = min(p_min, float(P_B.min()))
        p_max = max(p_max, float(P_B.max()))
    if p_max - p_min < 1e-12:
        p_max = p_min + 1.0
    levels_p = np.linspace(p_min, p_max, 80)
    for ax, (field, title) in zip(axes, [
        (P_A, 'P_A abs — Fluid A (+x)'),
        (P_B, 'P_B abs — Fluid B (-y)'),
    ]):
        if field is None:
            ax.set_visible(False); continue
        cf = ax.contourf(X, Y, field, levels=levels_p, cmap='turbo',
                          vmin=p_min, vmax=p_max, extend='both')
        cb = fig.colorbar(cf, ax=ax, format='%.2f', label='[kPa]')
        cb.mappable.set_clim(p_min, p_max)
        ax.set_title(title, fontweight='bold')
        ax.set_xlabel('x [mm]'); ax.set_ylabel('y [mm]')
        ax.set_aspect('equal')
    fig.suptitle('Pressure mid-z slice', y=1.0)
    fig.tight_layout()
    p3 = os.path.join(outdir, '3d_air_air_pressure.png')
    fig.savefig(p3, dpi=120, bbox_inches='tight')
    plt.close(fig)

    return p1, p2, p3


def plot_orthogonal_3d_slices(res, outdir, *, filename_prefix='3d_air_air_orthoslices'):
    """Three-view orthogonal slice plots for each scalar field — show the
    full 3D structure on 2D paper. Top (XY at mid-z), Front (XZ at mid-y),
    Side (YZ at mid-x). Uses real domain aspect ratio so the user reads
    the actual rectangle shape (182 × 42 × 42 mm — far from a cube).
    """
    f = res.fields
    Nx, Ny, Nz = f['Ta_display'].shape
    dx, dy, dz = res.grid['dx'], res.grid['dy'], res.grid['dz']
    xc = (np.cumsum(dx) - dx / 2) * 1000.0
    yc = (np.cumsum(dy) - dy / 2) * 1000.0
    zc = (np.cumsum(dz) - dz / 2) * 1000.0
    Lx_mm, Ly_mm, Lz_mm = dx.sum()*1000, dy.sum()*1000, dz.sum()*1000
    i_mid, j_mid, k_mid = Nx // 2, Ny // 2, Nz // 2

    fields = [
        ('Ta',  f['Ta_display'],  'turbo', '[K]', 'Ta — Fluid A (hot, +x stream)'),
        ('Tb',  f['Tb_display'],  'turbo', '[K]', 'Tb — Fluid B (cold, -y stream)'),
        ('Ts',  f['Ts_display'],  'turbo', '[K]', 'Ts — Solid (LTNE coupling)'),
        ('vmag', f['vmag_A'], 'turbo', '[m/s]', '|v|_A — Fluid A speed'),
        ('P_kPa', f['P_fA_display'] / 1000.0, 'turbo', '[kPa]', 'P_A abs — Fluid A pressure'),
    ]
    paths = []
    for fkey, F, cmap, unit, title in fields:
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
        vmin = float(F.min()); vmax = float(F.max())
        if vmax - vmin < 1e-12:
            vmax = vmin + 1.0
        levels = np.linspace(vmin, vmax, 80)

        # Top: XY plane at mid-z (look down -z)
        ax = axes[0]
        Y2, X2 = np.meshgrid(yc, xc)
        slc = F[:, :, k_mid]
        cf = ax.contourf(X2, Y2, slc, levels=levels, cmap=cmap,
                          vmin=vmin, vmax=vmax, extend='both')
        ax.set_title(f'TOP — XY @ z={zc[k_mid]:.1f} mm', fontweight='bold')
        ax.set_xlabel('x [mm]'); ax.set_ylabel('y [mm]')
        ax.set_aspect('equal')

        # Front: XZ plane at mid-y (look along -y)
        ax = axes[1]
        Z2, X2 = np.meshgrid(zc, xc)
        slc = F[:, j_mid, :]
        cf = ax.contourf(X2, Z2, slc, levels=levels, cmap=cmap,
                          vmin=vmin, vmax=vmax, extend='both')
        ax.set_title(f'FRONT — XZ @ y={yc[j_mid]:.1f} mm', fontweight='bold')
        ax.set_xlabel('x [mm]'); ax.set_ylabel('z [mm]')
        ax.set_aspect('equal')

        # Side: YZ plane at mid-x (look along -x)
        ax = axes[2]
        Z2, Y2 = np.meshgrid(zc, yc)
        slc = F[i_mid, :, :]
        cf = ax.contourf(Y2, Z2, slc, levels=levels, cmap=cmap,
                          vmin=vmin, vmax=vmax, extend='both')
        ax.set_title(f'SIDE — YZ @ x={xc[i_mid]:.1f} mm', fontweight='bold')
        ax.set_xlabel('y [mm]'); ax.set_ylabel('z [mm]')
        ax.set_aspect('equal')

        cb = fig.colorbar(cf, ax=axes.ravel().tolist(), shrink=0.8,
                           pad=0.02, label=unit, format='%.2f')
        cb.mappable.set_clim(vmin, vmax)
        fig.suptitle(
            f'{title}   |   domain {Lx_mm:.0f}×{Ly_mm:.0f}×{Lz_mm:.0f} mm '
            f'({Lx_mm/Lz_mm:.1f}:{Ly_mm/Lz_mm:.1f}:1)',
            fontweight='bold', y=1.02)
        p = os.path.join(outdir, f'{filename_prefix}_{fkey}.png')
        fig.savefig(p, dpi=120, bbox_inches='tight')
        plt.close(fig)
        paths.append(p)
    return paths


def main():
    cfg = build_cfg()
    print("Building 3D air-air case + running solver (3D LTNE × SIMPLE A+B)...")
    print(f"  Grid: {cfg.solver.Nx} × {cfg.solver.Ny} × {cfg.solver.Nz} = "
          f"{cfg.solver.Nx*cfg.solver.Ny*cfg.solver.Nz} cells")
    print(f"  Domain: {cfg.geometry.L_dom_m*1000:.0f} × {cfg.geometry.H_dom_m*1000:.0f} × "
          f"{cfg.geometry.Lz_m*1000:.0f} mm")
    print()
    import time
    t0 = time.time()
    case = prepare_case(cfg, case_id='demo-3d-air-air')
    res = run_case(case, RunControl(backend='python'))
    elapsed = time.time() - t0
    print(f"Solver wall-clock: {elapsed:.1f} s")
    print()
    passed = print_metrics(res, evaluate(res), cfg)
    outdir = str(Path(__file__).resolve().parents[3] / '.cache' / 'demos' / 'air_air')
    p1, p2, p3 = plot_clouds(res, outdir)
    print("MID-Z CLOUD PLOTS WRITTEN")
    print(f"  {p1}\n  {p2}\n  {p3}")
    print()
    paths = plot_orthogonal_3d_slices(res, outdir)
    print("3D ORTHOGONAL-SLICE PLOTS WRITTEN")
    for p in paths:
        print(f"  {p}")
    return 0 if passed else 2


if __name__ == '__main__':
    raise SystemExit(main())
