"""Air/air screening application: public module calls and optimizer objectives.

Q retains the volumetric LTNE convention in W/m. Manufacturability and bounded
bad-design penalties belong here. Physical fields and statuses remain in the
module results; this historical function still returns its objective tuple.
"""
from __future__ import annotations
import warnings
import numpy as np
from uuid import uuid4

from sjtu_tpmshx.models.screening import DEFAULT_CONFIG as DEFAULT_CONFIG, build_field
from sjtu_tpmshx.models.continuous_field import ContinuousFieldConfig
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)
_BC_LOG_DONE = False
_CHOKE_LOG_DONE = False


def _compute_cfg_to_evaluator_dict(compute_cfg) -> dict:
    """Map ``controllers.ComputeConfig`` → evaluator-style flat dict.

    Audit C3 (2026-05-28, L-a-1): callers can pass a strict-typed
    ComputeConfig instead of hand-rolling a dict. Keys are the subset
    that overlaps with :data:`DEFAULT_CONFIG`; everything else stays
    on the dataclass defaults.
    """
    return {
        'L_domain': compute_cfg.geometry.L_dom_m,
        'H_domain': compute_cfg.geometry.H_dom_m,
        'Nx': compute_cfg.solver.Nx,
        'Ny': compute_cfg.solver.Ny,
        'tpms_type': compute_cfg.geometry.tpms,
        'k_s': compute_cfg.geometry.k_s_W_mK,
        'u_A': compute_cfg.fluid_A.u_mps,
        'u_B': compute_cfg.fluid_B.u_mps,
        'T_inA': compute_cfg.fluid_A.T_in_K,
        'T_inB': compute_cfg.fluid_B.T_in_K,
        'P_inA': compute_cfg.fluid_A.P_in_Pa,
        'P_inB': compute_cfg.fluid_B.P_in_Pa,
        # R3 (2026-07-07): the evaluator budget reads the OPTIMIZER block —
        # SolverConfig now carries the production pipeline knobs (None=auto)
        # and no longer describes the cheap screening solves.
        'max_iter_simple': compute_cfg.optimizer.max_iter_simple,
        'tol_simple': compute_cfg.optimizer.tol_simple,
        'tol_energy': compute_cfg.optimizer.outer_tol_K,
    }



def evaluate_design(x: np.ndarray, cfg: dict | None = None,
                    fc: ContinuousFieldConfig | None = None, *, verbose=False,
                    compute_cfg=None) -> tuple:
    from sjtu_tpmshx.preprocess.api import prepare_screening_2d
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.postprocess.api import evaluate
    cc_dict = {} if compute_cfg is None else _compute_cfg_to_evaluator_dict(compute_cfg)
    cfg_full = {**DEFAULT_CONFIG, **cc_dict, **(cfg or {})}
    global _BC_LOG_DONE, _CHOKE_LOG_DONE
    if not _BC_LOG_DONE:
        _BC_LOG_DONE = True
        _log.info('[evaluator2d] BC resolved: ports_A=%s ports_B=%s per_cell_K=%s '
                  '(None ports = full-face inlet/outlet)', cfg_full.get('ports_A'),
                  cfg_full.get('ports_B'), cfg_full.get('per_cell_K', False))
    fc = build_field(x, cfg_full) if fc is None else fc
    case = prepare_screening_2d(x, {**cfg_full, 'verbose': verbose}, fc=fc,
                                case_id=str(uuid4()))
    result = run_case(case)
    metrics = evaluate(result).metrics
    mass = float(metrics['mass'].value)
    dp_cap = float(cfg_full.get('dp_cap_pa', 1.0e6))
    if result.run_status['execution'] == 'rejected':
        if result.run_status['rejection_stage'] == 'pre_solve' and not _CHOKE_LOG_DONE:
            _CHOKE_LOG_DONE = True
            _log.warning('[evaluator2d] choked design rejected pre-solve (%s) -- '
                         'returning the bounded dp_cap penalty; further chokes '
                         'this process are silent.', result.run_status['reason'])
        return -1e-6, dp_cap, mass
    pen = 0.
    if cfg_full['penalty_enabled']:
        pen = float(cfg_full['penalty_weight']) * fc.manufacturability_penalty()
    a, b = metrics['dP_A'].value, metrics['dP_B'].value
    dp = float('nan') if a is None or b is None else float(float(a + b) + pen)
    if not np.isfinite(dp) or dp > dp_cap:
        return -1e-6, dp_cap, mass
    return -float(metrics['Q'].value), dp, mass


if __name__ == '__main__':
    import time
    warnings.filterwarnings('ignore')

    # Build a uniform field at L=6, t=0.4 → equivalent to single-zone baseline
    from sjtu_tpmshx.models.continuous_field import uniform_field

    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0, 0.10, 0.05)
    print("Building uniform-field design …")
    t0 = time.perf_counter()
    Q_neg, dP, mass = evaluate_design(
        x=None, cfg={'fast_mode': False, 'max_iter_simple': 800,
                     'tol_simple': 1e-3, 'max_iter_energy': 1500,
                     'tol_energy': 0.5},
        fc=fc, verbose=False)
    dt = time.perf_counter() - t0
    print(f"Q  = {-Q_neg:8.1f} W/m   (Q_neg = {Q_neg:.1f})")
    print(f"dP = {dP:8.1f} Pa")
    print(f"mass = {mass:.3f} kg/m   solid")
    print(f"wall time {dt:.1f} s")
