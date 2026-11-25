"""快速设计 CLI: auto (枚举选胞元) / fixed (指定胞元只定外形)。"""
from __future__ import annotations
import argparse, sys
from collections import Counter
from pathlib import Path

from . import sizing
from .cases import load_cases
from .workflow import run_design
from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.applications.cli.cli_options import add_run_control_arguments, run_control_from_args

def _parse_cell(s):           # "Diamond,7,0.5"
    topo, l, t = s.split(","); return topo, float(l), float(t)

def _parse_nodes(s):          # "Diamond,Gyroid:6,7:0.4,0.5"
    topo, ls, ts = s.split(":")
    return {"topo": topo.split(","),
            "l": [float(x) for x in ls.split(",")],
            "t": [float(x) for x in ts.split(",")]}

def run(argv=None) -> int:
    default_rho = str(sizing.RHO_S).removesuffix(".0")
    default_ks = str(sizing.K_STEEL).removesuffix(".0")
    ap = argparse.ArgumentParser(description="TPMS 快速设计 (单模块)")
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--mode", choices=["auto", "fixed"], default="auto",
                    help="fixed=baseline(固定 l,t); auto=优化(放开 l,t 枚举)")
    ap.add_argument("--cell", help="fixed 模式: topo,l,t")
    ap.add_argument("--nodes", help="auto 模式: topo:l:t 列表")
    ap.add_argument("--arrangement", choices=["cross","counter"], default="cross")
    ap.add_argument("--refine", action="store_true",
                    help="auto 后对最优件做 warm-start 联合精修 (连续 l,t)")
    ap.add_argument("--rho-s", type=float, default=sizing.RHO_S,
                    help=f"固体材料密度 kg/m³ (默认 {default_rho} = 304 不锈钢)")
    ap.add_argument("--k-s", type=float, default=sizing.K_STEEL,
                    help=f"固体热导率 W/(m·K) (默认 {default_ks} = 304SS; 铝~150 铜~300)")
    ap.add_argument("--prop-model", choices=["const", "mean"], default="const",
                    help="const=入口物性求解一次(默认)；mean=再按入口/出口均温更新物性求解一次。"
                         "压降均用入口物性；水侧 Nu 的 Pr 均固定取 320 K / 0.2 MPa")
    ap.add_argument("--jobs", type=int, default=-1,
                    help="auto 枚举并行核数 (-1=全核, 1=串行; joblib loky)")
    ap.add_argument("--out", required=True)
    add_run_control_arguments(ap)
    a = ap.parse_args(argv)
    if Path(a.xlsx).resolve() == Path(a.out).resolve():
        ap.error(f'output overlaps input: {a.out}')
    control = run_control_from_args(a)
    cases = load_cases(a.xlsx)

    results = []
    try:
        cell = _parse_cell(a.cell) if a.mode == "fixed" and a.cell is not None else None
        nodes = _parse_nodes(a.nodes) if a.mode == "auto" and a.nodes else None
        results, best = run_design(
            cases,
            mode=a.mode,
            arrangement=a.arrangement,
            cell=cell,
            nodes=nodes,
            refine=a.refine,
            rho_s=a.rho_s,
            k_s=a.k_s,
            prop_model=a.prop_model,
            n_jobs=a.jobs,
            control=control,
            completed=results,
        )
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
