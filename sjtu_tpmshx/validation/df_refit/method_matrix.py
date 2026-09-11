"""method_matrix.py — 闭合方法对比矩阵（候选 D · D-2c'，两种流向都算）.

D-2c' 章程要的是"现行 γ 面 vs refit 基 vs 物理化 vs 贝叶斯标定，同考卷打分"。
它一直挂在 D10（产品交付按哪种进出口接法）后面——**但被阻塞的只是"裁决"，
不是"打分台"**。本工具把打分台建起来，并且**两种流向都算一遍**：D10 无论
怎么定，答案都已经在表里，届时只需读对应那一列。

### 流向这件事（审计 §14）

考卷（上海 16，`20260401`）与 γ_HX 锚（`20260407-调换进出口`）是**同一台样机、
同一组 16 工况（流量逐位相同）、相隔一周、进出口调换**；实测 Δp 比中位
**1.274**。生产 γ_df 的 534.8 对应 0401 原接法，双层合成面锚在 0407。
所以"双层面 + 流向因子"与"双层面"是同一张面在两种管路下的两个读数。

    DIR_FACTOR = 1.274   # 0401 原接法 / 0407 调换后（data-vs-data，§14）

### 参评变体

  `production`   现行 γ_df 面（含上海标定 534.8 —— 在上海考卷上是自己考自己，
                 列出来作**上界参照**，不作公平比较）
  `two_layer`    D-2b-4 双层合成面（零上海输入，锚在 0407 方向）
  `two_layer_dir` 双层面 × DIR_FACTOR（折算到 0401 方向）
  `smooth_only`  只有光滑基 cF_dev、γ≡1（下界参照：没有任何粗糙度/HX 修正）

物理化（Ergun 族）与贝叶斯标定两个变体**本轮未建**——它们要各自一套拟合，
不是同一天的量；打分台已留好接口（`_VARIANTS` 加一项即可）。

### 纪律

- **生产零改动**：各变体 backend 只在本脚本进程内注册；默认不动。
- 每个变体单独起子进程跑门（backend 有 `_CACHE`，同进程切 env 会串味）。
- 打分只报**数字与结构**，**不下"谁赢"的裁决**——裁决要等 D10。

用法（从仓库根）:
    python -u sjtu_tpmshx/validation/df_refit/method_matrix.py

输出: stdout 记分板 + reports/df_refit/method_matrix.csv。
"""
from __future__ import annotations

import os
import subprocess
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from sjtu_tpmshx.df_surrogate import backend as _backend
from sjtu_tpmshx.validation.df_refit.shanghai_blind_exam import (
    TwoLayerModel, campaign_compare)
from sjtu_tpmshx.validation.df_refit.gamma_specimen import cf_dev
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
REPORT_DIR = _REPO / "reports" / "df_refit"
_GATE = (_REPO / "sjtu_tpmshx" / "validation" / "cases"
         / "validate_shanghai_3d_real.py")
_OUT_DIR = _REPO / "sjtu_tpmshx" / "validation"

DIR_FACTOR = 1.274          # 0401 原接法 / 0407 调换后（审计 §14，data-vs-data）


class _ScaledTwoLayer(TwoLayerModel):
    """双层面 × 常数流向因子。"""
    SCALE = 1.0

    def predict(self, L_mm, t_mm, eps_f=None):
        K, cF = super().predict(L_mm, t_mm, eps_f)
        return K, cF * self.SCALE


class _DirTwoLayer(_ScaledTwoLayer):
    SCALE = DIR_FACTOR


class _Ergun:
    """物理化（Ergun 族）——**零参数**闭合，不看任何实验也不看任何 CFD。

    Ergun 原式（superficial 速度 u_s）：
        dp/dx = 150·μ·u_s·(1−ε)²/(ε³·d_p²) + 1.75·ρ·u_s²·(1−ε)/(ε³·d_p)

    化到本仓约定（**间隙**流速 u = u_s/ε）并代入水力直径关系
    d_p = 1.5·(1−ε)·D_h/ε（即 D_h = 4ε/S_v 的标准换算），ε 解析约掉：

        cF = 1.75/(1.5·D_h) = 1.1667/D_h        [1/m]
        K  = 2.25·D_h²/150  = 0.015·D_h²        [m²]

    **口径声明**：本仓 `tpms_geometry` 的 A_0 实测满足 A_0 = 4·(ε/2)/D_h，
    即 D_h 用的是**单侧**约定。上式的 d_p 换算假定 D_h = 4ε/S_v；若改按单侧
    口径（S_v = A_0，d_p = 6(1−ε)/A_0），cF 会再小一个 ~2 倍因子。
    工具在 [1] 段把两种口径都打出来，不藏这个选择。
    """

    C_F = 1.75 / 1.5
    C_K = 2.25 / 150.0

    def __init__(self, tpms: str):
        self.tpms = tpms

    def _geom(self, L_mm, t_mm):
        from sjtu_tpmshx.models.tpms_props import geometry
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return geometry(self.tpms, float(L_mm), float(t_mm), 0.5)

    def predict(self, L_mm, t_mm, eps_f=None):
        g = self._geom(L_mm, t_mm)
        Dh = float(g["D_h"])
        return self.C_K * Dh * Dh, self.C_F / Dh


class _SmoothOnly:
    """γ≡1：只有 dev 光滑基（下界参照）。K 取 dev 表 K 面。"""

    def __init__(self, tpms: str):
        self.tpms = tpms
        self._tl = TwoLayerModel(tpms)      # 只借它的 K 面

    def predict(self, L_mm, t_mm, eps_f=None):
        K, _ = self._tl.predict(L_mm, t_mm, eps_f)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return K, float(cf_dev(self.tpms, L_mm, t_mm))


def _mk(name: str, model_cls):
    @_backend.register(name)
    class _B(_backend.DFBackend):
        def _build(self, tpms_type):
            return model_cls(tpms_type)

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
    return _B


_mk("mm_two_layer", TwoLayerModel)
_mk("mm_two_layer_dir", _DirTwoLayer)
_mk("mm_smooth_only", _SmoothOnly)
_mk("mm_ergun", _Ergun)

# (显示名, backend method 或 None=生产默认, 一句话)
_VARIANTS = [
    ("production", None, "现行 γ_df 面（含上海标定 534.8）——自己考自己，上界参照"),
    ("two_layer", "mm_two_layer", "双层合成面（零上海输入，锚 0407 方向）"),
    ("two_layer_dir", "mm_two_layer_dir",
     f"双层面 × {DIR_FACTOR}（折算到 0401 原接法方向）"),
    ("ergun", "mm_ergun", "物理化 Ergun 族——零参数，不看实验也不看 CFD"),
    ("smooth_only", "mm_smooth_only", "只有光滑基 cF_dev、γ≡1——下界参照"),
]

_ENV_FIX = dict(PYTHONHASHSEED="0", QT_QPA_PLATFORM="offscreen")


def _run_gate(method: str | None, suffix: str) -> Path:
    env = dict(os.environ)
    env.update(_ENV_FIX)
    if method:
        env["TPMSHX_DF_METHOD"] = method
        boot = ("import runpy,sys;"
                "import sjtu_tpmshx.validation.df_refit.method_matrix;"
                f"sys.argv=['gate','--suffix','{suffix}','--no-gate'];"
                f"runpy.run_path(r'{_GATE}', run_name='__main__')")
        cmd = [sys.executable, "-u", "-c", boot]
    else:
        cmd = [sys.executable, "-u", str(_GATE), "--suffix", suffix,
               "--no-gate"]
    p = subprocess.run(cmd, cwd=str(_REPO), env=env, capture_output=True,
                       text=True, errors="replace")
    csv = _OUT_DIR / f"shanghai_3d_baseline{suffix}.csv"
    if p.returncode != 0 or not csv.exists():
        raise RuntimeError(f"gate({method}) rc={p.returncode}\n"
                           f"{p.stdout[-2500:]}\n{p.stderr[-2500:]}")
    return csv


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 80)
    print("D-2c' 闭合方法对比矩阵——上海 16 考卷，两种流向都算")
    print("=" * 80)

    cc = campaign_compare()
    ok = cc[~cc.anchor_floor]
    print(f"\n[0] 流向因子（审计 §14，data-vs-data）：0401/0407 实测 Δp 比 "
          f"中位 {ok.ratio.median():.3f}，区间 [{ok.ratio.min():.3f},"
          f"{ok.ratio.max():.3f}]，n={len(ok)}")
    print(f"    本工具取 DIR_FACTOR = {DIR_FACTOR}")

    print("\n[1] 闭合读数 @ Gyroid L=7.0 t=0.6")
    tl = TwoLayerModel("Gyroid")
    _, cF_tl = tl.predict(7.0, 0.6)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from sjtu_tpmshx.df_surrogate.gamma_df import GammaDF
        _, cF_pd = GammaDF(tpms="Gyroid").predict(7.0, 0.6)
        cF_sm = float(cf_dev("Gyroid", 7.0, 0.6))
    _er = _Ergun("Gyroid")
    _K_er, cF_er = _er.predict(7.0, 0.6)
    for nm, v in (("production", cF_pd), ("two_layer", cF_tl),
                  ("two_layer_dir", cF_tl * DIR_FACTOR),
                  ("ergun", cF_er), ("smooth_only", cF_sm)):
        print(f"    {nm:<16} cF = {v:8.2f}   (/production = {v / cF_pd:.3f})")
    _g = _er._geom(7.0, 0.6)
    _dh, _a0, _eps = float(_g["D_h"]), float(_g["A_0"]), float(_g["epsilon"])
    print(f"    [Ergun 口径敏感度] D_h={_dh:.4e} m，A_0={_a0:.1f} 1/m，"
          f"eps={_eps:.4f}；A_0 x D_h/(4 x eps/2) = {_a0 * _dh / (2 * _eps):.3f}"
          f"（=1 即单侧口径坐实）")
    print(f"      本工具用 D_h=4eps/S_v 换算 -> cF={cF_er:.1f}；"
          f"若按单侧口径(S_v=A_0) -> cF={cF_er / 2:.1f}。"
          f"两者夹住实测气侧 cF~400。")

    print("\n[2] 上海 3D 门（pipeline, 20x10x3, 16 例）")
    rows = []
    for name, method, note in _VARIANTS:
        print(f"    跑 {name} ...")
        csv = _run_gate(method, f"_mm_{name}")
        d = pd.read_csv(csv)
        e_dp = (d.dP_sim - d.dP_exp) / d.dP_exp
        e_q = (d.Q_sim - d.Q_exp) / d.Q_exp
        rows.append(dict(variant=name, note=note, n=len(d),
                         rmsre_dp=float(np.sqrt(np.mean(e_dp ** 2))),
                         bias_dp=float(np.mean(e_dp)),
                         med_dp=float(np.median(e_dp)),
                         max_abs_dp=float(np.max(np.abs(e_dp))),
                         n_low=int((e_dp < 0).sum()),
                         rmsre_q=float(np.sqrt(np.mean(e_q ** 2)))))
    sc = pd.DataFrame(rows)
    sc.to_csv(REPORT_DIR / "method_matrix.csv", index=False,
              encoding="utf-8-sig")

    print(f"\n  {'变体':<16}{'RMSRE_dP':>10}{'偏置':>10}{'中位':>9}"
          f"{'max|e|':>9}{'偏低':>8}{'RMSRE_Q':>10}")
    for _, r in sc.iterrows():
        print(f"  {r.variant:<16}{r.rmsre_dp:>10.2%}{r.bias_dp:>10.2%}"
              f"{r.med_dp:>9.2%}{r.max_abs_dp:>9.2%}"
              f"{f'{r.n_low}/16':>8}{r.rmsre_q:>10.2%}")

    print("\n[3] [!] 诚实性声明：`two_layer_dir` **不是纯盲考**")
    print("    DIR_FACTOR 取自 0401/0407 实测 Δp 之比，而 **0401 就是考卷本身**")
    print("    —— 所以它是\"除一个标量外全盲\"，不是全盲。公平的说法是：")
    print("      - production   用了 1 个上海标量（534.8，逐几何标定点）")
    print("      - two_layer_dir 也用了 1 个上海标量（流向因子），"
          "其余全部来自独立台架")
    print("    两者用掉的上海信息量**相同**；差别在于 two_layer_dir 的"
          "几何/粗糙度/HX\n    结构是独立数据给的，而非拟合到考卷上。")
    print("    另注：流向因子原则上是**管路的物理属性**，只要在任一台机器上"
          "测过两种\n    接法就能得到，不必依赖这份考卷——本轮只是手头恰好"
          "只有这一对数据。")

    print("\n[4] 怎么读这张表（**本工具不下裁决——裁决等 D10**）")
    print("  - `production` 含上海标定，在上海考卷上是自己考自己 -> 只作上界参照。")
    print("  - **若 D10 答 0401 原接法**：该看 `two_layer_dir` 那一行——"
          "它是无上海输入的\n    闭合折算到交付方向后的真盲考成绩。")
    print("  - **若 D10 答 0407 调换后**：该看 `two_layer` 那一行；"
          "同时意味着生产的 534.8\n    偏高约 27%，需按 §5 走一次有据重基准。")
    print("  - `smooth_only` 是下界：它量化了\"完全不做粗糙度/HX 修正\"的代价。")
    print("  - 物理化（Ergun 族）与贝叶斯标定两变体本轮未建——"
          "各需一套独立拟合，\n    打分台已留接口（`_VARIANTS` 加一项即可）。")
    print(f"\n已写出 {REPORT_DIR / 'method_matrix.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
