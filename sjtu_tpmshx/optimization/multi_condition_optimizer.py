"""Serial multi-condition design search with native batches and two objectives.

G (percent heat gain) is maximized and C (relative pressure cost) is minimized.
Only completed batch observations enter the model or Pareto set. Failed
designs consume budget and retain their original batch evidence.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from importlib import import_module
import json
from pathlib import Path

import numpy as np
from scipy import __version__ as scipy_version
from scipy.stats import qmc

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import ComputeConfig, ZoneInputConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.io.text_file import write_text
from sjtu_tpmshx.models.continuous_field import decision_bounds
from sjtu_tpmshx.optimization.multi_condition import evaluate_condition_batch
from sjtu_tpmshx.optimization.optimizer_qnehvi import _pareto_mask_max


def _bo_versions():
    """Import optional dependencies before spending any physical evaluations."""
    return {name: import_module(name).__version__ for name in ('torch', 'botorch', 'gpytorch')}


def _propose_bo(X, Y, lower, upper, ref_point, *, method, q_batch, seed):
    """Fit independent standardized outputs, then optimize a log acquisition.

    BoTorch 0.17.2 APIs; inputs are normalized with fixed design bounds and
    posterior outputs retain the original (G, -C) units. Fit/selection errors
    propagate: an unfitted GP or another search method is never substituted.
    """
    import torch
    from botorch.acquisition.multi_objective.logei import qLogNoisyExpectedHypervolumeImprovement
    from botorch.acquisition.multi_objective.parego import qLogNParEGO
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.models.transforms import Standardize
    from botorch.optim import optimize_acqf
    from botorch.sampling.normal import SobolQMCNormalSampler
    from gpytorch.mlls import ExactMarginalLogLikelihood

    train_X = torch.as_tensor((X-lower)/(upper-lower), dtype=torch.float64, device='cpu')
    train_Y = torch.as_tensor(Y, dtype=torch.float64, device='cpu')
    bounds = torch.stack((torch.zeros(X.shape[1], dtype=torch.float64),
                          torch.ones(X.shape[1], dtype=torch.float64)))
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = SingleTaskGP(train_X, train_Y, outcome_transform=Standardize(m=2))
        fit_gpytorch_mll(ExactMarginalLogLikelihood(model.likelihood, model))
        sampler = SobolQMCNormalSampler(sample_shape=torch.Size([128]), seed=seed)
        if method == 'qlognehvi':
            acquisition = qLogNoisyExpectedHypervolumeImprovement(
                model, ref_point=ref_point.tolist(), X_baseline=train_X,
                sampler=sampler, prune_baseline=True)
        else:
            acquisition = qLogNParEGO(model, X_baseline=train_X,
                                     sampler=sampler, prune_baseline=True)
        candidates, _ = optimize_acqf(acquisition, bounds=bounds, q=q_batch,
            num_restarts=5, raw_samples=128, options={'batch_limit': 5, 'maxiter': 100})
    return lower + candidates.detach().cpu().numpy()*(upper-lower)


def run_multi_condition_optimization(
    conditions, *, output_dir, method='qlognehvi', n_init=16, n_iter=8,
    q_batch=1, seed=0, field_spec=None, control=RunControl(),
) -> dict:
    """Optimize one complete XY/XYZ design across fixed operating conditions.

    ``conditions`` has the public batch interface's
    ``(condition_id, ComputeConfig, total_A_kg_s, total_B_kg_s)`` entries.
    ``field_spec`` contains continuous control counts, symmetry, degree and
    bounds, without ``x_decision``. Defaults are quadratic, unmirrored 3x3
    (2D) or 3x3x3 (3D) controls. Every candidate carries that complete spec.

    The design budget is ``n_init + n_iter*q_batch``, plus one separate uniform
    baseline batch. Initial design 0 is the original uniform L/t expressed as
    a continuous field; all methods use the same seeded Sobol initial designs.
    The reference point is fixed from usable initial (G, -C) observations:
    component minimum minus 10% of max(component span, [1 percent, 0.01]).
    It is recorded for every method, and used by qLogNEHVI. qLogNParEGO uses
    its sampled Chebyshev scalarization, not that hypervolume reference point.

    ``optimization.json`` checkpoints full inputs, field spec, decisions,
    statuses, native batch paths, objectives and zero-based Pareto history
    indices. Cancellation preserves that record and propagates CancelledError.
    A completed search describes its finite budget, not physical validation or
    convergence to the global Pareto front.
    """
    if method not in ('qlognehvi', 'qlognparego', 'sobol'):
        raise ValueError('method must be qlognehvi, qlognparego or sobol')
    for name, value, minimum in (('n_init', n_init, 1), ('n_iter', n_iter, 0),
                                 ('q_batch', q_batch, 1), ('seed', seed, 0)):
        if type(value) is not int or value < minimum:
            raise ValueError(f'{name} must be an integer >= {minimum}')
    inputs = deepcopy(tuple(conditions))
    if not inputs:
        raise ValueError('conditions must not be empty')
    ids = [row[0] for row in inputs]
    if any(not isinstance(item, str) or not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError('conditions require unique nonempty IDs')
    for _, config, flow_a, flow_b in inputs:
        if not isinstance(config, ComputeConfig):
            raise TypeError('condition config must be ComputeConfig')
        if not np.all(np.isfinite([flow_a, flow_b])) or min(flow_a, flow_b) <= 0:
            raise ValueError('total mass flows must be finite and positive')
    config = inputs[0][1]
    dimension = 3 if config.is_3d else 2
    frozen = ('geometry', 'solver', 'bc_A', 'bc_B', 'flags', 'df_mode',
              'sco2_nu', 'extrap', 'envelope_mode')
    first = asdict(config)
    for _, current, _, _ in inputs[1:]:
        current = asdict(current)
        if any(current[key] != first[key] for key in frozen):
            raise ValueError('all conditions must use the same geometry and evaluation settings')
    spec = dict(n_ctrl_x=3, n_ctrl_y=3, symmetric_y=False, spline_order=2,
                L_bounds=[4., 8.], t_bounds=[.3, .6])
    if dimension == 3:
        spec['n_ctrl_z'] = 3
    if field_spec is not None:
        if 'x_decision' in field_spec:
            raise ValueError('field_spec describes the search space; omit x_decision')
        spec.update(deepcopy(field_spec))
    lower, upper = decision_bounds(spec['n_ctrl_x'], spec['n_ctrl_y'], spec['symmetric_y'],
        spec['L_bounds'], spec['t_bounds'], n_ctrl_z=spec.get('n_ctrl_z'))
    count = len(lower)//2
    uniform_x = np.r_[np.full(count, config.geometry.L_cell_mm),
                      np.full(count, config.geometry.t_wall_mm)]
    seed_zones = ZoneInputConfig(enabled=True, axis='continuous',
                                 config={**spec, 'x_decision': uniform_x.tolist()})
    # Validates dimensionality, controls, resource bounds and the reference
    # design's inclusion in the requested search interval before making files.
    for _, current, _, _ in inputs:
        replace(current, zones=seed_zones).validate()
    versions = {'scipy': scipy_version}
    if method != 'sobol':
        versions.update(_bo_versions())

    budget = n_init + n_iter*q_batch
    engine = qmc.Sobol(d=len(lower), scramble=True, seed=seed)
    sobol = engine.random_base2((max(budget-1, 1)-1).bit_length())[:budget-1]
    designs = np.vstack((uniform_x, lower + sobol*(upper-lower)))
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    history = []
    record = dict(method=method, seed=seed, dimension=dimension, field_spec=spec,
        software_versions=versions, n_init=n_init, n_iter=n_iter, q_batch=q_batch,
        design_budget=budget, baseline_batches=1, status='running', stage='baseline', reason=None,
        objective_directions={'heat_gain_percent': 'maximize', 'pressure_ratio': 'minimize'},
        model_objectives=['heat_gain_percent', '-pressure_ratio'], ref_point=None,
        conditions=[dict(condition_id=name, config=asdict(cfg), mass_flow_A_kg_s=a,
                         mass_flow_B_kg_s=b) for name, cfg, a, b in inputs],
        baseline=dict(directory='baseline', status='not_run', reason=None),
        initial_designs=designs[:n_init].tolist(), proposals=[],
        history=history, pareto_indices=[], n_evaluated=0, n_usable=0)

    def observations():
        rows = [row for row in history if row['status'] == 'completed']
        return (np.asarray([row['x_decision'] for row in rows]).reshape(-1, len(lower)),
                np.asarray([row['model_y'] for row in rows]).reshape(-1, 2), rows)

    def publish():
        _, values, rows = observations()
        record['pareto_indices'] = [row['index'] for row, keep in zip(rows, _pareto_mask_max(values)) if keep]
        record['n_evaluated'] = sum(row['status'] in ('completed', 'failed') for row in history)
        record['n_usable'] = len(rows)
        write_text(root / 'optimization.json',
            json.dumps(record, ensure_ascii=False, allow_nan=False, indent=2) + '\n')

    def batch_control(unit):
        progress = (None if control.progress is None else
                    lambda percent: control.report_progress(int(100*(unit+percent/100)/(budget+1))))
        return replace(control, progress=progress)

    def evaluate_design(x, iteration):
        row = dict(index=len(history), iteration=iteration,
                   phase='initial' if iteration == 0 else 'iteration',
                   x_decision=np.asarray(x).tolist(), directory=f'design_{len(history):04d}',
                   status='running', reason=None, objectives=None, model_y=None)
        history.append(row)
        publish()
        try:
            control.check_cancelled()
            zones = ZoneInputConfig(enabled=True, axis='continuous',
                                     config={**spec, 'x_decision': row['x_decision']})
            candidates = [(name, replace(cfg, zones=zones), a, b) for name, cfg, a, b in inputs]
            result = evaluate_condition_batch(candidates, output_dir=root / row['directory'],
                baseline=baseline['results'], control=batch_control(row['index']+1))
            if result['status'] != 'completed':
                row.update(status='failed', reason=result.get('reason') or 'condition batch failed')
                return
            objectives = result['objectives']
            y = [float(objectives['heat_gain_percent']), -float(objectives['pressure_ratio'])]
            if not np.all(np.isfinite(y)):
                raise ValueError('completed condition batch returned nonfinite objectives')
            row.update(status='completed', objectives=dict(heat_gain_percent=y[0], pressure_ratio=-y[1]),
                       model_y=y)
        except CancelledError as exc:
            row.update(status='cancelled', reason=str(exc))
            raise
        except Exception as exc:
            row.update(status='failed', reason=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            publish()

    publish()
    try:
        control.check_cancelled()
        record['baseline']['status'] = 'running'
        publish()
        uniform = [(name, replace(cfg, zones=ZoneInputConfig()), a, b) for name, cfg, a, b in inputs]
        baseline = evaluate_condition_batch(uniform, output_dir=root / 'baseline', control=batch_control(0))
        record['baseline'].update(status=baseline['status'], reason=baseline.get('reason'))
        if baseline['status'] != 'completed':
            record.update(status='failed', reason='Uniform baseline batch failed')
            return record
        record['stage'] = 'initial'
        for x in designs[:n_init]:
            evaluate_design(x, 0)
        X, Y, _ = observations()
        if len(Y):
            reference = Y.min(axis=0) - .1*np.maximum(np.ptp(Y, axis=0), [1., .01])
            record['ref_point'] = reference.tolist()
        if n_iter > 0 and method != 'sobol' and (len(X) < 2 or len(np.unique(X, axis=0)) < 2):
            record.update(status='failed', reason='BO requires at least two distinct usable initial designs')
            return record
        publish()
        for iteration in range(1, n_iter+1):
            control.check_cancelled()
            record['stage'] = 'proposal'
            publish()
            if method == 'sobol':
                start = n_init + (iteration-1)*q_batch
                proposed = designs[start:start+q_batch]
            else:
                X, Y, _ = observations()
                proposed = _propose_bo(X, Y, lower, upper, reference, method=method,
                                       q_batch=q_batch, seed=seed+iteration)
            proposed = np.asarray(proposed, dtype=float)
            if (proposed.shape != (q_batch, len(lower)) or not np.all(np.isfinite(proposed))
                    or np.any(proposed < lower) or np.any(proposed > upper)):
                raise ValueError('proposed decisions must be finite and inside the complete field bounds')
            record['proposals'].append(dict(iteration=iteration, x_decisions=proposed.tolist()))
            record['stage'] = 'evaluation'
            publish()
            for x in proposed:
                evaluate_design(x, iteration)
        control.check_cancelled()
        record.update(status='completed' if observations()[2] else 'failed', stage='finished',
                      reason=None if observations()[2] else 'No usable design observations')
    except CancelledError as exc:
        if record['baseline']['status'] == 'running':
            record['baseline'].update(status='cancelled', reason=str(exc))
        record.update(status='cancelled', reason=str(exc))
        raise
    except Exception as exc:
        if record['baseline']['status'] == 'running':
            record['baseline'].update(status='failed', reason=f'{type(exc).__name__}: {exc}')
        record.update(status='failed', reason=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        publish()
    return record
