"""R4 evidence: 3D momentum SOU on/off grid-convergence comparison.

openspec solver-efficiency-r1-r4, task 4.3. Fixed representative D-F
coefficients (decoupled from the surrogate — this probes the convection
scheme only), air ideal-gas, streamwise y. Prints dP per (grid, scheme);
the gap between schemes vs its shrink rate under refinement is the
"is second-order worth promoting" evidence.

    python -m sjtu_tpmshx.runs.benchmark_sou_3d
"""
import time

import numpy as np
from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D

GRIDS = [(10, 40, 10), (20, 80, 20)]
K_VAL, CF_VAL = 2.0e-8, 100.0


def run(Nx, Ny, Nz, use_sou):
    s = SIMPLESolver3D(Lx=0.042, Ly=0.182, Lz=0.042, Nx=Nx, Ny=Ny, Nz=Nz,
                       rho=1.6, mu=2.35e-5, T_in=422.0, v_inlet=15.0,
                       eps=0.6,
                       K_arr=np.full((Ny, Nz), K_VAL),
                       cF_arr=np.full((Ny, Nz), CF_VAL),
                       P_ref_abs=192362.0)
    s.use_sou_momentum = use_sou
    t0 = time.perf_counter()
    conv, it = s.solve(max_iter=1500, verbose=False)
    wall = time.perf_counter() - t0
    dP = float(SIMPLESolver3D.extract_dP_face_extrap(s))
    return conv, it, wall, dP


def main():
    rows = []
    for (Nx, Ny, Nz) in GRIDS:
        r0 = run(Nx, Ny, Nz, False)
        r1 = run(Nx, Ny, Nz, True)
        gap = abs(r1[3] - r0[3]) / abs(r0[3])
        rows.append((Nx, Ny, Nz, r0, r1, gap))
        print(f"grid {Nx}x{Ny}x{Nz}:")
        print(f"  upwind1: conv={r0[0]} iters={r0[1]:4d} wall={r0[2]:6.2f}s"
              f" dP={r0[3]:9.1f} Pa")
        print(f"  SOU    : conv={r1[0]} iters={r1[1]:4d} wall={r1[2]:6.2f}s"
              f" dP={r1[3]:9.1f} Pa")
        print(f"  scheme gap |dP_sou-dP_up1|/dP_up1 = {gap:.3%}")
    if len(rows) >= 2:
        g_coarse, g_fine = rows[0][-1], rows[-1][-1]
        print(f"\ngap coarse->fine: {g_coarse:.3%} -> {g_fine:.3%}"
              f"  (shrinking gap = schemes converge to same solution;"
              f" large persistent gap = first-order diffusion is visible)")


if __name__ == '__main__':
    main()
