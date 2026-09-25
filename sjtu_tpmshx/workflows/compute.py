"""Sequence module calls without geometry, numerical or metric formulas."""
from sjtu_tpmshx.domain.module_ports import RunControl


def compute(config, *, case_id, control=RunControl(), prepare=None, solve=None, evaluate=None):
    if prepare is None:
        from sjtu_tpmshx.preprocess.api import prepare_case as prepare
    if solve is None:
        from sjtu_tpmshx.solvers.api import run_case as solve
    if evaluate is None:
        from sjtu_tpmshx.postprocess.api import evaluate
    control.check_cancelled()
    case = prepare(config, case_id=case_id)
    control.check_cancelled()
    result = solve(case, control)
    control.check_cancelled()
    performance = evaluate(result)
    control.check_cancelled()
    return case, result, performance
