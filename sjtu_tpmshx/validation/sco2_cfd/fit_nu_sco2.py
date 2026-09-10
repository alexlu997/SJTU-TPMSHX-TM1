"""fit_nu_sco2.py — sCO2 单胞 CFD（双拓扑）→ Nu 关联式（光滑壁）拟合与验证.

逐拓扑独立拟合（与产线 WATER_NU_COEFFS / SCO2_NU_COEFFS 的分拓扑惯例一致）。

用法:
    python sjtu_tpmshx/validation/sco2_cfd/fit_nu_sco2.py

数据基底：分段文件第 2/3 周期（入口段剔除），局部体物性由 CoolProp 在
(P, T_b_local) 重取（`df_surrogate.load_sco2_cfd.load_segments`）。
近临界工况 cp 尖峰在核心段 **内部** 穿越，整段平均会抹掉它，
逐段是本数据的分辨率上限。

拟合形式（全部在 log 空间线性）
------------------------------
基形     Nu = c · Re_b^a · Pr_b^b · (Dh/L)^d           [纯体物性, 推荐]
物性比   × (mu_w/mu_b)^e                              [Sieder-Tate 型, 参考]
         × (rho_w/rho_b)^p · (cp_bar/cp_b)^q          [Jackson 型, 对照]

推荐形式演变（2026-07-15 用户裁决）：首版推荐带 (mu_w/mu_b)^e 的 V2；
用户以"壁物性比不具通用性"否决 —— 本数据 ΔT≡50K，壁比项指数条件于该
过热度，且求解器/设计工具用体物性形式更通用。改推 **V0b（纯体物性基形，
全数据拟合）**。量化代价：P>=10 MPa 全温区（含近临界）RMSRE Diamond
13.3% / Gyroid 10.6%，与 V2 相当；差距全部集中在 8 MPa 近临界失效区
（B1 32–35% vs V2 ~25%——那里 V2 也失效，见 README 分域声明）。
远临界端 V0b 反而优于 V2（9.6%/7.5% vs 15.1%/12.6%——μ 项曾把远端带偏）。

可辨识性备注（保留给后来者）：ΔT≡50K 使 log(k_w/k_b)、log(rho_w/rho_b)
与 log(Pr_b) 相关 −1.00/−0.97，Jackson 型与 Pr 项不可分离（自由联合拟合
b=−0.9 病态）；mu_w/mu_b（corr −0.69）是唯一有独立信息的壁比项。

变体:
    V0   基形, 仅远临界子集 (dT_pc >= +10K) 拟合, b 固定 1/3
    V0f  同上, b 自由（Pr_b 1.1–12.8 实测 Pr 指数≈0.38, 支持 1/3）
    V0b  基形, 全数据拟合, b 固定 1/3                     ← 推荐
    V2   基形 + (mu_w/mu_b)^e, 全数据, b 固定 1/3          （参考）
    V1c  基形 + Jackson (rho, cp) 双项, b 固定 1/3         （对照, 共线警告）

验证
----
- 各变体在 远临界 / 近临界(|dT_pc|<=2) / 全数据 上的 RMSRE、medAPE
- LOGO（逐几何留一, V0b 形式）: 几何外推稳健性
- 压力留一（8/10/12 → 15 MPa, V0b 形式）: 压力外推稳健性
- 与产线实验拟合 SCO2_NU_COEFFS (0.28·Re^0.75·Pr^(1/3), D-7-6 粗糙件,
  Re 9k–41k, 远临界) 在重叠窗对照 —— 比值应 ~ SLM 粗糙度增强量级

输出
----
reports/sco2_cfd/nu_sco2_fit_coeffs.csv    各变体系数 + 全局指标
reports/sco2_cfd/nu_sco2_logo.csv          LOGO 逐几何误差
stdout                                     汇总
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PKG_ROOT = _THIS.parent.parent.parent          # .../sjtu_tpmshx

from sjtu_tpmshx.df_surrogate.load_sco2_cfd import LATTICES, load_segments  # noqa: E402
from sjtu_tpmshx.models.nu_correlations import SCO2_NU_COEFFS              # noqa: E402

from sjtu_tpmshx.preprocess.offline.nu_fit import fit_nu_sco2 as _fit

REPORT_DIR = _PKG_ROOT.parent / "reports" / "sco2_cfd"

FAR_CRITICAL_MIN_DT = 10.0      # dT_pc >= this ⇒ 远临界子集
NEAR_CRITICAL_ABS_DT = 2.0      # |dT_pc| <= this ⇒ 近临界子集


def _predict(d: pd.DataFrame, cf: dict[str, float]) -> np.ndarray:
    nu = cf["c"] * d["Re_b"].values ** cf["a"] * d["Pr_b"].values ** cf["b"]
    if "d" in cf:
        nu = nu * (d["Dh_m"].values / (d["L_mm"].values * 1e-3)) ** cf["d"]
    if "p" in cf:
        nu = nu * (d["rho_w"].values / d["rho_b"].values) ** cf["p"] \
                * (d["cp_bar"].values / d["cp_b"].values) ** cf["q"]
    if "e" in cf:
        nu = nu * (d["mu_w"].values / d["mu_b"].values) ** cf["e"]
    return nu


def _metrics(d: pd.DataFrame, cf: dict[str, float]) -> dict[str, float]:
    r = (_predict(d, cf) - d["Nu_b"].values) / d["Nu_b"].values
    return dict(rmsre=float(np.sqrt(np.mean(r * r))),
                medape=float(np.median(np.abs(r))),
                p95ape=float(np.quantile(np.abs(r), 0.95)))


def _run_lattice(tpms: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    seg = load_segments(tpms, drop_entrance=True)
    far = seg[seg["dT_pc"] >= FAR_CRITICAL_MIN_DT]
    near = seg[seg["dT_pc"].abs() <= NEAR_CRITICAL_ABS_DT]

    base_terms = ["re", "pr", "dhl"]
    mu_terms = base_terms + ["mu"]
    jackson_terms = base_terms + ["rho", "cp"]
    variants = {
        "V0_far_b13":  _fit(far, base_terms, fixed={"pr": 1 / 3}),
        "V0f_far":     _fit(far, base_terms),
        "V0b_all_b13": _fit(seg, base_terms, fixed={"pr": 1 / 3}),   # 推荐
        "V2_mu_b13":   _fit(seg, mu_terms, fixed={"pr": 1 / 3}),
        "V1c_jackson": _fit(seg, jackson_terms, fixed={"pr": 1 / 3}),
    }

    rows = []
    for name, cf in variants.items():
        row = {"tpms": tpms, "variant": name, **cf}
        for tag, sub in (("far", far), ("near", near), ("all", seg)):
            for k, v in _metrics(sub, cf).items():
                row[f"{k}_{tag}"] = v
        rows.append(row)
    coeffs = pd.DataFrame(rows)

    # ---- LOGO by geometry (V0b form) ---------------------------------
    logo_rows = []
    for gid in sorted(seg["geometry_id"].unique()):
        train = seg[seg["geometry_id"] != gid]
        test = seg[seg["geometry_id"] == gid]
        cf = _fit(train, base_terms, fixed={"pr": 1 / 3})
        logo_rows.append({"tpms": tpms, "geometry_id": gid,
                          "n_test": len(test),
                          "d_dhl": cf["d"], **_metrics(test, cf)})
    logo = pd.DataFrame(logo_rows)

    # ---- pressure holdout: fit 8/10/12 MPa -> predict 15 MPa (V0b) ---
    tr_p = seg[seg["P_MPa"] < 14.0]
    te_p = seg[seg["P_MPa"] >= 14.0]
    cf_p = _fit(tr_p, base_terms, fixed={"pr": 1 / 3})
    p_hold = _metrics(te_p, cf_p)

    pd.set_option("display.width", 200)
    print(f"\n================ {tpms} ================")
    print(f"分段样本: 全 {len(seg)} | 远临界 {len(far)} | 近临界 {len(near)}")
    print()
    print("=== 系数 (Nu = c·Re^a·Pr^b·(Dh/L)^d ×(mu_w/mu_b)^e "
          "×(rho_w/rho_b)^p (cp_bar/cp_b)^q) ===")
    show = [c for c in ["variant", "c", "a", "b", "d", "e", "p", "q"]
            if c in coeffs.columns]
    print(coeffs[show].round(4).to_string(index=False))
    print()
    print("=== 误差 (RMSRE / medAPE) ===")
    for _, r in coeffs.iterrows():
        print(f"{r['variant']:>13s}:  远临界 {r.rmsre_far:6.1%}/{r.medape_far:6.1%}"
              f"   近临界 {r.rmsre_near:6.1%}/{r.medape_near:6.1%}"
              f"   全数据 {r.rmsre_all:6.1%}/{r.medape_all:6.1%}")
    print()
    print("=== LOGO (V0b 形式, 逐几何留一) ===")
    print(logo.round(4).to_string(index=False))
    print(f"LOGO RMSRE: 中位 {logo.rmsre.median():.1%}  "
          f"最差 {logo.rmsre.max():.1%} ({logo.loc[logo.rmsre.idxmax(), 'geometry_id']})")
    print()
    print(f"=== 压力留一 (V0b: 8/10/12 → 15 MPa, n={len(te_p)}) ===")
    print(f"RMSRE {p_hold['rmsre']:.1%}  medAPE {p_hold['medape']:.1%}  "
          f"p95APE {p_hold['p95ape']:.1%}  (训练集系数 a={cf_p['a']:.4f} "
          f"d={cf_p['d']:.4f})")

    # ---- overlap check vs production experimental fit (Diamond only) --
    if tpms in SCO2_NU_COEFFS:
        exp = SCO2_NU_COEFFS[tpms]                      # rough, D-7-6 实验
        ov = far[(far["Re_b"] >= 9000) & (far["Re_b"] <= 41000)]
        nu_exp = exp["c"] * ov["Re_b"] ** exp["a"] * ov["Pr_b"] ** (1 / 3)
        ratio = nu_exp / _predict(ov, variants["V0b_all_b13"])
        print()
        print("=== 与产线实验拟合对照 (远临界, Re_b 9k–41k 重叠窗, n=%d) ==="
              % len(ov))
        print(f"Nu_exp(粗糙,D-7-6) / Nu_CFD拟合(光滑): "
              f"中位 {ratio.median():.3f}  p05–p95 "
              f"[{ratio.quantile(.05):.3f}, {ratio.quantile(.95):.3f}]")
        print("(参考: 空气侧 SLM 粗糙度 Nu 增强因子 = 1.28)")
    return coeffs, logo


def main() -> None:
    coeffs_all, logo_all = [], []
    for tpms in LATTICES:
        coeffs, logo = _run_lattice(tpms)
        coeffs_all.append(coeffs)
        logo_all.append(logo)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pd.concat(coeffs_all, ignore_index=True).to_csv(
        REPORT_DIR / "nu_sco2_fit_coeffs.csv", index=False)
    pd.concat(logo_all, ignore_index=True).to_csv(
        REPORT_DIR / "nu_sco2_logo.csv", index=False)
    print(f"\n已写出 {REPORT_DIR / 'nu_sco2_fit_coeffs.csv'}")
    print(f"已写出 {REPORT_DIR / 'nu_sco2_logo.csv'}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    main()
