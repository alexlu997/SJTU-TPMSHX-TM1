"""Quick design through public preparation, solver and postprocessing APIs."""
from dataclasses import dataclass, field
from uuid import uuid4
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.domain.performance_result import MetricValue
from sjtu_tpmshx.domain.run_warnings import record_warning
from sjtu_tpmshx.models.quick_design import K_STEEL, LTNE_TOL

@dataclass
class ForwardResult:
    T_out_hot: float; T_out_cold: float
    Q_hot: float; Q_cold: float
    dP_hot_frac: float; dP_cold_frac: float
    Re_hot: float; Re_cold: float
    fields: tuple | None = field(default=None, repr=False)  # (Ta,Tb,Ts) 供 warm-start

    run_status: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    energy_imbalance: MetricValue | None = None

def forward(case, topo: str, l: float, t: float, s: float, Lx: float,
            arrangement: str = "cross", init=None, k_s: float = K_STEEL,
            prop_model: str = "const", tol: float = LTNE_TOL,
            height=None) -> ForwardResult:
    from sjtu_tpmshx.preprocess.api import prepare_quick_design
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.postprocess.api import evaluate
    prepared = prepare_quick_design(
        case, topo, l, t, s, Lx, arrangement, case_id=str(uuid4()), init=init,
        k_s=k_s, prop_model=prop_model, tol=tol, height=height)
    result = run_case(prepared)
    performance = evaluate(result)
    names = ('T_out_A', 'T_out_B', 'Q', 'Q_cold', 'dP_A', 'dP_B', 'Re_A', 'Re_B')
    values = []
    for name in names:
        metric = performance.metrics[name]
        if metric.status != 'available':
            raise ValueError(f'quick-design {name}: {metric.status}: {metric.reason}')
        values.append(metric.value)
    values[4] /= case.P_in_h
    values[5] /= case.P_in_c
    messages = list(result.metadata['diagnostics']['warnings_list'])
    for message in messages:
        record_warning(('quick-design', message), message)
    return ForwardResult(*values, fields=tuple(result.fields[name] for name in ('Ta', 'Tb', 'Ts')),
                         run_status=mutable_data(result.run_status), warnings=messages,
                         energy_imbalance=performance.metrics.get('energy_imbalance_rel'))
