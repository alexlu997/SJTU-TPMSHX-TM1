"""demo_3d_cube_air_air.py — TRUE cube (50×50×50 mm) air-air case.

Same fluid defaults as `demo_3d_air_air.py` but L = H = Lz = 0.05 m so the
domain is literally cubic (1:1:1). Compare against the 4.3:1:1 brick to see
how cross-flow LTNE looks when both fluids have equal stream length.
"""
import os
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack


def build_cube_cfg():
    # B2 2.6: canonical template; cube deltas = 50 mm cube, 20^3 grid.
    from sjtu_tpmshx.runs._case_template import build_cfg as _template_cfg
    return _template_cfg(L=0.050, H=0.050, Lz=0.050, Nx=20, Ny=20, Nz=20)


def plot_cube_ortho(res, cfg, outdir):
    Nx, Ny, Nz = res['Ta'].shape
    dx, dy, dz = res['dx'], res['dy'], res['dz']
    xc = (np.cumsum(dx) - dx / 2) * 1000.0
    yc = (np.cumsum(dy) - dy / 2) * 1000.0
    zc = (np.cumsum(dz) - dz / 2) * 1000.0
    Lx_mm, Ly_mm, Lz_mm = res['Lx']*1000, res['Ly']*1000, res['Lz']*1000
    i_mid, j_mid, k_mid = Nx // 2, Ny // 2, Nz // 2

    fields = [
        ('Ta',  res['Ta'],  '[K]', 'Ta — Fluid A (hot, +x)'),
        ('Tb',  res['Tb'],  '[K]', 'Tb — Fluid B (cold, -y)'),
        ('Ts',  res['Ts'],  '[K]', 'Ts — Solid (LTNE coupling)'),
        ('vmag', res['vmag'], '[m/s]', '|v|_A — Fluid A speed'),
        ('P_kPa', res['P_kPa'], '[kPa]', 'P_A — Fluid A abs'),
    ]
    paths = []
    for fkey, F, unit, title in fields:
        fig, axes = plt.subplots(1, 3, figsize=(13, 4))
        vmin = float(F.min()); vmax = float(F.max())
        if vmax - vmin < 1e-12:
            vmax = vmin + 1.0
        levels = np.linspace(vmin, vmax, 80)

        ax = axes[0]
        Y2, X2 = np.meshgrid(yc, xc)
        cf = ax.contourf(X2, Y2, F[:, :, k_mid], levels=levels, cmap='turbo',
                          vmin=vmin, vmax=vmax, extend='both')
        ax.set_title(f'TOP — XY @ z={zc[k_mid]:.1f} mm', fontweight='bold')
        ax.set_xlabel('x [mm]'); ax.set_ylabel('y [mm]')
        ax.set_aspect('equal')

        ax = axes[1]
        Z2, X2 = np.meshgrid(zc, xc)
        cf = ax.contourf(X2, Z2, F[:, j_mid, :], levels=levels, cmap='turbo',
                          vmin=vmin, vmax=vmax, extend='both')
        ax.set_title(f'FRONT — XZ @ y={yc[j_mid]:.1f} mm', fontweight='bold')
        ax.set_xlabel('x [mm]'); ax.set_ylabel('z [mm]')
        ax.set_aspect('equal')

        ax = axes[2]
        Z2, Y2 = np.meshgrid(zc, yc)
        cf = ax.contourf(Y2, Z2, F[i_mid, :, :], levels=levels, cmap='turbo',
                          vmin=vmin, vmax=vmax, extend='both')
        ax.set_title(f'SIDE — YZ @ x={xc[i_mid]:.1f} mm', fontweight='bold')
        ax.set_xlabel('y [mm]'); ax.set_ylabel('z [mm]')
        ax.set_aspect('equal')

        cb = fig.colorbar(cf, ax=axes.ravel().tolist(), shrink=0.8,
                           pad=0.02, label=unit, format='%.2f')
        cb.mappable.set_clim(vmin, vmax)
        fig.suptitle(
            f'{title}   |   CUBE {Lx_mm:.0f}×{Ly_mm:.0f}×{Lz_mm:.0f} mm '
            f'(1:1:1)',
            fontweight='bold', y=1.02)
        p = os.path.join(outdir, f'3d_cube_air_air_{fkey}.png')
        fig.savefig(p, dpi=120, bbox_inches='tight')
        plt.close(fig)
        paths.append(p)
    return paths


if __name__ == '__main__':
    cfg = build_cube_cfg()
    print("=" * 70)
    print(" TRUE CUBE 3D AIR-AIR DEMO — 50×50×50 mm (1:1:1)")
    print("=" * 70)
    print(f"  Grid: {cfg['Nx']}^3 = {cfg['Nx']**3} cells")
    print(f"  Driving ΔT: {cfg['T_inA']-cfg['T_inB']:.1f} K")
    print(f"  u_A / u_B : {cfg['u_A']:.1f} / {cfg['u_B']:.1f} m/s")
    print(f"  ε / D_h   : {cfg['eps']:.3f} / {cfg['D_h']*1000:.3f} mm")
    print()
    import time
    t0 = time.time()
    res = _run_3d_stack(cfg)
    print(f"Solver wall-clock: {time.time()-t0:.1f} s")
    print()
    print("  PRIMARY METRICS")
    print(f"    Q (air-side duty)   : {res['Q']:.2f}  W")
    print(f"    Q_enthalpy_A        : {res['Q_enthalpy_A']:.2f}  W")
    print(f"    Q_enthalpy_B        : {res['Q_enthalpy_B']:.2f}  W")
    print(f"    dP_A                : {res['dP']:.1f}  Pa")
    print(f"    dP_B                : {res['dP_B']:.1f}  Pa")
    print(f"    T_A_out             : {res['T_A_out']:.2f} K  "
          f"(ΔT_A = {cfg['T_inA']-res['T_A_out']:.2f} K)")
    print(f"    T_B_out             : {res['T_B_out']:.2f} K  "
          f"(ΔT_B = {res['T_B_out']-cfg['T_inB']:.2f} K)")
    print(f"    Q_net  (LTNE 守恒)  : {res.get('Q_net', float('nan')):.3e} W")
    print(f"    AB_interior         : {res.get('AB_interior', float('nan'))*100:.2f} %")
    print(f"    mass imbal A/B      : "
          f"{res.get('mass_imbalance_rel_A', 0)*100:.4f}% / "
          f"{res.get('mass_imbalance_rel_B', 0)*100:.4f}%")
    print()
    print("  EFFECTIVENESS (cross-flow)")
    eps_A = (cfg['T_inA'] - res['T_A_out']) / (cfg['T_inA'] - cfg['T_inB'])
    eps_B = (res['T_B_out'] - cfg['T_inB']) / (cfg['T_inA'] - cfg['T_inB'])
    print(f"    ε_A = ΔT_A / ΔT_max : {eps_A:.3f}")
    print(f"    ε_B = ΔT_B / ΔT_max : {eps_B:.3f}")
    print()
    print("  FIELD STATS")
    Ta = res['Ta']; Tb = res['Tb']; Ts = res['Ts']
    vmag = res['vmag']; P_kPa = res['P_kPa']
    print(f"    Ta range : [{Ta.min():.2f}, {Ta.max():.2f}] K")
    print(f"    Tb range : [{Tb.min():.2f}, {Tb.max():.2f}] K")
    print(f"    Ts range : [{Ts.min():.2f}, {Ts.max():.2f}] K")
    print(f"    |v|_A    : [{vmag.min():.3f}, {vmag.max():.3f}] m/s")
    print(f"    P_A      : [{P_kPa.min():.2f}, {P_kPa.max():.2f}] kPa")
    print()
    outdir = os.path.join(os.path.dirname(__file__), 'demo_output')
    os.makedirs(outdir, exist_ok=True)
    paths = plot_cube_ortho(res, cfg, outdir)
    print("CUBE ORTHO PLOTS WRITTEN")
    for p in paths:
        print(f"  {p}")
