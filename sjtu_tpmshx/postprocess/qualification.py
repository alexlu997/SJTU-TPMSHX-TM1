"""One result verdict for postprocessing and application consumers."""
from math import isfinite

import numpy as np

from .applicability import evaluate_applicability
from .physical_balance import evaluate_physical_balance


_REQUIRED_METRICS = ('Q', 'Q_B', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B')


def _all_known(values):
    values = tuple(values)
    return False if False in values else True if values and all(v is True for v in values) else None


def _verdict(passed, source, **evidence):
    return dict(status='passed' if passed is True else 'failed' if passed is False else 'unverified',
                passed=passed, source=source, **evidence)


def _energy_gates(field):
    from sjtu_tpmshx.postprocess.conservation import compute_phase2a
    metadata = field.metadata
    if metadata['thermal_mode'] in ('true_h', 'conservative_energy'):
        balance = metadata['diagnostics']['true_h_balance']
        clips = np.asarray(balance['enthalpy_clip_counts']['total'])
        gates = [['true-h thermal solve converged', balance['converged'] is True],
                 ['true-h enthalpy remains unclipped', bool(clips.shape == (2,) and np.all(clips == 0))]]
        for name in ('coupled', 'equation'):
            ratio = balance[name + '_energy_balance']['ratio']
            tolerance = balance['effective_settings'][name + '_energy_tol']
            gates.append([f'true-h {name} energy balance',
                          bool(isfinite(ratio) and isfinite(tolerance)
                               and 0. <= ratio <= tolerance and tolerance > 0.)])
        return gates
    if metadata['thermal_mode'] == 'temperature':
        if metadata.get('temperature_transport') != 'model_enthalpy_temperature_v1':
            raise NotImplementedError('capacity-temperature has no common energy certificate')
        return [['native strict integral-enthalpy thermal gate',
                 metadata['diagnostics']['convergence_detail']['ltne_ok'] is True]]
    if metadata['thermal_mode'] != 'model_h':
        raise NotImplementedError('thermal route has no common energy certificate')
    if metadata['dimension'] == 2:
        diagnostics = metadata['diagnostics']
        gates = []
        for level, balance in diagnostics['model_h_balance'].items():
            gates.append([f'2D {level} native model-h certificate', balance['passed'] is True])
            for side in ('A', 'B'):
                gates.append([f'2D {level} {side} physical boundary complete',
                              balance[side]['physical_boundary_complete'] is True])
        if set(diagnostics['model_h_balance']) != {'main', 'fine'}:
            raise ValueError('2D energy certificate requires main and fine thermal results')
        gates.append(['2D native Richardson check', diagnostics['convergence_detail']['richardson_ok'] is True])
        return gates
    certificate = compute_phase2a(field)
    return [list(gate) for gate in certificate['gates']]


def evaluate_qualification(result, metrics):
    """Use saved state and existing gates; do not run a solver or property model."""
    metadata = result.metadata
    execution = result.run_status.get('execution')
    completed = execution == 'completed' if execution is not None else None
    detail = metadata.get('diagnostics', {}).get('convergence_detail', {})
    gates = {key: detail[key] for key in ('simple_ok', 'ltne_ok', 'outer_converged',
             'fields_finite', 'envelope_ok', 'richardson_ok') if key in detail}
    convergence = _verdict(_all_known((result.run_status.get('converged'),
        *(value for value in gates.values() if value is not None))),
        'run_status.converged and metadata.diagnostics.convergence_detail',
        gates=gates, thermal_state=result.boundary_fluxes.get('state'),
        pressure_states={side: result.field_metadata.get('P_report_' + side, {}).get('state')
                         for side, row in result.pressure_evidence.items()
                         if row is not None})
    full = metadata.get('mode', 'full') == 'full'
    execution_record = metadata.get('execution_record', {})
    sides = (execution_record.get('sides', {})
             if execution_record.get('version') == 'full_execution_v1' else {})
    physical = _verdict(None, 'boundary_fluxes and metadata.diagnostics', checks=[])
    if full:
        try:
            balance = evaluate_physical_balance(result)
            checks = []
            stages = (('energy', 'fine_energy') if balance['physical_dimension'] == 2
                      and metadata.get('thermal_mode') in ('model_h', 'temperature') else ('energy',))
            for name in stages:
                row = balance.get(name, {})
                checks.append([name + ' ledger available', True if row.get('status') == 'available' else None])
                if row.get('status') == 'available':
                    checks.append([name + ' physical boundary complete', row['physical_boundary_complete']])
            for side in ('A', 'B'):
                if (result.pressure_evidence.get(side) is not None
                        or sides.get(side, {}).get('solved') is True):
                    checks.append([side + ' thermal mass faces available',
                                   True if balance['mass'][side]['status'] == 'available' else None])
            try:
                checks.extend(_energy_gates(result))
            except (KeyError, TypeError, NotImplementedError) as exc:
                checks.append(['route energy certificate unavailable', None])
                physical['reason'] = str(exc)
            physical.update(checks=checks, balance=balance)
            physical.update(_verdict(_all_known(value for _, value in checks), physical['source']))
        except (KeyError, TypeError) as exc:
            physical['reason'] = str(exc)
        except (ValueError, IndexError) as exc:
            physical.update(_verdict(False, physical['source'], reason=str(exc)))
    else:
        physical['reason'] = 'Quick Design does not provide a full physical solve'
    try:
        application = evaluate_applicability(result)
        applicability = _verdict(application['within_limits'], 'metadata.applicability_evidence',
            definition=application['definition'], state=application['status'],
            missing=application.get('missing', ()), scope_notes=application.get('scope_notes', ()),
            checks=[dict(group=group, side=row['side'], source=row['source'],
                         quantity=row['quantity'], status=row['status'], passed=row['within_limit'])
                    for group, rows in application.get('checks', {}).items() for row in rows])
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        applicability = _verdict(False, 'metadata.applicability_evidence', reason=str(exc))
    statuses = {name: metrics[name].status if name in metrics else 'not_evaluated'
                for name in _REQUIRED_METRICS}
    available = _all_known(None if value == 'not_evaluated' else value == 'available'
                           for value in statuses.values())
    metric_verdict = _verdict(available, 'PerformanceResult.metrics', required=statuses)
    recorded_sides = set(sides) == {'A', 'B'} and all(
        row.get('fluid') and type(row.get('solved')) is bool for row in sides.values())
    scope = True if recorded_sides else None
    scope_reason = '' if recorded_sides else 'executed side models were not fully recorded'
    sco2_scope = any(row.get('fluid') == 'sco2' and row.get('solved') for row in sides.values())
    if sco2_scope:
        scope = None
        scope_reason = 'sCO2 joint P/T/Pr and wall heating or cooling qualification remains unverified'
    model_scope = _verdict(scope, 'metadata.execution_record.sides', reason=scope_reason)
    requirements = dict(execution=completed, convergence=convergence['passed'],
        physical=physical['passed'], applicability=applicability['passed'],
        metrics=available, model_scope=scope, full_solve=True if full else None)
    eligible = _all_known(requirements.values())
    # Model accuracy stays unverified when the user studies sCO2 designs.
    deferred = ['model_scope'] if recorded_sides and sco2_scope else []
    optimization_requirements = {name: passed for name, passed in requirements.items()
                                 if name not in deferred}
    optimization = _verdict(_all_known(optimization_requirements.values()),
        'result_qualification_v1 required optimization gates', requirements=optimization_requirements,
        reasons=[name for name, passed in optimization_requirements.items() if passed is not True],
        deferred=deferred)
    return dict(definition='result_qualification_v1', source_result_id=result.result_id,
        execution=_verdict(completed, 'run_status.execution', state=execution),
        convergence=convergence, physical=physical, applicability=applicability,
        metrics=metric_verdict, model_scope=model_scope, optimization=optimization,
        design=dict(status='eligible' if eligible is True else 'rejected' if eligible is False else 'unverified',
                    eligible=eligible, requirements=requirements,
                    reasons=[name for name, passed in requirements.items() if passed is not True],
                    scope='current recorded numerical and model gates; experimental and desktop acceptance remain separate'))
