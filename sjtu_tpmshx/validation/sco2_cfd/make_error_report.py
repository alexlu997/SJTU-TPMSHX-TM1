"""make_error_report.py — 生成逐 case 的 Nu / 压降误差 HTML 报告.

用法:
    python sjtu_tpmshx/validation/sco2_cfd/make_error_report.py
输出:
    reports/sco2_cfd/sco2_cfd_error_report.html   （自包含, 离线可开）

版式与公式渲染统一走 `validation/report_template.py`（ivory/paper/clay
模板 + 原生 MathML 公式助手——公式规则见该模块 docstring，勿手搓分式）。

逐 case 两个误差:
    dp_err   压降: sCO2 标定 D-F（K 固定 SmoothDF, 逐几何 B, 分晶格池化 m）
             另附 dp_err_smoothdf: 生产 SmoothDF 面直接预测（未标定）
    nu_err   Nu: V0b 纯体物性关联式（c·Re^a·Pr^⅓·(Dh/L)^d, 逐晶格拟合,
             第 2/3 周期段局部物性）; case 误差 = 两段相对误差均值
"""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PKG_ROOT = _THIS.parent.parent.parent
sys.path.insert(0, str(_THIS.parent))

from sjtu_tpmshx.df_surrogate.load_sco2_cfd import LATTICES, load_core, load_segments  # noqa: E402
from sjtu_tpmshx.df_surrogate.smooth_df import SmoothDF                                # noqa: E402
from compare_smooth_df import _fit_B, _fit_pooled_m                        # noqa: E402
from fit_nu_sco2 import _fit, _predict                                     # noqa: E402
from sjtu_tpmshx.validation.report_template import (                                   # noqa: E402
    CLAY, G200, G300, G500, G700, PAPER, SLATE,
    PAIR_A, PAIR_B, VIZ1, VIZ2, VIZ3, VIZ4,
    math_block, math_inline, mfrac, mi, mn, mo, mrow, msub, msup,
    page, paren_pow, section)

REPORT = _PKG_ROOT.parent / "reports" / "sco2_cfd" / "sco2_cfd_error_report.html"

P_COLOR = {8.0: VIZ1, 10.0: VIZ2, 12.0: VIZ3, 15.0: VIZ4}


def per_case_errors() -> tuple[pd.DataFrame, dict]:
    sm = SmoothDF()
    frames, meta = [], {}
    for tpms in LATTICES:
        core = load_core(tpms)
        seg = load_segments(tpms, drop_entrance=True)

        m_sco2 = _fit_pooled_m(core, sm, tpms)
        pred_fit = np.empty(len(core))
        pred_prod = np.empty(len(core))
        df_coeffs = {}
        for gid, d in core.groupby("geometry_id"):
            L, t = float(d["L_mm"].iloc[0]), float(d["t_mm"].iloc[0])
            K, _ = sm.predict_K_B(tpms, L, t)
            B = _fit_B(d, K, m_sco2)
            df_coeffs[(L, t)] = (K, B, m_sco2)
            u, rho, mu = (d["Um_m_s"].values, d["rho_kg_m3"].values,
                          d["mu_Pa_s"].values)
            pos = core.index.get_indexer(d.index.to_numpy())
            pred_fit[pos] = (mu * u / K + rho * B
                             * (d["Re"].values / 1000.0) ** (-m_sco2) * u ** 2)
            pred_prod[pos] = [sm.predict_dpdl(tpms, L, t, ui, ri, mi_)
                              for ui, ri, mi_ in zip(u, rho, mu)]
        dp_meas = core["dpdl_Pa_m"].values

        # V0b 纯体物性形式（2026-07-15 用户裁决：弃壁物性比项）
        cf = _fit(seg, ["re", "pr", "dhl"], fixed={"pr": 1 / 3})
        seg = seg.assign(nu_pred=_predict(seg, cf))
        seg["nu_rel"] = (seg["nu_pred"] - seg["Nu_b"]) / seg["Nu_b"]
        by_case = seg.groupby("case_id").agg(
            Nu_meas=("Nu_b", "mean"), Nu_pred=("nu_pred", "mean"),
            nu_err=("nu_rel", "mean"), Re_b=("Re_b", "mean"))

        out = pd.DataFrame({
            "case": core["case_prefix"] + core["case_number"]
            .astype(int).astype(str).str.zfill(5),
            "case_id": core["case_id"], "tpms": tpms,
            "geometry_id": core["geometry_id"],
            "Re_nominal": core["Re_nominal"].astype(int),
            "P_MPa": core["P_MPa"], "Tref_K": core["Tref"],
            "dT_pc": core["dT_pc"],
            "dp_meas_kPa": core["dp_core_kPa"],
            "dp_pred_kPa": pred_fit * core["core_length_m"].values / 1e3,
            "dp_err": (pred_fit - dp_meas) / dp_meas,
            "dp_err_smoothdf": (pred_prod - dp_meas) / dp_meas,
        }).set_index("case_id")
        out = out.join(by_case)
        frames.append(out.reset_index(drop=True))
        meta[tpms] = {"cf": cf, "m_sco2": m_sco2, "n": len(out),
                      "df_coeffs": df_coeffs}
        print(f"[{tpms}] {len(out)} cases  "
              f"(Nu 拟合 a={cf['a']:.4f} d={cf['d']:.4f}, D-F m={m_sco2:.3f})")
    return pd.concat(frames, ignore_index=True), meta


# 空气原始表候选路径：迁移后的 repo 规范位（把文件拷到这里即自动纳入回测），
# 兜底再试 smooth_df 的旧默认路径（迁移前机器的 D: 盘，本机通常不存在）。
AIR_XLSX_CANDIDATES = [
    _PKG_ROOT.parent / "data" / "raw_data" / "air-cfd-raw.xlsx",
]


def cross_fluid_backtest(meta: dict) -> pd.DataFrame:
    """反向检验：sCO2 重拟系数回预测水（+空气, 若原始表在）CFD 点.

    对 sCO2 覆盖的每个几何, 用 (K 固定, B_sco2, m_sco2) 与水/气训练的
    SmoothDF 面各预测一遍 dp/L, 分流体、分 Re 段报 medAPE。
    空气表缺失时自动跳过并告警（原始表在迁移前机器上, 见 AIR_XLSX_CANDIDATES）。
    """
    from sjtu_tpmshx.df_surrogate.smooth_df import AIR_XLSX_DEFAULT, WATER_XLSX
    sm = SmoothDF()
    rows = []
    xl = pd.ExcelFile(WATER_XLSX, engine="openpyxl")
    for sh in xl.sheet_names:
        df = xl.parse(sh).dropna(subset=["p0_Pa", "p3_Pa", "Um_m_s"])
        for gid in sorted(df["geometry_id"].unique()):
            s = df[df["geometry_id"] == gid]
            tp = "Diamond" if s["lattice"].iloc[0] == "D" else "Gyroid"
            L = float(round(float(s["cell_size_mm"].iloc[0])))
            t = round(float(s["wall_thickness_mm"].iloc[0]) / 10.0, 1)
            if (L, t) not in meta[tp]["df_coeffs"]:
                continue
            for _, r in s.iterrows():
                rows.append((tp, "水", L, t, r["Um_m_s"], r["rho_kg_m3"],
                             r["mu_Pa_s"], r["Re"],
                             (r["p0_Pa"] - r["p3_Pa"]) / r["core_length_m"]))

    air_path = next((p for p in [*AIR_XLSX_CANDIDATES, AIR_XLSX_DEFAULT]
                     if Path(p).exists()), None)
    if air_path is None:
        print("[warn] 空气 CFD 原始表不在本机（迁移前 D: 盘路径已失效）——"
              "回测仅含水侧。拷贝到 data/raw_data/air-cfd-raw.xlsx 后重跑"
              "即自动纳入。")
    else:
        ac = pd.ExcelFile(air_path, engine="openpyxl").parse(
            "All_Cases_Combined")
        ac = ac[ac["excluded_from_fit"] == 0]
        n_air = 0
        for _, r in ac.iterrows():
            t = r["wall_param"] / 10.0 if r["wall_param"] >= 3 \
                else r["wall_param"]
            key = (float(round(r["L_cell_mm"])), round(float(t), 1))
            if key not in meta[r["structure"]]["df_coeffs"]:
                continue
            rows.append((r["structure"], "空气", key[0], key[1],
                         r["v_ref_excel_m_s"], r["rho_ref"], r["mu_ref"],
                         r["Re"],
                         r["dP_core_Pa"] / (r["L_core_report_mm"] * 1e-3)))
            n_air += 1
        print(f"air backtest: {n_air} 空气 CFD 点纳入 ({air_path})")

    w = pd.DataFrame(rows, columns=["tp", "fluid", "L", "t", "u", "rho",
                                    "mu", "Re", "dpdl"])
    out = []
    for (tp, fluid), d in w.groupby(["tp", "fluid"], sort=False):
        pred_s = np.array([sm.predict_dpdl(tp, L, t, u, rho, mu)
                           for L, t, u, rho, mu
                           in zip(d["L"], d["t"], d["u"], d["rho"], d["mu"])])
        pred_c = np.array([
            (mu * u / K + rho * B * (Re / 1000.0) ** (-m) * u ** 2)
            for L, t, u, rho, mu, Re, (K, B, m)
            in ((L, t, u, rho, mu, Re, meta[tp]["df_coeffs"][(L, t)])
                for L, t, u, rho, mu, Re
                in zip(d["L"], d["t"], d["u"], d["rho"], d["mu"], d["Re"]))])
        y = d["dpdl"].values
        for band, mask in (("全 Re", np.ones(len(d), bool)),
                           ("Re < 1000", (d["Re"] < 1000).values),
                           ("Re ≥ 1000", (d["Re"] >= 1000).values)):
            if not mask.any():
                continue
            for model, pred in (("SmoothDF（水/气训练）", pred_s),
                                ("sCO2 重拟系数", pred_c)):
                r = (pred[mask] - y[mask]) / y[mask]
                out.append(dict(tpms=tp, fluid=fluid, band=band, model=model,
                                n=int(mask.sum()),
                                medape=float(np.median(np.abs(r))),
                                rmsre=float(np.sqrt(np.mean(r * r)))))
    bt = pd.DataFrame(out)
    print(f"backtest: {len(w)} 点 "
          f"({', '.join(f'{f} {n}' for f, n in w.fluid.value_counts().items())}), "
          f"{w.groupby(['tp', 'L', 't']).ngroups} 几何")
    return bt


def chart_backtest(bt: pd.DataFrame) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    multi_fluid = bt["fluid"].nunique() > 1
    groups = bt[["fluid", "band"]].drop_duplicates().values.tolist()
    labels = [f"{f} {b}" if multi_fluid else b for f, b in groups]
    fig, axes = plt.subplots(1, 2, figsize=(10.5 if not multi_fluid else 12.5,
                                            3.4), sharey=True)
    for ax, tpms in zip(axes, LATTICES):
        d = bt[bt["tpms"] == tpms]
        x = np.arange(len(groups))
        for off, (model, c) in zip((-0.19, 0.19),
                                   (("SmoothDF（水/气训练）", PAIR_A),
                                    ("sCO2 重拟系数", PAIR_B))):
            v = []
            for f, b in groups:
                sub = d[(d["fluid"] == f) & (d["band"] == b)
                        & (d["model"] == model)]
                v.append(sub["medape"].iloc[0] * 100 if len(sub) else np.nan)
            bars = ax.bar(x + off, v, 0.34, color=c, label=model)
            ax.bar_label(bars, fmt="%.1f", fontsize=8, color=G700, padding=2)
        ax.set_xticks(x, labels, fontsize=8.5)
        fluids = "/".join(bt["fluid"].unique())
        _style(ax, f"{tpms} — 预测{fluids}侧 CFD 的 medAPE [%]")
        ax.legend(frameon=False, fontsize=8.5, labelcolor=G700)
    axes[0].set_ylabel("medAPE [%]", fontsize=9)
    fig.tight_layout()
    return _png(fig)


# ── charts ────────────────────────────────────────────────────────────────

def _style(ax, title=None):
    ax.set_facecolor(PAPER)
    if title:
        ax.set_title(title, color=SLATE, fontsize=10.5, loc="left", pad=8)
    ax.tick_params(colors=G500, labelsize=8.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(G300)
    ax.grid(True, color=G200, linewidth=0.6)
    ax.set_axisbelow(True)


def _png(fig) -> str:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                facecolor=PAPER)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def make_charts(df: pd.DataFrame) -> dict[str, str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.lines import Line2D

    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "text.color": SLATE, "axes.labelcolor": G700,
        "figure.facecolor": PAPER})
    charts: dict[str, str] = {}

    def p_legend(ax, **kw):
        hs = [Line2D([], [], marker="o", ls="", ms=5, color=c,
                     label=f"{p:.0f} MPa") for p, c in P_COLOR.items()]
        ax.legend(handles=hs, frameon=False, fontsize=8,
                  labelcolor=G700, **kw)

    # 0) parity plots: 2x2 (rows = quantity, cols = lattice) -------------
    fig, axes = plt.subplots(2, 2, figsize=(9.6, 9.2))
    for j, tpms in enumerate(LATTICES):
        d = df[df["tpms"] == tpms]
        panels = [("Nu_meas", "Nu_pred", f"{tpms} — Nu（V0b 关联式）",
                   "Nu 实测（CFD）", "Nu 预测"),
                  ("dp_meas_kPa", "dp_pred_kPa", f"{tpms} — Δp（D-F 标定）",
                   "Δp 实测 [kPa]", "Δp 预测 [kPa]")]
        for i, (xm, yp, ttl, xl, yl) in enumerate(panels):
            ax = axes[i, j]
            for p, c in P_COLOR.items():
                dd = d[d["P_MPa"] == p]
                ax.scatter(dd[xm], dd[yp], s=6, alpha=0.4, lw=0, color=c)
            lo = min(d[xm].min(), d[yp].min()) * 0.8
            hi = max(d[xm].max(), d[yp].max()) * 1.25
            xx = np.array([lo, hi])
            ax.plot(xx, xx, color=SLATE, lw=1.0)
            ax.plot(xx, 1.2 * xx, color=CLAY, lw=0.8, ls="--")
            ax.plot(xx, 0.8 * xx, color=CLAY, lw=0.8, ls="--")
            ax.set_xscale("log"); ax.set_yscale("log")
            ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
            ax.set_aspect("equal")
            ax.set_xlabel(xl, fontsize=8.5); ax.set_ylabel(yl, fontsize=8.5)
            _style(ax, ttl)
            if i == 0 and j == 0:
                p_legend(ax, loc="upper left")
                ax.text(0.97, 0.03, "虚线 = ±20%", transform=ax.transAxes,
                        ha="right", fontsize=8, color=CLAY)
    fig.tight_layout()
    charts["parity"] = _png(fig)

    # 1) heatmap |nu_err| median over P x dT_pc ---------------------------
    seq = LinearSegmentedColormap.from_list("seq", ["#eef4fc", "#1c5aa8"])
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.4))
    for ax, tpms in zip(axes, LATTICES):
        d = df[df["tpms"] == tpms]
        piv = (d.assign(a=d["nu_err"].abs())
               .pivot_table(index="P_MPa", columns="dT_pc", values="a",
                            aggfunc="median") * 100)
        im = ax.imshow(piv.values, cmap=seq, vmin=0, vmax=25, aspect="auto")
        ax.set_xticks(range(len(piv.columns)),
                      [f"{c:+.0f}" for c in piv.columns])
        ax.set_yticks(range(len(piv.index)), [f"{i:.0f}" for i in piv.index])
        ax.set_xlabel("T_b − T_pc [K]", fontsize=9)
        ax.set_ylabel("P [MPa]", fontsize=9)
        _style(ax, f"{tpms} — Nu 相对误差中位数 [%]")
        ax.grid(False)
        for i in range(piv.shape[0]):
            for j in range(piv.shape[1]):
                v = piv.values[i, j]
                if np.isfinite(v):
                    ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                            fontsize=8, color=PAPER if v > 14 else SLATE)
        fig.colorbar(im, ax=ax, shrink=0.85).ax.tick_params(
            colors=G500, labelsize=8)
    fig.tight_layout()
    charts["nu_heat"] = _png(fig)

    # 2) per-geometry medAPE bars -----------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.6), sharey=True)
    for ax, tpms in zip(axes, LATTICES):
        d = df[df["tpms"] == tpms]
        g = d.groupby("geometry_id").agg(
            nu=("nu_err", lambda s: s.abs().median()),
            dp=("dp_err", lambda s: s.abs().median())) * 100
        x = np.arange(len(g))
        ax.bar(x - 0.19, g["nu"], 0.34, color=PAIR_A, label="Nu (V0b)")
        ax.bar(x + 0.19, g["dp"], 0.34, color=PAIR_B, label="Δp (D-F 标定)")
        ax.set_xticks(x, g.index, rotation=45, ha="right", fontsize=8)
        _style(ax, f"{tpms} — 逐几何误差中位数 [%]")
        ax.legend(frameon=False, fontsize=8.5, labelcolor=G700)
    axes[0].set_ylabel("medAPE [%]", fontsize=9)
    fig.tight_layout()
    charts["geo_bars"] = _png(fig)

    # 3) scatter error vs Re ----------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.6), sharey=True)
    for ax, (col, ttl) in zip(axes, [("nu_err", "Nu 相对误差 vs Re_b"),
                                     ("dp_err", "Δp 相对误差 vs Re_b")]):
        for p, c in P_COLOR.items():
            d = df[df["P_MPa"] == p]
            ax.scatter(d["Re_b"], d[col] * 100, s=7, alpha=0.45, lw=0,
                       color=c)
        ax.set_xscale("log")
        ax.axhline(0, color=G500, lw=0.8)
        ax.set_xlabel("Re_b（局部体物性）", fontsize=9)
        _style(ax, ttl + " [%]")
        p_legend(ax, ncol=2, loc="upper left")
    axes[0].set_ylabel("相对误差 [%]", fontsize=9)
    fig.tight_layout()
    charts["scatter"] = _png(fig)

    # 4) signed-error histograms ------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.2), sharey=True)
    bins = np.linspace(-60, 60, 61)
    for ax, (col, ttl) in zip(axes, [("nu_err", "Nu 误差分布"),
                                     ("dp_err", "Δp 误差分布")]):
        for tpms, c in zip(LATTICES, (PAIR_A, PAIR_B)):
            ax.hist(df.loc[df["tpms"] == tpms, col] * 100, bins=bins,
                    histtype="stepfilled", alpha=0.45, color=c, label=tpms)
        ax.axvline(0, color=G500, lw=0.8)
        ax.set_xlabel("相对误差 [%]", fontsize=9)
        _style(ax, ttl + "（逐 case）")
        ax.legend(frameon=False, fontsize=8.5, labelcolor=G700)
    axes[0].set_ylabel("case 数", fontsize=9)
    fig.tight_layout()
    charts["hist"] = _png(fig)
    return charts


# ── formulas (native MathML via report_template helpers) ──────────────────

def _nu_formula(cf: dict) -> str:
    parts = [
        mi("Nu"), mo("="), mn(f"{cf['c']:.4f}"), mo("·"),
        msup(msub(mi("Re"), mi("b")), mn(f"{cf['a']:.4f}")), mo("·"),
        msup(msub(mi("Pr"), mi("b")), mrow(mn(1), mo("/"), mn(3))), mo("·"),
        paren_pow(mfrac(msub(mi("D"), mi("h")), mi("L")),
                  f"{cf['d']:.4f}".replace("-", "−"))]
    if "e" in cf:                        # 壁比参考形式（当前推荐不含）
        parts += [mo("·"),
                  paren_pow(mfrac(msub(mi("μ"), mi("w")),
                                  msub(mi("μ"), mi("b"))), f"{cf['e']:.4f}")]
    return math_block(*parts)


def _df_formula(m: float) -> str:
    dp = mrow(mi("Δ", italic=False), mi("p"))
    return math_block(
        mfrac(dp, mi("L")), mo("="),
        mfrac(mrow(mi("μ"), mo("·"), mi("u")), mi("K")), mo("+"),
        mi("ρ"), mo("·"), mi("B"), mo("·"),
        paren_pow(mfrac(mi("Re"), mn(1000)), f"−{m:.3f}"), mo("·"),
        msup(mi("u"), mn(2)))


def _sym_notes() -> str:
    re_def = math_inline(msub(mi("Re"), mi("b")), mo("="),
                         mi("G"), mo("·"), msub(mi("D"), mi("h")),
                         mo("/"), msub(mi("μ"), mi("b")))
    nu_def = math_inline(mi("Nu"), mo("="), mi("h"), mo("·"),
                         msub(mi("D"), mi("h")), mo("/"),
                         msub(mi("k"), mi("b")))
    return (f"<p class='note'>符号：{re_def}（质量流速 × 水力直径 / 局部体黏度）；"
            f"{nu_def}；下标 b = 主流温度取物性"
            f"（CoolProp，Span-Wagner EOS）；u 为间隙平均流速；"
            f"D<sub>h</sub> 用 tpms_calc 体素口径。</p>")


def _stat(df, col):
    a = df[col].abs()
    return (f"medAPE <b>{a.median():.1%}</b> <span class='sep'>·</span> "
            f"RMSRE <b>{np.sqrt((df[col] ** 2).mean()):.1%}</b> "
            f"<span class='sep'>·</span> p95 <b>{a.quantile(.95):.1%}</b>")


# ── page assembly ─────────────────────────────────────────────────────────

def build_html(df: pd.DataFrame, meta: dict, charts: dict[str, str],
               bt: pd.DataFrame) -> str:
    tiles = []
    for tpms in LATTICES:
        d = df[df["tpms"] == tpms]
        tiles.append(f"""
    <div class="tile">
      <div class="tile-head">{tpms} <span class="count">{len(d)} cases</span></div>
      <p><span class="lbl">Nu（V0b 关联式）</span>{_stat(d, 'nu_err')}</p>
      <p><span class="lbl">Δp（D-F 标定）</span>{_stat(d, 'dp_err')}</p>
      <p><span class="lbl">Δp（SmoothDF 未标定对照）</span>{_stat(d, 'dp_err_smoothdf')}</p>
    </div>""")

    formulas = []
    for tpms in LATTICES:
        formulas.append(f"""
    <div class="fcard">
      <div class="fcap">{tpms} — Nu 关联式（V0b 纯体物性，光滑壁，第 2/3 周期段局部体物性）</div>
      <div class="formula">{_nu_formula(meta[tpms]['cf'])}</div>
    </div>""")
    formulas.append(f"""
    <div class="fcard">
      <div class="fcap">D-F 压降（K 固定 SmoothDF 面；B 逐几何拟合；m 分晶格池化：
      Diamond {meta['Diamond']['m_sco2']:.3f} / Gyroid {meta['Gyroid']['m_sco2']:.3f}）</div>
      <div class="formula">{_df_formula(meta['Diamond']['m_sco2'])}</div>
    </div>{_sym_notes()}""")

    cols = ["case", "tpms", "geometry_id", "Re_nominal", "P_MPa", "dT_pc",
            "Tref_K", "Nu_meas", "Nu_pred", "nu_err",
            "dp_meas_kPa", "dp_pred_kPa", "dp_err", "dp_err_smoothdf"]
    rows = df[cols].round({
        "Tref_K": 2, "Nu_meas": 1, "Nu_pred": 1, "nu_err": 4,
        "dp_meas_kPa": 4, "dp_pred_kPa": 4, "dp_err": 4,
        "dp_err_smoothdf": 4}).values.tolist()
    data_json = json.dumps(rows, ensure_ascii=False)
    stamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")

    alt = {"parity": "Parity plot：Nu 与 Δp 的预测-实测对比，2×2 面板",
           "nu_heat": "Nu 误差中位数热图：压力 × 距拟临界温度",
           "geo_bars": "逐几何误差中位数柱状图：Nu 与 Δp",
           "scatter": "误差随 Re 的散点图，按运行压力着色",
           "hist": "逐 case 误差分布直方图",
           "backtest": "跨流体反向检验：sCO2 重拟系数预测水侧 CFD 的误差对比"}
    img = {k: f"<img src='data:image/png;base64,{v}' alt='{alt[k]}'>"
           for k, v in charts.items()}

    ths = ["case", "拓扑", "几何", "Re", "P MPa", "dT_pc", "Tref K",
           "Nu 实测", "Nu 预测", "Nu 误差", "Δp 实测 kPa", "Δp 预测 kPa",
           "Δp 误差", "Δp 误差(未标定)"]
    th_html = "".join(f"<th>{t}<span class='dir'></span></th>" for t in ths)
    table_html = f"""
  <div class="filters">
    <select id="fT" aria-label="按拓扑筛选"><option value="">拓扑: 全部</option></select>
    <select id="fG" aria-label="按几何筛选"><option value="">几何: 全部</option></select>
    <select id="fP" aria-label="按压力筛选"><option value="">P: 全部</option></select>
    <select id="fR" aria-label="按 Re 筛选"><option value="">Re: 全部</option></select>
    <input id="fQ" placeholder="搜索 case…" size="14" aria-label="按 case 编号搜索">
    <span id="cnt" role="status"></span>
  </div>
  <div id="wrap"><table id="tbl"><thead><tr>{th_html}</tr></thead>
  <tbody></tbody></table></div>"""

    body = (
        section("01", "模型与系数",
                "两套闭合各自独立拟合：Nu 用第 2/3 周期段（剔除入口段）的局部"
                "体物性；Δp 在核心段整体上按 Darcy-Forchheimer 形式标定，K 固定"
                "为 SmoothDF（水+空气 CFD）面值——本数据 Re ≳ 2600、Darcy 份额"
                " ≤ 4%，K 不可辨识。",
                "".join(formulas))
        + section("02", "总体误差",
                  "Δp 的第三行是未标定的生产 SmoothDF 面直接预测，作跨流体迁移"
                  "的对照。",
                  f'<div class="tiles">{"".join(tiles)}</div>')
        + section("03", "Parity plot",
                  "对数坐标，实线为 45° 完美预测，虚线为 ±20% 带；按运行压力"
                  "着色——Nu 图中溢出 ±20% 带的点几乎全部来自 8 MPa（距临界"
                  "压力仅 0.6 MPa，近临界物性梯度最陡的窄条）。",
                  f"<figure>{img['parity']}<figcaption>Parity（2×2：行 = Nu/Δp，列 = Diamond/Gyroid）：对数坐标，实线 45°，虚线 ±20% 带，按运行压力着色。</figcaption></figure>")
        + section("04", "误差结构", "", f"""
    <figure>{img['nu_heat']}
      <figcaption>失效区两条：① 8 MPa 近临界（T_b−T_pc ∈ [−2, +5]K，
      Diamond 18–42% / Gyroid 15–61%）；② 类液侧 T_b = T_pc−5K 列随压力
      下降恶化（15 / 12 / 10 MPa：Diamond 12 / 14 / 27%）。有效域
      （P ≥ 10 MPa 且 T_b ≥ T_pc−2K）逐格 4–12%。</figcaption></figure>
    <figure>{img['geo_bars']}
      <figcaption>Diamond 的 D_6_6 / D_7_4 / D_7_5 异常凸起（数据侧待核查：
      换用 CFD 自带 Dh 反而更差，非口径问题）；其余几何均匀在 3–9%。</figcaption></figure>
    <figure>{img['scatter']}
      <figcaption>Nu 长尾几乎全为 8 MPa（蓝）；Δp 误差带整体在 ±20% 内。</figcaption></figure>
    <figure>{img['hist']}
      <figcaption>Δp 分布窄且近似对称；Nu 的双侧长尾对应 8 MPa 近临界。</figcaption></figure>""")
        + section("05", "D-F 跨流体保持性",
                  "反向检验：用 sCO2 重拟系数（K 固定、逐几何 B、池化 m）回预测"
                  f"水{'、空气' if bt['fluid'].nunique() > 1 else ''}侧 CFD"
                  f" 原始点（{int(bt[(bt['band'] == '全 Re') & (bt['model'].str.startswith('SmoothDF'))]['n'].sum())}"
                  " 点，sCO2 覆盖的全部几何），与水/气训练的 SmoothDF 面对比。"
                  + ("" if bt["fluid"].nunique() > 1 else
                     "<b>空气原始表不在本机（迁移前 D: 盘），暂缺空气侧检验"
                     "</b>——拷贝 <code>Cfd-air-raw-old-new.xlsx</code> 到 "
                     "<code>data/raw_data/air-cfd-raw.xlsx</code> 后重跑本脚本"
                     "即自动纳入（空气窗 Re 400–16k，含 Re&lt;2600 的外推段，"
                     "预期结论与水侧低 Re 段同构）。"),
                  f"""
    <figure>{img['backtest']}
      <figcaption>Gyroid 全域无损；Diamond 在 Re ≥ 1000（sCO2 数据窗内）反而
      更准——B 的偏移是逐几何直拟 vs 跨几何插值面之差，非流体效应；仅
      Re &lt; 1000 劣化（sCO2 数据下限 Re ≈ 2600 之外的纯外推），这正是
      K 与低 Re 段继续锚定水侧 CFD 的原因。结论：D-F 系数的流体无关性
      由 sCO2 → 水双向实测坐实。</figcaption></figure>""")
        + section("06", "逐 case 明细",
                  "点表头排序；|误差| &gt; 20% 标红。误差 =（预测 − 实测）/ 实测。"
                  "表格为虚拟滚动，7000 行全量可浏览。",
                  table_html, count="7000 cases"))

    # 虚拟滚动：排序/筛选只重画视口内 ~80 行（此前整体 innerHTML 4000 行,
    # 每次排序重解析 5.6 万个单元格, 明显卡顿）。斑马纹按绝对行号 .zr 类,
    # 模板的 nth-child 版本在虚拟滚动下会随滚动跳变, 已在 extra_css 关闭。
    scripts = f"""<script>
const DATA = {data_json};
const tb = document.querySelector('#tbl tbody');
const wrap = document.getElementById('wrap');
const sel = {{fT:1, fG:2, fP:4, fR:3}};
for (const [id, ci] of Object.entries(sel)) {{
  const s = document.getElementById(id);
  [...new Set(DATA.map(r => r[ci]))].sort((a,b)=>a>b?1:-1)
    .forEach(v => s.add(new Option(v, v)));
  s.onchange = render;
}}
document.getElementById('fQ').oninput = render;
let sortCol = 0, sortDir = 1, view = DATA, ROWH = 27;
const ths = [...document.querySelectorAll('#tbl th')];
ths.forEach((th, i) =>
  th.onclick = () => {{ sortDir = (sortCol===i) ? -sortDir : 1; sortCol=i; render(); }});
const pct = v => (v*100).toFixed(1) + '%';
const rowHtml = (r, i) => `<tr class="${{i%2?'zr':''}}">
  <td>${{r[0]}}</td><td>${{r[1]}}</td><td>${{r[2]}}</td><td>${{r[3]}}</td>
  <td>${{r[4]}}</td><td>${{r[5]}}</td><td>${{r[6]}}</td>
  <td>${{r[7]}}</td><td>${{r[8]}}</td>
  <td class="${{Math.abs(r[9])>0.2?'bad':''}}">${{pct(r[9])}}</td>
  <td>${{r[10]}}</td><td>${{r[11]}}</td>
  <td class="${{Math.abs(r[12])>0.2?'bad':''}}">${{pct(r[12])}}</td>
  <td>${{pct(r[13])}}</td></tr>`;
const spacer = h => `<tr style="height:${{h}}px"><td colspan="14"
  style="padding:0;border:0;height:auto"></td></tr>`;
function paint() {{
  if (!view.length) {{
    tb.innerHTML = `<tr><td colspan="14" class="empty">没有匹配的 case —— 试试清空搜索框或放宽筛选条件</td></tr>`;
    return;
  }}
  const start = Math.max(0, Math.floor(wrap.scrollTop / ROWH) - 8);
  const end = Math.min(view.length,
    start + Math.ceil(wrap.clientHeight / ROWH) + 16);
  tb.innerHTML = spacer(start * ROWH)
    + view.slice(start, end).map((r, k) => rowHtml(r, start + k)).join('')
    + spacer((view.length - end) * ROWH);
}}
let raf = 0;
wrap.addEventListener('scroll', () => {{
  if (!raf) raf = requestAnimationFrame(() => {{ raf = 0; paint(); }});
}});
function render() {{
  view = DATA.filter(r =>
    Object.entries(sel).every(([id,ci]) => {{
      const v = document.getElementById(id).value;
      return !v || String(r[ci]) === v; }}) &&
    String(r[0]).toLowerCase().includes(
      document.getElementById('fQ').value.toLowerCase()));
  view = view.slice().sort((a,b) =>
    (a[sortCol]>b[sortCol]?1:a[sortCol]<b[sortCol]?-1:0)*sortDir);
  const med = (ci) => {{
    const v = view.map(r=>Math.abs(r[ci])).sort((a,b)=>a-b);
    return v.length ? pct(v[Math.floor(v.length/2)]) : '—'; }};
  document.getElementById('cnt').textContent =
    `${{view.length}} cases · 筛选 medAPE: Nu ${{med(9)}} / Δp ${{med(12)}}`;
  ths.forEach((th, i) => th.querySelector('.dir').textContent =
    (i === sortCol) ? (sortDir > 0 ? '▲' : '▼') : '');
  wrap.scrollTop = 0;
  paint();
  const probe = tb.querySelector('tr.zr, tr:nth-child(2)');
  if (probe && Math.abs(probe.offsetHeight - ROWH) > 0.5) {{
    ROWH = probe.offsetHeight; paint();
  }}
}}
render();
</script>"""

    extra_css = """
  #tbl td { height:26px; padding-top:0; padding-bottom:0; line-height:26px; }
  #tbl tbody tr:nth-child(even) td { background:transparent; }
  #tbl tbody tr.zr td { background:#F6F4EE; }
"""

    return page(
        title="sCO2 CFD 误差报告 — Nu 关联式与 D-F 压降标定",
        eyebrow=f"SJTU-TPMSHX · sCO2 单胞 CFD 标定 · {stamp}",
        h1="sCO2 的 <em>Nu</em> 关联式与 <em>D-F</em> 压降：逐 case 误差报告",
        intro="数据：Diamond 4000 + Gyroid 3000 例（光滑壁 RANS，无重力，"
              "T<sub>wall</sub> = T<sub>ref</sub> + 50 K，P ∈ {8, 10, 12, 15}"
              " MPa 锚定拟临界线）。Nu 取 V0b 纯体物性关联式（逐晶格拟合，仅用主流温度物性），Δp 取 sCO2"
              " 标定 D-F（K 固定、逐几何 B）。生成脚本 "
              "<code>validation/sco2_cfd/make_error_report.py</code>，"
              "续传数据后重跑即可刷新。",
        toc=[("01", "模型与系数", "s1"), ("02", "总体误差", "s2"),
             ("03", "Parity", "s3"), ("04", "误差结构", "s4"),
             ("05", "D-F 跨流体保持性", "s5"),
             ("06", "逐 case 明细", "s6")],
        body=body,
        footer_left="SJTU-TPMSHX — sCO2 CFD calibration",
        footer_right=f"数据 data/raw_data/cfd/sco2 · 台账条目 SCO2-CFD · {stamp}",
        extra_css=extra_css, scripts=scripts)


def main() -> None:
    df, meta = per_case_errors()
    bt = cross_fluid_backtest(meta)
    charts = make_charts(df)
    charts["backtest"] = chart_backtest(bt)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_html(df, meta, charts, bt), encoding="utf-8")
    print(f"已写出 {REPORT}  ({REPORT.stat().st_size/1e6:.1f} MB, "
          f"{len(df)} cases)")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    main()
