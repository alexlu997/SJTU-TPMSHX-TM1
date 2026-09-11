"""compare_exp_vs_cfd.py — sCO2 实验 (D-7-6/G-7-6) vs CFD 闭合: Nu 与 Darcy f 倍数.

用法:
    python sjtu_tpmshx/validation/sco2_exp/compare_exp_vs_cfd.py

产出（reports/sco2_exp/）:
    exp_points.csv              逐点: 实验 Re/Pr/Nu/f + CFD 预测 + 比值
    exp_fit_summary.csv         实验关联式系数 + 倍数汇总
    sco2_exp_vs_cfd.html        模板化报告（CFD 关联式原形）
    sco2_exp_vs_cfd_subst.html  代入几何版: CFD 关联式把实际 D_h、L 代入,
                                (D_h/L)^d 并入系数 c_eff, 便于与实验拟合
                                直接对比（用户需求 2026-07-16）

方法
----
实验点经 load_sco2_exp 重算（repo Dh 口径, 与 CFD 侧同源）。
Nu 集 = ok_dT & ok_hb & ok_done;  f 集 = ok_dp & ok_done（负压差剔除,
用户裁决）。两侧分开报——实验 f 高温侧系统性高于低温侧 2–5 倍
（传感器/边界效应, 用户裁决不深究, 但倍数必须分侧给）。

CFD 基准（现产线闭合, 光滑壁）:
    Nu_cfd = SCO2_NU_COEFFS: c·Re^a·Pr^(1/3)·(Dh/L)^d   [7/0.6 现有真实 CFD,
             2026-07-23 重拟, 已在网内; γ_Nu 为纯粹粗糙度因子]
    f_cfd  = 2·Dh²/(K·Re) + 2·Dh·cF_sco2(Re)            [K=CFD-refit 面;
             cF 仍为 sco2_df 代理, 与 Nu 重拟无关]

倍数定义:
    逐点   γ = 实验值 / CFD 预测值 (同 Re, Pr), 报中位 [p5, p95]
    锚定拟合  指数 a 固定为 CFD 值, 只拟前置系数 → γ_fit = c_exp/c_cfd
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PKG_ROOT = _THIS.parent.parent.parent
sys.path.insert(0, str(_THIS.parent))

from load_sco2_exp import load_exp                              # noqa: E402
from sjtu_tpmshx.models.nu_correlations import SCO2_NU_COEFFS              # noqa: E402
from sjtu_tpmshx.models.tpms_props import geometry as tpms_geometry        # noqa: E402
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF                   # noqa: E402
from sjtu_tpmshx.df_surrogate.sco2_df import predict_cF_sco2                # noqa: E402
from sjtu_tpmshx.validation.report_template import (                        # noqa: E402
    ANNO_BOX, CFD_C, CHART_ANNO_FS, CHART_LEGEND_FS, COLD_C, G700, HOT_C, IVORY, SLATE,
    G300, G500, CLAY,
    math_block, math_inline, mfrac, mi, mn, mo, mrow, msub, msup, page,
    paren_pow, section, style_journal_ax)

REPORT_DIR = _PKG_ROOT.parent / "reports" / "sco2_exp"
TOPOS = ("Diamond", "Gyroid")
L_MM, T_MM = 7.0, 0.6


# ── 行内 MathML 片段（正文数学统一渲染, 2026-07-16）──────────────────
def _up(x):        # 直立体下标标签（exp/cfd/hot/cold/w/streams/Nu/f/Δ）
    return mi(x, italic=False)


def _bar(x):       # 上划线（T̄）
    return f'<mover accent="true"><mi>{x}</mi><mo>\u00af</mo></mover>'


_G0 = msub(mi("\u0393"), mn("0"))                        # Γ₀
M_G = math_inline(mi("\u03b3"))                          # γ
M_GNU = math_inline(msub(mi("\u03b3"), _up("Nu")))       # γ_Nu
M_GF = math_inline(msub(mi("\u03b3"), _up("f")))         # γ_f
M_A = math_inline(mi("\u03b1"))                          # α
M_B = math_inline(mi("\u03b2"))                          # β
M_RE = math_inline(mi("Re"))
M_PR = math_inline(mi("Pr"))
M_PR13 = math_inline(msup(mi("Pr"), mrow(mn(1), mo("/"), mn(3))))  # Pr^(1/3)
M_NUEXP = math_inline(msub(mi("Nu"), _up("exp")))
M_NUCFD = math_inline(msub(mi("Nu"), _up("cfd")))
M_GNU_FORM = math_inline(msub(mi("\u03b3"), _up("Nu")), mo("="), _G0,
                         mo("\u00b7"), msup(mi("Re"), mi("\u03b1")),
                         mo("\u00b7"), msup(mi("Pr"), mi("\u03b2")))
M_GF_FORM = math_inline(msub(mi("\u03b3"), _up("f")), mo("="), _G0,
                        mo("\u00b7"), msup(mi("Re"), mi("\u03b1")))
M_G_GT1 = math_inline(mi("\u03b3"), mo("\u003e"), mn(1))   # γ > 1
_DT = mrow(_up("\u0394"), mi("T"))                          # ΔT
M_DT = math_inline(_DT)
M_TW = math_inline(msub(mi("T"), _up("w")), mo("="),
                   mfrac(mrow(msub(_bar("T"), _up("hot")), mo("+"),
                             msub(_bar("T"), _up("cold"))), mn(2)))
M_NUPROP = math_inline(mi("Nu"), mo("\u221d"),
                       mfrac(mn(1), msub(_DT, _up("streams"))))  # Nu ∝ 1/ΔT_streams
M_NUPROP_S = math_inline(mi("Nu"), mo("\u221d"), mfrac(mn(1), _DT))  # Nu ∝ 1/ΔT


def _nu_cfd(topo, Re, Pr, Dh_mm):
    co = SCO2_NU_COEFFS[topo]
    return (co["c"] * np.asarray(Re) ** co["a"] * np.asarray(Pr) ** (1 / 3)
            * (Dh_mm / L_MM) ** co["d"])


def _f_cfd(topo, Re, Dh_m, eps_f):
    # This legacy refit defines the frozen gamma_f constants relative to the
    # historical gamma_df base, not the current production default.
    K = predict_K_cF(topo, L_MM, T_MM, eps_f, method="gamma_df")[0]
    cF = np.array([predict_cF_sco2(topo, L_MM, T_MM, r)
                   for r in np.atleast_1d(Re)])
    return 2.0 * Dh_m ** 2 / (K * np.asarray(Re)) + 2.0 * Dh_m * cF


def _fit_power(x_ln: np.ndarray, y_ln: np.ndarray) -> tuple[float, float]:
    """ln y = ln c + a·x  →  (c, a)."""
    A = np.column_stack([np.ones_like(x_ln), x_ln])
    beta, *_ = np.linalg.lstsq(A, y_ln, rcond=None)
    return float(np.exp(beta[0])), float(beta[1])


def _fit_power2(Re, Pr, y):
    """γ = Γ₀·Re^a·Pr^b 二元幂律（log 空间 OLS）→ (G0, a, b, se_b, sig).
    sig = |b| > 2·se_b（远临界 Pr 窄 → 多不显著）。"""
    Re, Pr, y = map(lambda z: np.asarray(z, float), (Re, Pr, y))
    X = np.column_stack([np.ones_like(Re), np.log(Re), np.log(Pr)])
    beta, *_ = np.linalg.lstsq(X, np.log(y), rcond=None)
    resid = np.log(y) - X @ beta
    dof = max(len(y) - 3, 1)
    s2 = float(resid @ resid) / dof
    se_b = float(np.sqrt(s2 * np.linalg.inv(X.T @ X)[2, 2]))
    return (float(np.exp(beta[0])), float(beta[1]), float(beta[2]),
            se_b, abs(float(beta[2])) > 2 * se_b)


def _band(r):
    """(mean, median, p5, p95)"""
    r = np.asarray(r)
    return (float(np.mean(r)), float(np.median(r)),
            float(np.quantile(r, 0.05)), float(np.quantile(r, 0.95)))


def analyse(topo: str) -> dict:
    df = load_exp(topo)
    geo = tpms_geometry(topo, L_MM, T_MM, 16.0)
    Dh_m = float(geo["D_h"])
    eps_f = float(geo["epsilon"]) / 2.0

    nu_set = df[df.ok_dT & df.ok_hb & df.ok_done].copy()
    f_set = df[df.ok_dp & df.ok_done].copy()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")     # 7/0.6 在 CFD 包络外, 外推告警已知
        nu_set["Nu_cfd"] = _nu_cfd(topo, nu_set["Re"], nu_set["Pr"],
                                   Dh_m * 1e3)
        f_set["f_cfd"] = _f_cfd(topo, f_set["Re"].to_numpy(), Dh_m, eps_f)
    nu_set["gamma_Nu"] = nu_set["Nu"] / nu_set["Nu_cfd"]
    f_set["gamma_f"] = f_set["f"] / f_set["f_cfd"]

    out = {"topo": topo, "nu_set": nu_set, "f_set": f_set, "Dh_m": Dh_m}

    # ── 实验 Nu 关联式（仅 7/0.6）───────────────────────────────
    lnRe = np.log(nu_set["Re"].to_numpy())
    lnNu = (np.log(nu_set["Nu"].to_numpy())
            - np.log(nu_set["Pr"].to_numpy()) / 3.0)
    c_free, a_free = _fit_power(lnRe, lnNu)
    pred = c_free * nu_set["Re"] ** a_free * nu_set["Pr"] ** (1 / 3)
    r = (pred - nu_set["Nu"]) / nu_set["Nu"]
    out["nu_fit"] = dict(c=c_free, a=a_free,
                         rmsre=float(np.sqrt(np.mean(r ** 2))),
                         medape=float(np.median(np.abs(r))), n=len(nu_set))
    # 锚定拟合: a 固定 CFD 值 → γ = c_exp/c_cfd_eff
    a_cfd = SCO2_NU_COEFFS[topo]["a"]
    c_cfd_eff = (SCO2_NU_COEFFS[topo]["c"]
                 * (Dh_m * 1e3 / L_MM) ** SCO2_NU_COEFFS[topo]["d"])
    c_anch = float(np.exp(np.mean(lnNu - a_cfd * lnRe)))
    out["gamma_nu_fit"] = c_anch / c_cfd_eff
    out["gamma_nu_pt"] = {s: _band(g["gamma_Nu"])
                          for s, g in nu_set.groupby("side")}
    out["gamma_nu_pt"]["pooled"] = _band(nu_set["gamma_Nu"])

    # ── 实验 f（分侧, 两侧不一致是数据事实）────────────────────
    out["f_fit"], out["gamma_f_pt"] = {}, {}
    for s, g in f_set.groupby("side"):
        Bf, nf = _fit_power(np.log(g["Re"].to_numpy()),
                            np.log(g["f"].to_numpy()))
        out["f_fit"][s] = dict(B=Bf, n=nf, npts=len(g))
        out["gamma_f_pt"][s] = _band(g["gamma_f"])
    # CFD D-F 曲线在实验 Re 窗内的同形幂律拟合（subst 版相除用;
    # D-F 本身非幂律, Darcy 项在 Re>9000 处占比小, 幂律近似良好）
    Bc, nc = _fit_power(np.log(f_set["Re"].to_numpy()),
                        np.log(f_set["f_cfd"].to_numpy()))
    out["f_cfd_fit"] = dict(B=Bc, n=nc)

    # ── γ(Re) 幂律函数: 两边均为幂律 ⇒ 比值也是幂律 Γ0·Re^Δ ──────
    # 对逐点 γ 直接 OLS（与散点自洽; Nu 的 Δ≈0.02 即"均值成立"的证明,
    # f 的 Δ 显著非零 ⇒ 均值误导, 须用函数）。
    out["gamma_fn"] = {}
    G0, dlt = _fit_power(np.log(nu_set["Re"].to_numpy()),
                         np.log(nu_set["gamma_Nu"].to_numpy()))
    out["gamma_fn"]["Nu"] = dict(G0=G0, d=dlt)
    for s, g in f_set.groupby("side"):
        G0, dlt = _fit_power(np.log(g["Re"].to_numpy()),
                             np.log(g["gamma_f"].to_numpy()))
        out["gamma_fn"][f"f_{s}"] = dict(G0=G0, d=dlt)

    # ── γ(Re, Pr) 二元幂律（2026-07-16 用户裁决: 加入 Pr 维度）───────
    # γ = Nu_exp/Nu_cfd, 两者都含 Pr^(1/3) ⇒ Pr 指数 b 是"超出 1/3 律的
    # 残余"; 远临界 Pr 仅 0.79–1.04, b 多不显著（sig 标记）, Re 仍是主变量。
    out["gamma_fn2"] = {}
    G0, a, b, se_b, sig = _fit_power2(
        nu_set["Re"], nu_set["Pr"], nu_set["gamma_Nu"])
    out["gamma_fn2"]["Nu"] = dict(G0=G0, a=a, b=b, se_b=se_b, sig=sig)
    # γ_f 不含 Pr —— 摩擦（Darcy f）是纯动量现象, 与 Prandtl 数无关
    # （物理约束, 非拟合结果）; γ_f(Re) 用上面的一元 gamma_fn。
    return out


def make_charts(res: list[dict], subst_geom: bool = False) -> dict[str, str]:
    """subst_geom=True: Nu 图的 CFD 标注用代入几何后的 c_eff 形式."""
    import io

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "text.color": SLATE, "axes.labelcolor": G700,
        # 融底（模板硬性规则 9）: 图透明底坐在米色纸面上;
        # legend 底用 IVORY（遮点, 与纸面同色）
        "figure.facecolor": "none",
        "legend.facecolor": IVORY, "legend.edgecolor": G300,
        "legend.framealpha": 1.0,
        # 内联 SVG（模板硬性规则 10）: 文字留真实文本, 与正文同字体渲染
        "svg.fonttype": "none"})

    def _svg(fig, salt):
        # salt → svg.hashsalt: 同页多图内联, clipPath id 必须互异
        # （模板硬性规则 10）; 返回去掉 XML 头的 <svg> 片段直接内联。
        # 同步落一份白底 PNG 到 _docx_assets（Word 导出用, 2026-07-16）。
        png_dir = REPORT_DIR / "_docx_assets"
        png_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(png_dir / f"{salt}.png", dpi=160, bbox_inches="tight",
                    transparent=False, facecolor="#FFFFFF")
        plt.rcParams["svg.hashsalt"] = salt
        buf = io.StringIO()
        fig.savefig(buf, format="svg", bbox_inches="tight",
                    transparent=True)
        plt.close(fig)
        svg = buf.getvalue()
        return svg[svg.index("<svg"):]

    def _parity(ax, r, dset, xcol, pred_col, ttl, unit=""):
        """Parity: x=实验, y=CFD 预测; 45° 黑实线 + ±20% 灰虚线 +
        分侧中位倍数红参考线。编码与主图统一（2026-07-16 格式统一）:
        红 = 实验数据、方框 hot / 实心圆 cold、hot 实线 / cold 虚线;
        蓝保留给 CFD 曲线, 不再挪用为 cold 侧。"""
        d = r[dset]
        lo = min(d[xcol].min(), d[pred_col].min()) * 0.7
        hi = max(d[xcol].max(), d[pred_col].max()) * 1.4
        xx = np.array([lo, hi])
        ax.plot(xx, xx, color=SLATE, lw=1.0)
        ax.plot(xx, 1.2 * xx, color=G500, lw=0.8, ls="--")
        ax.plot(xx, 0.8 * xx, color=G500, lw=0.8, ls="--")
        for side, col in (("hot", HOT), ("cold", COLD)):
            g = d[d["side"] == side]
            gam = float((g[xcol] / g[pred_col]).median())
            if side == "hot":
                ax.scatter(g[xcol], g[pred_col], s=20, marker="s",
                           facecolors="none", edgecolors=col, lw=1.0,
                           label=f"hot（中位 ×{gam:.2f}）")
            else:
                ax.scatter(g[xcol], g[pred_col], s=20, marker="o",
                           color=col, lw=0, alpha=0.75,
                           label=f"cold（中位 ×{gam:.2f}）")
            # 中位倍数参考线: y = x/γ（点落在其上 = 恒定倍数）
            ax.plot(xx, xx / gam, color=col, lw=0.9, alpha=0.75)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
        ax.set_aspect("equal")
        style_journal_ax(ax, f"实验{unit}", f"CFD 预测{unit}", ttl)
        ax.legend(fontsize=CHART_LEGEND_FS, labelcolor=G700,
                  loc="upper left")

    # 期刊风格（用户指定样式 2026-07-15）: 线性坐标、全框、
    # 拟合曲线 + 公式标注在曲线旁; 公式本体全黑（方案 C「期刊经典」）。
    # 三色方案（用户选定 2026-07-16, Okabe-Ito, 常量在模板单一来源）:
    #   hot 朱红方框 / cold 深海蓝实心圆 / CFD 蓝绿三角+虚线;
    #   侧别相关线用侧别色, 实验合并拟合线用黑实线。
    HOT, COLD, CFDC = HOT_C, COLD_C, CFD_C
    INK = SLATE

    def _two_tone(fig, ax, x, y, prefix, body, pcolor, ha="left",
                  va="baseline", fs=10):
        """彩色前缀 + 黑色公式本体; 用渲染后包围盒精确接排."""
        pad = 0.008
        if ha == "left":
            t0 = ax.text(x, y, prefix, transform=ax.transAxes,
                         fontsize=fs, color=pcolor, va=va)
            fig.canvas.draw()
            bb = t0.get_window_extent()
            x1 = ax.transAxes.inverted().transform((bb.x1, 0))[0]
            ax.text(x1 + pad, y, body, transform=ax.transAxes,
                    fontsize=fs, color=INK, va=va)
        else:
            t0 = ax.text(x, y, body, transform=ax.transAxes,
                         fontsize=fs, color=INK, ha="right", va=va)
            fig.canvas.draw()
            bb = t0.get_window_extent()
            x0 = ax.transAxes.inverted().transform((bb.x0, 0))[0]
            ax.text(x0 - pad, y, prefix, transform=ax.transAxes,
                    fontsize=fs, color=pcolor, ha="right", va=va)

    charts = {}
    # ── Nu–Re 期刊风格主图 ────────────────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.2))
    _nu_annos = []   # 标注在 tight_layout 后统一画（包围盒接排需最终布局）
    for ax, r in zip(axes, res):
        d = r["nu_set"]
        Pr_med = float(d["Pr"].median())
        Re_line = np.linspace(d["Re"].min() * 0.9, d["Re"].max() * 1.05, 100)
        h = d[d["side"] == "hot"]; c = d[d["side"] == "cold"]
        ax.scatter(h["Re"], h["Nu"], s=26, facecolors="none",
                   edgecolors=HOT, lw=1.1, marker="s", label="实验 hot 侧 Nu")
        ax.scatter(c["Re"], c["Nu"], s=26, color=COLD, lw=0, marker="o",
                   label="实验 cold 侧 Nu")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            nu_cfd_pts = _nu_cfd(r["topo"], d["Re"], d["Pr"],
                                 r["Dh_m"] * 1e3)
            nu_cfd_line = _nu_cfd(r["topo"], Re_line, Pr_med,
                                  r["Dh_m"] * 1e3)
        ax.scatter(d["Re"], nu_cfd_pts, s=26, color=CFDC, lw=0, marker="^",
                   alpha=0.85, label="CFD 预测 Nu")
        nf = r["nu_fit"]
        # 曲线: 实验合并拟合黑实线 / CFD 蓝绿虚线（分侧点朱红/深蓝）
        ax.plot(Re_line, nf["c"] * Re_line ** nf["a"] * Pr_med ** (1 / 3),
                color=INK, lw=1.4)
        ax.plot(Re_line, nu_cfd_line, color=CFDC, lw=1.4, ls="--")
        # 公式标注在各自曲线旁（均为本项目自己的 sCO2 拟合:
        # 上 = 本实验拟合; 下 = 产线 CFD 关联式 SCO2_NU_COEFFS 完整原形）
        co = SCO2_NU_COEFFS[r["topo"]]
        _nu_annos.append((ax, nf, co, r["Dh_m"]))
        gam = float((d["Nu"] / d["Nu_cfd"]).median())
        style_journal_ax(ax, "Re", "Nu",
                         f"{r['topo']} 7/0.6 — 实验/CFD 中位 ×{gam:.2f}")
        ax.legend(fontsize=CHART_LEGEND_FS, labelcolor=G700,
                  loc="center left")
    fig.tight_layout()
    for ax, nf, co, Dh_m in _nu_annos:
        _two_tone(fig, ax, 0.03, 0.96, "实验:",
                  f"$Nu={nf['c']:.4f}Re^{{{nf['a']:.3f}}}Pr^{{1/3}}$",
                  INK, ha="left", va="top", fs=CHART_ANNO_FS)
        if subst_geom:
            # 代入几何版: (D_h/L)^d 并入系数 c_eff, 与实验拟合同形可比
            c_eff = co["c"] * (Dh_m * 1e3 / L_MM) ** co["d"]
            cfd_body = f"$Nu={c_eff:.4f}Re^{{{co['a']:.3f}}}Pr^{{1/3}}$"
            # 修正系数 = 实验/CFD 两条同形关联式相除（用户需求 2026-07-16）
            ratio, da = nf["c"] / c_eff, nf["a"] - co["a"]
            _two_tone(fig, ax, 0.03, 0.885, "修正:",
                      f"$Nu_{{exp}}/Nu_{{cfd}} = "
                      f"{ratio:.3f}\\,Re^{{{da:+.4f}}}$",
                      CLAY, ha="left", va="top", fs=CHART_ANNO_FS)
        else:
            cfd_body = (f"$Nu={co['c']:.4f}Re^{{{co['a']:.3f}}}Pr^{{1/3}}"
                        f"(D_h/L)^{{{co['d']:.3f}}}$")
        _two_tone(fig, ax, 0.97, 0.06, "CFD:", cfd_body,
                  CFDC, ha="right", fs=CHART_ANNO_FS)
    charts["nu"] = _svg(fig, "nu" + ("_subst" if subst_geom else ""))

    # ── f–Re 期刊风格主图 ─────────────────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.2))
    _f_annos = []
    for ax, r in zip(axes, res):
        d = r["f_set"]
        geo = tpms_geometry(r["topo"], L_MM, T_MM, 16.0)
        Re_line = np.linspace(d["Re"].min() * 0.9, d["Re"].max() * 1.05, 100)
        h = d[d["side"] == "hot"]; c = d[d["side"] == "cold"]
        ax.scatter(h["Re"], h["f"], s=26, facecolors="none", edgecolors=HOT,
                   lw=1.1, marker="s", label="实验 hot 侧 f")
        ax.scatter(c["Re"], c["f"], s=26, color=COLD, lw=0, marker="o",
                   label="实验 cold 侧 f")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            f_line = _f_cfd(r["topo"], Re_line, r["Dh_m"],
                            float(geo["epsilon"]) / 2.0)
            f_pts = _f_cfd(r["topo"], d["Re"].to_numpy(), r["Dh_m"],
                           float(geo["epsilon"]) / 2.0)
        ax.scatter(d["Re"], f_pts, s=26, color=CFDC, lw=0, marker="^",
                   alpha=0.85, label="CFD D-F 预测 f")
        ax.plot(Re_line, f_line, color=CFDC, lw=1.4, ls="--")
        # 分侧拟合线用侧别色（色即侧别, 无须再用线型区分）
        for side_key, col in (("hot", HOT), ("cold", COLD)):
            ff = r["f_fit"][side_key]
            ax.plot(Re_line, ff["B"] * Re_line ** ff["n"], color=col,
                    lw=1.3)
        gh = float((h["f"] / f_pts[d["side"] == "hot"]).median())
        gc = float((c["f"] / f_pts[d["side"] == "cold"]).median())
        # 顶部留白带：标注与图例都放进这条带，避免压住 hot 侧点群
        # （subst 版 5 行公式栈, 留更高）
        y_top = float(max(d["f"].max(), f_line.max())) * (1.9 if subst_geom
                                                          else 1.30)
        ax.set_ylim(top=y_top)
        _f_annos.append((ax, gh, gc, r))
        style_journal_ax(ax, "Re", "f", f"{r['topo']} 7/0.6 — Darcy f")
        ax.legend(fontsize=CHART_LEGEND_FS, labelcolor=G700,
                  loc="upper right", ncol=1)
    fig.tight_layout()
    for ax, gh, gc, r in _f_annos:
        if subst_geom:
            # f 侧与 Nu 同款三件套: 实验幂律 / CFD 同形幂律 / 修正系数
            def _sci(x):
                # mathtext 科学计数: 1e-2 ~ 1e4 之外用 m×10^e
                if x == 0 or 1e-2 <= abs(x) < 1e4:
                    return f"{x:.3g}"
                m, e = f"{x:.2e}".split("e")
                return f"{float(m):.2f}\\times10^{{{int(e)}}}"

            ffh, ffc = r["f_fit"]["hot"], r["f_fit"]["cold"]
            fcf = r["f_cfd_fit"]
            _two_tone(fig, ax, 0.03, 0.97, "实验 hot:",
                      f"$f={_sci(ffh['B'])}\\,Re^{{{ffh['n']:+.3f}}}$",
                      INK, ha="left", va="top", fs=CHART_ANNO_FS)
            _two_tone(fig, ax, 0.03, 0.90, "实验 cold:",
                      f"$f={_sci(ffc['B'])}\\,Re^{{{ffc['n']:+.3f}}}$",
                      INK, ha="left", va="top", fs=CHART_ANNO_FS)
            _two_tone(fig, ax, 0.03, 0.83, "CFD:",
                      f"$f={_sci(fcf['B'])}\\,Re^{{{fcf['n']:+.3f}}}$"
                      "（Re 窗内幂律拟合）",
                      CFDC, ha="left", va="top", fs=CHART_ANNO_FS)
            _two_tone(fig, ax, 0.03, 0.76, "修正 hot:",
                      f"$f_{{exp}}/f_{{cfd}}={_sci(ffh['B'] / fcf['B'])}"
                      f"\\,Re^{{{ffh['n'] - fcf['n']:+.3f}}}$",
                      CLAY, ha="left", va="top", fs=CHART_ANNO_FS)
            _two_tone(fig, ax, 0.03, 0.69, "修正 cold:",
                      f"$f_{{exp}}/f_{{cfd}}={_sci(ffc['B'] / fcf['B'])}"
                      f"\\,Re^{{{ffc['n'] - fcf['n']:+.3f}}}$",
                      CLAY, ha="left", va="top", fs=CHART_ANNO_FS)
        else:
            _two_tone(fig, ax, 0.03, 0.97, "实验拟合:",
                      f"hot ×{gh:.1f} / cold ×{gc:.1f}",
                      INK, ha="left", va="top", fs=CHART_ANNO_FS)
    charts["f"] = _svg(fig, "f" + ("_subst" if subst_geom else ""))

    # ── γ(Re, Pr) 函数图（第 05 节; 2026-07-16: γ 扩为 Re,Pr 二元幂律）──
    # γ_Nu 按 Pr 着色（蓝序列）+ 中位 Pr 处拟合线; γ_f 保留分侧红。
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    from matplotlib.ticker import LogLocator, FuncFormatter, NullFormatter
    PR_CMAP = LinearSegmentedColormap.from_list("pr", ["#CBD9F0", "#1F4E9C"])
    pr_all = np.concatenate([r["nu_set"]["Pr"].values for r in res])
    prnorm = Normalize(float(pr_all.min()), float(pr_all.max()))

    def _fmt(ax):
        # 对数纵轴去次刻度标签杂乱: 仅标 1/2/3/5×10ⁿ, 次刻度不标
        ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 3, 5),
                                              numticks=12))
        ax.yaxis.set_minor_locator(LogLocator(base=10, subs=(4, 6, 7, 8, 9),
                                              numticks=12))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        ax.yaxis.set_minor_formatter(NullFormatter())

    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.0),
                             constrained_layout=True)
    sc = None
    for ax, r in zip(axes, res):
        nu = r["nu_set"]; fn = r["gamma_fn2"]["Nu"]
        sc = ax.scatter(nu["Re"], nu["gamma_Nu"], s=34, c=nu["Pr"],
                        cmap=PR_CMAP, norm=prnorm, lw=.4, edgecolors=IVORY)
        Pr_med = float(nu["Pr"].median())
        Re_line = np.geomspace(nu["Re"].min(), nu["Re"].max(), 60)
        ax.plot(Re_line, fn["G0"] * Re_line ** fn["a"] * Pr_med ** fn["b"],
                color=INK, lw=1.6, label="拟合 @ 中位 Pr")
        ax.axhline(1.0, color=G500, lw=.8, ls=":")
        ax.set_xscale("log"); ax.set_yscale("log"); _fmt(ax)
        ax.set_ylim(top=float(nu["gamma_Nu"].max()) * 1.5)
        # \u03b3 \u4e0b\u6807\u7528 mathtext \u6e32\u67d3\uff08\u7528\u6237\u53cd\u9988 2026-07-16: \u88f8 \u03b3_Nu \u672a\u6e32\u67d3\uff09
        style_journal_ax(ax, "Re", r"$\gamma_{\mathrm{Nu}}$",
                         f"{r['topo']} 7/0.6 \u2014 "
                         r"$\gamma_{\mathrm{Nu}}$"
                         "(Re, Pr)\uff08\u4e24\u4fa7\u5408\u5e76\uff09")
        tag = "" if fn["sig"] else "\uff08Pr \u9879\u4e0d\u663e\u8457\uff09"
        ax.text(0.035, 0.95,
                r"$\gamma_{\mathrm{Nu}}$"
                f" = {fn['G0']:.3g}\u00b7Re$^{{{fn['a']:+.3f}}}$\u00b7Pr$^{{{fn['b']:+.3f}}}$\n{tag}",
                transform=ax.transAxes, fontsize=CHART_ANNO_FS, color=INK,
                va="top", bbox=ANNO_BOX)
    cb = fig.colorbar(sc, ax=list(axes), fraction=.032, pad=.012)
    cb.set_label("Pr", fontsize=10.5); cb.ax.tick_params(labelsize=8.5)
    charts["gamma_nu"] = _svg(fig, "gamma_nu")

    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.0),
                             constrained_layout=True)
    for ax, r in zip(axes, res):
        fs_ = r["f_set"]
        h = fs_[fs_["side"] == "hot"]; c = fs_[fs_["side"] == "cold"]
        ax.scatter(h["Re"], h["gamma_f"], s=26, facecolors="none",
                   edgecolors=HOT, lw=1.1, marker="s",
                   label=r"$\gamma_{\mathrm{f}}$ hot")
        ax.scatter(c["Re"], c["gamma_f"], s=26, color=COLD, lw=0,
                   marker="o", label=r"$\gamma_{\mathrm{f}}$ cold")
        Re_line = np.geomspace(fs_["Re"].min(), fs_["Re"].max(), 60)
        for key, col in (("f_hot", HOT), ("f_cold", COLD)):
            fn = r["gamma_fn"][key]
            ax.plot(Re_line, fn["G0"] * Re_line ** fn["d"],
                    color=col, lw=1.4)
        ax.axhline(1.0, color=G500, lw=.8, ls=":")
        ax.set_xscale("log"); ax.set_yscale("log"); _fmt(ax)
        # \u9876\u90e8\u4f59\u91cf \u00d73: \u7ed9\u516c\u5f0f\u6846\u7559\u7a7a, \u4e0d\u538b hot \u4fa7\u70b9\u7fa4\uff08\u7528\u6237\u53cd\u9988 2026-07-16\uff09
        ax.set_ylim(top=float(fs_["gamma_f"].max()) * 3.0)
        style_journal_ax(ax, "Re", r"$\gamma_{\mathrm{f}}$",
                         f"{r['topo']} 7/0.6 \u2014 "
                         r"$\gamma_{\mathrm{f}}$"
                         "(Re)\uff08\u5206\u4fa7\uff09")
        ax.legend(fontsize=CHART_LEGEND_FS, labelcolor=G700,
                  loc="lower right")
        # \u516c\u5f0f\u6807\u6ce8\u4e0e \u03b3_Nu \u56fe\u540c\u6b3e: \u7edf\u4e00\u76d2\u5f0f ANNO_BOX; \u03b3 \u4e0b\u6807 mathtext
        fh = r["gamma_fn"]["f_hot"]; fc = r["gamma_fn"]["f_cold"]
        ax.text(0.035, 0.95,
                r"$\gamma_{\mathrm{f,hot}}$"
                f" = {fh['G0']:.3g}\u00b7Re$^{{{fh['d']:+.3f}}}$\n"
                r"$\gamma_{\mathrm{f,cold}}$"
                f" = {fc['G0']:.2g}\u00b7Re$^{{{fc['d']:+.3f}}}$",
                transform=ax.transAxes, fontsize=CHART_ANNO_FS, color=INK,
                va="top", bbox=ANNO_BOX)
    charts["gamma_f"] = _svg(fig, "gamma_f")

    # ── parity 辅图（保留: 恒定倍数一致性的判读） ────────────────
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 5.2))
    for ax, r in zip(axes, res):
        _parity(ax, r, "nu_set", "Nu", "Nu_cfd",
                f"{r['topo']} 7/0.6 — Nu parity")
    axes[0].text(0.97, 0.03,
                 "黑实线 45° · 灰虚线 ±20% · 同色线 = 分侧中位倍数",
                 transform=axes[0].transAxes, ha="right",
                 fontsize=CHART_LEGEND_FS, color=G700)
    fig.tight_layout()
    charts["nu_parity"] = _svg(fig, "nu_parity")

    return charts


def build_html(res: list[dict], charts: dict[str, str],
               subst_geom: bool = False) -> str:
    """subst_geom=True: CFD 关联式代入实际 D_h、L（(D_h/L)^d 并入 c_eff）,
    与实验拟合同形直接可比 —— 输出到 *_subst.html, 原版不动."""
    stamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")

    # ── 方案 A（2026-07-15）: hero 大数字 + 公式对比表 + 统计脚注 ──
    heroes = []
    for r in res:
        gn = r["gamma_nu_pt"]["pooled"]
        heroes.append(f"""
    <div class="hero"><div class="lbl">{M_GNU} · {r['topo']} 7/0.6</div>
      <div class="big">×{gn[0]:.2f}</div>
      <div class="sub">中位 {gn[1]:.2f} [{gn[2]:.2f}, {gn[3]:.2f}]</div></div>""")
    for r in res:
        gh, gc = r["gamma_f_pt"]["hot"], r["gamma_f_pt"]["cold"]
        heroes.append(f"""
    <div class="hero"><div class="lbl">{M_GF} · {r['topo']} 7/0.6</div>
      <div class="big">{gh[0]:.1f}<span class="u"> / </span>{gc[0]:.1f}</div>
      <div class="sub">hot / cold 均值 · 中位 {gh[1]:.1f} / {gc[1]:.1f}</div></div>""")

    def _nu_math(c, a):
        return math_block(mi('Nu'), mo('='), mn(f"{c:.4f}"), mo('·'),
                          msup(mi('Re'), mn(f"{a:.4f}")), mo('·'),
                          msup(mi('Pr'), mrow(mn(1), mo('/'), mn(3))))

    cmp_rows = []
    for r in res:
        nf = r["nu_fit"]
        co = SCO2_NU_COEFFS[r["topo"]]
        if subst_geom:
            # 代入几何: (D_h/L)^d 并入系数, 与实验拟合同形;
            # 修正系数 = 两条同形关联式相除 γ = (c_exp/c_eff)·Re^Δa
            gfac = (r["Dh_m"] * 1e3 / L_MM) ** co["d"]
            c_eff = co["c"] * gfac
            cfd_cell = (
                _nu_math(c_eff, co["a"])
                + f'<div style="font-family:var(--mono);font-size:10.5px;'
                f'color:var(--g500)">D_h={r["Dh_m"] * 1e3:.3f}mm · L=7mm · '
                f'(D_h/L)^d={gfac:.4f} 已并入系数</div>')
            ratio, da = nf["c"] / c_eff, nf["a"] - co["a"]
            corr_math = math_block(
                mi('γ'), mo('='), mn(f"{ratio:.4f}"), mo('·'),
                msup(mi('Re'), mn(f"{da:+.4f}".replace('-', '−'))))
            cmp_rows.append(f"""
      <tr><td class="topo">{r['topo']} 7/0.6</td>
          <td>{_nu_math(nf['c'], nf['a'])}</td>
          <td>{cfd_cell}</td>
          <td>{corr_math}</td></tr>""")
        else:
            cfd_cell = math_block(
                mi('Nu'), mo('='), mn(f"{co['c']:.4f}"), mo('·'),
                msup(mi('Re'), mn(f"{co['a']:.4f}")), mo('·'),
                msup(mi('Pr'), mrow(mn(1), mo('/'), mn(3))), mo('·'),
                paren_pow(mfrac(msub(mi('D'), mi('h')), mi('L')),
                          f"{co['d']:.4f}".replace('-', '−')))
            cmp_rows.append(f"""
      <tr><td class="topo">{r['topo']} 7/0.6</td>
          <td>{_nu_math(nf['c'], nf['a'])}</td>
          <td>{cfd_cell}</td></tr>""")
    if subst_geom:
        cmp_head = ("<tr><th>几何</th><th>实验拟合（粗糙 SLM 件, 仅此几何）</th>"
                    "<th>CFD 关联式（代入 7/0.6 几何, 光滑壁）</th>"
                    "<th>修正系数（实验/CFD 相除）</th></tr>")
    else:
        cmp_head = ("<tr><th>几何</th><th>实验拟合（粗糙 SLM 件, 仅此几何）</th>"
                    "<th>CFD 关联式（产线 SCO2_NU_COEFFS, 光滑壁）</th></tr>")
    cmp_table = f"""
    <div class="cmp-wrap"><table class="cmp">
      {cmp_head}
      {''.join(cmp_rows)}
    </table></div>"""

    # 统计明细: 密排 statline 改小号 booktabs 表（优化 C, 2026-07-16）
    stat_rows = []
    for r in res:
        gn, gf, nf = r["gamma_nu_pt"], r["gamma_f_pt"], r["nu_fit"]
        d = r["nu_set"]
        stat_rows.append(
            f'<tr><td>{r["topo"]}</td>'
            f'<td class="n">{gn["hot"][0]:.2f} / {gn["cold"][0]:.2f}</td>'
            f'<td class="n">{r["gamma_nu_fit"]:.2f}</td>'
            f'<td class="n">{gf["hot"][1]:.2f} [{gf["hot"][2]:.2f}, {gf["hot"][3]:.2f}]</td>'
            f'<td class="n">{gf["cold"][1]:.2f} [{gf["cold"][2]:.2f}, {gf["cold"][3]:.2f}]</td>'
            f'<td class="n">{nf["medape"]:.1%}（n={nf["n"]}）</td>'
            f'<td class="n">{d["Re"].min():,.0f}–{d["Re"].max():,.0f}</td></tr>')
    stat_table = (
        '<table class="spec" style="margin-top:14px"><thead>'
        f'<tr><th>几何</th><th class="n">{M_GNU} 均值 hot / cold</th>'
        f'<th class="n">锚定拟合 {M_G}</th>'
        f'<th class="n">{M_GF} hot 中位 [p5, p95]</th>'
        f'<th class="n">{M_GF} cold 中位 [p5, p95]</th>'
        f'<th class="n">实验拟合 medAPE</th>'
        f'<th class="n">Re 窗</th></tr></thead><tbody>'
        + "".join(stat_rows) + "</tbody></table>")

    # 每图数据表（优化 D: dataviz 规范的 table view, 折叠不占版面）
    def _dtable(label, header, rows_html):
        return (f'<details class="dtable"><summary>{label}</summary>'
                f'<div class="dwrap"><table><thead><tr>{header}</tr></thead>'
                f'<tbody>{rows_html}</tbody></table></div></details>')

    nu_rows, f_rows = "", ""
    for r in res:
        for _, p in r["nu_set"].sort_values("Re").iterrows():
            nu_rows += (f'<tr><td>{r["topo"]}</td><td>{p["side"]}</td>'
                        f'<td>{p["Re"]:,.0f}</td><td>{p["Pr"]:.3f}</td>'
                        f'<td>{p["Nu"]:.1f}</td><td>{p["Nu_cfd"]:.1f}</td>'
                        f'<td>{p["gamma_Nu"]:.2f}</td></tr>')
        for _, p in r["f_set"].sort_values("Re").iterrows():
            f_rows += (f'<tr><td>{r["topo"]}</td><td>{p["side"]}</td>'
                       f'<td>{p["Re"]:,.0f}</td><td>{p["f"]:.2f}</td>'
                       f'<td>{p["f_cfd"]:.2f}</td>'
                       f'<td>{p["gamma_f"]:.2f}</td></tr>')
    n_nu = sum(len(r["nu_set"]) for r in res)
    n_f = sum(len(r["f_set"]) for r in res)
    nu_dt = _dtable(f"数据表 · Nu 集 {n_nu} 点（点击展开）",
                    "<th>几何</th><th>side</th><th>Re</th><th>Pr</th>"
                    "<th>Nu 实验</th><th>Nu CFD</th><th>γ_Nu</th>", nu_rows)
    f_dt = _dtable(f"数据表 · f 集 {n_f} 点（点击展开）",
                   "<th>几何</th><th>side</th><th>Re</th><th>f 实验</th>"
                   "<th>f CFD</th><th>γ_f</th>", f_rows)

    # ── γ 函数档案（复用大数字带 .heroes + booktabs .cmp; 用户偏好样式）──
    import math as _math

    def _mn_sci(x):
        if x == 0:
            return [mn("0")]
        exp = int(_math.floor(_math.log10(abs(x))))
        if -2 <= exp <= 4:
            return [mn(f"{x:.4g}")]
        mant = x / 10.0 ** exp
        return [mn(f"{mant:.2f}"), mo("\u00d7"),
                msup(mn("10"), mn(str(exp).replace("-", "\u2212")))]

    def _gamma_math(G0, a, b=None):
        parts = list(_mn_sci(G0)) + [mo("\u00b7"),
                 msup(mi("Re"), mn(f"{a:+.3f}".replace("-", "\u2212")))]
        if b is not None:
            parts += [mo("\u00b7"),
                      msup(mi("Pr"), mn(f"{b:+.3f}".replace("-", "\u2212")))]
        return math_block(*parts)

    _dia = next(r for r in res if r["topo"] == "Diamond")
    _gyr = next(r for r in res if r["topo"] == "Gyroid")

    def _gcell(r, kind):
        if kind == "Nu":
            fn = r["gamma_fn2"]["Nu"]
            return _gamma_math(fn["G0"], fn["a"], fn["b"])
        fn = r["gamma_fn"][kind]
        return _gamma_math(fn["G0"], fn["d"])

    _grows = ""
    for _lab, _kind, _note in (
            ("\u03b3<sub>Nu</sub>(Re, Pr)", "Nu", "\u6362\u70ed\u589e\u5f3a"),
            ("\u03b3<sub>f,hot</sub>(Re)", "f_hot", "\u6469\u64e6\u00b7\u9ad8\u6e29\u4fa7"),
            ("\u03b3<sub>f,cold</sub>(Re)", "f_cold", "\u6469\u64e6\u00b7\u4f4e\u6e29\u4fa7")):
        _grows += (f'<tr><td class="topo">{_lab}<br>'
                   f'<span style="font-family:var(--mono);font-size:10.5px;'
                   f'font-weight:400;color:var(--g500)">{_note}</span></td>'
                   f'<td>{_gcell(_dia, _kind)}</td>'
                   f'<td>{_gcell(_gyr, _kind)}</td></tr>')
    gamma_table = (f'<div class="cmp-wrap"><table class="cmp">'
                   f'<tr><th>\u500d\u6570\u51fd\u6570</th>'
                   f'<th>Diamond 7/0.6</th><th>Gyroid 7/0.6</th></tr>'
                   f'{_grows}</table></div>')

    # \u2500\u2500 f \u4fa7\u540c\u5f62\u5bf9\u6bd4\u8868\uff08\u4ec5 subst \u7248; \u4e0e Nu \u7684 cmp \u8868\u540c\u6b3e\u4e09\u4ef6\u5957\uff09\u2500\u2500
    f_cmp = ""
    if subst_geom:
        def _f_math(B, n):
            return math_block(mi('f'), mo('='), *_mn_sci(B), mo('\u00b7'),
                              msup(mi('Re'),
                                   mn(f"{n:+.4f}".replace('-', '\u2212'))))

        frows = ""
        for r in res:
            fcf = r["f_cfd_fit"]
            for side in ("hot", "cold"):
                ff = r["f_fit"][side]
                corr = math_block(
                    mi('\u03b3'), mo('='), *_mn_sci(ff['B'] / fcf['B']),
                    mo('\u00b7'),
                    msup(mi('Re'),
                         mn(f"{ff['n'] - fcf['n']:+.4f}".replace('-', '\u2212'))))
                frows += (f'<tr><td class="topo">{r["topo"]} \u00b7 {side}</td>'
                          f'<td>{_f_math(ff["B"], ff["n"])}</td>'
                          f'<td>{_f_math(fcf["B"], fcf["n"])}</td>'
                          f'<td>{corr}</td></tr>')
        f_cmp = ('<div class="cmp-wrap"><table class="cmp">'
                 '<tr><th>\u51e0\u4f55 \u00b7 \u4fa7</th><th>\u5b9e\u9a8c\u62df\u5408\uff08\u5206\u4fa7\uff09</th>'
                 '<th>CFD D-F\uff08\u4ee3\u5165\u51e0\u4f55, Re \u7a97\u5185\u5e42\u5f8b\u62df\u5408\uff09</th>'
                 '<th>\u4fee\u6b63\u7cfb\u6570\uff08\u5b9e\u9a8c/CFD \u76f8\u9664\uff09</th></tr>'
                 f'{frows}</table></div>')

    # \u2500\u2500 \u5de5\u7a0b\u53d6\u7528\u5361\uff08\u4f18\u5316 A, 2026-07-16, \u4ec5 subst \u7248\uff09: \u5168\u9875\u4fee\u6b63\u7cfb\u6570
    #    \u6536\u655b\u4e00\u5904, \u7ea2\u6846\u5361\u7247, \u53ef\u76f4\u63a5\u6284\u8fdb\u6c42\u89e3\u5668 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    usecard = ""
    if subst_geom:
        def _corr(G0, d):
            return math_block(mi('\u03b3'), mo('='), *_mn_sci(G0), mo('\u00b7'),
                              msup(mi('Re'),
                                   mn(f"{d:+.4f}".replace('-', '\u2212'))))

        _cells = {"Nu": {}, "f_hot": {}, "f_cold": {}}
        for r in res:
            co = SCO2_NU_COEFFS[r["topo"]]
            c_eff = co["c"] * (r["Dh_m"] * 1e3 / L_MM) ** co["d"]
            _cells["Nu"][r["topo"]] = _corr(r["nu_fit"]["c"] / c_eff,
                                            r["nu_fit"]["a"] - co["a"])
            fcf = r["f_cfd_fit"]
            for side in ("hot", "cold"):
                ff = r["f_fit"][side]
                _cells[f"f_{side}"][r["topo"]] = _corr(
                    ff["B"] / fcf["B"], ff["n"] - fcf["n"])
        _urows = ""
        for key, lab, note in (
                ("Nu", f"{M_GNU}(Re)", "\u6362\u70ed\u4fee\u6b63 \u00b7 \u4e24\u4fa7\u5408\u7528"),
                ("f_hot", f"{M_GF}(Re) \u00b7 hot", "\u6469\u64e6\u4fee\u6b63 \u00b7 \u9ad8\u6e29\u4fa7"),
                ("f_cold", f"{M_GF}(Re) \u00b7 cold", "\u6469\u64e6\u4fee\u6b63 \u00b7 \u4f4e\u6e29\u4fa7")):
            _urows += (f'<tr><td class="topo">{lab}<br>'
                       f'<span style="font-family:var(--mono);'
                       f'font-size:10.5px;font-weight:400;'
                       f'color:var(--g500)">{note}</span></td>'
                       f'<td>{_cells[key]["Diamond"]}</td>'
                       f'<td>{_cells[key]["Gyroid"]}</td></tr>')
        _win = {r["topo"]: (min(float(r["nu_set"]["Re"].min()),
                                float(r["f_set"]["Re"].min())),
                            max(float(r["nu_set"]["Re"].max()),
                                float(r["f_set"]["Re"].max())))
                for r in res}
        usage_math = (math_inline(mi("Nu"), mo("="),
                                  msub(mi("\u03b3"), _up("Nu")), mo("\u00b7"),
                                  msub(mi("Nu"), _up("cfd")))
                      + "\uff0c"
                      + math_inline(mi("f"), mo("="),
                                    msub(mi("\u03b3"), _up("f")), mo("\u00b7"),
                                    msub(mi("f"), _up("cfd"))))
        usecard = (
            f'<div class="usecard">'
            f'<div class="uc-h">CLOSURE CORRECTION \u00b7 \u53d6\u7528\u5f0f \u2014\u2014 '
            f'\u4e58\u5728\u5149\u6ed1\u58c1 CFD \u95ed\u5408\u4e0a\uff1a{usage_math}</div>'
            f'<table class="cmp"><tr><th>\u4fee\u6b63\u51fd\u6570</th>'
            f'<th>Diamond 7/0.6</th><th>Gyroid 7/0.6</th></tr>'
            f'{_urows}</table>'
            f'<div class="uc-note">\u9002\u7528\u7a97\uff08\u5b9e\u9a8c\u8986\u76d6\uff0c<b>\u4ec5\u7a97\u5185\u63d2\u503c</b>\uff09\uff1a'
            f'Diamond {M_RE} {_win["Diamond"][0]:,.0f}\u2013{_win["Diamond"][1]:,.0f}'
            f' \u00b7 Gyroid {M_RE} {_win["Gyroid"][0]:,.0f}\u2013{_win["Gyroid"][1]:,.0f}\u3002'
            f'cold \u4fa7\u6307\u6570\u7269\u7406\u4e0d\u5408\u7406\uff08\u538b\u5dee\u8fd1\u4f20\u611f\u5668\u5730\u677f\uff09\uff0c<b>\u7981\u6b62\u5916\u63a8</b>\uff1b'
            f'{M_G} = \u7c97\u7cd9\u5ea6 \u00d7 \u51e0\u4f55\u5916\u63a8\u7684\u5408\u6210\uff0c\u57fa\u51c6 = \u4ea7\u7ebf\u5149\u6ed1\u58c1 CFD \u95ed\u5408'
            f'\uff08SCO2_NU_COEFFS + sco2_df cF\uff09\u3002\u53e3\u5f84\uff1a\u5b9e\u9a8c/CFD \u4e24\u6761\u540c\u5f62\u5173\u8054\u5f0f'
            f'\u76f8\u9664\uff0c\u4e0e 05 \u8282\u9010\u70b9\u62df\u5408\u4e92\u76f8\u5370\u8bc1\u3002</div></div>')

    subst_note = ("；CFD 公式已代入实际 D<sub>h</sub>、L（几何项并入系数），"
                  "红色「修正」= 实验/CFD 两条关联式相除的修正系数"
                  if subst_geom else "")
    body = (
        (section("00", "闭合修正 · 工程取用",
                 "全页六条修正系数收敛为一处可抄用的取用式；"
                 "推导与验证见后续各节。", usecard)
         if subst_geom else "")
        + section("01", "数据与过滤",
                "实验数据的口径、约化方式与过滤规则。",
                f"""
    <div class="speclist">
      <div class="srow"><div class="sk">实验工况</div>
        <div class="sv">sCO2–sCO2 逆流换热器；高温回路 ~9 MPa / 低温回路
        ~10 MPa；远临界区 Pr 0.8–1.0。每工况产两个数据点（高温侧、低温侧）。</div></div>
      <div class="srow"><div class="sk">数据约化</div>
        <div class="sv">Re / Nu / Darcy f 全部从原始测量重算，用 repo 体素 Dh
        口径（与 CFD 关联式同源）；物性由 CoolProp 取进出口均温均压。</div></div>
      <div class="srow"><div class="sk">壁温构造</div>
        <div class="sv">取两股流均温 {M_TW}（与 D-7-6 历史分析同款）⇒
        {M_NUPROP}，小 {M_DT} 工况放大伪影。</div></div>
    </div>
    <table class="spec"><thead>
      <tr><th>过滤规则</th><th>条件</th><th>理由 / 影响</th></tr></thead><tbody>
      <tr><td>负压差</td><td><code>ΔP ≤ 0</code> 剔除</td>
          <td>低流量端传感器坏点（用户裁决剔除）</td></tr>
      <tr><td>小温差</td><td><code>ΔT_streams ≤ 10 K</code> 剔除</td>
          <td>均温构造下 {M_NUPROP_S}，小 {M_DT} 爆伪影 —— Diamond 因此仅剩约一半</td></tr>
      <tr><td>热平衡</td><td><code>|HB| &gt; 0.15</code> 剔除</td>
          <td>仅作用于 Nu 集</td></tr>
    </tbody></table>
    <div class="callout">⚠ 实验 <b>Darcy f 高温侧系统性高于低温侧数倍</b>
    （传感器 / 边界效应，用户裁决不深究）—— 故所有 f 倍数<b>分侧报告</b>，不合并。</div>""")
        + section("02", "实验关联式与倍数汇总",
                  "先读大数字带（逐点倍数），再看两套关联式并排与统计明细；"
                  "倍数的定义与解读边界收在本节末。",
                  f'<div class="heroes">{"".join(heroes)}</div>'
                  + cmp_table + stat_table + f"""
    <div class="speclist" style="margin-top:24px">
      <div class="srow"><div class="sk">倍数定义</div>
        <div class="sv">{M_G_GT1} = 实验高于 CFD 光滑壁预测
        （同 {M_RE}、{M_PR} 逐点比，报均值与中位 [p5, p95]）。</div></div>
      <div class="srow"><div class="sk">几何在网</div>
        <div class="sv">7/0.6 现有<b>真实 CFD</b>（2026-07 补测，D_7_6 / G_7_6
        各 270 案例），已进 CFD 关联式拟合——不再是此前的 RBF 几何外推。
        关联式对该几何真实 CFD 的内插 medAPE：Diamond 9.0% / Gyroid 8.8%。</div></div>
      <div class="srow"><div class="sk">解读边界</div>
        <div class="sv">{M_G} 现为<b>纯粹的粗糙度增强因子</b>（实验粗糙 SLM 件
        / CFD 光滑壁），已不含几何外推误差。参考：空气侧 SLM 粗糙度 Nu
        增强 ~1.28。</div></div>
    </div>""")
        + section("03", "Nu：实验 vs CFD",
                  "主图（期刊样式）：藏青方框 = 实验 hot 侧、亮青实心圆 = "
                  "实验 cold 侧，浅紫三角 + 浅紫虚线 = CFD 预测，黑实线 = "
                  "实验合并拟合，公式标注在曲线旁——实线与虚线的纵向间距即"
                  "倍数。辅图 parity 同一套分侧色：点贴同色参考线 = 恒定"
                  "倍数偏差（灰虚线 ±20%）。",
                  f"<figure><div class='figwrap' role='img' "
                  f"aria-label='Nu–Re：实验点与拟合曲线 vs CFD 预测曲线'>"
                  f"{charts['nu']}</div>"
                  f"<figcaption>Nu–Re 主图：藏青方框 = hot、亮青实心圆 = cold；黑实线 = 实验合并拟合、浅紫虚线 = CFD 关联式（浅紫三角 = 逐点预测）；公式标注于曲线旁{subst_note}。</figcaption>"
                  f"{nu_dt}</figure>"
                  f"<figure><div class='figwrap' role='img' "
                  f"aria-label='Nu parity：实验 vs CFD 预测'>"
                  f"{charts['nu_parity']}</div>"
                  f"<figcaption>Nu parity 辅图：分侧色同主图（藏青方框 hot / 亮青实心圆 cold）；黑实线 45°、灰虚线 ±20%、同色线 = 分侧中位倍数。</figcaption></figure>")
        + section("04", "Darcy f：实验 vs CFD",
                  "主图同 Nu 画法（藏青线 = hot 侧拟合、亮青线 = cold 侧拟合，"
                  "浅紫虚线 = CFD D-F）。hot 侧实验 f 近乎不随 Re 变化、两侧互差"
                  "一倍——非恒定倍数，压差测量含非摩擦成分的特征。"
                  + ("下表并列实验/CFD 同形幂律与分侧修正系数（相除；"
                     "CFD D-F 曲线先在实验 Re 窗内拟成幂律）。"
                     if subst_geom else ""),
                  f_cmp
                  + f"<figure><div class='figwrap' role='img' "
                  f"aria-label='f–Re：实验点与拟合曲线 vs CFD D-F 曲线'>"
                  f"{charts['f']}</div>"
                  f"<figcaption>Darcy f–Re 主图：藏青方框/藏青线 = hot 侧、亮青实心圆/亮青线 = cold 侧、浅紫三角 + 浅紫虚线 = CFD D-F；"
                  + ("左上标注实验/CFD 同形幂律与红色分侧修正系数。"
                     if subst_geom else "顶部标注分侧中位倍数。")
                  + f"</figcaption>{f_dt}</figure>")
        + section("05", "倍数 γ 的函数关系",
                  "γ 的拟合形式、Pr 依赖解读与取用边界。",
                  f"""
    <div class="speclist">
      <div class="srow"><div class="sk">拟合形式</div>
        <div class="sv"><b>{M_GNU_FORM}</b>（点按 {M_PR} 着色）；
        <b>{M_GF_FORM}</b>（无 {M_PR}）—— 摩擦是纯动量现象，与 Prandtl 数无关
        （物理约束，非拟合选择）。</div></div>
      <div class="srow"><div class="sk">{M_GNU} 的 {M_B}</div>
        <div class="sv">{M_NUEXP} 与 {M_NUCFD} 都含 {M_PR13}，故 {M_B} 是【超出
        标准 1/3 律的<b>残余</b>】；远临界 {M_PR} 仅 0.79–1.04 ⇒ {M_B} 大多不显著
        （Diamond {M_B}/se≈0.3）。<b>{M_RE} 才是主变量。</b></div></div>
      <div class="srow"><div class="sk">读图结论</div>
        <div class="sv">{M_GNU} 的 {M_RE} 指数 ≈ ±0.02（平线，<b>均值即可代表</b>）；
        {M_GF} 的 {M_RE} 指数显著（cold 侧尤甚），取用时<b>代入函数</b>，不用均值。</div></div>
    </div>
    <div class="callout">⚠ {M_GF} <b>cold 侧指数物理不合理</b>（低 {M_RE} 端压差近
    传感器地板的系统性低偏）—— 函数<b>仅限实验 {M_RE} 窗内插值，禁止外推</b>。</div>"""
                  + gamma_table
                  + f"<figure><div class='figwrap' role='img' "
                  f"aria-label='γ_Nu 随 Re：散点与幂律拟合'>"
                  f"{charts['gamma_nu']}</div>"
                  f"<figcaption>{M_GNU}(Re)：两侧合并；拟合线近水平（指数 ±0.02），均值即可代表。</figcaption></figure>"
                  f"<figure><div class='figwrap' role='img' "
                  f"aria-label='γ_f 随 Re（分侧）：散点与幂律拟合'>"
                  f"{charts['gamma_f']}</div>"
                  f"<figcaption>{M_GF}(Re) 分侧幂律（无 {M_PR}）：取用时代入函数；cold 侧指数物理不合理，仅限窗内插值。</figcaption></figure>")
)

    gN = {r["topo"]: r["gamma_nu_pt"]["pooled"][0] for r in res}
    gfh = {r["topo"]: r["gamma_f_pt"]["hot"][0] for r in res}
    gfc = {r["topo"]: r["gamma_f_pt"]["cold"][0] for r in res}
    re_lo = min(r["nu_set"]["Re"].min() for r in res)
    re_hi = max(r["nu_set"]["Re"].max() for r in res)
    aside = f"""
      <div class="at">速览 · AT A GLANCE</div>
      <div class="row"><span class="k">换热增强 {M_GNU}</span>
        <span class="v"><b>×{gN['Diamond']:.2f}</b> D · <b>×{gN['Gyroid']:.2f}</b> G</span></div>
      <div class="row"><span class="k">摩擦增强 {M_GF} · hot/cold</span>
        <span class="v">{gfh['Diamond']:.1f}/{gfc['Diamond']:.1f} · {gfh['Gyroid']:.1f}/{gfc['Gyroid']:.1f}</span></div>
      <div class="row"><span class="k">工况数</span>
        <span class="v">Diamond 51 · Gyroid 44</span></div>
      <div class="row"><span class="k">Re 范围</span>
        <span class="v">{re_lo:,.0f} – {re_hi:,.0f}</span></div>
      <div class="row"><span class="k">Pr 范围</span>
        <span class="v">0.79 – 1.04（远临界）</span></div>
      <div class="row"><span class="k">数据源</span>
        <span class="v"><code>sCO2-Experient.xlsx</code></span></div>"""
    ver = "（CFD 代入几何版）" if subst_geom else ""
    ver_eb = " · CFD 代入几何版" if subst_geom else ""
    toc = [("01", "数据与过滤", "s1"), ("02", "关联式与倍数", "s2"),
           ("03", "Nu 对比", "s3"), ("04", "f 对比", "s4"),
           ("05", "γ(Re,Pr) 函数", "s5")]
    if subst_geom:
        toc = [("00", "工程取用", "s0")] + toc
    return page(
        title="sCO2 实验 vs CFD 闭合 — Nu 与 Darcy f 倍数" + ver,
        eyebrow=f"SJTU-TPMSHX · D-7-6 / G-7-6 实验对标{ver_eb} · {stamp}",
        h1="sCO2 实验 vs <em>CFD 闭合</em>：Nu 与 Darcy f 差多少倍",
        intro="用 D-7-6 / G-7-6 实测数据，量化实验相对现产线光滑壁 CFD "
              "闭合的换热与摩擦倍数 " + M_G + "。",
        toc=toc,
        body=body, aside=aside,
        footer_left="SJTU-TPMSHX — sCO2 experiment vs CFD closures",
        footer_right=f"台账 SCO2-CFD · {stamp}")


def main() -> None:
    res = [analyse(t) for t in TOPOS]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    pts = pd.concat(
        [pd.concat([r["nu_set"].assign(metric="Nu"),
                    r["f_set"].assign(metric="f")]) for r in res],
        ignore_index=True)
    pts.to_csv(REPORT_DIR / "exp_points.csv", index=False)

    rows = []
    for r in res:
        rows.append(dict(
            topo=r["topo"], **{f"nu_{k}": v for k, v in r["nu_fit"].items()},
            gamma_nu_fit=r["gamma_nu_fit"],
            gamma_nu_mean=r["gamma_nu_pt"]["pooled"][0],
            gamma_nu_med=r["gamma_nu_pt"]["pooled"][1],
            gamma_nu_hot_mean=r["gamma_nu_pt"]["hot"][0],
            gamma_nu_cold_mean=r["gamma_nu_pt"]["cold"][0],
            gamma_f_hot_mean=r["gamma_f_pt"]["hot"][0],
            gamma_f_hot_med=r["gamma_f_pt"]["hot"][1],
            gamma_f_cold_mean=r["gamma_f_pt"]["cold"][0],
            gamma_f_cold_med=r["gamma_f_pt"]["cold"][1],
            f_fit_hot_B=r["f_fit"]["hot"]["B"],
            f_fit_hot_n=r["f_fit"]["hot"]["n"],
            f_fit_cold_B=r["f_fit"]["cold"]["B"],
            f_fit_cold_n=r["f_fit"]["cold"]["n"],
            gfn_nu_G0=r["gamma_fn"]["Nu"]["G0"],
            gfn_nu_d=r["gamma_fn"]["Nu"]["d"],
            gfn_fhot_G0=r["gamma_fn"]["f_hot"]["G0"],
            gfn_fhot_d=r["gamma_fn"]["f_hot"]["d"],
            gfn_fcold_G0=r["gamma_fn"]["f_cold"]["G0"],
            gfn_fcold_d=r["gamma_fn"]["f_cold"]["d"],
            gfn2_nu_G0=r["gamma_fn2"]["Nu"]["G0"],
            gfn2_nu_a=r["gamma_fn2"]["Nu"]["a"],
            gfn2_nu_b=r["gamma_fn2"]["Nu"]["b"],
            gfn2_nu_b_sig=r["gamma_fn2"]["Nu"]["sig"]))
    summary = pd.DataFrame(rows)
    summary.to_csv(REPORT_DIR / "exp_fit_summary.csv", index=False)

    charts = make_charts(res)
    (REPORT_DIR / "sco2_exp_vs_cfd.html").write_text(
        build_html(res, charts), encoding="utf-8")
    # 代入几何版（用户需求 2026-07-16）: 仅 CFD 关联式呈现口径不同
    charts_s = make_charts(res, subst_geom=True)
    (REPORT_DIR / "sco2_exp_vs_cfd_subst.html").write_text(
        build_html(res, charts_s, subst_geom=True), encoding="utf-8")
    for r in res:
        co = SCO2_NU_COEFFS[r["topo"]]
        c_eff = co["c"] * (r["Dh_m"] * 1e3 / L_MM) ** co["d"]
        print(f"修正系数[{r['topo']} Nu]: γ = "
              f"{r['nu_fit']['c'] / c_eff:.4f}·Re^"
              f"{r['nu_fit']['a'] - co['a']:+.4f}")
        fcf = r["f_cfd_fit"]
        for side in ("hot", "cold"):
            ff = r["f_fit"][side]
            print(f"修正系数[{r['topo']} f {side}]: γ = "
                  f"{ff['B'] / fcf['B']:.4g}·Re^"
                  f"{ff['n'] - fcf['n']:+.4f}")

    pd.set_option("display.width", 200)
    for r in res:
        nf, gn, gf = r["nu_fit"], r["gamma_nu_pt"], r["gamma_f_pt"]
        print(f"\n===== {r['topo']} 7/0.6 =====")
        print(f"实验 Nu 关联式: Nu = {nf['c']:.4f}·Re^{nf['a']:.4f}·Pr^(1/3)"
              f"  (medAPE {nf['medape']:.1%}, RMSRE {nf['rmsre']:.1%}, "
              f"n={nf['n']})")
        print(f"γ_Nu 逐点: 合并 均值 {gn['pooled'][0]:.2f} / 中位 "
              f"{gn['pooled'][1]:.2f} [{gn['pooled'][2]:.2f},{gn['pooled'][3]:.2f}]"
              f"  hot 均值 {gn['hot'][0]:.2f}  cold 均值 {gn['cold'][0]:.2f}"
              f"  |  锚定拟合 γ = {r['gamma_nu_fit']:.2f}")
        print(f"γ_f  逐点: hot 均值 {gf['hot'][0]:.2f} / 中位 {gf['hot'][1]:.2f} "
              f"[{gf['hot'][2]:.2f},{gf['hot'][3]:.2f}]  "
              f"cold 均值 {gf['cold'][0]:.2f} / 中位 {gf['cold'][1]:.2f} "
              f"[{gf['cold'][2]:.2f},{gf['cold'][3]:.2f}]")
        for s in ("hot", "cold"):
            ff = r["f_fit"][s]
            print(f"  实验 f 拟合[{s}]: f = {ff['B']:.3g}·Re^{ff['n']:.3f} "
                  f"(n={ff['npts']})")
        g = r["gamma_fn"]
        print(f"  γ(Re) 函数: γ_Nu = {g['Nu']['G0']:.3g}·Re^{g['Nu']['d']:+.3f}"
              f"  γ_f,hot = {g['f_hot']['G0']:.3g}·Re^{g['f_hot']['d']:+.3f}"
              f"  γ_f,cold = {g['f_cold']['G0']:.3g}·Re^{g['f_cold']['d']:+.3f}")
        g2 = r["gamma_fn2"]
        sg = "" if g2["Nu"]["sig"] else " (Pr 不显著)"
        print(f"  γ(Re,Pr) 函数: γ_Nu = {g2['Nu']['G0']:.3g}·Re^{g2['Nu']['a']:+.3f}"
              f"·Pr^{g2['Nu']['b']:+.3f}{sg}")
    print(f"\n已写出 {REPORT_DIR}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    main()
