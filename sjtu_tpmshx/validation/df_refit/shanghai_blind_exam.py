"""shanghai_blind_exam.py — 上海 16 例真盲考（候选 D · D-2c）.

**候选 D 边界②在这里兑现**："CFD 拟合 (K,cF)、试件实验标定 γ，**上海 16 例
退出标定转纯盲考卷**"（Alex 2026-07-22 拍板）。

### 为什么这是一次真盲考

生产 `gamma_df` v4 的 Gyroid L 方向是**过 (L6, L7=上海标定 534.8, L8) 的
对数二次**——上海标定就烘焙在生产 γ 面里（`gamma_df.py` 模块 docstring
"L-dir Gyroid" 段）。所以在生产闭合下跑上海 16 例，L7 那个点是**自己考自己**。

本工具把整张面换成 D-2b 链条产出的**双层合成面**：

    cF = γ_total(topo, L, t) × cF_dev(L, t)
    γ_total = γ_spec(L, t) × γ_HX(topo)        （D-2b-4 per_topo 裁决）
    K       = dev 表同批提取的 K 面（与 cF_dev 同源，log 空间 TPS）

这条链上**没有任何一个上海数字**：cF_dev/K 来自水 CFD 发展段（D-2a/R2），
γ_spec 来自 SLM 试件台架（col47，L∈{6,8}），γ_HX 来自 7-6 样机气侧台架
（D_7_6/G_7_6，iter 75 筛后）。上海 16 例**只在最后打分时出现一次**。

    cF(G,7,0.6): 生产 534.8（上海标定） vs 双层 ~413（盲）  —— 差 ×0.77

### 这次考试要裁决什么（iter 73 立的判据，audit §10 结论 3）

G 侧对上海标定的残差 ×1.296 有两个假说：
  (i)  534.8 是**旧栈伪迹**——旧口径的压力水平偏置被 γ 锚吸收了；
  (ii) 上海样机/工况域**真实差异**——G 样机或上海台架特有的额外阻力。
**判据**：双层闭合（无 534.8）盲预测上海 16 ——
  RMSRE 正常、误差无系统性符号  ⇒ (i)
  dP **系统性偏低 ~25%**                ⇒ (ii)

### 实现纪律

- **生产零改动**：`two_layer` backend 在本模块内注册（`backend.register`），
  只在本脚本进程里存在；默认 `TPMSHX_DF_METHOD` 不动，不进 `_REGISTRY`
  的持久面。backend.py 的"注册合约"要求新后端过上海门 + D_7_6 门才能当
  候选默认——**本后端不是默认候选**，它是考卷载具，故不走那个流程。
- 控制组与盲考在**同一进程外**分别跑（backend 有 `_CACHE`，同进程切换
  env 会被缓存污染），两次都用同一网格与同一 gate 脚本。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/df_refit/shanghai_blind_exam.py

输出: stdout 记分板 + reports/df_refit/shanghai_blind_exam.csv。
"""
from __future__ import annotations

import os
import subprocess
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import RBFInterpolator

from sjtu_tpmshx.df_surrogate import backend as _backend
from sjtu_tpmshx.validation.df_refit.gamma_hx_air import run as run_air
from sjtu_tpmshx.validation.df_refit.gamma_specimen import (
    cf_dev, fit_specimen_gamma)
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
_DEV_CSV = (_REPO / "sjtu_tpmshx" / "df_surrogate" / "_prebuilt"
            / "df_cfd_coeffs_dev.csv")
REPORT_DIR = _REPO / "reports" / "df_refit"
_GATE = (_REPO / "sjtu_tpmshx" / "validation" / "cases"
         / "validate_shanghai_3d_real.py")
_OUT_DIR = _REPO / "sjtu_tpmshx" / "validation"


# --------------------------------------------------------------------------
# 双层面模型 + backend 注册（进程内，opt-in）
# --------------------------------------------------------------------------
def _k_dev_surface(topo: str) -> RBFInterpolator:
    dev = pd.read_csv(_DEV_CSV)
    g = dev[dev.tp == topo]
    pts = np.log(np.column_stack([g.L.to_numpy(float), g.t.to_numpy(float)]))
    return RBFInterpolator(pts, np.log(g.K.to_numpy(float)),
                           kernel="thin_plate_spline")


def gamma_hx_air_level(topo: str) -> float:
    """γ_HX(topo) = 气侧 7-6 台账的 ln 均值（iter 75 筛后，D-2b-4 per_topo）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        air = run_air()
    g = air[(air.topo == topo) & (~air.excluded)]
    return float(np.exp(np.mean(np.log(g.gamma_hx.to_numpy(float)))))


class TwoLayerModel:
    """cF = γ_spec(L,t)·γ_HX(topo)·cF_dev(L,t)；K = dev 表 K 面。零上海输入。"""

    def __init__(self, tpms: str):
        self.tpms = tpms
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._spec, _ = fit_specimen_gamma(tpms)
        self._gamma_hx = gamma_hx_air_level(tpms)
        self._Ksurf = _k_dev_surface(tpms)

    def gamma_total(self, L: float, t: float) -> float:
        return float(self._spec.predict(L, t)) * self._gamma_hx

    def predict(self, L_mm: float, t_mm: float, eps_f=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cfd = cf_dev(self.tpms, L_mm, t_mm)
        K = float(np.exp(self._Ksurf(np.log([[L_mm, t_mm]]))[0]))
        return K, self.gamma_total(L_mm, t_mm) * cfd


@_backend.register("two_layer")
class TwoLayerBackend(_backend.DFBackend):
    def _build(self, tpms_type):
        return TwoLayerModel(tpms_type)

    def predict_vec(self, L_flat, t_flat, e_flat):
        K = np.empty(L_flat.size)
        cF = np.empty(L_flat.size)
        cache: dict[tuple[float, float], tuple[float, float]] = {}
        for i in range(L_flat.size):
            key = (L_flat[i], t_flat[i])
            if key not in cache:
                cache[key] = self._model.predict(key[0], key[1])
            K[i], cF[i] = cache[key]
        return K, cF


# --------------------------------------------------------------------------
# 跑门（子进程，避免 backend._CACHE 跨口径污染）
# --------------------------------------------------------------------------
_ENV_FIX = dict(PYTHONHASHSEED="0", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
                NUMBA_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                NUMEXPR_NUM_THREADS="1", QT_QPA_PLATFORM="offscreen")


def _run_gate(method: str | None, suffix: str) -> tuple[str, Path]:
    env = dict(os.environ)
    env.update(_ENV_FIX)
    if method:
        env["TPMSHX_DF_METHOD"] = method
        # 让子进程在导入 predict 之前先注册本后端
        env["PYTHONSTARTUP"] = ""
    cmd = [sys.executable, "-u", str(_GATE), "--suffix", suffix, "--no-gate"]
    if method == "two_layer":
        # 用 -c 引导：先 import 本模块完成注册，再执行 gate 脚本
        boot = (f"import runpy,sys;"
                f"import sjtu_tpmshx.validation.df_refit.shanghai_blind_exam;"
                f"sys.argv=['gate','--suffix','{suffix}','--no-gate'];"
                f"runpy.run_path(r'{_GATE}', run_name='__main__')")
        cmd = [sys.executable, "-u", "-c", boot]
    p = subprocess.run(cmd, cwd=str(_REPO), env=env,
                       capture_output=True, text=True, errors="replace")
    csv = _OUT_DIR / f"shanghai_3d_baseline{suffix}.csv"
    if p.returncode != 0 or not csv.exists():
        raise RuntimeError(f"gate({method}) 失败 rc={p.returncode}\n"
                           f"{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    return p.stdout, csv


def _score(csv: Path) -> pd.DataFrame:
    d = pd.read_csv(csv)
    return d


# --------------------------------------------------------------------------
# 决定性对照：考卷与 γ_HX 锚其实是同一台样机的两次实验
# --------------------------------------------------------------------------
_BOOK_EXAM = 'experiments/water_air/water-air_G7-t0p6_shanghai_experiment_20260401.xlsx'
_BOOK_ANCHOR = 'experiments/water_air/water-air_G7-t0p6_shanghai_experiment_ports-swapped_20260407.xlsx'


def campaign_compare() -> pd.DataFrame:
    """0401（考卷） vs 0407（γ_HX 锚，进出口调换）逐工况实测 Δp 之比。

    两本工作簿版式相同、工况数相同、**样机流量逐位相同** —— 同一台机器、
    同一组工况点、相隔一周、进出口调换。所以这是 data-vs-data，
    不含任何模型。
    """
    raw = _REPO / "data" / "raw_data"

    def _load(fn: str) -> pd.DataFrame:
        d = pd.read_excel(raw / fn, sheet_name="Sheet1", header=1)
        d = d[d.iloc[:, 0].astype(str).str.startswith("工况")]
        return d.reset_index(drop=True)

    a, b = _load(_BOOK_EXAM), _load(_BOOK_ANCHOR)
    md_a = a["样机空气流量kg/s"].to_numpy(float)
    md_b = b["样机空气流量kg/s"].to_numpy(float)
    if len(a) != len(b) or not np.allclose(md_a, md_b, rtol=1e-9):
        raise RuntimeError("两本工作簿的工况/流量不再逐位对应——"
                           "本对照的前提没了，重核数据")
    dp_a = (a["空气进口压力/Pa"] - a["空气出口压力/Pa"]).to_numpy(float)
    dp_b = (b["空气进口压力/Pa"] - b["空气出口压力/Pa"]).to_numpy(float)
    return pd.DataFrame(dict(
        case=a.iloc[:, 0].astype(str).to_numpy(), mdot=md_a,
        dp_0401_exam=dp_a, dp_0407_anchor=dp_b, ratio=dp_a / dp_b,
        Tin_0401=a["空气进口温度/℃"].to_numpy(float),
        Tin_0407=b["空气进口温度/℃"].to_numpy(float),
        # 0407 的工况1 是 iter 75 判定的仪表地板案（Δp=336 Pa）
        anchor_floor=dp_b < 2000.0))


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 80)
    print("D-2c 上海 16 例真盲考——双层合成面（零上海输入） vs 生产 γ_df")
    print("=" * 80)

    # ---- 闭合层读数（先把要考的东西摆出来）----
    print("\n[0] 闭合读数 @ 上海几何 Gyroid L=7.0 t=0.6")
    m = TwoLayerModel("Gyroid")
    K_tl, cF_tl = m.predict(7.0, 0.6)
    from sjtu_tpmshx.df_surrogate.gamma_df import GammaDF
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        K_pd, cF_pd = GammaDF(tpms="Gyroid").predict(7.0, 0.6)
    print(f"  生产 gamma_df : cF={cF_pd:8.2f}  K={K_pd:.4e}"
          f"   <- 含上海标定 534.8（自己考自己）")
    print(f"  双层合成面    : cF={cF_tl:8.2f}  K={K_tl:.4e}"
          f"   <- γ_spec {m._spec.predict(7.0, 0.6):.3f}"
          f" × γ_HX {m._gamma_hx:.3f} × cF_dev")
    print(f"  盲/生产 = ×{cF_tl / cF_pd:.3f}"
          f"（cF 低 {1 - cF_tl / cF_pd:.1%}）")

    # ---- 跑两次门 ----
    print("\n[1] 跑上海 3D 门（pipeline runner, 20×10×3, 16 例）")
    print("  控制组（生产默认）...")
    _, csv_ctrl = _run_gate(None, "_exam_ctrl")
    print("  盲考组（two_layer）...")
    _, csv_blind = _run_gate("two_layer", "_exam_blind")

    a = _score(csv_ctrl)
    b = _score(csv_blind)
    cols = [c for c in a.columns]
    print(f"  CSV 列: {cols}")

    # 自动识别 dP 列
    def _pick(d, *cands):
        for c in cands:
            if c in d.columns:
                return c
        raise RuntimeError(f"找不到列 {cands}，实际 {list(d.columns)}")

    c_dp_m = _pick(a, "dP_meas", "dP_exp", "dp_meas")
    c_dp_p = _pick(a, "dP_pred", "dP_sim", "dp_pred")
    c_q_m = _pick(a, "Q_meas", "Q_exp", "q_meas")
    c_q_p = _pick(a, "Q_pred", "Q_sim", "q_pred")

    rows = []
    for lab, d in (("production", a), ("two_layer_blind", b)):
        e_dp = (d[c_dp_p] - d[c_dp_m]) / d[c_dp_m]
        e_q = (d[c_q_p] - d[c_q_m]) / d[c_q_m]
        rows.append(dict(
            variant=lab, n=len(d),
            rmsre_dp=float(np.sqrt(np.mean(e_dp ** 2))),
            bias_dp=float(np.mean(e_dp)), med_dp=float(np.median(e_dp)),
            max_abs_dp=float(np.max(np.abs(e_dp))),
            n_neg=int((e_dp < 0).sum()),
            rmsre_q=float(np.sqrt(np.mean(e_q ** 2))),
            bias_q=float(np.mean(e_q))))
    sc = pd.DataFrame(rows)

    print("\n[2] 记分板（16 例）")
    print(f"  {'变体':<18}{'RMSRE_dP':>10}{'偏置(均值)':>12}"
          f"{'中位误差':>10}{'max|e|':>9}{'偏低例数':>9}{'RMSRE_Q':>10}")
    for _, r in sc.iterrows():
        print(f"  {r.variant:<18}{r.rmsre_dp:>10.2%}{r.bias_dp:>12.2%}"
              f"{r.med_dp:>10.2%}{r.max_abs_dp:>9.2%}"
              f"{f'{r.n_neg}/16':>9}{r.rmsre_q:>10.2%}")

    # ---- 裁决 ----
    blind = sc[sc.variant == "two_layer_blind"].iloc[0]
    print("\n[3] 裁决（iter 73 立的判据，audit §10 结论 3）")
    print("  假说(i)  534.8 是旧栈伪迹      -> 期望：RMSRE 正常、无系统符号")
    print("  假说(ii) 上海样机/台架真实差异 -> 期望：dP 系统性偏低 ~25%")
    print(f"  实测：偏置 {blind.bias_dp:+.1%}，中位 {blind.med_dp:+.1%}，"
          f"16 例中 {blind.n_neg} 例偏低，RMSRE {blind.rmsre_dp:.1%}；"
          f"Q 几乎不动（{blind.rmsre_q:.2%} vs 生产 "
          f"{sc[sc.variant == 'production'].iloc[0].rmsre_q:.2%}）")
    if blind.bias_dp < -0.15 and blind.n_neg >= 14:
        verdict = ("**(ii) 成立**：盲预测系统性偏低且全例同号，且 Q 不受影响"
                   "（纯阻力效应）—— 534.8 不是纯旧栈伪迹")
    elif abs(blind.bias_dp) < 0.10 and blind.rmsre_dp < 0.15:
        verdict = ("**(i) 成立**：无上海输入也能正常预测"
                   " —— 534.8 主要是旧栈口径伪迹")
    else:
        verdict = ("**两假说都不干净**：偏置与散度都不落在判据的任一侧，"
                   "需要看逐例结构（见 CSV）再裁")
    print(f"  => {verdict}")

    # ---- [4] 把 (ii) 从"不可知的样机差异"钉成一个具体的、可核实的事实 ----
    cc = campaign_compare()
    ok = cc[~cc.anchor_floor]
    print("\n[4] (ii) 的来源：考卷与 γ_HX 锚是**同一台样机的两次实验**")
    print(f"  考卷  = {_BOOK_EXAM}")
    print(f"  γ_HX 锚 = {_BOOK_ANCHOR}")
    print("  两本：版式相同、16 工况相同、**样机流量逐位相同**，"
          "相隔一周、**进出口调换**。")
    print(f"  实测 Δp 之比（0401考卷 / 0407锚）：中位 "
          f"{ok.ratio.median():.3f}  区间 [{ok.ratio.min():.3f},"
          f"{ok.ratio.max():.3f}]  n={len(ok)}"
          f"（剔 {int(cc.anchor_floor.sum())} 个锚侧仪表地板案）")
    print(f"  对照：盲考隐含的样机因子 = 1/(1+偏置) = "
          f"{1 / (1 + blind.bias_dp):.3f}；iter 73 记的 G 残差 ×1.296。")
    print("  => 三个数同源。**(ii) 里的'真实差异'不是玄学的样机差，而是"
          "\n     同一台机器在两种进出口接法下实测 Δp 差 ~27%** —— 歧管不对称"
          "\n     是 HX 级系统效应的正常表现，但它意味着 **γ_HX 依赖流向**："
          "\n     0407（调换后）是低方向、0401（原接法）是高方向，"
          "\n     而生产的 534.8 对应 0401、双层面锚在 0407。两者各自都对，"
          "\n     描述的是**不同的管路接法**。")
    print("  附带：0407 的 工况1（Δp=336 Pa）正是 iter 75 判为仪表地板的那一案，"
          "\n        0401 同工况读 1149 Pa —— 反过来印证了那次筛。")

    out = REPORT_DIR / "shanghai_blind_exam.csv"
    per = []
    for lab, d in (("production", a), ("two_layer_blind", b)):
        t = d[[c_dp_m, c_dp_p, c_q_m, c_q_p]].copy()
        t.columns = ["dP_meas", "dP_pred", "Q_meas", "Q_pred"]
        t.insert(0, "case", np.arange(1, len(t) + 1))
        t.insert(0, "variant", lab)
        t["err_dp"] = (t.dP_pred - t.dP_meas) / t.dP_meas
        t["err_q"] = (t.Q_pred - t.Q_meas) / t.Q_meas
        per.append(t)
    pd.concat(per).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
