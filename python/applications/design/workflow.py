"""Run the shared Quick Design selection and refinement workflow."""
from __future__ import annotations

import math

from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.run_control.provenance import study_source

from . import select, sizing
from .sizing import Design, K_STEEL, RHO_S

DEFAULT_ARRANGEMENT = 'cross'
DEFAULT_PROP_MODEL = 'mean'


# A study records the source context one time, also for the runs of its workers.
@study_source()
def run_design(
    cases,
    *,
    mode: str = 'auto',
    arrangement: str = DEFAULT_ARRANGEMENT,
    cell: tuple[str, float, float] | None = None,
    nodes: dict | None = None,
    refine: bool = False,
    rho_s: float = RHO_S,
    k_s: float = K_STEEL,
    prop_model: str = DEFAULT_PROP_MODEL,
    height: float | None = None,
    n_jobs: int = 1,
    control: RunControl | None = None,
    completed: list | None = None,
) -> tuple[list[Design], Design | None]:
    """Run fixed sizing or auto enumeration with optional warm-start refinement.

    Append completed candidates to ``completed`` when given. Callers keep
    finished work if an error or cancellation stops the run.
    """
    if mode not in ('auto', 'fixed'):
        raise ValueError(f'unsupported quick design mode: {mode!r}')
    if height is not None and (
        isinstance(height, bool)
        or not isinstance(height, (int, float))
        or not math.isfinite(height)
        or height <= 0
    ):
        raise ValueError('height must be finite and positive')
    if completed:
        raise ValueError('completed must be empty for each design run')
    results = [] if completed is None else completed
    control = RunControl() if control is None else control

    if mode == 'fixed':
        if cell is None:
            raise ValueError('cell is required in fixed mode')
        control.check_cancelled()
        topo, l, t = cell
        design = sizing.size_fixed_cell(
            cases, topo, l, t, arrangement,
            rho_s=rho_s, k_s=k_s, prop_model=prop_model,
            height=height, control=control,
        )
        results.append(design)
        control.check_cancelled()
        return results, (design if design.feasible else None)

    try:
        control.check_cancelled()
        selected, best = select.enumerate_select(
            cases, arrangement, nodes,
            rho_s=rho_s, n_jobs=n_jobs, k_s=k_s,
            prop_model=prop_model, height=height,
            control=control, completed=results,
        )
        if selected is not results:
            results[:] = selected
        if refine and best is not None:
            control.check_cancelled()
            from . import optimize
            refined = optimize.warm_start_joint(
                cases, best, arrangement,
                rho_s=rho_s, k_s=k_s, prop_model=prop_model,
                height=height, control=control,
            )
            if refined is not best and refined.feasible and refined.V < best.V:
                results.append(refined)
                best = refined
        control.check_cancelled()
    except select.SelectionCancelled as exc:
        if exc.results is not results:
            results[:] = exc.results
        raise
    except CancelledError as exc:
        raise select.SelectionCancelled(results) from exc
    return results, best
