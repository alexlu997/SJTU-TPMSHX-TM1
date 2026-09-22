"""warm-start 联合精修 (单模块): 从枚举/baseline 最优出发, 对连续 (l,t)
求 min-V (外形由 size_fixed_cell 确定性内定)。= ZONED-OPT Stage B 的单模块退化
(无分区梯度)。已知可行 baseline 给出最小体积的上界；各流体 Nu 与阻力的
适用范围由现行模型分别检查，不按旧 RBF 训练节点推定置信度。"""
from __future__ import annotations
import numpy as np
from scipy.optimize import minimize

from .sizing import size_fixed_cell, Design, RHO_S
from sjtu_tpmshx.models.quick_design import K_STEEL
from sjtu_tpmshx.domain.module_ports import RunControl

# 训练凸包 [mm] — single source in df_surrogate/_domain.py.
from sjtu_tpmshx.df_surrogate._domain import TRAIN_L as L_BOUNDS, TRAIN_T as T_BOUNDS

def warm_start_joint(cases, baseline: Design, arrangement: str = "cross",
                     maxiter: int = 20, rho_s: float = RHO_S,
                     k_s: float = K_STEEL, prop_model: str = "const",
                     height=None, control: RunControl | None = None) -> Design:
    """从 baseline (topo,l,t) warm-start, Nelder-Mead 在凸包内对 (l,t) 求 min-V。
    外形每评估由 size_fixed_cell 内定 (串行, 每次一整定尺含 all-K 校正 → 单次贵)。
    不可行/不优于 baseline → 回退 baseline。
    收敛阈务实: 连续 (l,t) 精修相对离散最优通常仅 <1% 增益, fatol/maxiter 故设宽松 +
    低上限 → 早停 (避免死追 <0.5% 微改善花数倍时间)。fatol 单位 m³ (1e-6=1mL≈0.5%V)。"""
    topo = baseline.topo
    control = control or RunControl()

    def obj(x) -> float:
        control.check_cancelled()
        l, t = float(x[0]), float(x[1])
        if not (L_BOUNDS[0] <= l <= L_BOUNDS[1]
                and T_BOUNDS[0] <= t <= T_BOUNDS[1]):
            return 1e9
        d = size_fixed_cell(cases, topo, l, t, arrangement, rho_s=rho_s,
                            k_s=k_s, prop_model=prop_model, height=height, control=control)
        return d.V if d.feasible else 1e9

    res = minimize(obj, np.array([baseline.l, baseline.t]),
                   method="Nelder-Mead", bounds=[L_BOUNDS, T_BOUNDS],
                   options={"xatol": 0.05, "fatol": 1e-6, "maxiter": maxiter})
    d = size_fixed_cell(cases, topo, float(res.x[0]), float(res.x[1]),
                        arrangement, rho_s=rho_s, k_s=k_s, prop_model=prop_model,
                        height=height, control=control)
    if (not d.feasible) or d.V >= baseline.V:      # 下界对照 → 回退
        return baseline
    return d
