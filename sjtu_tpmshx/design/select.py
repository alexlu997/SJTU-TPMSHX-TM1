"""枚举选型: 遍历 {拓扑×l×t}, 各跑 size_fixed_cell, Pareto-tag。"""
from __future__ import annotations
from .sizing import size_fixed_cell, RHO_S
from .forward import K_STEEL
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.cancellation import CancelledError


class SelectionCancelled(CancelledError):
    """A stopped search retains fully evaluated candidates, never a partial solve."""

    def __init__(self, results):
        super().__init__('Design selection cancelled; completed candidates retained')
        self.results = list(results)

# 默认枚举网格 = 2 拓扑 × 5 l × 4 t = 40 构型。
# 几何范围为 l=4–8 mm、t=0.3–0.6 mm；各流体 Nu、阻力模型的适用范围
# 由现行模型独立检查，不能按已退役 RBF 的旧训练节点判断置信度。
NODES = {"topo": ["Diamond", "Gyroid"],
         "l": [4.0, 5.0, 6.0, 7.0, 8.0], "t": [0.3, 0.4, 0.5, 0.6]}

def enumerate_select(cases, arrangement="cross", nodes=None, rho_s=RHO_S,
                     n_jobs=1, k_s=K_STEEL, prop_model="const", height=None,
                     control: RunControl | None = None):
    """枚举 {拓扑×l×t}, 各跑 size_fixed_cell, 取可行件 + min-V best。
    候选彼此独立 → n_jobs!=1 时用 joblib(loky 进程, 绕 GIL)跨候选并行
    (size_fixed_cell 为顶层函数, 可 pickle); n_jobs=1 走串行(确定性/测试)。
    结果顺序按 combos 不变, 故并行与串行 feasible/best 一致。
    k_s: 固体热导率 [W/(m·K)]; prop_model: 物性取值温 (const/mean), 均传入定尺。
    height: 矩形迎风高 [m] (None=方形 sz=s, 现状/UI 默认), 透传 size_fixed_cell。"""
    nd = nodes or NODES
    combos = [(topo, l, t) for topo in nd["topo"]
              for l in nd["l"] for t in nd["t"]]
    control = control or RunControl()
    results = []
    try:
        control.check_cancelled()
        if n_jobs == 1 or len(combos) <= 1:
            for topo, l, t in combos:
                control.check_cancelled()
                results.append(size_fixed_cell(cases, topo, l, t, arrangement,
                                               rho_s=rho_s, k_s=k_s, prop_model=prop_model,
                                               height=height, control=control))
        else:
            from joblib import Parallel, delayed, effective_n_jobs
            # Finish the active wave before honouring cancellation. Qt callbacks
            # remain in this process; no queued candidates launch after that wave.
            width = min(effective_n_jobs(n_jobs), len(combos))
            with Parallel(n_jobs=n_jobs, backend="loky") as parallel:
                for start in range(0, len(combos), width):
                    control.check_cancelled()
                    results.extend(parallel(
                        delayed(size_fixed_cell)(cases, topo, l, t, arrangement,
                                                 rho_s=rho_s, k_s=k_s, prop_model=prop_model,
                                                 height=height)
                        for topo, l, t in combos[start:start + width]))
        control.check_cancelled()
    except CancelledError as exc:
        raise SelectionCancelled(results) from exc
    feasible = [d for d in results if d.feasible]
    best = min(feasible, key=lambda d: d.V) if feasible else None
    return results, best          # results = 全部候选 (含不可行, 供汇总表 40 行)

def pareto_tags(designs) -> dict:
    """对每件标记其所属"某目标最优"tag (仅在可行件中比, 避免不可行件 V=0 误选)。"""
    tags: dict = {}
    feasible = [d for d in designs if getattr(d, "feasible", False)]
    if not feasible:
        return tags
    for key, name in [(lambda d: d.V, "min-V"),
                      (lambda d: d.weight, "min-wt"),
                      (lambda d: d.dP_hot_max, "min-dP")]:
        b = min(feasible, key=key)
        tags.setdefault(id(b), []).append(name)
    return tags
