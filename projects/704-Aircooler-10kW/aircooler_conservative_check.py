"""空冷器: 旧 2D plug-velocity 内核 vs 最新守恒内核 (conservative_ltne) 对照。

设计路径用解析 plug 速度 (秒级)。守恒内核 (B-plan, strict-conservation 3D default)
需交错 SIMPLE 面速度。本脚本构造与 plug 速度一致的**均匀**交错面 (常量场天然
solenoidal → telescoping 精确成立), 在同一定尺几何 / 同一 h_v / 同一入口物性下,
仅替换能量离散内核, 隔离对 Q / 出口温 / 能量守恒的纯内核影响。
"""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import sjtu_tpmshx.design.sizing as SZ
SZ.S_MAX = 2.0; SZ.LX_MAX = 2.0          # 放开包络 (同 predict 脚本)
from sjtu_tpmshx.design.sizing import size_fixed_cell
from sjtu_tpmshx.design.forward import forward, _hvol, K_STEEL, GEOM_N, NX, NY_CROSS
from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry
from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d
from predict_aircooler_10kw import build_cases

K0 = 273.15
NZ_CONS = 4                               # 守恒内核 z 层 (>1 才进 3D 内核; plug 在 z 均匀)


def _cons_one(case, topo, l, t, s, sz, Lx, k_s, Th_eval, Tc_eval, seed):
    """守恒内核单趟解 (Nz=NZ_CONS + 均匀交错面)。物性在 Th_eval/Tc_eval 取值。"""
    geo = tpms_geometry(topo, l, t, k_s, N=GEOM_N)
    EPS, EPS_A, A0, D_h = geo["epsilon"], geo["epsilon_A"], geo["A_0"], geo["D_h"]
    Ny, Nz = NY_CROSS, NZ_CONS
    shp = (NX, Ny, Nz); zc = np.zeros(shp)
    h_vA, Re_h, u_h, pA = _hvol(case.hot_fluid, topo, l, t, A0, D_h, EPS_A,
                                case.mdot_h, s, sz, Th_eval, case.P_in_h)
    h_vB, Re_c, u_c, pB = _hvol(case.cold_fluid, topo, l, t, A0, D_h, EPS_A,
                                case.mdot_c, Lx, sz, Tc_eval, case.P_in_c)
    ucA = np.full(shp, u_h); vcB = np.full(shp, u_c)        # cell-centred plug
    ufA = np.full((NX + 1, Ny, Nz), u_h)                    # A +x 均匀面 (solenoidal)
    vfA = np.zeros((NX, Ny + 1, Nz)); wfA = np.zeros((NX, Ny, Nz + 1))
    vfB = np.full((NX, Ny + 1, Nz), u_c)                    # B +y 均匀面
    ufB = np.zeros((NX + 1, Ny, Nz)); wfB = np.zeros((NX, Ny, Nz + 1))
    Ta0 = Tb0 = Ts0 = None
    if seed is not None:
        Ta0, Tb0, Ts0 = seed
    out = solve_full_domain_3d(
        Lx, s, sz, NX, Ny, Nz, case.T_in_h, case.T_in_c,
        np.full(shp, EPS_A * pA.k), np.full(shp, EPS_A * pB.k),
        np.full(shp, (1.0 - EPS) * k_s),
        np.full(shp, h_vA), np.full(shp, h_vB),
        pA.rho * pA.cp, pB.rho * pB.cp, np.full(shp, EPS),
        ucA, zc, zc, zc, vcB, zc, dir_A=0, dir_B=2,
        Ta_init=Ta0, Tb_init=Tb0, Ts_init=Ts0,
        dx_arr=np.full(NX, Lx / NX), dy_arr=np.full(Ny, s / Ny),
        dz_arr=np.full(Nz, sz / Nz),
        max_iter=30000, tol=1e-6, alpha_T=0.7,
        ufA=ufA, vfA=vfA, wfA=wfA, ufB=ufB, vfB=vfB, wfB=wfB,
        conservative_ltne=True, return_info=True)
    if len(out) == 4:
        Ta, Tb, Ts, info = out
    else:
        Ta, Tb, Ts = out; info = {}
    Toh = float(np.asarray(Ta)[-1, :, :].mean())
    Toc = float(np.asarray(Tb)[:, -1, :].mean())
    return (Ta, Tb, Ts), Toh, Toc, pA, pB, Re_h, Re_c, info


def conservative_solve(case, topo, l, t, s, Lx, k_s=K_STEEL, prop_model="mean"):
    """守恒内核定值。prop_model='mean' → 2-pass 均温物性 (匹配报告口径)。"""
    sz = s                                                  # 方形
    fld, Toh, Toc, pA, pB, Re_h, Re_c, info = _cons_one(
        case, topo, l, t, s, sz, Lx, k_s, case.T_in_h, case.T_in_c, None)
    if prop_model == "mean":
        Th = 0.5 * (case.T_in_h + Toh); Tc = 0.5 * (case.T_in_c + Toc)
        fld, Toh, Toc, pA, pB, Re_h, Re_c, info = _cons_one(
            case, topo, l, t, s, sz, Lx, k_s, Th, Tc, fld)
    Q_h = case.mdot_h * pA.cp * (case.T_in_h - Toh)
    Q_c = case.mdot_c * pB.cp * (Toc - case.T_in_c)
    return dict(Toh=Toh, Toc=Toc, Q_h=Q_h, Q_c=Q_c, Re_h=Re_h, Re_c=Re_c,
                eps_A=info.get("eps_A_strict"), eps_B=info.get("eps_B_strict"))


def main():
    topo, l, t = "Diamond", 6.0, 0.4
    pm = "mean"                                             # 匹配报告口径
    cases = build_cases()
    print(f"[size] 旧 2D 定尺 {topo} l{l}/t{t} 叉流 (prop={pm}) ...")
    d = size_fixed_cell(cases, topo, l, t, "cross", prop_model=pm)
    s, Lx = d.s, d.Lx
    print(f"  s={s*1e3:.1f}mm Lx={Lx*1e3:.1f}mm V={d.V*1e3:.3f}L  (Nz_cons={NZ_CONS})\n")

    print(f"{'工况':<5}{'内核':<9}{'出风°C':>9}{'出水°C':>9}{'Q_air W':>11}"
          f"{'Q_wat W':>11}{'守恒A%':>9}{'守恒B%':>9}{'A-B失衡%':>10}")
    print("-" * 80)
    for c in cases:
        r = forward(c, topo, l, t, s, Lx, "cross", prop_model=pm)
        imb0 = abs(r.Q_hot - r.Q_cold) / max(abs(r.Q_hot), 1.0) * 100
        print(f"#{c.case:<4}{'旧 2D':<9}{r.T_out_hot-K0:>9.2f}{r.T_out_cold-K0:>9.2f}"
              f"{r.Q_hot:>11.0f}{r.Q_cold:>11.0f}{'—':>9}{'—':>9}{imb0:>10.2f}")
        t0 = time.time()
        cc = conservative_solve(c, topo, l, t, s, Lx, prop_model=pm)
        dt = time.time() - t0
        imb = abs(cc["Q_h"] - cc["Q_c"]) / max(abs(cc["Q_h"]), 1.0) * 100
        sa = f"{cc['eps_A']*100:.3f}" if cc["eps_A"] is not None else "n/a"
        sb = f"{cc['eps_B']*100:.3f}" if cc["eps_B"] is not None else "n/a"
        print(f"#{c.case:<4}{'守恒 3D':<9}{cc['Toh']-K0:>9.2f}{cc['Toc']-K0:>9.2f}"
              f"{cc['Q_h']:>11.0f}{cc['Q_c']:>11.0f}{sa:>9}{sb:>9}{imb:>10.2f}  ({dt:.0f}s)")
        print()


if __name__ == "__main__":
    main()
