"""快速设计 CLI: auto (枚举选胞元) / fixed (指定胞元只定外形)。"""
from __future__ import annotations
import argparse, sys
from collections import Counter

from .cases import load_cases
from .sizing import size_fixed_cell
from .select import enumerate_select
from sjtu_tpmshx.domain.cancellation import CancelledError

def _parse_cell(s):           # "Diamond,7,0.5"
    topo, l, t = s.split(","); return topo, float(l), float(t)

def _parse_nodes(s):          # "Diamond,Gyroid:6,7:0.4,0.5"
    topo, ls, ts = s.split(":")
    return {"topo": topo.split(","),
            "l": [float(x) for x in ls.split(",")],
            "t": [float(x) for x in ts.split(",")]}

def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TPMS 快速设计 (单模块)")
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--mode", choices=["auto", "fixed"], default="auto",
                    help="fixed=baseline(固定 l,t); auto=优化(放开 l,t 枚举)")
    ap.add_argument("--cell", help="fixed 模式: topo,l,t")
    ap.add_argument("--nodes", help="auto 模式: topo:l:t 列表")
    ap.add_argument("--arrangement", choices=["cross","counter"], default="cross")
    ap.add_argument("--refine", action="store_true",
                    help="auto 后对最优件做 warm-start 联合精修 (连续 l,t)")
    ap.add_argument("--rho-s", type=float, default=7900.0,
                    help="固体材料密度 kg/m³ (默认 7900 = 304 不锈钢)")
    ap.add_argument("--k-s", type=float, default=16.0,
                    help="固体热导率 W/(m·K) (默认 16 = 304SS; 铝~150 铜~300)")
    ap.add_argument("--prop-model", choices=["const", "mean"], default="const",
                    help="物性取值温: const=入口(快,默认) / mean=均温(消大-ΔT偏置,~1.5×)")
    ap.add_argument("--jobs", type=int, default=-1,
                    help="auto 枚举并行核数 (-1=全核, 1=串行; joblib loky)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    cases = load_cases(a.xlsx)

    results = []
    try:
        if a.mode == "fixed":
            topo, l, t = _parse_cell(a.cell)
            d = size_fixed_cell(cases, topo, l, t, a.arrangement,
                                rho_s=a.rho_s, k_s=a.k_s, prop_model=a.prop_model)
            results, best = [d], (d if d.feasible else None)
        else:
            nodes = _parse_nodes(a.nodes) if a.nodes else None
            results, best = enumerate_select(cases, a.arrangement, nodes,
                                             rho_s=a.rho_s, n_jobs=a.jobs, k_s=a.k_s,
                                             prop_model=a.prop_model, completed=results)
            if a.refine and best is not None:           # Stage B warm-start 精修
                from .optimize import warm_start_joint
                ref = warm_start_joint(cases, best, a.arrangement,
                                       rho_s=a.rho_s, k_s=a.k_s,
                                       prop_model=a.prop_model)
                if ref is not best:
                    results = results + [ref]
                    best = ref
    except CancelledError:
        raise
    except Exception:
        if results:
            try:
                from .report import write_xlsx
                write_xlsx(a.out, results, partial=True, termination_reason='failed')
                print(f"[partial written] {a.out} · 失败前 {len(results)} 个已完成候选，"
                      "不代表完整搜索最优", file=sys.stderr)
            except Exception as report_error:
                print(f"部分结果导出失败: {report_error}", file=sys.stderr)
        raise
    from .report import write_xlsx, cid, warning_text  # CLI/UI 共用
    n_total, n_feas, n_det = write_xlsx(a.out, results)
    print(f"[written] {a.out}  构型 {n_total} (可行 {n_feas}) × 工况 {len(cases)} "
          f"→ 工况明细 {n_det} 行 (sheet: 构型汇总 / 工况明细)")
    if best is not None:
        print(f"best (min-V): {cid(best)}  "
              f"{best.s*1e3:.1f}×{best.s*1e3:.1f}×{best.Lx*1e3:.1f}mm  "
              f"V={best.V*1e3:.3f}L  wt={best.weight:.3f}kg")
        notices = warning_text(best)
        if notices:
            print(notices)
    else:
        reasons = Counter(d.reason or '未记录失败原因' for d in results)
        detail = '；'.join(f'{reason} ({count})' for reason, count in reasons.items())
        print(f"无可行构型：{detail or '未生成候选构型'}", file=sys.stderr)
    return 0

if __name__ == "__main__":
    raise SystemExit(run())
