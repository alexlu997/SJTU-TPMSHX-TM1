"""设计结果 → 双 sheet Excel。CLI 与 UI 共用, 避免输出格式分叉。

构型汇总:  每构型一行 (含不可行) — 长宽高 + 重量 + dP 上限值。
工况明细:  构型 × 工况 每行 — 该工况各自的出口温/两侧压损/换热量/Re,
           明确对应输入 Excel 的具体工况 (而非 max-over-工况 的单值)。
"""
from __future__ import annotations
import math
from pathlib import Path
import pandas as pd

from sjtu_tpmshx.io.file_set import staged_files
from .select import pareto_tags


def cid(d) -> str:
    """构型唯一标识, 如 Diamond_l7_t0.5。"""
    return f"{d.topo}_l{d.l:g}_t{d.t:g}"


def _H_mm(d):
    """矩形 (d.height>0) 取固定高; 方形回退 W=s。"""
    h = d.height if getattr(d, "height", 0.0) else d.s
    return round(h * 1e3, 2)

def warning_text(d) -> str:
    """Render final-case notices for the shared UI/CLI/export contract."""
    return '\n'.join(f"[工况 {pc['case']}] {message}"
                     for pc in getattr(d, 'percase', [])
                     for message in pc.get('warnings', []))


def _round_re(value):
    return round(value) if math.isfinite(value) else value


def summary_rows(results, tags) -> list:
    return [dict(
        构型=cid(d), 拓扑=d.topo, l_mm=d.l, t_mm=d.t, 布置=d.arrangement,
        可行=("是" if d.feasible else "否"),
        W_mm=round(d.s * 1e3, 2), H_mm=_H_mm(d),
        Lx_mm=round(d.Lx * 1e3, 2),
        V_L=round(d.V * 1e3, 4), 重量_kg=round(d.weight, 4),
        dP热_max=round(d.dP_hot_max, 4), dP冷_max=round(d.dP_cold_max, 4),
        Re热_max=_round_re(getattr(d, "Re_hot_max", 0.0)),
        Re冷_max=_round_re(getattr(d, "Re_cold_max", 0.0)),
        验证=getattr(d, "validity", ""),
        警告=warning_text(d),
        备注=d.reason, 标记=",".join(tags.get(id(d), []))) for d in results]


def detail_rows(results) -> list:
    return [dict(
        构型=cid(d), 工况=pc["case"], 热流体=pc["hot_fluid"], 冷流体=pc["cold_fluid"],
        热侧出口_K=round(pc["T_air_out"], 2), 冷侧出口_K=round(pc["T_cold_out"], 2),
        热侧绝对压损_Pa=round(pc["dP_hot_pa"], 1),
        热侧相对压损_pct=round(pc["dP_hot_frac"] * 100, 3),
        冷侧绝对压损_Pa=round(pc["dP_cold_pa"], 1),
        冷侧相对压损_pct=round(pc["dP_cold_frac"] * 100, 3),
        换热量_kW=round(pc["Q_W"] / 1e3, 3),
        Re热=_round_re(pc["Re_hot"]), Re冷=_round_re(pc["Re_cold"]),
        数值收敛=(pc.get('run_status') or {}).get('converged', 'unknown'),
        终验='; '.join(pc.get('acceptance_reasons', [])),
        警告='\n'.join(pc.get('warnings', [])))
        for d in results for pc in d.percase]


def write_xlsx(path, results, *, partial=False) -> tuple:
    """完整写好双 sheet 后发布，失败保留原报告；返回 (构型数, 可行数, 明细行数)。"""
    tags = pareto_tags(results)
    if partial:
        tags = {key: [f'已完成候选内 {tag}' for tag in value] for key, value in tags.items()}
    df_s = pd.DataFrame(summary_rows(results, tags))
    if not df_s.empty:
        df_s = df_s.sort_values(["可行", "V_L"], ascending=[True, True])
    det = detail_rows(results)
    df_d = pd.DataFrame(det) if det else pd.DataFrame([{"提示": "无可行构型"}])
    if partial:
        for frame in (df_s, df_d):
            frame['任务状态'] = '已取消：部分候选，不代表完整搜索最优'
    path = Path(path)
    with staged_files([path]) as stage:
        with pd.ExcelWriter(stage / path.name, engine="openpyxl") as xw:
            df_s.to_excel(xw, sheet_name="构型汇总", index=False)
            df_d.to_excel(xw, sheet_name="工况明细", index=False)
    return len(results), sum(d.feasible for d in results), len(det)
