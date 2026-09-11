"""gamma_hx_water.py — γ_HX 水侧提取 + 气/水跨流体一致性（候选 D · D-2b-3）.

审计 §8 双层架构第二层的第二块数据：7-6 样机 HX 级**水侧**压损实验
（`data/raw_data/7-6-Water-dp.xlsx`，G_7_6 16 工况 / D_7_6 18 工况）。
上海 16 例零参与。

**为什么水侧是比气侧更干净的一刀**（本工具的存在理由）：

  - 试件层的基 `cF_dev` 本身就是**水** CFD 提出来的（D-2a/R2，
    `extract_dev_coeffs.py` ← `load_water_cfd`），水侧读数因此不含任何
    跨流体迁移假设；气侧 γ_HX 必须先默认 "cF 是几何量、与流体无关"。
  - 水侧不可压（ρ 冻结）⇒ 无 P² 闭式、无 Δp/P_abs 谱外点，Δp 直读。
  - 两拓扑的水侧数据来自**同一工作簿、同一批次**——iter 73 判定气侧
    D 1.08 / G 1.23 的分化 "是拓扑差还是台架差不可分辨"（D 20260609
    水直空气侧 / G 20260407 上海系调换进出口，两台架两批次）。水侧把
    台架维度消掉：若水侧仍见同量级分化 ⇒ 拓扑差；若水侧一致 ⇒ 气侧
    分化归台架。**这是本轮要买的信息。**

口径（与 `gamma_hx_air` 逐项对齐，常量直接 import 复用，不复制）：
  - 该工作簿是 water+air 换热实验。两种流体分别流过完整且互不连通的
    TPMS 网络，入口覆盖各自完整端面；对称双流道、delta=0，因此两侧使用
    同一个由单侧孔隙率得到的 A_flow（D 5.94e-4 / G 6.50e-4 m²）。通道数
    只是歧管信息，不以 28/34 缩放面积，也不使用 42×42 mm 全端面或除以 2。
  - L_flow=0.182 m，与匹配 air-side HX campaign 一致。
  - u = ṁ/(ρ·A_flow) 为**间隙**流速（全仓约定），ρ、μ 取进出口均温。
  - 不可压 Forchheimer：Δp_pred = L·(μ·u/K_dev + γ_spec·cF_dev·ρ·u²)。
  - 几何 7/0.6 是 dev 表网格节点——K/cF 直取，零插值。

γ_HX(case) ≜ Δp_meas / Δp_pred(γ_specimen-only)：>1 的部分就是试件层
装不下的 HX 级系统效应（歧管/入口/分配）。

**原始表两处数据缺陷（本工具检出并标记，不静默丢弃）**：
  1. G_7_6 工况1 Δp = **−48.4 Pa**（负压差，非物理）——G 表进出口压力为
     负表压且逐工况游走 ±2 kPa 量级，低流量端差值落进传感器地板。
     `dp_nonphysical` 标记 + 退出统计（保留在 CSV 里作证据）。
  2. D_7_6 工况10 与 工况11 除 ṁ 外**逐位相同**（T/p/Δp 全同，
     ṁ 0.082867 vs 0.091167）——原始表复制粘贴痕迹，其一必错。
     `dup_row` 标记 + 退出统计（两条都退，谁对未知）。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/df_refit/gamma_hx_water.py

输出: stdout 记分板 + reports/df_refit/gamma_hx_water.csv。生产零改动。
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from sjtu_tpmshx.validation.df_refit.gamma_hx_air import (
    A_FLOW, L_FLOW, _dev_node)
from sjtu_tpmshx.validation.df_refit.gamma_hx_air import run as run_air
from sjtu_tpmshx.validation.df_refit.gamma_specimen import fit_specimen_gamma
from sjtu_tpmshx.models.tpms_props import water_density, water_viscosity
from sjtu_tpmshx.models.fluid_props import check_water_state
from sjtu_tpmshx.validation.water_exp import with_water_absolute_pressures
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
_BOOK = _REPO / "data" / "raw_data" / "7-6-Water-dp.xlsx"
REPORT_DIR = _REPO / "reports" / "df_refit"

# 表头行号逐 sheet 不同：G_7_6 首行是标题带（"水侧进口温度150℃"），
# D_7_6 首行即列名。写死并在 _load_cases 里校验列名，版式变了立刻炸。
_SHEETS = {"Diamond": ("D_7_6", 0), "Gyroid": ("G_7_6", 1)}
_NEED = ["样机水流量kg/s", "水进口温度/℃", "水出口温度/℃",
         "水进口压力/Pa", "水出口压力/Pa", "水侧压差/Pa"]
# 参考 Re 的特征长度：沿用气侧工具的 2.599 mm（`gamma_hx_air.py:115`）以便
# 两侧 Re 同尺；D-7-6 工作簿 特征长度 列记 2.57 mm（差 1.1%，仅读数不进 γ）。
DH_REF = 2.599e-3


def _load_cases(topo: str) -> pd.DataFrame:
    sheet, header = _SHEETS[topo]
    d = pd.read_excel(_BOOK, sheet_name=sheet, header=header)
    missing = [c for c in _NEED if c not in d.columns]
    if missing:
        raise RuntimeError(f"{topo}: 列缺失 {missing} —— 表版式变了，重核列图")
    d = d[d.iloc[:, 0].astype(str).str.startswith("工况")].copy()
    d = d.dropna(subset=_NEED)
    d = d[d["样机水流量kg/s"] > 0].reset_index(drop=True)
    d["case"] = d.iloc[:, 0].astype(str)

    # 缺陷 1：负压差（传感器地板）
    d["dp_nonphysical"] = d["水侧压差/Pa"] <= 0.0
    # 缺陷 2：除 ṁ 外逐位重复的行（原始表复制粘贴）
    key = ["水进口温度/℃", "水出口温度/℃", "水进口压力/Pa",
           "水出口压力/Pa", "水侧压差/Pa"]
    d["dup_row"] = d.duplicated(subset=key, keep=False)
    # 一致性自检：压差列 == 进口 − 出口（表若改为独立差压计读数，这里会亮）
    resid = (d["水侧压差/Pa"]
             - (d["水进口压力/Pa"] - d["水出口压力/Pa"])).abs().max()
    if resid > 1e-6:
        _log.warning("%s: 压差列与进出口差不一致（max %.3g Pa）——口径变了，"
                     "核实哪一列是原始读数", topo, resid)
    return with_water_absolute_pressures(
        d, source=_BOOK, sheet=sheet, tin="水进口温度/℃", tout="水出口温度/℃",
        pin="水进口压力/Pa", pout="水出口压力/Pa")


def run() -> pd.DataFrame:
    rows = []
    for topo, (sheet, _) in _SHEETS.items():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model, _ = fit_specimen_gamma(topo)
        g_spec = model.predict(7.0, 0.6)
        K_dev, cF_dev = _dev_node(topo)
        A = A_FLOW[topo]
        d = _load_cases(topo)
        for _, r in d.iterrows():
            mdot = float(r["样机水流量kg/s"])
            T_in = float(r["水进口温度/℃"]) + 273.15
            T_out = float(r["水出口温度/℃"]) + 273.15
            T_bar = 0.5 * (T_in + T_out)
            P_bar = 0.5 * (r.water_P_in_abs_Pa + r.water_P_out_abs_Pa)
            check_water_state('water', T_bar, P_bar, where='water HX mean properties')
            rho = float(water_density(T_bar))
            mu = float(water_viscosity(T_bar))
            u = mdot / (rho * A)
            darcy = mu * u / K_dev
            forch = g_spec * cF_dev * rho * u * u
            dpdl = darcy + forch
            dp_pred = dpdl * L_FLOW
            dp_meas = float(r["水侧压差/Pa"])
            bad = bool(r.dp_nonphysical or r.dup_row)
            rows.append(dict(
                topo=topo, sheet=sheet, case=str(r.case), mdot=mdot,
                T_bar_C=T_bar - 273.15, rho=rho, mu=mu, u=u,
                Re_ref=rho * u * DH_REF / mu,
                dp_meas=dp_meas, dp_pred_spec=dp_pred,
                gamma_hx=dp_meas / dp_pred,
                darcy_frac=darcy / dpdl,
                dp_nonphysical=bool(r.dp_nonphysical),
                dup_row=bool(r.dup_row), excluded=bad,
                g_spec=g_spec, K_dev=K_dev, cF_dev=cF_dev))
    return pd.DataFrame(rows)


def _stats(g: pd.DataFrame) -> str:
    gs = g.gamma_hx
    return (f"中位 {gs.median():.2f}  [P10,P90]=[{gs.quantile(.1):.2f},"
            f"{gs.quantile(.9):.2f}]  min/max [{gs.min():.2f},{gs.max():.2f}]")


def main() -> int:
    df = run()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "gamma_hx_water.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print("=" * 78)
    print("D-2b-3 γ_HX 水侧提取（7-6 HX 水实验 ÷ 试件层不可压 Forchheimer）")
    print("=" * 78)
    med_w = {}
    for topo, g_all in df.groupby("topo"):
        g = g_all[~g_all.excluded]
        nbad = int(g_all.excluded.sum())
        print(f"\n[{topo}]  n={len(g)}（原表 {len(g_all)}，剔 {nbad}："
              f"负压差 {int(g_all.dp_nonphysical.sum())} / "
              f"重复行 {int(g_all.dup_row.sum())}）")
        print(f"  γ_spec(7,0.6)={g.g_spec.iloc[0]:.2f}  "
              f"K_dev={g.K_dev.iloc[0]:.3e}  cF_dev={g.cF_dev.iloc[0]:.1f}")
        print(f"  Re_ref 范围 [{g.Re_ref.min():.0f},{g.Re_ref.max():.0f}]  "
              f"Δp_meas 范围 [{g.dp_meas.min():.0f},{g.dp_meas.max():.0f}] Pa")
        print(f"  Darcy 份额 μu/K ÷ 总预测: "
              f"[{g.darcy_frac.min():.2f},{g.darcy_frac.max():.2f}]"
              f"  中位 {g.darcy_frac.median():.2f}"
              f"   <- γ_spec 只乘 Forchheimer 项，份额越高 γ_HX 越读的是 K")
        print(f"  γ_HX: {_stats(g)}")
        lo = g[g.mdot <= g.mdot.median()]
        hi = g[g.mdot > g.mdot.median()]
        print(f"  流量分半: 低半中位 {lo.gamma_hx.median():.2f} / "
              f"高半中位 {hi.gamma_hx.median():.2f}"
              f"   (平 -> 幅值制; 斜 -> 需 γ_HX(Re) 或基的 Re 形状不对)")
        if nbad:
            for _, r in g_all[g_all.excluded].iterrows():
                tag = "负压差" if r.dp_nonphysical else "重复行"
                print(f"    [剔] {r.case} {tag}: mdot={r.mdot:.6f} "
                      f"Δp_meas={r.dp_meas:.1f} → γ={r.gamma_hx:.2f}")
        med_w[topo] = float(g.gamma_hx.median())

    # ---- 跨流体一致性：同一芯、同一试件层、两种流体 ----
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        air = run_air()
    # 气侧同样带缺陷筛（iter 75 补：仪表地板 + 重复行，见 gamma_hx_air）
    air = air[~air.excluded].copy()
    med_a, dfr_a, re_a = {}, {}, {}
    for t, g in air.groupby("topo"):
        # 气侧 Darcy 份额：C 的两项之比（与水侧同定义，闭式里逐点不变）
        G = g.mdot.to_numpy(float) / A_FLOW[t]
        mu = G * (2 * 1.2995e-3) / g.Re_ref.to_numpy(float)
        K_dev, cF_dev = _dev_node(t)
        dar = mu * G / K_dev
        forc = g.g_spec.to_numpy(float) * cF_dev * G * G
        med_a[t] = float(g.gamma_hx.median())
        dfr_a[t] = float(np.median(dar / (dar + forc)))
        re_a[t] = (float(g.Re_ref.min()), float(g.Re_ref.max()))
    print("\n" + "=" * 78)
    print("跨流体一致性（γ_HX 中位；气侧数取自 gamma_hx_air 同轮重跑）")
    print("=" * 78)
    print(f"{'拓扑':<9}{'水 γ_HX':>9}{'气 γ_HX':>9}{'水/气':>8}"
          f"{'水 Darcy':>10}{'气 Darcy':>10}{'水 Re':>14}{'气 Re':>16}")
    for topo in ("Diamond", "Gyroid"):
        w = df[(df.topo == topo) & (~df.excluded)]
        print(f"{topo:<9}{med_w[topo]:>9.2f}{med_a[topo]:>9.2f}"
              f"{med_w[topo] / med_a[topo]:>8.2f}"
              f"{w.darcy_frac.median():>10.2f}{dfr_a[topo]:>10.2f}"
              f"{f'[{w.Re_ref.min():.0f},{w.Re_ref.max():.0f}]':>14}"
              f"{f'[{re_a[topo][0]:.0f},{re_a[topo][1]:.0f}]':>16}")
    print(f"{'G/D 比':<9}{med_w['Gyroid'] / med_w['Diamond']:>9.2f}"
          f"{med_a['Gyroid'] / med_a['Diamond']:>9.2f}")
    # ---- 匹配 Re 带对照：两侧 Re 窗有重叠，去掉"流态区间不同"这个解释 ----
    # Darcy 份额 = 1/(1 + Re·K·γ_spec·cF/Dh) 只是 Re 的函数（G 约掉），
    # 故同 Re 下两侧的项配比逐位相同 —— 重叠带里的差值是纯粹的口径/物理差。
    print("\n匹配 Re 带对照（两侧 Re 窗重叠，同 Re 下 Darcy/Forchheimer 配比"
          "逐位相同）：")
    for topo in ("Diamond", "Gyroid"):
        w = df[(df.topo == topo) & (~df.excluded)]
        a = air[air.topo == topo]
        lo = max(w.Re_ref.min(), a.Re_ref.min())
        hi = min(w.Re_ref.max(), a.Re_ref.max())
        wb = w[(w.Re_ref >= lo) & (w.Re_ref <= hi)]
        ab = a[(a.Re_ref >= lo) & (a.Re_ref <= hi)]
        if not len(wb) or not len(ab):
            print(f"  {topo}: Re 窗无重叠，跳过")
            continue
        print(f"  {topo}  重叠带 Re[{lo:.0f},{hi:.0f}]："
              f"水 n={len(wb)} γ_HX 中位 {wb.gamma_hx.median():.2f} / "
              f"气 n={len(ab)} γ_HX 中位 {ab.gamma_hx.median():.2f}"
              f"  -> 水/气 {wb.gamma_hx.median() / ab.gamma_hx.median():.2f}")
        if len(ab) < 5 or len(wb) < 5:
            print(f"       [薄] 重叠样本 <5（气侧 n={len(ab)}），且落在气侧"
                  f"自身最低流量端——气侧的仪表地板案已按 iter 75 的筛剔除，"
                  f"剩下的最低点 γ_HX={ab.gamma_hx.min():.2f}；本行不作裁决用")

    print("\n判读要点：")
    print("  1. 水侧两拓扑同工作簿同批次 -> G/D 比是**纯拓扑**读数；气侧 G/D"
          " 含台架/批次混杂\n     （D 20260609 vs G 20260407）。两比一致 ->"
          " 分化是拓扑的；不一致 -> 气侧含台架效应。")
    print("  2. Re 窗重叠 -> 水/气差**不能**用 Darcy/Forchheimer 配比不同来"
          "解释；\n     Darcy 份额中位的差别只反映两批工况点在 Re 轴上的分布"
          "位置，不是窗不重叠。")
    print("  3. A_water=A_air 是已确认的双网络完整端面口径；水侧与气侧的"
          " effective 差异保留为 campaign/system 读数，不归因于流体本征物理。")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
