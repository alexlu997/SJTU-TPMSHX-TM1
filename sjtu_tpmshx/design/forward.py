"""Quick design through public preparation, solver and postprocessing APIs."""
from dataclasses import dataclass, field
from sjtu_tpmshx.models.quick_design import (
    K_STEEL, GEOM_N as GEOM_N, NX as NX, NY_CROSS as NY_CROSS, LTNE_TOL,
    SIZING_QTOL as SIZING_QTOL, SIZING_CHUNK as SIZING_CHUNK, _ARR as _ARR,
    _hvol as _hvol, _dp_one as _dp_one, dP_fracs as dP_fracs,
)
from sjtu_tpmshx.result_math import _cold_outlet as _cold_outlet

@dataclass
class ForwardResult:
    T_out_hot: float; T_out_cold: float
    Q_hot: float; Q_cold: float
    dP_hot_frac: float; dP_cold_frac: float
    Re_hot: float; Re_cold: float
    fields: tuple | None = field(default=None, repr=False)  # (Ta,Tb,Ts) 供 warm-start

    run_status: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

def forward(case, topo: str, l: float, t: float, s: float, Lx: float,
            arrangement: str = "cross", init=None, k_s: float = K_STEEL,
            prop_model: str = "const", tol: float = LTNE_TOL,
            height=None) -> ForwardResult:
    from .public_forward import forward as public_forward
    return public_forward(case, topo, l, t, s, Lx, arrangement,
                          init=init, k_s=k_s, prop_model=prop_model, tol=tol, height=height)
