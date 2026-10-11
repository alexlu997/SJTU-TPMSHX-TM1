"""demo_3d_cube_air_air.py — TRUE cube (50×50×50 mm) air-air case.

Same fluid defaults as `demo_3d_air_air.py` but L = H = Lz = 0.05 m so the
domain is literally cubic (1:1:1). Compare against the 4.3:1:1 brick to see
how cross-flow LTNE looks when both fluids have equal stream length.
"""
import os
from pathlib import Path

from sjtu_tpmshx.runs.demos.demo_3d_air_air import (
    build_cfg, plot_orthogonal_3d_slices, print_metrics,
)
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate


def build_cube_cfg():
    return build_cfg(L=0.050, H=0.050, Lz=0.050, Nx=20, Ny=20, Nz=20)


def main():
    cfg = build_cube_cfg()
    print("=" * 70)
    print(" TRUE CUBE 3D AIR-AIR DEMO — 50×50×50 mm (1:1:1)")
    print("=" * 70)
    print(f"  Grid: {cfg.solver.Nx}^3 = {cfg.solver.Nx**3} cells")
    print()
    import time
    t0 = time.time()
    case = prepare_case(cfg, case_id='demo-3d-cube-air-air')
    res = run_case(case, RunControl(backend='python'))
    print(f"Solver wall-clock: {time.time()-t0:.1f} s")
    print()
    passed = print_metrics(res, evaluate(res), cfg)
    print("  BACKEND TEMPERATURE RATIOS (original outlet diagnostics)")
    diagnostics = res.metadata['diagnostics']
    delta_T = cfg.fluid_A.T_in_K - cfg.fluid_B.T_in_K
    eps_A = (cfg.fluid_A.T_in_K - diagnostics['T_A_out']) / delta_T
    eps_B = (diagnostics['T_B_out'] - cfg.fluid_B.T_in_K) / delta_T
    print(f"    ε_A = ΔT_A / ΔT_max : {eps_A:.3f}")
    print(f"    ε_B = ΔT_B / ΔT_max : {eps_B:.3f}")
    print()
    print("  DISPLAY FIELD STATS (full volume)")
    Ta = res.fields['Ta_display']; Tb = res.fields['Tb_display']; Ts = res.fields['Ts_display']
    vmag = res.fields['vmag_A']; P_kPa = res.fields['P_fA_display'] / 1000.0
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
    return 0 if passed else 2


if __name__ == '__main__':
    raise SystemExit(main())
