"""Serial design search with native batches and fixed operating conditions.

Search heat/pressure trade-offs, or minimize core mass under absolute limits.
Only completed batch observations enter the model or Pareto set. Failed
designs consume budget and retain their original batch evidence.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from importlib import import_module
import json
from pathlib import Path
import shutil
from time import perf_counter

import numpy as np
from scipy import __version__ as scipy_version
from scipy.stats import qmc

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import ComputeConfig, ZoneInputConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.paused_run import PausedRun
from sjtu_tpmshx.io.text_file import write_text
from sjtu_tpmshx.logutil import get_logger
from sjtu_tpmshx.models.continuous_field import decision_bounds, decision_dim
from sjtu_tpmshx.optimization.multi_condition import (
    _condition_worker_count, _evaluate_condition_batch, _saved_condition_config,
)
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.optimization.mass_design import (
    constraint_keys, mass_lower_bound, mass_observation, model_observation, validate_mass_requirements,
)


_log = get_logger(__name__)


def _pareto_mask_max(Y: np.ndarray, *, valid=None) -> np.ndarray:
    """Boolean mask of non-dominated rows under MAXIMIZATION semantics.

    Y shape: (N, M). A row is non-dominated when no other row weakly dominates
    it on every objective AND strictly dominates on at least one.
    """
    N = Y.shape[0]
    mask = np.isfinite(Y).all(axis=1)
    if valid is not None:
        mask &= valid
    for i in range(N):
        if not mask[i]:
            continue
        for j in range(N):
            if i == j or not mask[j]:
                continue
            if np.all(Y[j] >= Y[i]) and np.any(Y[j] > Y[i]):
                mask[i] = False
                break
    return mask


def _bo_versions():
    """Import optional dependencies before spending any physical evaluations."""
    return {name: import_module(name).__version__ for name in ('torch', 'botorch', 'gpytorch')}


def _propose_bo(X, Y, lower, upper, ref_point, *, method, q_batch, seed, on_stage=None):
    """Fit independent standardized outputs, then optimize a log acquisition.

    BoTorch 0.18.1 APIs; inputs are normalized with fixed design bounds and
    posterior outputs retain their physical units or relative constraint margins. Fit/selection errors
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

    active = upper > lower
    train_X = torch.as_tensor((X[:, active]-lower[active])/(upper[active]-lower[active]),
                              dtype=torch.float64, device='cpu')
    train_Y = torch.as_tensor(Y, dtype=torch.float64, device='cpu')
    bounds = torch.stack((torch.zeros(int(active.sum()), dtype=torch.float64),
                          torch.ones(int(active.sum()), dtype=torch.float64)))
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        if on_stage is not None:
            on_stage('model_fit')
        model = SingleTaskGP(train_X, train_Y, outcome_transform=Standardize(m=Y.shape[1]))
        fit_gpytorch_mll(ExactMarginalLogLikelihood(model.likelihood, model))
        if on_stage is not None:
            on_stage('proposal')
        sampler = SobolQMCNormalSampler(sample_shape=torch.Size([128]), seed=seed)
        if method == 'qlognei':
            from botorch.acquisition.logei import qLogNoisyExpectedImprovement
            from botorch.acquisition.objective import GenericMCObjective
            acquisition = qLogNoisyExpectedImprovement(
                model, X_baseline=train_X, sampler=sampler, prune_baseline=True,
                objective=GenericMCObjective(lambda samples, X=None: samples[..., 0]),
                constraints=[lambda samples, index=index: samples[..., index]
                             for index in range(1, Y.shape[1])])
        elif method == 'qlognehvi':
            acquisition = qLogNoisyExpectedHypervolumeImprovement(
                model, ref_point=ref_point.tolist(), X_baseline=train_X,
                sampler=sampler, prune_baseline=True)
        else:
            acquisition = qLogNParEGO(model, X_baseline=train_X,
                                     sampler=sampler, prune_baseline=True)
        candidates, _ = optimize_acqf(acquisition, bounds=bounds, q=q_batch,
            num_restarts=5, raw_samples=128, options={'batch_limit': 5, 'maxiter': 100})
    full = np.tile(lower, (q_batch, 1))
    full[:, active] += candidates.detach().cpu().numpy()*(upper[active]-lower[active])
    return full


def _check_saved_search(record, frozen, designs, lower, upper):
    keys = constraint_keys(frozen['mass_requirements']) if 'mass_requirements' in frozen else ()
    for key, value in frozen.items():
        if key == 'conditions':
            current, saved = deepcopy(record[key]), deepcopy(value)
            for rows in (current, saved):
                for row in rows:
                    for side in 'AB':
                        row['config']['fluid_'+side].update(u_mps=None, mass_flow_kg_s=None)
            if current != saved:
                raise ValueError('saved search conditions differ from the fixed input')
        elif record.get(key) != value:
            raise ValueError(f'saved search {key} differs from the fixed input')
    n_init, q_batch = frozen['n_init'], frozen['q_batch']
    budget = n_init + frozen['n_iter']*q_batch
    if (record['design_budget'] != budget or record['baseline']['directory'] != 'baseline'
            or record['initial_designs'] != designs[:n_init].tolist()):
        raise ValueError('saved search budget, baseline or initial designs differ')
    decisions = [(0, x) for x in designs[:n_init].tolist()]
    if len(record['proposals']) > frozen['n_iter']:
        raise ValueError('saved search has too many proposals')
    for iteration, proposal in enumerate(record['proposals'], 1):
        values = np.asarray(proposal['x_decisions'], dtype=float)
        if (proposal['iteration'] != iteration or values.shape != (q_batch, len(lower))
                or not np.isfinite(values).all() or np.any(values < lower) or np.any(values > upper)):
            raise ValueError('saved proposal identity or bounds differ')
        if frozen['method'] == 'sobol':
            start = n_init + (iteration-1)*q_batch
            if not np.array_equal(values, designs[start:start+q_batch]):
                raise ValueError('saved Sobol proposals differ from the seeded sequence')
        decisions.extend((iteration, x) for x in values.tolist())
    if len(record['history']) > len(decisions):
        raise ValueError('saved history exceeds the proposed design budget')
    states = {'not_run', 'running', 'completed', 'failed', 'paused', 'cancelled'}
    for index, (row, (iteration, decision)) in enumerate(zip(record['history'], decisions)):
        if (row['index'] != index or row['directory'] != f'design_{index:04d}'
                or row['iteration'] != iteration or row['x_decision'] != decision
                or row['status'] not in states):
            raise ValueError('saved history differs from the proposed design sequence')
        if row['status'] == 'completed':
            y = model_observation(row['objectives'], constrained='mass_requirements' in frozen,
                                  constraint_names=keys)
            if 'mass_requirements' in frozen and row.get('feasible') != all(value <= 0 for value in y[1:]):
                raise ValueError('saved feasibility differs from the constraint observations')
            if row['model_y'] != y or not np.isfinite(y).all():
                raise ValueError('saved objectives differ from the model observations')
        elif row['objectives'] is not None or row['model_y'] is not None:
            raise ValueError('unfinished or failed design has usable observations')
    initial = [row['model_y'] for row in record['history'][:n_init] if row['status'] == 'completed']
    if record['ref_point'] is not None:
        values = np.asarray(initial)
        if (len(record['history']) < n_init or not len(values)
                or record['ref_point'] != (values.min(axis=0)
                    - .1*np.maximum(np.ptp(values, axis=0), [1., .01])).tolist()):
            raise ValueError('saved reference point differs from the initial observations')


def run_multi_condition_optimization(
    conditions, *, output_dir, method='qlognehvi', n_init=16, n_iter=8,
    q_batch=1, seed=0, field_spec=None, control=RunControl(), workers=None, on_update=None,
    pause_check=None, mass_requirements=None,
) -> dict:
    """Start a search and retain its fixed input for recovery in a new directory."""
    return _run_multi_condition_optimization(conditions, output_dir=output_dir, method=method,
        n_init=n_init, n_iter=n_iter, q_batch=q_batch, seed=seed, field_spec=field_spec,
        control=control, workers=workers, on_update=on_update, pause_check=pause_check,
        mass_requirements=mass_requirements)


def resume_multi_condition_optimization(checkpoint_file, *, output_dir, control=RunControl(),
                                        workers=None, on_update=None, pause_check=None):
    """Validate and continue a saved search without changing its source directory."""
    source = Path(checkpoint_file).resolve(strict=True)
    if source.name != 'optimization.json':
        raise ValueError('select optimization.json to continue a search')
    destination = Path(output_dir).resolve()
    if any(parent.exists() and parent.samefile(source.parent)
           for parent in (destination, *destination.parents)):
        raise ValueError('the recovery directory must be outside the saved search')
    record = json.loads(source.read_text(encoding='utf-8'))
    frozen = json.loads(source.with_name('optimization-input.json').read_text(encoding='utf-8'))
    if frozen.get('format') != 'optimization_v1':
        raise ValueError('saved search does not have a supported fixed input')
    for saved in (record, frozen):
        for row in saved['conditions']:
            if row['config']['flags'].get('wall_refine_3d') is False:
                del row['config']['flags']['wall_refine_3d']
    conditions = [(row['condition_id'], _saved_condition_config(row),
                   row['mass_flow_A_kg_s'], row['mass_flow_B_kg_s']) for row in frozen['conditions']]
    return _run_multi_condition_optimization(conditions, output_dir=destination, control=control,
        workers=workers, on_update=on_update, pause_check=pause_check,
        resume_from=(source.parent, record, frozen), mass_requirements=frozen.get('mass_requirements'),
        **{key: frozen[key] for key in ('method', 'n_init', 'n_iter', 'q_batch', 'seed', 'field_spec')})


def _run_multi_condition_optimization(
    conditions, *, output_dir, method='qlognehvi', n_init=16, n_iter=8,
    q_batch=1, seed=0, field_spec=None, control=RunControl(), workers=None, on_update=None,
    pause_check=None, resume_from=None, mass_requirements=None,
) -> dict:
    """Optimize one complete XY/XYZ design across fixed operating conditions.

    ``conditions`` has the public batch interface's
    ``(condition_id, ComputeConfig, total_A_kg_s, total_B_kg_s)`` entries.
    ``field_spec`` contains continuous control counts, symmetry, degree and
    bounds, without ``x_decision``. Defaults are quadratic, unmirrored 3x3
    (2D) or 3x3x3 (3D) controls. Every candidate carries that complete spec.

    The maximum design budget is ``n_init + n_iter*q_batch``, plus one separate uniform
    baseline batch. Initial design 0 is the original uniform L/t expressed as
    a continuous field. New mass searches then check the geometry mass bound.
    The remaining initial designs use the same seeded Sobol sequence.
    The reference point is fixed from usable initial (G, -C) observations:
    component minimum minus 10% of max(component span, [1 percent, 0.01]).
    It is recorded for every method, and used by qLogNEHVI. qLogNParEGO uses
    its sampled Chebyshev scalarization, not that hypervolume reference point.

    With ``mass_requirements``, minimize core mass in kg. Each condition has
    Q_min_W and dP_A_max_Pa / dP_B_max_Pa limits. The heat metric is -Q_B;
    multiply 2D heat and mass by physical depth. qLogNEI models negative mass
    and the requested worst-condition relative residuals. Optional outlet
    temperature and pressure limits use native metrics. A residual <= 0 is feasible.
    Keep usable infeasible observations in the model, but exclude them from
    the selected designs. The supplied density covers the TPMS core only.

    ``optimization.json`` checkpoints full inputs, field spec, decisions,
    statuses, native batch paths, objectives and zero-based Pareto history
    indices. Cancellation preserves that record and propagates CancelledError.
    A completed search describes its finite budget, not physical validation or
    convergence to the global Pareto front.

    ``on_update`` receives independent search and condition snapshots. Time
    estimates use observed batch and proposal durations. The first BO proposal
    must finish before its remaining cost can be estimated.
    """
    if method not in ('qlognehvi', 'qlognparego', 'qlognei', 'sobol'):
        raise ValueError('method must be qlognehvi, qlognparego, qlognei or sobol')
    constrained = mass_requirements is not None
    if (method == 'qlognei' and not constrained
            or constrained and method not in ('qlognei', 'sobol')):
        raise ValueError('Core-mass requirements need qlognei or sobol; qlognei needs requirements')
    for name, value, minimum in (('n_init', n_init, 1), ('n_iter', n_iter, 0),
                                 ('q_batch', q_batch, 1), ('seed', seed, 0)):
        if type(value) is not int or value < minimum:
            raise ValueError(f'{name} must be an integer >= {minimum}')
    inputs = deepcopy(tuple(conditions))
    if not inputs:
        raise ValueError('conditions must not be empty')
    workers = _condition_worker_count(workers, len(inputs), control)
    ids = [row[0] for row in inputs]
    if any(not isinstance(item, str) or not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError('conditions require unique nonempty IDs')
    if constrained:
        mass_requirements = validate_mass_requirements(mass_requirements, ids)
    keys = constraint_keys(mass_requirements) if constrained else ()
    for _, config, flow_a, flow_b in inputs:
        if not isinstance(config, ComputeConfig):
            raise TypeError('condition config must be ComputeConfig')
        if not np.all(np.isfinite([flow_a, flow_b])) or min(flow_a, flow_b) <= 0:
            raise ValueError('total mass flows must be finite and positive')
    inputs = tuple((name, replace(cfg, zones=ZoneInputConfig(),
        fluid_A=replace(cfg.fluid_A, mass_flow_kg_s=a),
        fluid_B=replace(cfg.fluid_B, mass_flow_kg_s=b)), a, b) for name, cfg, a, b in inputs)
    config = inputs[0][1]
    dimension = 3 if config.is_3d else 2
    frozen = ('geometry', 'solver', 'bc_A', 'bc_B', 'flags', 'df_mode',
              'sco2_nu', 'extrap', 'envelope_mode')
    first = asdict(config)
    for _, current, _, _ in inputs[1:]:
        current = asdict(current)
        if (any(current[key] != first[key] for key in frozen)
                or any(current['fluid_' + s]['type'] != first['fluid_' + s]['type'] for s in 'AB')):
            raise ValueError('all conditions must use the same geometry and evaluation settings')
    spec = dict(n_ctrl_x=3, n_ctrl_y=3, symmetric_y=False, spline_order=2,
                L_bounds=[4., 8.], t_bounds=[.3, .6])
    if dimension == 3:
        spec['n_ctrl_z'] = 3
    if field_spec is not None:
        if 'x_decision' in field_spec:
            raise ValueError('field_spec describes the search space; omit x_decision')
        spec.update(deepcopy(field_spec))
    dimension_count = decision_dim(spec['n_ctrl_x'], spec['n_ctrl_y'], spec['symmetric_y'],
                                   n_ctrl_z=spec.get('n_ctrl_z'))
    if dimension_count > qmc.Sobol.MAXDIM:
        raise ValueError(f'{method} initialization supports at most {qmc.Sobol.MAXDIM} variables; '
                         f'this control layout has {dimension_count}')
    lower, upper = decision_bounds(spec['n_ctrl_x'], spec['n_ctrl_y'], spec['symmetric_y'],
        spec['L_bounds'], spec['t_bounds'], n_ctrl_z=spec.get('n_ctrl_z'))
    if not np.any(upper > lower):
        raise ValueError('A search needs at least one variable field; use a single calculation for fixed L/t')
    count = len(lower)//2
    uniform_x = np.r_[np.full(count, config.geometry.L_cell_mm),
                      np.full(count, config.geometry.t_wall_mm)]
    seed_zones = ZoneInputConfig(enabled=True, axis='continuous',
                                 config={**spec, 'x_decision': uniform_x.tolist()})
    # Validates dimensionality, controls, resource bounds and the reference
    # design's inclusion in the requested search interval before making files.
    for _, current, _, _ in inputs:
        replace(current, zones=seed_zones).validate_static_inputs()
    versions = {'scipy': scipy_version}
    if method != 'sobol':
        versions.update(_bo_versions())

    budget = n_init + n_iter*q_batch
    engine = qmc.Sobol(d=len(lower), scramble=True, seed=seed)
    sobol = engine.random_base2((max(budget-1, 1)-1).bit_length())[:budget-1]
    designs = np.vstack((uniform_x, lower + sobol*(upper-lower)))
    bound = None
    policy = (resume_from[2].get('initial_design_policy') if resume_from is not None
              else 'mass_bound_v1' if constrained else None)
    if policy is not None:
        if policy != 'mass_bound_v1' or not constrained:
            raise ValueError('Unknown initialization policy for this search')
        bound = mass_lower_bound(config, spec, mass_requirements['solid_density_kg_m3'], count)
        if budget > 1 and bound['x_decision'] != uniform_x.tolist():
            designs = np.vstack((uniform_x, bound['x_decision'], designs[1:]))[:budget]
    root = Path(output_dir).resolve()
    frozen = dict(format='optimization_v1', method=method, backend=control.backend, seed=seed,
        dimension=dimension, field_spec=spec, software_versions=versions,
        n_init=n_init, n_iter=n_iter, q_batch=q_batch,
        conditions=[dict(condition_id=name, config=cfg.to_dict(), mass_flow_A_kg_s=a,
                         mass_flow_B_kg_s=b) for name, cfg, a, b in inputs])
    if constrained:
        frozen['mass_requirements'] = mass_requirements
    if bound is not None:
        frozen.update(initial_design_policy=policy, mass_lower_bound=bound)
    if resume_from is not None:
        source_root, saved, saved_input = resume_from
        if saved_input != frozen:
            raise ValueError('saved search input or software versions differ from this execution')
        _check_saved_search(saved, frozen, designs, lower, upper)
        # Keep all pending evidence local before a second pause can occur.
        from sjtu_tpmshx.io.file_snapshot import copy_saved_file
        shutil.copytree(source_root, root, copy_function=copy_saved_file, ignore=lambda directory, names:
            {'optimization.json'} if Path(directory) == source_root else set())
    else:
        root.mkdir(parents=True, exist_ok=False)
        write_text(root / 'optimization-input.json',
            json.dumps(frozen, ensure_ascii=False, allow_nan=False, indent=2) + '\n')
    history = []
    record = dict(**deepcopy(frozen), workers=workers,
        design_budget=budget, baseline_batches=1, status='running', stage='baseline', reason=None,
        iteration=0,
        objective_directions={'heat_gain_percent': 'maximize', 'pressure_ratio': 'minimize'},
        model_objectives=['heat_gain_percent', '-pressure_ratio'], ref_point=None,
        baseline=dict(directory='baseline', status='not_run', reason=None),
        initial_designs=designs[:n_init].tolist(), proposals=[],
        history=history, pareto_indices=[], n_evaluated=0, n_usable=0)
    if constrained:
        record.update(objective_directions={'core_mass_kg': 'minimize'},
            model_objectives=['-core_mass_kg', *keys], n_feasible=0)
    if resume_from is not None:
        record = deepcopy(saved)
        record.update(status='running', stage='baseline', iteration=0, reason=None,
                      workers=workers, resumed_from=str(source_root))
        record.pop('stop_reason', None)
        history = record['history']
    cursor = 0

    def observations():
        rows = [row for row in history if row['status'] == 'completed']
        return (np.asarray([row['x_decision'] for row in rows]).reshape(-1, len(lower)),
                np.asarray([row['model_y'] for row in rows]).reshape(-1, 1 + len(keys) if constrained else 2), rows)

    started = perf_counter()
    prior_elapsed = record.get('elapsed_s', 0.)
    batch_started = proposal_started = None
    condition_states = []

    def notify():
        if on_update is None:
            return
        now = perf_counter()
        finished = [row for row in (record['baseline'], *history)
                    if row['status'] in ('completed', 'failed') and 'elapsed_s' in row]
        proposals = record['proposals']
        pending_proposals = n_iter - len(proposals) if method != 'sobol' else 0
        eta = None
        if finished and (not pending_proposals or proposals):
            mean_batch = float(np.mean([row['elapsed_s'] for row in finished]))
            pending_batches = budget + 1 - len(finished)
            eta = pending_batches * mean_batch
            if batch_started is not None:
                eta -= min(now - batch_started, mean_batch)
            if pending_proposals:
                mean_proposal = float(np.mean([row['elapsed_s'] for row in proposals]))
                eta += pending_proposals * mean_proposal
                if proposal_started is not None:
                    eta -= min(now - proposal_started, mean_proposal)
        if record['status'] != 'running':
            eta = 0. if record['status'] == 'completed' else None
        on_update(dict(report=deepcopy(record), conditions=deepcopy(condition_states),
                       elapsed_s=prior_elapsed+now-started, eta_s=eta))

    def batch_update(states):
        nonlocal condition_states
        condition_states = states
        notify()

    notifications = {'on_update': batch_update} if on_update is not None else {}
    if pause_check is not None:
        notifications['pause_check'] = pause_check

    def publish(primary_error=None):
        try:
            _, values, rows = observations()
            valid = np.all(values[:, 1:] <= 0, axis=1) if constrained else None
            front = _pareto_mask_max(values[:, :1] if constrained else values, valid=valid)
            record['pareto_indices'] = [row['index'] for row, keep in zip(rows, front) if keep]
            if constrained:
                record['n_feasible'] = int(np.count_nonzero(valid))
            record['n_evaluated'] = sum(row['status'] in ('completed', 'failed') for row in history)
            record['n_usable'] = len(rows)
            record['elapsed_s'] = prior_elapsed + perf_counter() - started
            write_text(root / 'optimization.json',
                json.dumps(record, ensure_ascii=False, allow_nan=False, indent=2) + '\n')
        except Exception as save_error:
            if primary_error is None:
                raise
            primary_error.add_note(f'Could not save {root / "optimization.json"}: {save_error!r}')
            _log.exception('Could not save optimization checkpoint')
            raise primary_error
        try:
            notify()
        except Exception as callback_error:
            if primary_error is None:
                raise
            primary_error.add_note(f'Search update failed: {callback_error}')
            raise primary_error

    def check_stop():
        control.check_cancelled()
        if pause_check is not None and pause_check():
            raise PausedRun(root / 'optimization.json')

    def set_stage(stage):
        record['stage'] = stage
        publish()
        check_stop()

    def bound_attained():
        if bound is None or cursor != len(history):
            return False
        for row in history:
            if row.get('feasible') and row['status'] == 'completed' and np.isclose(
                    row['objectives']['core_mass_kg'], bound['mass_kg'], rtol=1e-12, atol=0.):
                record.update(status='completed', stage='finished',
                              reason=None, stop_reason='mass_lower_bound')
                control.report_progress(100)
                return True
        return False

    highest_progress = int(100 * sum(row['status'] in ('completed', 'failed')
        for row in (record['baseline'], *history)) / (budget+1))
    def batch_control(unit):
        highest = 0
        def progress(percent):
            nonlocal highest, highest_progress
            highest = max(highest, percent)
            highest_progress = max(highest_progress, int(100*(unit+highest/100)/(budget+1)))
            control.report_progress(highest_progress)
        return replace(control, progress=progress if control.progress is not None else None)

    def evaluate_batch(conditions, directory, unit, baseline=None):
        path = root / directory
        recovery = {}
        if resume_from is not None and (path / 'batch.json').exists():
            recovery = dict(resume_from=(path, json.loads((path / 'batch.json').read_text(encoding='utf-8'))),
                            keep_failed=True)
        return _evaluate_condition_batch(conditions, output_dir=path, baseline=baseline,
            control=batch_control(unit), workers=workers, **notifications, **recovery,
            allow_nu_re_extrapolation=bool(constrained and mass_requirements.get('allow_nu_re_extrapolation', False)))

    def evaluate_design(x, iteration):
        nonlocal batch_started, condition_states, cursor
        previous = deepcopy(history[cursor]) if cursor < len(history) else None
        if previous is None:
            row = dict(index=cursor, iteration=iteration, phase='initial' if iteration == 0 else 'iteration',
                       x_decision=np.asarray(x).tolist(), directory=f'design_{cursor:04d}',
                       status='running', reason=None, objectives=None, model_y=None)
            history.append(row)
        else:
            row = history[cursor]
        cursor += 1
        check_stop()
        if row['status'] == 'failed':
            batch_control(row['index']+1).report_progress(100)
            return
        if row['status'] != 'completed':
            row.update(status='running', reason=None)
        condition_states = []
        batch_started = perf_counter()
        publish()
        primary_error = None
        try:
            check_stop()
            zones = ZoneInputConfig(enabled=True, axis='continuous',
                                     config={**spec, 'x_decision': row['x_decision']})
            candidates = [(name, replace(cfg, zones=zones), a, b) for name, cfg, a, b in inputs]
            result = evaluate_batch(candidates, row['directory'], row['index']+1, baseline['summaries'])
            if result['status'] != 'completed':
                if previous is not None and previous['status'] == 'completed':
                    raise ValueError('retained design no longer has a completed batch')
                row.update(status='failed', reason=result.get('reason') or 'condition batch failed')
                return
            objectives = result['objectives']
            if constrained:
                objectives, checks = mass_observation(result['summaries'], mass_requirements)
                if previous is not None and previous['status'] == 'completed' and checks != previous['constraint_checks']:
                    raise ValueError('retained constraint checks differ from the saved observation')
                row.update(constraint_checks=checks)
            if previous is not None and previous['status'] == 'completed' and objectives != previous['objectives']:
                raise ValueError('retained design objectives differ from its saved observation')
            y = model_observation(objectives, constrained=constrained, constraint_names=keys)
            if not np.all(np.isfinite(y)):
                raise ValueError('completed condition batch returned nonfinite objectives')
            row.update(status='completed', objectives=objectives, model_y=y)
            if constrained:
                row['feasible'] = all(value <= 0 for value in y[1:])
        except (CancelledError, PausedRun) as exc:
            primary_error = exc
            if previous is None or previous['status'] != 'completed':
                row.update(status='paused' if isinstance(exc, PausedRun) else 'cancelled', reason=str(exc))
            raise
        except Exception as exc:
            primary_error = exc
            row.update(status='failed', reason=f'{type(exc).__name__}: {exc}', objectives=None, model_y=None)
            raise
        finally:
            row['elapsed_s'] = (previous or {}).get('elapsed_s', 0.) + perf_counter() - batch_started
            if previous is not None and previous['status'] == 'completed':
                row['elapsed_s'] = previous['elapsed_s']
            batch_started = None
            publish(primary_error)

    publish()
    primary_error = None
    try:
        check_stop()
        if record['baseline']['status'] == 'failed':
            record.update(status='failed', reason='Uniform baseline batch failed')
            return record
        if record['baseline']['status'] != 'completed':
            record['baseline']['status'] = 'running'
        publish()
        batch_started = perf_counter()
        try:
            baseline = evaluate_batch(inputs, 'baseline', 0)
        finally:
            record['baseline']['elapsed_s'] = record['baseline'].get('elapsed_s', 0.) + perf_counter() - batch_started
            batch_started = None
        record['baseline'].update(status=baseline['status'], reason=baseline.get('reason'))
        if baseline['status'] != 'completed':
            record.update(status='failed', reason='Uniform baseline batch failed')
            return record
        # Resolve replayable speeds only after the baseline has retained each
        # condition's preparation/solve outcome, including invalid target flows.
        inputs = tuple((name, ComputeConfig.from_dict(mutable_data(
            baseline['summaries'][name]['config_snapshot'])), a, b) for name, _, a, b in inputs)
        for archived, (_, cfg, _, _) in zip(record['conditions'], inputs):
            archived['config'] = cfg.to_dict()
        record['stage'] = 'initial'
        for x in designs[:n_init]:
            evaluate_design(x, 0)
            if bound_attained():
                return record
        initial = [row for row in history[:n_init] if row['status'] == 'completed']
        X = np.asarray([row['x_decision'] for row in initial])
        Y = np.asarray([row['model_y'] for row in initial])
        reference = None
        if len(Y) and not constrained:
            reference = Y.min(axis=0) - .1*np.maximum(np.ptp(Y, axis=0), [1., .01])
            record['ref_point'] = reference.tolist()
        if n_iter > 0 and method != 'sobol' and (len(X) < 2 or len(np.unique(X, axis=0)) < 2):
            record.update(status='failed', reason='BO requires at least two distinct usable initial designs')
            return record
        publish()
        for iteration in range(1, n_iter+1):
            check_stop()
            record.update(stage='evaluation' if iteration <= len(record['proposals']) else 'proposal',
                          iteration=iteration)
            condition_states = []
            proposal_started = perf_counter()
            publish()
            if iteration <= len(record['proposals']):
                proposed = record['proposals'][iteration-1]['x_decisions']
            elif method == 'sobol':
                start = n_init + (iteration-1)*q_batch
                proposed = designs[start:start+q_batch]
            else:
                X, Y, _ = observations()
                proposed = _propose_bo(X, Y, lower, upper, reference, method=method,
                                       q_batch=q_batch, seed=seed+iteration, on_stage=set_stage)
            proposed = np.asarray(proposed, dtype=float)
            if (proposed.shape != (q_batch, len(lower)) or not np.all(np.isfinite(proposed))
                    or np.any(proposed < lower) or np.any(proposed > upper)):
                raise ValueError('proposed decisions must be finite and inside the complete field bounds')
            if iteration > len(record['proposals']):
                record['proposals'].append(dict(iteration=iteration, x_decisions=proposed.tolist(),
                                               elapsed_s=perf_counter()-proposal_started))
            proposal_started = None
            record['stage'] = 'evaluation'
            publish()
            for x in proposed:
                evaluate_design(x, iteration)
                if bound_attained():
                    return record
        check_stop()
        record.update(status='completed' if observations()[2] else 'failed', stage='finished',
                      reason=None if observations()[2] else 'No usable design observations')
    except (CancelledError, PausedRun) as exc:
        primary_error = exc
        status = 'paused' if isinstance(exc, PausedRun) else 'cancelled'
        if record['baseline']['status'] == 'running':
            record['baseline'].update(status=status, reason=str(exc))
        record.update(status=status, reason=str(exc))
        raise
    except Exception as exc:
        primary_error = exc
        if record['baseline']['status'] == 'running':
            record['baseline'].update(status='failed', reason=f'{type(exc).__name__}: {exc}')
        record.update(status='failed', reason=f'{type(exc).__name__}: {exc}')
        for row in history:
            if row['status'] == 'running':
                row.update(status='failed', reason=record['reason'])
        raise
    finally:
        publish(primary_error)
    return record
