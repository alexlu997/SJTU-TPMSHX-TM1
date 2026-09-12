"""anchor_health.py — col47 试件锚逐层体检（候选 D · D-2b 前置，iter 68）.

06-30（openspec df-coeffs-cfd-refit）曾标记"col47 锚异常：L4 t 趋势反转、
L6 3-4× 尖峰"，其中 L6 是现行 gamma_df 的可信层——D-2b 纯试件重锚开工前
必须裁定该层的存废。本工具把三条证据轴固化为一条命令：

  [ANCHOR]  逐试件 cF_exp 与 γ（对双光滑基：SmoothDF@Re_ref 现约定 +
            dev 发展段新基）——"尖峰"的量化形态
  [FITQ]    逐试件原始 f-Re 的 D-F 形式拟合 R²——区分"真信号"与"坏数据"
  [ISOF]    col47/col43 摩阻隔离因子逐层中位——归约链有无 L6 断点

iter 68 首跑裁定（数字见 docs/DF-CALIBRATION-AUDIT-2026-07.md §8）：
L6/L8 是全表最干净的数据（R² 0.996-0.9997），隔离因子逐层平滑，两拓扑
同构 ⇒ **L6 保留可信层；"尖峰"重释为 γ(L) 陡坡**（相对粗糙度 ε_r/D_h
随胞元增大而降，γ 随 L 递减是物理预期；真正的异常是 L4/L5 的 γ<1——
小胞元本应 γ 最高，数据破损坐实〔R² 0.90-0.94 佐证〕，维持弃用）。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/df_refit/anchor_health.py

输出: stdout 三段记分板 + reports/df_refit/anchor_health.csv。
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from sjtu_tpmshx.df_surrogate.load_data import load_all
from sjtu_tpmshx.df_surrogate.smooth_df import SmoothDF
from sjtu_tpmshx.df_surrogate.surrogate_v3 import SurrogateV3
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
_DEV_CSV = (_REPO / "sjtu_tpmshx" / "df_surrogate" / "_prebuilt"
            / "df_cfd_coeffs_dev.csv")
_XLSX = _REPO / "data" / "raw_data" / 'experiments/air/air_DG_specimen_experiment_summary.xlsx'
REPORT_DIR = _REPO / "reports" / "df_refit"

RE_REF = 2530.0
_SHEETS = {"Diamond": "Diamond_汇总", "Gyroid": "Gyroid_汇总"}


def run() -> pd.DataFrame:
    sm = SmoothDF()
    dev = pd.read_csv(_DEV_CSV)
    raw_all = load_all()
    rows = []
    for topo in _SHEETS:
        sv = SurrogateV3(tpms=topo)
        d = raw_all[raw_all.tpms == topo]
        for _, r in sv.ref.sort_values(["L_mm", "t_mm"]).iterrows():
            L, t, cfe = float(r.L_mm), float(r.t_mm), float(r.c_F)
            g_sm = cfe / float(sm.predict_cF(topo, L, t, RE_REF))
            drow = dev[(dev.tp == topo) & np.isclose(dev.L, L)
                       & np.isclose(dev.t, round(t, 1))]
            g_dev = (cfe / float(drow.cF.iloc[0])) if len(drow) else np.nan
            g = d[np.isclose(d.L_mm, L) & np.isclose(d.t_mm, t)]
            r2 = np.nan
            if len(g) >= 4:
                y = g.dP_Pa.to_numpy(float) / g.u_mps.to_numpy(float)
                X = np.column_stack([g.mu.to_numpy(float),
                                     g.rho.to_numpy(float)
                                     * g.u_mps.to_numpy(float)])
                beta, *_ = np.linalg.lstsq(X, y, rcond=None)
                yhat = X @ beta
                r2 = float(1 - np.sum((y - yhat) ** 2)
                           / np.sum((y - y.mean()) ** 2))
            rows.append(dict(topo=topo, L=L, t=t, cF_exp=cfe,
                             gamma_smoothdf=g_sm, gamma_dev=g_dev,
                             fit_r2=r2, n=len(g)))
        # 隔离因子逐层（原始 col43/47）
        raw = pd.read_excel(_XLSX, sheet_name=_SHEETS[topo], header=0)
        c43 = pd.to_numeric(raw.iloc[:, 43], errors="coerce")
        c47 = pd.to_numeric(raw.iloc[:, 47], errors="coerce")
        cL = pd.to_numeric(raw.iloc[:, 1], errors="coerce")
        ok = c43.notna() & c47.notna() & (c43 > 0)
        iso = pd.DataFrame(dict(L=cL[ok], r=c47[ok] / c43[ok]))
        for Lv, med in iso.groupby("L").r.median().items():
            rows.append(dict(topo=topo, L=float(Lv), t=np.nan, cF_exp=np.nan,
                             gamma_smoothdf=np.nan, gamma_dev=np.nan,
                             fit_r2=np.nan, n=int((iso.L == Lv).sum()),
                             iso_factor_med=float(med)))
    return pd.DataFrame(rows)


def main() -> int:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = run()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "anchor_health.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")

    for topo in _SHEETS:
        d = df[(df.topo == topo) & df.t.notna()]
        print(f"\n[{topo}]  cF_exp | γ_SmoothDF γ_dev | R^2")
        for _, r in d.iterrows():
            print(f"  L{r.L:.0f} t{r.t:.1f}: {r.cF_exp:7.1f} | "
                  f"{r.gamma_smoothdf:6.2f} {r.gamma_dev:6.2f} | "
                  f"{r.fit_r2:.4f} (n={r.n:.0f})")
        iso = df[(df.topo == topo) & df.t.isna()]
        pairs = "  ".join(f"L{r.L:.0f}={r.iso_factor_med:.3f}"
                          for _, r in iso.iterrows())
        print(f"  隔离因子 col47/col43 逐层中位: {pairs}")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
