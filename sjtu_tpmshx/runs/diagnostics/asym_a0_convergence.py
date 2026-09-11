"""
A0 网格收敛诊断（非对称孔隙率，极端 δ）。

回答「偏极端非对称下 A0 算得准吗 / 体素粗网格误差」(2026-06-09):
  1. voxel vs marching-cubes：极端 δ 全程一致 <1%（1.553 修正在极端 δ 仍 work；
     「voxel 25% 高估」未复现）→ 误差源**不是方法**。
  2. ε（体积）：瞬间收敛，准。
  3. 薄侧 A0_B（挤压侧 εB≈0.12）：marching-cubes 面积**从下方慢收敛**，
     N=128 低 ~3%，N≥200 <1%（与壁厚无关，纯分辨率）。
  4. Richardson 3-网格外推（a0_sides_richardson）：从便宜网格 (96,144,216) 即 <1%。

用法: python -u runs/asym_a0_convergence.py
"""
import sys

from sjtu_tpmshx.models.tpms_geometry import _phi_grid, _find_C_for_eps
from sjtu_tpmshx.models.asym_geometry import (
    eps_sides, a0_sides, a0_sides_mc, a0_sides_richardson, find_delta_max,
)

TP = "Diamond"
L_M = 0.005


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    phiR = _phi_grid(TP, 256)
    for poro in (0.85, 0.90):                     # solid 15% / 10%（壁越来越薄）
        C = _find_C_for_eps(phiR, poro)
        dmax = find_delta_max(phiR, C)
        delta = 0.9 * dmax                        # 近连通极限 → 薄侧最薄
        eA0, eB0, _ = eps_sides(phiR, C, delta)
        print(f"=== {TP}  solid={1-poro:.0%}  C={C:.3f}  delta={delta:.3f}(0.9dmax)  "
              f"r=epsA:epsB={eA0/eB0:.1f}:1 ===")
        print(f"{'N':>5} {'epsB':>6} | {'A0B_mc':>8} {'A0B_vox':>8} {'vox/mc':>7} | dA0B_mc")
        pb = None
        for N in (96, 128, 160, 200, 256):
            phi = _phi_grid(TP, N)
            _, eB, _ = eps_sides(phi, C, delta)
            _, aB = a0_sides_mc(phi, C, delta, L_M, N)
            _, vB = a0_sides(phi, C, delta, L_M, N)
            d = f"{abs(aB - pb) / pb * 100:4.1f}%" if pb else "   -"
            print(f"{N:5d} {eB:6.3f} | {aB:8.1f} {vB:8.1f} {vB/aB:6.2f}x | {d}")
            pb = aB
        # Richardson 外推 vs 单网格 vs 近收敛参考
        _, richB = a0_sides_richardson(TP, C, delta, L_M, Ns=(96, 144, 216))
        _, ref = a0_sides_mc(_phi_grid(TP, 288), C, delta, L_M, 288)
        _, mc128 = a0_sides_mc(_phi_grid(TP, 128), C, delta, L_M, 128)
        print(f"  Richardson(96,144,216) A0B={richB:.1f}  vs ref(N=288)={ref:.1f} "
              f"({abs(richB-ref)/ref*100:.1f}%)  vs single mc128={mc128:.1f} "
              f"({abs(mc128-ref)/ref*100:.1f}%)\n")


if __name__ == "__main__":
    main()
