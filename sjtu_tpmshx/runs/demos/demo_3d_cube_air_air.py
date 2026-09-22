"""demo_3d_cube_air_air.py — TRUE cube (50×50×50 mm) air-air case.

Same fluid defaults as `demo_3d_air_air.py` but L = H = Lz = 0.05 m so the
domain is literally cubic (1:1:1). Compare against the 4.3:1:1 brick to see
how cross-flow LTNE looks when both fluids have equal stream length.
"""
import os
from pathlib import Path

from sjtu_tpmshx.runs.demos.demo_3d_air_air import plot_orthogonal_3d_slices

from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack


def build_cube_cfg():
    # B2 2.6: canonical template; cube deltas = 50 mm cube, 20^3 grid.
    from sjtu_tpmshx.runs._case_template import build_cfg as _template_cfg
    return _template_cfg(L=0.050, H=0.050, Lz=0.050, Nx=20, Ny=20, Nz=20)


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
    outdir = str(Path(__file__).resolve().parents[3] / '.cache' / 'demos' / 'cube_air_air')
    os.makedirs(outdir, exist_ok=True)
    paths = plot_orthogonal_3d_slices(res, outdir, filename_prefix='3d_cube_air_air')
    print("CUBE ORTHO PLOTS WRITTEN")
    for p in paths:
        print(f"  {p}")
