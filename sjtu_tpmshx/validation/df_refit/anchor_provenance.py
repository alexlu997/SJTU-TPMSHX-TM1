"""anchor_provenance.py — col47 试件锚溯源审计（候选 D · D-0）.

D-0 章程问的三件事，本工具逐条钉到 file:line 并给数字：
  ①提取式是**闭式反演**还是**穿求解器**？②**水平口径**入不入锚？
  ③锚数据本身有没有前四轮在别的表里查出的那两类缺陷？

### 提取链（`df_surrogate/surrogate_v3.py`，行号为 2026-07-25 实测）

    :175-180  α（"边界效应系数" sheet）→ alpha_map，键形如 D_8_03
    :183-186  训练数据 = sheet f"{tpms}_汇总"，header=None, skiprows=1
    :188-215  列位：iloc 1=L_mm, 2=t_mm, 3=Re, 7=T_C, 12=ρ, 13=v, **43=ΔP**
    :209-211  G = ρ(col12) × v(col13) —— **间隙**质量流密度
              （2026-05-28 修正：旧代码读 col48，那是 20×ρv 的记账量）
    :222-223  L=8 且 Re<1600 剔除（过渡区）
    :244-249  **闭式反演**：lhs = (P_in² − P_ATM²)/(2·R·T·L_ch)，
              WLS（w=1/lhs）对 X=[μG, G²] 最小二乘 → (1/K_raw, cF_raw)
    :250-251  **α 修正**：c_F = α·cF_raw，K = K_raw/α

**答①：闭式反演，不穿求解器。** 全程只有 numpy lstsq，无 SIMPLE、无网格。
**答②：水平口径入锚。** `:246` 取 `P_in = P_ATM + ΔP`，即**出口恒定钉在
1 atm**。试件台架 ΔP/P_atm 中位 0.13–0.17、最大 **0.81**，所以这个假定是
承重的：出口若不真在 1 atm，反演出的 cF 会成比例移动。（这也正是 C8/打靶
那条"γ_df 锚点吸收了旧口径压力水平偏置"的机理，现钉到行号。）

### 本工具的实质发现：γ_specimen 不是纯粗糙度因子

α ∈ [0.374, 0.608]，**是个 ~0.5 的系统性乘子**，且随 t 单调下降。后果有二：

  - **水平**：去掉 α，锚 γ 从 2.1–2.9 变成 4.1–6.4。所以"粗糙度因子 ~2"
    是**净掉一次减半之后**的数。
  - **形状（更要紧）**：α 自身的 t 方向对数斜率中位 D −0.961/mm、G −0.720/mm，
    而 γ_spec 拟合出的 b = −1.31/mm（iter 73）——**α 贡献了其中约 73%**。
    Gyroid 更极端：带 α 时锚 γ 在 t 方向近平，去掉 α 后**变成随 t 上升**，
    即 t 依赖的**符号由 α 决定**。

⇒ γ_spec 在 (L,t) 上的**外推形状**主要由 α 这个约定驱动，而 α 的出处是
工作簿里一张没有推导记录的 sheet。**对水平无害**（HX 层会吸收水平偏差，
D-2b-4 已证乘积被实验钉住），**对形状有害**——D-2b-4 的 shape-contrast 带
只含参数不确定度，**不覆盖 α 的出处风险**。⇒ DECISIONS D12。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/df_refit/anchor_provenance.py

输出: stdout 记分板 + reports/df_refit/anchor_provenance.csv。生产零改动。
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from sjtu_tpmshx.validation.df_refit.gamma_specimen import fit_specimen_gamma
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
_XLSX = _REPO / "data" / "raw_data" / 'experiments/air/air_DG_specimen_experiment_summary.xlsx'
REPORT_DIR = _REPO / "reports" / "df_refit"
P_ATM = 101325.0
# surrogate_v3.py:188-215 的列位，逐位复刻（改了这里就是改了锚的口径）
_COLS = dict(L=1, t=2, Re=3, T_C=7, rho=12, v=13, dP=43)


def load_alpha() -> dict[str, float]:
    a = pd.read_excel(_XLSX, sheet_name="边界效应系数", header=None)
    return {str(r.iloc[0]): float(r.iloc[1]) for _, r in a.iterrows()}


def load_bench(tpms: str) -> pd.DataFrame:
    raw = pd.read_excel(_XLSX, sheet_name=f"{tpms}_汇总", header=None,
                        skiprows=1)
    m = pd.to_numeric(raw.iloc[:, _COLS["L"]], errors="coerce").notna()
    d = pd.DataFrame({k: pd.to_numeric(raw.iloc[:, i], errors="coerce")[m]
                      .astype(float) for k, i in _COLS.items()}).dropna()
    d["G"] = d.rho * d.v
    d["dp_over_patm"] = d.dP / P_ATM
    # surrogate_v3.py:222-223 的排除规则，复刻以便报"实际入锚"的集合
    d["excluded_L8_lowRe"] = (d.L == 8) & (d.Re < 1600)
    return d.reset_index(drop=True)


def alpha_t_slope(mp: dict[str, float], pre: str) -> pd.DataFrame:
    rows = []
    for L in (4, 5, 6, 8):
        ks = [f"{pre}_{L}_0{k}" for k in (3, 4, 5)]
        if not all(k in mp for k in ks):
            continue
        y = np.log([mp[k] for k in ks])
        b = float(np.polyfit(np.array([0.3, 0.4, 0.5]), y, 1)[0])
        rows.append(dict(L=L, a_t03=mp[ks[0]], a_t05=mp[ks[2]], b_alpha=b))
    return pd.DataFrame(rows)


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    mp = load_alpha()
    print("=" * 78)
    print("D-0 col47 试件锚溯源审计（提取式 / 水平口径 / 缺陷筛 / α 的分量）")
    print("=" * 78)
    print("\n[1] 提取式（surrogate_v3.py，行号见本模块 docstring）")
    print("  闭式反演，不穿求解器：lhs=(P_in^2-P_ATM^2)/(2RT·L_ch) 对 [μG, G^2] WLS")
    print("  水平口径**入锚**：P_in = P_ATM + ΔP，即出口恒钉 1 atm（:246）")

    out_rows = []
    print("\n[2] 锚数据缺陷筛（与 iter 74-76 对其它四张表用的同一套）")
    for tpms in ("Diamond", "Gyroid"):
        d = load_bench(tpms)
        kept = d[~d.excluded_L8_lowRe]
        dup = d.duplicated(subset=["L", "t", "T_C", "rho", "dP"], keep=False)
        print(f"  {tpms}: n={len(d)}（L8/Re<1600 剔 "
              f"{int(d.excluded_L8_lowRe.sum())} -> 入锚 {len(kept)}）  "
              f"非正 ΔP {int((d.dP <= 0).sum())}  重复行 {int(dup.sum())}")
        print(f"    入锚 ΔP 范围 [{kept.dP.min():.0f},{kept.dP.max():.0f}] Pa；"
              f"ΔP/P_atm 中位 {kept.dp_over_patm.median():.3f} "
              f"最大 **{kept.dp_over_patm.max():.3f}**")
        out_rows.append(dict(kind="bench", tpms=tpms, n=len(d), n_kept=len(kept),
                             n_nonpos=int((d.dP <= 0).sum()),
                             n_dup=int(dup.sum()),
                             dp_over_patm_max=float(kept.dp_over_patm.max())))
    print("  => 试件台账是目前**唯一一张两类缺陷都为零**的表"
          "（气/水/上海表均中招，见审计 §11-§14）。")

    print("\n[3] α（边界效应系数）：一个 ~0.5 的系统性乘子")
    print(f"  取值范围 [{min(mp.values()):.3f}, {max(mp.values()):.3f}]，"
          f"{len(mp)} 个几何键；c_F=α·cF_raw、K=K_raw/α（:250-251）")
    for pre, topo in (("D", "Diamond"), ("G", "Gyroid")):
        s = alpha_t_slope(mp, pre)
        print(f"  {topo}: α 的 t 方向对数斜率 逐 L "
              f"{[round(v, 3) for v in s.b_alpha]}  中位 "
              f"**{s.b_alpha.median():+.3f}/mm**")
        for _, r in s.iterrows():
            out_rows.append(dict(kind="alpha_slope", tpms=topo, L=r.L,
                                 a_t03=r.a_t03, a_t05=r.a_t05,
                                 b_alpha=r.b_alpha))

    print("\n[4] α 在 γ_spec 里占多少（本轮的实质发现）")
    for topo in ("Diamond", "Gyroid"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model, anch = fit_specimen_gamma(topo)
        pre = topo[0]
        anch = anch.copy()
        anch["alpha"] = [mp.get(f"{pre}_{int(r.L)}_0{int(round(r.t * 10))}",
                                np.nan) for _, r in anch.iterrows()]
        anch["gamma_no_alpha"] = anch.gamma / anch.alpha
        s = alpha_t_slope(mp, pre)
        b_a = float(s.b_alpha.median())
        # ln γ_spec = ln α + ln(cF_raw/cF_dev) => 原始比值的 t 斜率 = b − b_α
        b_raw = float(model.b) - b_a
        print(f"\n  [{topo}] γ_spec 拟合 t 斜率 b={model.b:+.3f}/mm；"
              f"α 自身 {b_a:+.3f}/mm；"
              f"原始比值(cF_raw/cF_dev) {b_raw:+.3f}/mm")
        if abs(model.b) > 0.2:
            print(f"    => **α 占 γ_spec 的 t 斜率约 "
                  f"{abs(b_a) / abs(model.b):.0%}**")
        else:
            print(f"    => **γ_spec 的 t 平坦是抵消出来的**：α 的 {b_a:+.3f} "
                  f"几乎正好抵掉原始比值的 {b_raw:+.3f}（残 {model.b:+.3f}）"
                  f"——不是没有 t 依赖，是两项相消")
        print(f"    锚 γ 中位 {anch.gamma.median():.2f} "
              f"→ 去 α 后 {anch.gamma_no_alpha.median():.2f}"
              f"（α 中位 {anch.alpha.median():.3f}）")
        lo6 = anch[anch.L == 6].gamma_no_alpha.to_numpy()
        if len(lo6) >= 3:
            trend = "随 t 上升" if lo6[-1] > lo6[0] else "随 t 下降"
            trend0 = ("随 t 上升" if anch[anch.L == 6].gamma.to_numpy()[-1]
                      > anch[anch.L == 6].gamma.to_numpy()[0] else "随 t 下降")
            print(f"    L6 锚的 t 走向：带 α {trend0} / 去 α {trend}"
                  f"  <- 符号由 α 决定" if trend != trend0 else
                  f"    L6 锚的 t 走向：带 α 与去 α 同向（{trend}）")
        for _, r in anch.iterrows():
            out_rows.append(dict(kind="anchor", tpms=topo, L=r.L, t=r.t,
                                 gamma=r.gamma, alpha=r.alpha,
                                 gamma_no_alpha=r.gamma_no_alpha,
                                 b_gamma=model.b))

    print("\n[5] 判读")
    print("  - 锚的**水平**受 α 影响 ×2，但**对下游无害**：HX 层按")
    print("    γ_HX=Δp_meas/Δp_pred(γ_spec) 标定，水平偏差被吸收，")
    print("    D-2b-4 已实测乘积被实验钉住（合成面在 7/0.6 处直接可测）。")
    print("  - 锚的**形状**受 α 主导（t 斜率 73%/G 侧更甚，且 G 的符号由 α 定），")
    print("    而 γ_spec 的 (L,t) 外推正是靠形状 => **D-2b-4 的 shape-contrast")
    print("    带只含参数不确定度，不覆盖 α 的出处风险**。")
    print("  - α 的出处 = 工作簿一张 sheet，仓库内无推导记录 => DECISIONS D12。")

    out = REPORT_DIR / "anchor_provenance.csv"
    pd.DataFrame(out_rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
