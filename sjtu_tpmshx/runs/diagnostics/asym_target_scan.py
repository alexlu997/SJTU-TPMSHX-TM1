"""
Phase 0.5：指定配比 (A%, B%, solid%) 反解 (C, δ) + 出每侧 ε/A0/D_h + 连通性。

核心：给定目标 (A,B)，用 φ 的分位数直接反解固体带边界——
  φ_lo = quantile(φ, A)      # void_A 上界 (δ−C)
  φ_hi = quantile(φ, 1−B)    # void_B 下界 (δ+C)
  δ = (φ_lo+φ_hi)/2,  C = (φ_hi−φ_lo)/2
体积配比按构造恒精确命中；唯一问号 = 连通性（两侧是否还贯穿）。
壁厚 = 2C（φ-单位常数，物理壁厚延后 STL）。

用法：python -m sjtu_tpmshx.runs.diagnostics.asym_target_scan
"""
import numpy as np

from sjtu_tpmshx.models.tpms_geometry import _phi_grid
from sjtu_tpmshx.models.asym_geometry import eps_sides, a0_sides_mc, dh_sides, percolates_z

N = 128
TPMS = ["Diamond", "Gyroid"]
L_mm = 5.0

# 目标 (A 占比, B 占比, 标签)；固体 = 1 − A − B
TARGETS = [
    (0.45, 0.45, "45/45/10 sym"),
    (0.60, 0.30, "60/30/10 r=2.0"),
    (0.70, 0.20, "70/20/10 r=3.5 <-YOURS"),
    (0.80, 0.10, "80/10/10 r=8.0"),
    (0.60, 0.20, "60/20/20 r=3.0 thickwall"),
    (0.50, 0.20, "50/20/30 r=2.5 thickwall"),
]


def solve_target(phi, A, B, L_m):
    flat = phi.ravel()
    phi_lo = float(np.quantile(flat, A))          # F^{-1}(A)
    phi_hi = float(np.quantile(flat, 1.0 - B))    # F^{-1}(1-B)
    delta = 0.5 * (phi_lo + phi_hi)
    C = 0.5 * (phi_hi - phi_lo)
    eps_A, eps_B, eps = eps_sides(phi, C, delta)
    A0_A, A0_B = a0_sides_mc(phi, C, delta, L_m, N)        # marching cubes 精确
    Dh_A, Dh_B = dh_sides(phi, C, delta, L_m, N, mc=True)
    pA = percolates_z(phi < (delta - C))
    pB = percolates_z(phi > (delta + C))
    return dict(C=C, delta=delta, eps_A=eps_A, eps_B=eps_B, solid=1.0 - eps,
                A0_A=A0_A, A0_B=A0_B, Dh_A=Dh_A, Dh_B=Dh_B, pA=pA, pB=pB)


def main():
    for tpms in TPMS:
        phi = _phi_grid(tpms, N)
        L_m = L_mm / 1000.0
        print(f"\n=== {tpms} (L={L_mm}mm, N={N}, wall=2C const) ===")
        hdr = (f"{'target':24s} {'C':>5s} {'delta':>6s} {'2C':>5s}  "
               f"{'epsA':>5s} {'epsB':>5s} {'solid':>6s}  "
               f"{'A0_A':>6s} {'A0_B':>6s}  {'DhA_mm':>7s} {'DhB_mm':>7s}  {'conn':>7s}")
        print(hdr)
        print("-" * len(hdr))
        for A, B, lab in TARGETS:
            r = solve_target(phi, A, B, L_m)
            conn = "OK" if (r["pA"] and r["pB"]) else (
                "cut-B" if not r["pB"] else "cut-A")
            print(f"{lab:24s} {r['C']:5.2f} {r['delta']:6.2f} {2*r['C']:5.2f}  "
                  f"{r['eps_A']*100:4.0f}% {r['eps_B']*100:4.0f}% {r['solid']*100:5.0f}%  "
                  f"{r['A0_A']:6.0f} {r['A0_B']:6.0f}  "
                  f"{r['Dh_A']*1e3:7.3f} {r['Dh_B']*1e3:7.3f}  {conn:>7s}")
        # 命中校验：ε_A/ε_B 应 == 目标
        r = solve_target(phi, 0.70, 0.20, L_m)
        print(f"  [check 70/20] eps_A={r['eps_A']*100:.1f}% eps_B={r['eps_B']*100:.1f}% "
              f"(target 70/20) -> 分位反解精确命中体积")


if __name__ == "__main__":
    main()
