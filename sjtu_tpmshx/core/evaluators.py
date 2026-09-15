"""Historical 3D screening facade shared by optimization and validation.

The physical mode uses independent public preparation, solve and postprocess
APIs. Validation callers retain the original NaN/invalid and convergence
contract; the optimizer separately applies per-depth normalization and caps.
"""
from __future__ import annotations
from uuid import uuid4
import numpy as np

from sjtu_tpmshx.models.envelope import R_AIR_DEFAULT as R_AIR
from sjtu_tpmshx.models.screening import _build_3d_arrays as _build_3d_arrays

__all__ = ['evaluate_3d', '_build_3d_arrays', 'R_AIR']


def evaluate_3d(x_decision: np.ndarray,
                cfg: dict,
                *,
                Nx: int = 40, Ny: int = 16, Nz: int = 16,
                Lz: float = 0.042,
                max_outer: int = 3,
                outer_tol_K: float = 0.5,
                alpha_outer: float = 0.6,
                max_iter_simple: int = 800,
                tol_simple: float = 1e-2,
                max_iter_energy: int = 2000,
                tol_energy: float = 0.5,
                roughness_mode: str | None = None,
                roughness_eps_um: float | None = None,
                convergence_mode: str = 'f2',
                verbose: bool = True) -> dict:
    from sjtu_tpmshx.preprocess.api import prepare_screening_3d
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.postprocess.api import evaluate
    case = prepare_screening_3d(
        x_decision, cfg, case_id=str(uuid4()), Nx=Nx, Ny=Ny, Nz=Nz, Lz=Lz,
        max_outer=max_outer, outer_tol_K=outer_tol_K, alpha_outer=alpha_outer,
        max_iter_simple=max_iter_simple, tol_simple=tol_simple,
        max_iter_energy=max_iter_energy, tol_energy=tol_energy,
        roughness_mode=roughness_mode, roughness_eps_um=roughness_eps_um,
        convergence_mode=convergence_mode, verbose=verbose)
    result = run_case(case)
    metrics = evaluate(result).metrics
    values = {key: float('nan') if metrics[name].value is None else float(metrics[name].value)
              for key, name in (('Q_3D_W', 'Q'), ('dP_A_Pa', 'dP_A'), ('dP_B_Pa', 'dP_B'), ('mass_kg', 'mass'))}
    values.update(dP_total_Pa=values['dP_A_Pa'] + values['dP_B_Pa'], Lz_m=Lz, grid=(Nx, Ny, Nz))
    if result.run_status['execution'] == 'rejected':
        values.update(invalid=True, converged=False, invalid_reason=result.run_status['reason'])
        return values
    finite = bool(all(np.isfinite(values[key]) for key in ('Q_3D_W', 'dP_A_Pa', 'dP_B_Pa', 'mass_kg')))
    truth = {key: bool(result.run_status[key]) for key in ('simple_A_converged', 'simple_B_converged', 'ltne_inner_converged', 'outer_converged')}
    truth['finite'] = finite
    values.update(invalid=False, converged=all(truth.values()), **truth)
    return values
