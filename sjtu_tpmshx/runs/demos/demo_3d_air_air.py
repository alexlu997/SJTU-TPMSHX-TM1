"""demo_3d_air_air.py — fire a 3D air-air run with the new GUI defaults.

Drives `_run_3d_stack` directly (no Qt) so we can inspect numerical results
and dump mid-z cloud plots without a display server.

Defaults mirror ui_builders.py:
    Geometry: L=0.182 m, H=0.042 m, Lz=0.042 m, Nx=30, Ny=20, Nz=5
    TPMS    : Gyroid, L_cell=7 mm, t=0.5 mm (in-range for ConstDF-v1)
    Solid   : k_s = 16 W/(m·K)
    Fluid A : Air, u_A=20 m/s, T_inA=422 K, P_inA=192362 Pa, +x stream
    Fluid B : Air, u_B=10 m/s, T_inB=293.15 K, P_inB=101325 Pa, -y stream
"""
import os
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
from sjtu_tpmshx.runs._case_template import build_cfg as _template_cfg


def build_cfg():
    # B2 2.6: canonical template; this demo IS the template defaults
    # except its 30x20x5 grid.
    return _template_cfg(Nx=30, Ny=20, Nz=5)


def print_metrics(res, cfg):
    print("=" * 70)
    print(" 3D AIR-AIR DEMO — current defaults (Gyroid 0.182×0.042×0.042 m)")
    print("=" * 70)
    print(f"  Driving ΔT     : {cfg['T_inA'] - cfg['T_inB']:.1f} K  "
          f"(T_inA={cfg['T_inA']:.1f}, T_inB={cfg['T_inB']:.2f})")
    print(f"  u_A / u_B      : {cfg['u_A']:.1f} / {cfg['u_B']:.1f} m/s")
    print(f"  ε (porosity)   : {cfg['eps']:.4f}")
    print(f"  D_h            : {cfg['D_h']*1000:.3f} mm")
    print()
    print("  PRIMARY METRICS")
    print(f"    Q (air-side duty)   : {res['Q']:.2f}  W")
    print(f"    Q_enthalpy_A        : {res['Q_enthalpy_A']:.2f}  W   "
          f"(m_dot·cp·|T_inA-T_A_out|)")
    print(f"    Q_enthalpy_B        : {res['Q_enthalpy_B']:.2f}  W")
    print(f"    Q_solid_B (diag)    : {res['Q_solid_B']:.2f}  W   "
          f"(∫h_vB·(Ts-Tb)·dV)")
    print(f"    Q_interior          : {res.get('Q_interior', float('nan')):.2f} W "
          f"(BC-layer excluded)")
    print()
    print(f"    dP_A                : {res['dP']:.1f}  Pa")
    print(f"    dP_B                : {res['dP_B']:.1f}  Pa")
    print()
    print(f"    T_A_out (mass-wgt)  : {res['T_A_out']:.2f} K  "
          f"(ΔT_A = {cfg['T_inA']-res['T_A_out']:.2f} K)")
    print(f"    T_B_out (mass-wgt)  : {res['T_B_out']:.2f} K  "
          f"(ΔT_B = {res['T_B_out']-cfg['T_inB']:.2f} K)")
    print()
    print("  CONSERVATION DIAGNOSTICS")
    print(f"    Q_sA (LTNE)         : {res.get('Q_sA', float('nan')):.2f} W")
    print(f"    Q_sB (LTNE)         : {res.get('Q_sB', float('nan')):.2f} W")
    print(f"    Q_net  (= Q_sA+Q_sB): {res.get('Q_net', float('nan')):.3e} W "
          f"(should → 0)")
    print(f"    energy_imbalance_rel: {res.get('energy_imbalance_rel', float('nan'))*100:.3f} %")
    print(f"    mass_imbal_rel_A    : {res.get('mass_imbalance_rel_A', float('nan'))*100:.3f} %")
    print(f"    mass_imbal_rel_B    : {res.get('mass_imbalance_rel_B', float('nan'))*100:.3f} %")
    print(f"    AB_interior         : {res.get('AB_interior', float('nan'))*100:.2f} %")
    print()
    print("  FIELD STATS (mid-z slice)")
    Nz = res['Ta'].shape[2]
    k_mid = Nz // 2
    Ta = res['Ta'][:, :, k_mid]
    Tb = res['Tb'][:, :, k_mid]
    Ts = res['Ts'][:, :, k_mid]
    vmag = res['vmag'][:, :, k_mid]
    P_kPa = res['P_kPa'][:, :, k_mid]
    print(f"    Ta  range   : [{Ta.min():.2f}, {Ta.max():.2f}] K")
    print(f"    Tb  range   : [{Tb.min():.2f}, {Tb.max():.2f}] K")
    print(f"    Ts  range   : [{Ts.min():.2f}, {Ts.max():.2f}] K")
    print(f"    |v|_A range : [{vmag.min():.4f}, {vmag.max():.3f}] m/s")
    print(f"    P_A range   : [{P_kPa.min():.2f}, {P_kPa.max():.2f}] kPa")
    print()


def plot_clouds(res, cfg, outdir):
    os.makedirs(outdir, exist_ok=True)
    Nx, Ny, Nz = res['Ta'].shape
    k_mid = Nz // 2
    dx = res['dx']; dy = res['dy']
    xc = (np.cumsum(dx) - dx / 2) * 1000.0   # mm
    yc = (np.cumsum(dy) - dy / 2) * 1000.0
    Y, X = np.meshgrid(yc, xc)

    Ta = res['Ta'][:, :, k_mid]; Tb = res['Tb'][:, :, k_mid]
    Ts = res['Ts'][:, :, k_mid]
    vmag_A = res['vmag'][:, :, k_mid]
    vmag_B = res.get('vmag_B')
    if vmag_B is not None:
        vmag_B = vmag_B[:, :, k_mid]
    P_A = res['P_kPa'][:, :, k_mid]
    P_B = None
    if res.get('P_Pa_B') is not None:
        P_B = res['P_Pa_B'][:, :, k_mid] / 1000.0

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


def plot_orthogonal_3d_slices(res, cfg, outdir):
    """Three-view orthogonal slice plots for each scalar field — show the
    full 3D structure on 2D paper. Top (XY at mid-z), Front (XZ at mid-y),
    Side (YZ at mid-x). Uses real domain aspect ratio so the user reads
    the actual rectangle shape (182 × 42 × 42 mm — far from a cube).
    """
    Nx, Ny, Nz = res['Ta'].shape
    dx, dy, dz = res['dx'], res['dy'], res['dz']
    xc = (np.cumsum(dx) - dx / 2) * 1000.0
    yc = (np.cumsum(dy) - dy / 2) * 1000.0
    zc = (np.cumsum(dz) - dz / 2) * 1000.0
    Lx_mm, Ly_mm, Lz_mm = res['Lx']*1000, res['Ly']*1000, res['Lz']*1000
    i_mid, j_mid, k_mid = Nx // 2, Ny // 2, Nz // 2

    fields = [
        ('Ta',  res['Ta'],  'turbo', '[K]', 'Ta — Fluid A (hot, +x stream)'),
        ('Tb',  res['Tb'],  'turbo', '[K]', 'Tb — Fluid B (cold, -y stream)'),
        ('Ts',  res['Ts'],  'turbo', '[K]', 'Ts — Solid (LTNE coupling)'),
        ('vmag', res['vmag'], 'turbo', '[m/s]', '|v|_A — Fluid A speed'),
        ('P_kPa', res['P_kPa'], 'turbo', '[kPa]', 'P_A abs — Fluid A pressure'),
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
        p = os.path.join(outdir, f'3d_air_air_orthoslices_{fkey}.png')
        fig.savefig(p, dpi=120, bbox_inches='tight')
        plt.close(fig)
        paths.append(p)
    return paths


if __name__ == '__main__':
    cfg = build_cfg()
    print("Building 3D air-air case + running solver (3D LTNE × SIMPLE A+B)...")
    print(f"  Grid: {cfg['Nx']} × {cfg['Ny']} × {cfg['Nz']} = "
          f"{cfg['Nx']*cfg['Ny']*cfg['Nz']} cells")
    print(f"  Domain: {cfg['L']*1000:.0f} × {cfg['H']*1000:.0f} × "
          f"{cfg['Lz']*1000:.0f} mm  "
          f"(NOT a cube — aspect "
          f"{cfg['L']/cfg['Lz']:.1f}:{cfg['H']/cfg['Lz']:.1f}:1)")
    print()
    import time
    t0 = time.time()
    res = _run_3d_stack(cfg)
    elapsed = time.time() - t0
    print(f"Solver wall-clock: {elapsed:.1f} s")
    print()
    print_metrics(res, cfg)
    outdir = os.path.join(os.path.dirname(__file__), 'demo_output')
    p1, p2, p3 = plot_clouds(res, cfg, outdir)
    print("MID-Z CLOUD PLOTS WRITTEN")
    print(f"  {p1}\n  {p2}\n  {p3}")
    print()
    paths = plot_orthogonal_3d_slices(res, cfg, outdir)
    print("3D ORTHOGONAL-SLICE PLOTS WRITTEN")
    for p in paths:
        print(f"  {p}")
