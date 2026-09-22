"""cf_cross_fluid.py — 当前生产 CFD 基线上的三数据集有效 cF 对照.

本工具从 air、water、sCO2 三套实验数据反演 effective cF 并并列比较。
三套数据来自不同实验层级、边界和测量配置；比较结果只描述数据集适用域，
不能在缺少同装置对照时解释为工质本征效应。

    C ≡ μ̄·G/K + cF·G²          （G = ṁ/A_flow 质量流密度，逐流体同定义）
      空气（可压 ideal-gas）:  C = (P_in² − P_out²) / (2·R·T̄·L)
      水 / sCO2（不可压）:     C = ρ̄·ΔP / L
    ⇒ cF_meas = (C − μ̄·G/K) / G²

K 统一取当前生产 `cfd_full_core_3cell_fixed_v2` 的 7/0.6 节点，不复用旧 dev
表或旧 gamma。K 的份额和 K±50% 敏感性同时输出。

**口径已核（这是本工具能成立的前提）**：气侧工具的 A_flow
（D 5.94e-4 / G 6.50e-4 m²）与 sCO2 实验表自带的 A_flow
（D 5.9359e-4 / G 6.4915e-4）逐位一致，L 同为 0.182 m，Dh 同源
——气与 sCO2 表面记录的面积/长度口径一致，工具启动时断言之；这并不排除
测点、歧管、突缩突扩、仪器零点或数据归约等 campaign 系统差异。
water+air 试件是对称、delta=0 的两个完整且互不连通的流体网络；Gyroid 空气
使用 4 月 1 日直通数据，互换流道不等于双侧全端面入口。
water 与 air 使用相同的单侧有效 A_flow，不按通道数
28/34 缩放，也不使用 42×42 mm 几何端面或简单除以 2。

用法（从仓库根）:
    python -m sjtu_tpmshx.validation.df_refit.cf_cross_fluid

输出: stdout 记分板 + .cache/reports/df_refit/cf_cross_fluid.csv。生产零改动。
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from sjtu_tpmshx.validation.hx_experiments import (
    AIR_BOOKS, A_FLOW, L_FLOW, P_ATM, R_AIR, DH_REF, air_mu, load_air_cases, load_water_cases)
from sjtu_tpmshx.validation.sco2_exp.load_sco2_exp import load_exp
from sjtu_tpmshx.df_surrogate.full_core_3cell_fixed_v2 import FullCore3CellFixedDFV2
from sjtu_tpmshx.models.fluid_props import check_water_state
from sjtu_tpmshx.models.tpms_props import water_density, water_viscosity
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
REPORT_DIR = _REPO / ".cache" / "reports" / "df_refit"
_TOPOS = ("Diamond", "Gyroid")


def _base_node(topo: str) -> tuple[float, float]:
    return FullCore3CellFixedDFV2(topo).predict(7.0, 0.6)


def _assert_same_caliber() -> dict:
    """气侧常量 vs sCO2 表自带几何：不一致就停手（口径差会伪装成物理）。"""
    out = {}
    for topo in _TOPOS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            a = load_exp(topo).attrs
        rel_A = abs(a["A_flow_m2"] - A_FLOW[topo]) / A_FLOW[topo]
        rel_L = abs(a["L_ch_m"] - L_FLOW) / L_FLOW
        if rel_A > 0.01 or rel_L > 0.01:
            raise RuntimeError(
                f"{topo}: 口径不一致 A {a['A_flow_m2']:.4e} vs "
                f"{A_FLOW[topo]:.4e}（{rel_A:.1%}）/ L {a['L_ch_m']} vs "
                f"{L_FLOW}（{rel_L:.1%}）——先核口径再谈跨流体")
        out[topo] = dict(A_sheet=a["A_flow_m2"], A_air=A_FLOW[topo],
                         rel_A=rel_A, Dh=a["Dh_m"])
    return out


def _cf_from_C(C: np.ndarray, G: np.ndarray, mu: np.ndarray,
               K: float) -> tuple[np.ndarray, np.ndarray]:
    """(cF_meas, Darcy 份额)。"""
    darcy = mu * G / K
    return (C - darcy) / (G * G), darcy / C


def collect() -> pd.DataFrame:
    rows = []
    for topo in _TOPOS:
        K, _cF_base_unused = _base_node(topo)

        # 只按原始数据质量取样，不以旧 gamma 模型的预测是否有解筛行。
        a = load_air_cases(topo)
        a = a[~a.excluded]
        P_in = P_ATM + a["空气进口压力/Pa"].to_numpy(float)
        dp = (a["空气进口压力/Pa"] - a["空气出口压力/Pa"]).to_numpy(float)
        P_out = P_in - dp
        T_bar = 0.5 * (a["空气进口温度/℃"].to_numpy(float) + 273.15
                       + a["空气出口温度/℃"].to_numpy(float) + 273.15)
        G = a["样机空气流量kg/s"].to_numpy(float) / A_FLOW[topo]
        mu = np.array([air_mu(t) for t in T_bar])
        Re = G * DH_REF / mu
        C = (P_in ** 2 - P_out ** 2) / (2.0 * R_AIR * T_bar * L_FLOW)
        cf, dsh = _cf_from_C(C, G, mu, K)
        for i in range(len(a)):
            rows.append(dict(fluid="air", topo=topo, case=str(a.case.iloc[i]), Re=float(Re[i]),
                             source=AIR_BOOKS[topo][0],
                             G=float(G[i]), cF_meas=float(cf[i]),
                             darcy_frac=float(dsh[i]), A_used=A_FLOW[topo]))

        # ---- 水：不可压 ----
        w = load_water_cases(topo)
        w = w[~(w.dp_nonphysical | w.dup_row)]
        T_bar_w = 0.5 * (w["水进口温度/℃"].to_numpy(float) + 273.15
                         + w["水出口温度/℃"].to_numpy(float) + 273.15)
        P_bar_w = 0.5 * (w.water_P_in_abs_Pa + w.water_P_out_abs_Pa).to_numpy(float)
        check_water_state('water', T_bar_w, P_bar_w, where='water HX mean properties')
        rho = np.asarray(water_density(T_bar_w), dtype=float)
        mu_w = np.asarray(water_viscosity(T_bar_w), dtype=float)
        Gw = w["样机水流量kg/s"].to_numpy(float) / A_FLOW[topo]
        Re_w = Gw * DH_REF / mu_w
        Cw = rho * w["水侧压差/Pa"].to_numpy(float) / L_FLOW
        cfw, dshw = _cf_from_C(Cw, Gw, mu_w, K)
        for i in range(len(w)):
            rows.append(dict(fluid="water", topo=topo, case=str(w.case.iloc[i]), Re=float(Re_w[i]),
                             G=float(Gw[i]), cF_meas=float(cfw[i]),
                             darcy_frac=float(dshw[i]), A_used=A_FLOW[topo]))

        # ---- sCO2：不可压（热侧，ok_dp）----
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            s = load_exp(topo)
        A_s = s.attrs["A_flow_m2"]
        s = s[(s.side == "hot") & s.ok_dp]
        Gs = s.mdot.to_numpy(float) / A_s
        Cs = (s.rho.to_numpy(float) * s.dP_MPa.to_numpy(float) * 1e6 / L_FLOW)
        cfs, dshs = _cf_from_C(Cs, Gs, s.mu.to_numpy(float), K)
        for i in range(len(s)):
            rows.append(dict(fluid="sco2", topo=topo, case=str(s.case.iloc[i]), Re=float(s.Re.iloc[i]),
                             G=float(Gs[i]), cF_meas=float(cfs[i]),
                             darcy_frac=float(dshs[i]), A_used=A_s))
    return pd.DataFrame(rows)


def _k_sensitivity(df: pd.DataFrame) -> pd.DataFrame:
    """K±50% 下 cF_meas 中位的位移（水侧敏感、气/sCO2 近乎免疫）。"""
    out = []
    for topo in _TOPOS:
        K0, _ = _base_node(topo)
        for fluid in ("air", "water", "sco2"):
            g = df[(df.topo == topo) & (df.fluid == fluid)]
            if not len(g):
                continue
            base = float(np.median(g.cF_meas))
            # C = cF·G² + darcy，且 darcy = darcy_frac·C  ⇒  C = cF·G²/(1−frac)
            C = g.cF_meas * g.G ** 2 / (1.0 - g.darcy_frac)
            darcy = g.darcy_frac * C
            shifts = {}
            for lab, mult in (("K×0.5", 0.5), ("K×1.5", 1.5)):
                cf_new = (C - darcy / mult) / g.G ** 2   # K→mult·K ⇒ darcy/mult
                shifts[lab] = float(np.median(cf_new)) / base - 1.0
            out.append(dict(topo=topo, fluid=fluid, cF_med=base, **shifts))
    return pd.DataFrame(out)


def main() -> int:
    cal = _assert_same_caliber()
    df = collect()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "cf_cross_fluid.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print("=" * 80)
    print("同一 7/0.6 芯、三套实验数据的 effective cF 对照（生产 CFD K0）")
    print("=" * 80)
    print("\n[0] 口径核对（气侧常量 vs sCO2 表自带几何）")
    for topo, c in cal.items():
        print(f"  {topo}: A 表内 {c['A_sheet']:.4e} vs 气侧常量 "
              f"{c['A_air']:.4e}  相对差 {c['rel_A']:.2%}  "
              f"L 同 {L_FLOW} m  -> 口径一致")
    print("  => water+air 双网络使用同一单侧有效 A；sCO2 表内 A/L 也一致。")

    print("\n[1] cF_meas（1/m）逐流体")
    print(f"  {'拓扑':<9}{'流体':<7}{'n':>4}{'Re 窗':>18}"
          f"{'cF 中位':>10}{'[P10,P90]':>18}{'Darcy份额中位':>14}")
    med = {}
    for topo in _TOPOS:
        for fluid in ("air", "water", "sco2"):
            g = df[(df.topo == topo) & (df.fluid == fluid)]
            if not len(g):
                continue
            m = float(np.median(g.cF_meas))
            med[(topo, fluid)] = m
            print(f"  {topo:<9}{fluid:<7}{len(g):>4}"
                  f"{f'[{g.Re.min():.0f},{g.Re.max():.0f}]':>18}"
                  f"{m:>10.1f}"
                  f"{f'[{g.cF_meas.quantile(.1):.0f},{g.cF_meas.quantile(.9):.0f}]':>18}"
                  f"{g.darcy_frac.median():>14.2f}")

    print("\n[2] 相对空气数据集的有效倍数（不可解释为工质本征效应）")
    print(f"  {'拓扑':<9}{'水/气':>10}{'sCO2/气':>10}")
    for topo in _TOPOS:
        print(f"  {topo:<9}{med[(topo,'water')]/med[(topo,'air')]:>10.2f}"
              f"{med[(topo,'sco2')]/med[(topo,'air')]:>10.2f}")

    print("\n[3] Re 窗相邻性（气顶 vs sCO2 底——两者几乎接壤，可作近匹配对照）")
    for topo in _TOPOS:
        a = df[(df.topo == topo) & (df.fluid == "air")]
        s = df[(df.topo == topo) & (df.fluid == "sco2")]
        a_top = a.nlargest(3, "Re")
        s_bot = s.nsmallest(3, "Re")
        print(f"  {topo}: 气 top3 Re[{a_top.Re.min():.0f},{a_top.Re.max():.0f}] "
              f"cF 中位 {a_top.cF_meas.median():.0f}   |   "
              f"sCO2 bot3 Re[{s_bot.Re.min():.0f},{s_bot.Re.max():.0f}] "
              f"cF 中位 {s_bot.cF_meas.median():.0f}   -> "
              f"×{s_bot.cF_meas.median()/a_top.cF_meas.median():.2f}")
    print("  两窗仅擦肩；V3 不引入 Re 修正，也不据此把 campaign 差异归因于工质。")

    print("\n[4] K 敏感度（K±50% 对 cF 中位的位移）")
    ks = _k_sensitivity(df)
    print(f"  {'拓扑':<9}{'流体':<7}{'cF 中位':>10}{'K×0.5':>10}{'K×1.5':>10}")
    for _, r in ks.iterrows():
        print(f"  {r.topo:<9}{r.fluid:<7}{r.cF_med:>10.1f}"
              f"{r['K×0.5']:>10.1%}{r['K×1.5']:>10.1%}")
    print("  气/sCO2 近乎免疫（Darcy 份额小）；水侧敏感——水的读数确实依赖 K。")

    print("\n[5] 收口所需的量级（cF ∝ ρ·Δp·A^2 / (L·mdot^2)）")
    print("  下列量级只是在工作簿名义 A/L 均正确且边界等价时的代数敏感性；"
          "\n  现有跨 campaign 数据不能证明这些前提。")
    for topo in _TOPOS:
        r = med[(topo, "sco2")] / med[(topo, "air")]
        print(f"  {topo}: 要把 ×{r:.2f} 抹平，需其一：sCO2 的 Δp 实际低 "
              f"{1 - 1 / r:.0%}、或 sCO2 的 mdot 实际高 {np.sqrt(r) - 1:.0%}、"
              f"或气侧 Δp 实际高 {r - 1:.0%}、或气侧 mdot 实际低 "
              f"{1 - 1 / np.sqrt(r):.0%}（ρ 同量级同理）。")
    print("  这些量可向数据方核实，但本工具不拟合或分解各自贡献。")

    print("\n[5b] 判读")
    print("  - 三套 campaign 在同一 CFD K0 下反演的 effective cF 不一致。现有数据")
    print("    来自不同实验层级、边界和归约，差异原因未分离；工质这里只是数据路由键，")
    print("    不能在缺少同装置对照时归因于工质本身。")
    print("  - water/air 的单侧有效 A 已按对称双网络完整端面口径闭合；仍不能")
    print("    排除测点、边界、歧管、仪器或归约差异。")
    print("  - V3 仅把这些差异作为与 campaign、边界和压降定义绑定的 effective")
    print("    correction；不分解测点、突缩突扩、歧管、面积、零点或归约贡献。")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
