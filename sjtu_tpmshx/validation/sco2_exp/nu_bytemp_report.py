"""nu_bytemp_report.py — sCO2 实验 Nu 按温度分层 vs CFD 关联式（代入实际 D_h/L）.

用法:
    python sjtu_tpmshx/validation/sco2_exp/nu_bytemp_report.py
输出:
    reports/sco2_exp/sco2_exp_nu_bytemp.html   （独立于主报告 sco2_exp_vs_cfd.html）

与主报告的区别
--------------
主报告用单一实验拟合 Nu = c·Re^a·Pr^(1/3)（跨全温区）。本报告改为
**按均温分 3 箱、每箱独立拟合 Nu = c·Re^a**，逐温度画曲线，并与
CFD 关联式（把 7/0.6 的实际 D_h、L 代入 (D_h/L)^d，收成等效系数
c_eff = c·(D_h/L)^d）逐温度对比。远临界 Pr 窄（0.8–1.0），温度主要
通过 Pr^(1/3) 进入 Nu，故各温度曲线在 log-log 上近乎平行、间距小。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PKG_ROOT = _THIS.parent.parent.parent
sys.path.insert(0, str(_THIS.parent))

from load_sco2_exp import load_exp                              # noqa: E402
from compare_exp_vs_cfd import (analyse as analyse_full,        # noqa: E402
                                make_charts as make_charts_full)
from sjtu_tpmshx.models.nu_correlations import SCO2_NU_COEFFS              # noqa: E402
from sjtu_tpmshx.models.tpms_props import geometry as tpms_geometry        # noqa: E402
from sjtu_tpmshx.validation.report_template import (                        # noqa: E402
    ANNO_BOX, CFD_C, CHART_ANNO_FS, CHART_LEGEND_FS,
    G300, G700, IVORY, SLATE,
    math_block, math_inline, mfrac, mi, mn, mo, mrow, msub, msup,
    page, paren_pow, section, style_journal_ax)

REPORT = _PKG_ROOT.parent / "reports" / "sco2_exp" / "sco2_exp_nu_bytemp.html"
TOPOS = ("Diamond", "Gyroid")
L_MM, T_MM = 7.0, 0.6
N_BINS = 3
# 温度分箱色（冷→暖，语义化: 低温蓝 / 中温琥珀 / 高温红）
BIN_COLORS = ["#2a78d6", "#eda100", "#e34948"]
BIN_NAMES = ["低温", "中温", "高温"]


# ── 行内 MathML 片段 ──────────────────────────────────────────────────
def _up(x):
    return mi(x, italic=False)


M_NU = math_inline(mi("Nu"))
M_RE = math_inline(mi("Re"))
M_PR = math_inline(mi("Pr"))
M_G_NU = math_inline(msub(mi("γ"), _up("Nu")))
M_G_F = math_inline(msub(mi("γ"), _up("f")))
M_DH = math_inline(msub(mi("D"), _up("h")))
M_PR13 = math_inline(msup(mi("Pr"), mrow(mn(1), mo("/"), mn(3))))
M_DHL = math_inline(paren_pow(mfrac(msub(mi("D"), _up("h")), mi("L")), "d"))
M_CEFF = math_inline(msub(mi("c"), _up("eff")))
M_NUFORM = math_inline(mi("Nu"), mo("="), msub(mi("c"), _up("eff")),
                       mo("·"), msup(mi("Re"), mi("a")), mo("·"),
                       msup(mi("Pr"), mrow(mn(1), mo("/"), mn(3))))
M_NUBIN = math_inline(mi("Nu"), mo("="), mi("c"), mo("·"),
                      msup(mi("Re"), mi("a")))


def _nu_ca_math(c, a):
    return math_block(mi("Nu"), mo("="), mn(f"{c:.4f}"), mo("·"),
                      msup(mi("Re"), mn(f"{a:.4f}")), mo("·"),
                      msup(mi("Pr"), mrow(mn(1), mo("/"), mn(3))))


# ── 分析 ──────────────────────────────────────────────────────────────

def analyse(topo: str) -> dict:
    df = load_exp(topo)
    ok = df[df.ok_dT & df.ok_hb & df.ok_done].copy()
    ok["Tc"] = ok["T_mean_K"] - 273.15
    ok["bin"] = pd.qcut(ok["Tc"], N_BINS, labels=list(range(N_BINS)))

    g = tpms_geometry(topo, L_MM, T_MM, 16.0)
    Dh_m = float(g["D_h"])
    co = SCO2_NU_COEFFS[topo]
    geom_factor = (Dh_m * 1e3 / L_MM) ** co["d"]       # (D_h/L)^d
    c_eff = co["c"] * geom_factor

    bins = []
    for bi in range(N_BINS):
        s = ok[ok["bin"] == bi]
        X = np.column_stack([np.ones(len(s)), np.log(s["Re"])])
        beta, *_ = np.linalg.lstsq(X, np.log(s["Nu"]), rcond=None)
        c_bin, a_bin = float(np.exp(beta[0])), float(beta[1])
        r = (c_bin * s["Re"] ** a_bin - s["Nu"]) / s["Nu"]
        # 该箱代表: 中位 T / Pr / Re 区间
        Re_lo, Re_hi = float(s["Re"].min()), float(s["Re"].max())
        Pr_med = float(s["Pr"].median())
        # exp/CFD 倍数（该箱几何中位 Re 处）
        Re_g = float(np.sqrt(Re_lo * Re_hi))
        nu_e = c_bin * Re_g ** a_bin
        nu_c = c_eff * Re_g ** co["a"] * Pr_med ** (1 / 3)
        bins.append(dict(
            bi=bi, n=len(s), T_lo=float(s["Tc"].min()),
            T_hi=float(s["Tc"].max()), T_med=float(s["Tc"].median()),
            Pr_med=Pr_med, Re_lo=Re_lo, Re_hi=Re_hi,
            c=c_bin, a=a_bin, medape=float(np.median(np.abs(r))),
            gamma=nu_e / nu_c))
    return dict(topo=topo, ok=ok, Dh_m=Dh_m, co=co,
                geom_factor=geom_factor, c_eff=c_eff, bins=bins)


# ── 图 ────────────────────────────────────────────────────────────────

def make_chart(res: list[dict]) -> str:
    """逐温度分面板: 行=拓扑, 列=温度箱; 每格一个温度的数据+实验拟合(实线)
    +CFD 关联式(黑虚线)。不再把所有温度曲线叠在一起。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import LogLocator, FuncFormatter, NullFormatter
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "text.color": SLATE, "axes.labelcolor": G700,
        # 融底（模板硬性规则 9）: 透明底 + IVORY 遮点色
        "figure.facecolor": "none",
        "legend.facecolor": IVORY, "legend.edgecolor": G300,
        "legend.framealpha": 1.0,
        # 内联 SVG（模板硬性规则 10）
        "svg.fonttype": "none"})

    fig, axes = plt.subplots(len(res), N_BINS, figsize=(13.5, 8.4),
                             sharey="row", sharex="row")
    for ri, r in enumerate(res):
        ok = r["ok"]; co = r["co"]
        for ci, b in enumerate(r["bins"]):
            ax = axes[ri, ci]
            c = BIN_COLORS[b["bi"]]
            s = ok[ok["bin"] == b["bi"]]
            ax.scatter(s["Re"], s["Nu"], s=32, color=c, lw=.4,
                       edgecolors=IVORY, alpha=.9, zorder=3,
                       label="实测")
            Re_line = np.geomspace(b["Re_lo"], b["Re_hi"], 40)
            ax.plot(Re_line, b["c"] * Re_line ** b["a"], color=c, lw=2.3,
                    zorder=4, label="实验拟合")
            ax.plot(Re_line, r["c_eff"] * Re_line ** co["a"]
                    * b["Pr_med"] ** (1 / 3), color=CFD_C, lw=1.6, ls="--",
                    zorder=4, label="CFD 关联式")
            ax.set_xscale("log"); ax.set_yscale("log")
            for axis in (ax.yaxis, ax.xaxis):
                axis.set_major_locator(LogLocator(base=10, subs=(1, 2, 3, 5),
                                                  numticks=12))
                axis.set_minor_locator(LogLocator(base=10,
                                                  subs=(4, 6, 7, 8, 9),
                                                  numticks=12))
                axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
                axis.set_minor_formatter(NullFormatter())
            # 统一期刊轴样式（模板 style_journal_ax; 共享轴只标边缘面板）
            style_journal_ax(
                ax, "Re" if ri == len(res) - 1 else "",
                "Nu" if ci == 0 else "",
                title=f"{r['topo']} · {BIN_NAMES[b['bi']]} "
                      f"{b['T_lo']:.0f}–{b['T_hi']:.0f}°C  "
                      f"实验/CFD ×{b['gamma']:.2f}")
            # 公式标注统一盒式（黑字, 系列身份由点/线色承担）
            ax.text(0.05, 0.94,
                    f"Nu={b['c']:.3f}·Re$^{{{b['a']:.3f}}}$",
                    transform=ax.transAxes, fontsize=CHART_ANNO_FS,
                    va="top", color=SLATE, bbox=ANNO_BOX)
            if ri == 0 and ci == N_BINS - 1:
                ax.legend(fontsize=CHART_LEGEND_FS, labelcolor=G700,
                          loc="lower right")
    fig.tight_layout()
    # 白底 PNG 资产（Word 导出用）+ 内联 SVG
    png_dir = REPORT.parent / "_docx_assets"
    png_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_dir / "bytemp.png", dpi=160, bbox_inches="tight",
                transparent=False, facecolor="#FFFFFF")
    plt.rcParams["svg.hashsalt"] = "bytemp"    # 模板硬性规则 10
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)
    svg = buf.getvalue()
    return svg[svg.index("<svg"):]


# ── HTML ──────────────────────────────────────────────────────────────

def build_html(res: list[dict], chart: str, fcharts: dict,
               res_full: list[dict]) -> str:
    stamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")

    # 代入几何后的 CFD 关联式表（只留代入后的形式）
    cmp_rows = ""
    for r in res:
        co = r["co"]
        subst = _nu_ca_math(r["c_eff"], co["a"])
        cmp_rows += (f'<tr><td class="topo">{r["topo"]} 7/0.6<br>'
                     f'<span style="font-family:var(--mono);font-size:10.5px;'
                     f'font-weight:400;color:var(--g500)">'
                     f'D_h={r["Dh_m"] * 1e3:.3f}mm · L=7mm · '
                     f'(D_h/L)^d={r["geom_factor"]:.4f}</span></td>'
                     f'<td>{subst}</td></tr>')
    cmp_table = (f'<div class="cmp-wrap"><table class="cmp">'
                 f'<tr><th>几何</th><th>Nu 关联式（代入 7/0.6 几何）</th></tr>'
                 f'{cmp_rows}</table></div>')

    # 逐温度箱系数表（结论列 = 实验/CFD 倍数: td.key 红重 + 迷你条,
    # 条宽 ∝ (γ−1) 即"超出 CFD 的增强量"）
    bin_rows = ""
    for r in res:
        for b in r["bins"]:
            fit_math = math_inline(mi("Nu"), mo("="), mn(f"{b['c']:.3f}"),
                                   mo("·"), msup(mi("Re"), mn(f"{b['a']:.3f}")))
            bw = max(2, round((b["gamma"] - 1.0) * 70))
            bin_rows += (
                f'<tr><td class="topo">{r["topo"]}</td>'
                f'<td>{BIN_NAMES[b["bi"]]} {b["T_lo"]:.0f}–{b["T_hi"]:.0f}°C'
                f'</td><td class="n">{b["Pr_med"]:.3f}</td>'
                f'<td class="n">{b["n"]}</td>'
                f'<td>{fit_math}</td><td class="n">{b["medape"]:.1%}</td>'
                f'<td class="key">×{b["gamma"]:.2f}'
                f'<span class="kbar" style="width:{bw}px"></span></td></tr>')
    bin_table = (f'<div class="cmp-wrap"><table class="cmp">'
                 f'<tr><th>几何</th><th>温度箱</th><th class="n">中位 Pr</th>'
                 f'<th class="n">n</th>'
                 f'<th>实验拟合</th><th class="n">medAPE</th>'
                 f'<th>实验/CFD</th></tr>'
                 f'{bin_rows}</table></div>')

    # 逐温度图的数据表（优化 D: dataviz table view, 折叠）
    pt_rows = ""
    for r in res:
        for _, p in r["ok"].sort_values(["bin", "Re"]).iterrows():
            pt_rows += (f'<tr><td>{r["topo"]}</td>'
                        f'<td>{BIN_NAMES[int(p["bin"])]}</td>'
                        f'<td>{p["side"]}</td>'
                        f'<td>{p["Tc"]:.0f}</td><td>{p["Re"]:,.0f}</td>'
                        f'<td>{p["Pr"]:.3f}</td><td>{p["Nu"]:.1f}</td></tr>')
    n_pt = sum(len(r["ok"]) for r in res)
    pt_dt = (f'<details class="dtable"><summary>数据表 · {n_pt} 点'
             f'（点击展开）</summary><div class="dwrap"><table><thead>'
             f'<tr><th>几何</th><th>温度箱</th><th>side</th><th>T̄ °C</th>'
             f'<th>Re</th><th>Pr</th><th>Nu</th></tr></thead>'
             f'<tbody>{pt_rows}</tbody></table></div></details>')

    # hero 大数字带（优化 B: 与主报告同构 —— γ_Nu 跨箱范围 + γ_f 分侧）
    heroes = ""
    for r in res:
        gs = [b["gamma"] for b in r["bins"]]
        subs = " / ".join(f"×{g:.2f}" for g in gs)
        heroes += (
            f'<div class="hero"><div class="lbl">{M_G_NU} · {r["topo"]} '
            f'7/0.6</div><div class="big">×{min(gs):.2f}'
            f'<span class="u">–</span>{max(gs):.2f}</div>'
            f'<div class="sub">低/中/高温 {subs}</div></div>')
    for rf in res_full:
        gh, gc = rf["gamma_f_pt"]["hot"], rf["gamma_f_pt"]["cold"]
        heroes += (
            f'<div class="hero"><div class="lbl">{M_G_F} · {rf["topo"]} '
            f'7/0.6</div><div class="big">{gh[0]:.1f}'
            f'<span class="u"> / </span>{gc[0]:.1f}</div>'
            f'<div class="sub">hot / cold 均值 · 中位 '
            f'{gh[1]:.1f} / {gc[1]:.1f}</div></div>')
    hero_band = f'<div class="heroes">{heroes}</div>'

    body = (
        section("01", "CFD 预测关联式（7/0.6）",
                f"把 7/0.6 的实际 {M_DH}、L 代入 {M_DHL}，"
                "CFD 关联式收成本几何专用预测式，可直接与实验拟合对比。",
                f"""
    <div class="speclist">
      <div class="srow"><div class="sk">几何代入</div>
        <div class="sv">几何项收成常数 {M_CEFF}，关联式化为
        {M_NUFORM} —— 即本几何下 CFD 的 Nu 预测式。</div></div>
      <div class="srow"><div class="sk">分箱口径</div>
        <div class="sv">实验按均温分 3 箱（等频三分位），每箱独立拟合
        {M_NUBIN}；远临界 {M_PR} 窄，温度主要经 {M_PR13} 进入 Nu。</div></div>
      <div class="srow"><div class="sk">CFD 求值</div>
        <div class="sv">CFD 曲线在各箱<b>中位 {M_PR}</b> 处求值，
        与该箱实验拟合同图对比，曲线间距即倍数。</div></div>
    </div>""" + cmp_table)
        + section("02", "逐温度 Nu 曲线",
                  "每个温度箱一条实验拟合（实线，按温度着色）与一条 CFD "
                  "关联式（浅紫虚线）；散点为该箱实测。",
                  f"<figure><div class='figwrap' role='img' "
                  f"aria-label='逐温度 Nu 曲线：实验分箱拟合 vs CFD 关联式'>"
                  f"{chart}</div>"
                  f"<figcaption>逐温度 Nu(Re)：实线 = 实验分箱拟合（按温度"
                  f"着色，冷→暖 = 低→高温）、浅紫虚线 = CFD 关联式（代入 "
                  f"7/0.6 几何、各箱中位 Pr）。曲线间距即 exp/CFD 倍数。"
                  f"</figcaption>"
                  f"{pt_dt}</figure>")
        + section("03", "逐温度箱系数与倍数",
                  "先读大数字带（跨箱倍数范围——γ 随温度稳定即 Pr 依赖弱的"
                  "直接证据），逐箱系数与精度见下表。",
                  hero_band + bin_table)
        + section("04", "Darcy f：实验 vs CFD",
                  "换热之外，压降侧的对比：主图藏青线 = hot 侧拟合、亮青线 = "
                  "cold 侧拟合、浅紫虚线 = CFD D-F。hot 侧实验 f 近乎不随 Re "
                  "变化、两侧互差一倍——压差测量含非摩擦成分（与主报告一致，"
                  "此处并列）。",
                  f"<figure><div class='figwrap' role='img' "
                  f"aria-label='f–Re：实验点与拟合曲线 vs CFD D-F 曲线'>"
                  f"{fcharts['f']}</div>"
                  f"<figcaption>Darcy f–Re：藏青方框/藏青线 = hot 侧、"
                  f"亮青实心圆/亮青线 = cold 侧、浅紫三角 + 浅紫虚线 = "
                  f"CFD D-F；顶部标注分侧中位倍数。</figcaption></figure>")
        + section("05", "倍数 γ 随 Re 的函数",
                  f"{M_G_NU}(Re, Pr) 与 {M_G_F}(Re) 的幂律拟合（{M_G_F} 无 Pr——"
                  "摩擦与 Prandtl 数无关）。γ_Nu 点按 Pr 着色。",
                  f"<figure><div class='figwrap' role='img' "
                  f"aria-label='γ_Nu 随 Re：散点与幂律拟合'>"
                  f"{fcharts['gamma_nu']}</div>"
                  f"<figcaption>{M_G_NU}(Re, Pr)：两侧合并；拟合线近水平"
                  f"（Re 指数 ±0.02），均值即可代表。</figcaption></figure>"
                  f"<figure><div class='figwrap' role='img' "
                  f"aria-label='γ_f 随 Re（分侧）：散点与幂律拟合'>"
                  f"{fcharts['gamma_f']}</div>"
                  f"<figcaption>{M_G_F}(Re) 分侧幂律（无 Pr）：取用时代入函数；"
                  f"cold 侧指数物理不合理，仅限窗内插值。</figcaption></figure>"))

    # masthead 速览（优化 B: 与主报告同构的 at-a-glance aside）
    grange = {r["topo"]: (min(b["gamma"] for b in r["bins"]),
                          max(b["gamma"] for b in r["bins"])) for r in res}
    tlo = min(b["T_lo"] for r in res for b in r["bins"])
    thi = max(b["T_hi"] for r in res for b in r["bins"])
    n_by = {r["topo"]: sum(b["n"] for b in r["bins"]) for r in res}
    re_lo = min(float(r["ok"]["Re"].min()) for r in res)
    re_hi = max(float(r["ok"]["Re"].max()) for r in res)
    pr_lo = min(float(r["ok"]["Pr"].min()) for r in res)
    pr_hi = max(float(r["ok"]["Pr"].max()) for r in res)
    aside = f"""
      <div class="at">速览 · AT A GLANCE</div>
      <div class="row"><span class="k">换热增强 {M_G_NU}</span>
        <span class="v"><b>×{grange['Diamond'][0]:.2f}–{grange['Diamond'][1]:.2f}</b> D · <b>×{grange['Gyroid'][0]:.2f}–{grange['Gyroid'][1]:.2f}</b> G</span></div>
      <div class="row"><span class="k">温度跨度</span>
        <span class="v">{tlo:.0f} – {thi:.0f}°C · 每拓扑 3 箱</span></div>
      <div class="row"><span class="k">工况数（Nu 集）</span>
        <span class="v">Diamond {n_by['Diamond']} · Gyroid {n_by['Gyroid']}</span></div>
      <div class="row"><span class="k">Re 范围</span>
        <span class="v">{re_lo:,.0f} – {re_hi:,.0f}</span></div>
      <div class="row"><span class="k">Pr 范围</span>
        <span class="v">{pr_lo:.2f} – {pr_hi:.2f}（远临界）</span></div>
      <div class="row"><span class="k">数据源</span>
        <span class="v"><code>sco2_DG7-t0p6_hx_experiment_summary.xlsx</code></span></div>"""
    return page(
        title="sCO2 实验 Nu（逐温度）vs CFD 关联式",
        eyebrow=f"SJTU-TPMSHX · D-7-6 / G-7-6 逐温度 Nu 对标 · {stamp}",
        h1="sCO2 实验 <em>Nu</em>（逐温度）vs CFD 关联式",
        intro="把实验 Nu 按均温分 3 箱，每温度一条 Nu(Re) 曲线，"
              "与 CFD 关联式（代入 7/0.6 实际 " + M_DH + "、L）逐温度对比。",
        toc=[("01", "CFD 预测式", "s1"), ("02", "逐温度曲线", "s2"),
             ("03", "系数与倍数", "s3"), ("04", "Darcy f", "s4"),
             ("05", "γ 函数", "s5")],
        body=body, aside=aside,
        footer_left="SJTU-TPMSHX — sCO2 experiment Nu by temperature",
        footer_right=f"台账 SCO2-CFD · {stamp}")


def main() -> None:
    res = [analyse(t) for t in TOPOS]
    chart = make_chart(res)
    # 复用主报告的 f / γ 图（同一 analyse+make_charts 管线）
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res_full = [analyse_full(t) for t in TOPOS]
        fcharts = make_charts_full(res_full)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_html(res, chart, fcharts, res_full),
                      encoding="utf-8")
    for r in res:
        print(f"\n=== {r['topo']} 7/0.6 (D_h={r['Dh_m']*1e3:.3f}mm) ===")
        print(f"  CFD 代入几何: Nu = {r['c_eff']:.4f}·Re^{r['co']['a']:.4f}"
              f"·Pr^(1/3)")
        for b in r["bins"]:
            print(f"  {BIN_NAMES[b['bi']]} {b['T_lo']:.0f}–{b['T_hi']:.0f}°C "
                  f"(Pr {b['Pr_med']:.3f}, n={b['n']}): "
                  f"Nu={b['c']:.3f}·Re^{b['a']:.3f}  实验/CFD ×{b['gamma']:.2f}")
    print(f"\n已写出 {REPORT}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    main()
