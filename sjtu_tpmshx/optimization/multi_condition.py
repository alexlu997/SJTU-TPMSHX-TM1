"""Fixed-flow preparation and equal-weight multi-condition objectives."""
from collections.abc import Sequence
from dataclasses import asdict, replace
import json
from math import fsum, isfinite
from pathlib import Path
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.performance_result import PerformanceResult
from sjtu_tpmshx.preprocess.api import prepare_case


ConditionResult = tuple[str, FieldResult, PerformanceResult]
ConditionInput = tuple[str, ComputeConfig, float, float]
_METRICS = ('Q_B', 'dP_A', 'dP_B')


def _inlet_mass_capacity(design_fields, prepared, side):
    axis = prepared['axes'][side]
    eps_in = np.take(design_fields['eps_' + side],
                     -1 if axis['is_reverse'] else 0, axis=axis['stream_real_axis'])
    area = np.asarray(axis['dcross1'])[:, None] * np.asarray(axis['dcross2'])[None, :]
    pore_area = float(np.sum(eps_in * prepared['openings'][side]['inlet'] * area))
    capacity = prepared['properties'][side]['rho'] * pore_area
    if not isfinite(capacity) or capacity <= 0:
        raise ValueError(f'side {side}: inlet density times open pore area must be finite and positive')
    return capacity


def _total_inlet_mass_capacity(design, parameters, grid, side):
    if grid['dimension'] == 3:
        return _inlet_mass_capacity(design, parameters['prepared'], side)
    geometry = parameters['run_settings']['geometry']
    depth = geometry['Lz_m']
    if depth is None or not isfinite(depth) or depth <= 0:
        raise ValueError('2D total mass flow requires a positive physical Lz_m')
    if geometry['delta_levelset'] != 0:
        raise ValueError('2D fixed-flow optimization currently requires delta_levelset=0')
    direction = parameters['cfg' + side]['dir']
    axis = direction // 2
    eps_in = np.take(design['eps_arr'], -1 if direction % 2 else 0, axis=axis) / 2.
    widths = grid['dy' if axis == 0 else 'dx']
    opening = parameters['boundary_openings'][side]['in_profile_frac']
    capacity = parameters['static_properties'][side]['rho'] * float(np.sum(eps_in * opening * widths)) * depth
    if not isfinite(capacity) or capacity <= 0:
        raise ValueError(f'side {side}: inlet density times open pore area must be finite and positive')
    return capacity


def prepare_fixed_mass_flow_case(
    config: ComputeConfig, *, mass_flow_A_kg_s: float,
    mass_flow_B_kg_s: float, case_id: str,
) -> CaseData:
    """Prepare a 2D or 3D candidate at prescribed total inlet mass flows.

    The native inlet velocity contains the fractional opening once. Therefore
    its total flow is ``rho * u * sum(eps_side * opening * face_area)`` using
    the actual physical inlet slice, including reverse directions. Prepared
    ``eps_A/B`` already represent each fluid's pore fraction in 3D. A 2D
    case requires an explicit physical depth ``geometry.Lz_m`` to convert
    total flow to the solver's per-unit-depth flow; its symmetric channel
    porosity is half the prepared total porosity.

    Prepare twice so the returned immutable snapshot and all speed-dependent
    preparation use the adjusted velocities. The caller's configuration and
    its geometry, inlet temperature/pressure, and model choices stay intact.
    No numerical solve is performed.
    """
    if config.fluid_A is None or config.fluid_B is None:
        raise ValueError('fixed mass flow requires a dual-fluid ComputeConfig')
    if not config.is_3d and (config.geometry.Lz_m is None or not isfinite(config.geometry.Lz_m)
                             or config.geometry.Lz_m <= 0):
        raise ValueError('2D total mass flow requires a positive physical Lz_m')
    targets = {'A': mass_flow_A_kg_s, 'B': mass_flow_B_kg_s}
    for side, target in targets.items():
        if not isfinite(target) or target <= 0:
            raise ValueError(f'mass_flow_{side}_kg_s must be finite and positive')
    provisional = prepare_case(config, case_id=case_id)
    fluids = {}
    for side, target in targets.items():
        capacity = _total_inlet_mass_capacity(
            provisional.design_fields, provisional.parameters, provisional.grid, side)
        fluids['fluid_' + side] = replace(getattr(config, 'fluid_' + side),
                                          u_mps=target / capacity)
    return prepare_case(replace(config, **fluids), case_id=case_id)


def _full_result_metadata(field):
    metadata = field.metadata
    dimension = metadata.get('dimension')
    if (dimension not in (2, 3) or field.grid['dimension'] != dimension
            or metadata.get('quantity_basis') != {2: 'per_unit_depth', 3: 'total'}[dimension]
            or metadata.get('mode', 'full') != 'full' or metadata.get('thermal_mode') != 'model_h'):
        raise ValueError('batch comparison requires full 2D/3D model_h results with native units')
    parameters = metadata['parameters']
    df_mode = parameters['df_mode'] if dimension == 3 else parameters['run_settings']['df_mode']
    if metadata['df_metadata']['mode'] != df_mode:
        raise ValueError('result D-F mode disagrees with prepared parameters')
    return metadata


def _energy_gates(field):
    from sjtu_tpmshx.postprocess.conservation import compute_phase2a
    metadata = field.metadata
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
    certificate = compute_phase2a({**metadata['diagnostics'],
        '_audit_fB': metadata['parameters']['fluid_B_cfg']})
    return [list(gate) for gate in certificate['gates']]


def _check_baseline_case(reference, case, flow_a, flow_b):
    """Pair like-for-like inputs, allowing candidate inlet speed to change."""
    metadata = _full_result_metadata(reference)
    if metadata['dimension'] != case.grid['dimension']:
        raise ValueError('baseline and candidate dimensions differ')
    if metadata['design_mode'] != 'uniform':
        raise ValueError('baseline must retain the original uniform design')
    parameters = metadata['parameters']
    if case.grid['dimension'] == 2:
        from sjtu_tpmshx.domain.portable_data import mutable_data
        previous, current = (mutable_data(values['run_settings'])
                             for values in (parameters, case.parameters))
        for settings in (previous, current):
            for side in ('A', 'B'):
                settings['fluid_' + side].pop('u_mps')
        if previous != current or parameters['_environment'] != case.parameters['_environment']:
            raise ValueError('baseline and candidate fixed 2D inputs differ')
        fixed_keys = ()
    else:
        fixed_keys = ('L', 'H', 'Lz', 'tpms_type', 'k_s', 'delta_levelset',
                'fluid_type_A', 'fluid_type_B', 'T_inA', 'T_inB', 'P_inA', 'P_inB',
                'fluid_A_cfg', 'fluid_B_cfg', 'df_mode', 'sco2_nu',
                'variable_rho_cp', 'envelope_mode', '_environment', 'roughness_resolved')
    for key in fixed_keys:
        if parameters[key] != case.parameters[key]:
            raise ValueError(f'baseline and candidate differ in fixed input {key}')
    for key in ('max_iter_simple', 'max_outer_ltne', 'outer_tol_K', 'convergence_mode',
                'mom_tol', 'mass_local_tol', 'mass_global_tol'):
        if parameters.get(key) != case.parameters.get(key):
            raise ValueError(f'baseline and candidate solver setting {key} differs')
    if reference.model_refs != case.model_refs:
        raise ValueError('baseline and candidate model resources differ')
    for axis in 'xyz'[:case.grid['dimension']]:
        if not np.array_equal(reference.grid['d' + axis], case.grid['d' + axis]):
            raise ValueError('baseline and candidate evaluation grids differ')
    for name, parameter in (('L_field_m', 'L_cell_m'), ('t_field_m', 't_wall_m')):
        if not np.all(metadata['design_fields'][name] == case.parameters[parameter]):
            raise ValueError(f'baseline {name} differs from original uniform geometry')
    for side, target in (('A', flow_a), ('B', flow_b)):
        prescribed = parameters['u_' + side] * _total_inlet_mass_capacity(
            metadata['design_fields'], parameters, reference.grid, side)
        # This checks serialized input arithmetic, not measured flow accuracy.
        if not np.isclose(prescribed, target, rtol=1e-12, atol=0.):
            raise ValueError(f'baseline and candidate prescribed mass flow {side} differs')
    failed = [label for label, passed in _energy_gates(reference) if not passed]
    if failed:
        raise ValueError('Baseline energy certificate failed: ' + '; '.join(failed))


def evaluate_condition_batch(
    conditions: Sequence[ConditionInput], *, output_dir: str | Path,
    baseline: Sequence[ConditionResult] | None = None,
    control: RunControl = RunControl(),
) -> dict:
    """Run one air-A/water-B design's conditions serially, without penalties.

    Each input is ``(condition_id, config, mass_flow_A_kg_s, mass_flow_B_kg_s)``.
    Use the same design and fixed condition list for every comparison. The
    caller selects the model and its extrapolation policy. ``completed`` records
    native convergence, each dimension's existing energy certificate and
    available objective metrics, not experimental accuracy. Total input mass
    flows retain kg/s; 2D native metrics retain their per-unit-depth units.

    A new output directory is required. Every requested member appears in
    ``batch.json``, including failures and conditions not run after cancellation.
    Native results and metrics are saved before rejecting unconverged results.
    Ordinary condition failures do not discard later conditions; cancellation
    persists the current record and propagates ``CancelledError``. Only a fully
    completed batch with a supplied baseline can produce aggregate objectives.
    The return value adds in-memory ``results`` to the JSON record.
    """
    from sjtu_tpmshx.io.case_io import save_case
    from sjtu_tpmshx.io.result_io import save_result
    from sjtu_tpmshx.io.metrics_io import save_metrics
    from sjtu_tpmshx.io.text_file import write_text
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.postprocess.api import evaluate

    inputs = tuple(conditions)
    ids = tuple(row[0] for row in inputs)
    if (not ids or any(not isinstance(item, str) or not item for item in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('conditions require unique, nonempty condition IDs')
    for condition_id, config, flow_a, flow_b in inputs:
        if not isinstance(config, ComputeConfig):
            raise TypeError(f'condition {condition_id}: config must be ComputeConfig')
        if config.fluid_A.type != 'air' or config.fluid_B.type != 'water':
            raise ValueError('condition batch requires air-A/water-B inputs')
        if not all(isfinite(value) and value > 0 for value in (flow_a, flow_b)):
            raise ValueError(f'condition {condition_id}: mass flows must be finite and positive')
    frozen_keys = ('geometry', 'zones', 'bc_A', 'bc_B', 'flags', 'solver', 'df_mode',
                   'sco2_nu', 'envelope_mode', 'extrap')
    first = asdict(inputs[0][1])
    for condition_id, config, _, _ in inputs[1:]:
        current = asdict(config)
        if any(current[key] != first[key] for key in frozen_keys):
            raise ValueError(f'condition {condition_id}: design and evaluation settings must be fixed')
    if baseline is not None:
        _condition_metrics(baseline, ids, 'baseline')
    references = {} if baseline is None else {condition_id: field for condition_id, field, _ in baseline}
    reference_metrics = {} if baseline is None else {
        condition_id: dict(case_id=field.case_id, result_id=field.result_id,
            metrics_id=performance.result_id,
            metrics={name: asdict(performance.metrics[name]) for name in _METRICS})
        for condition_id, field, performance in baseline}

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    batch_id = str(uuid4())
    history = [dict(condition_id=condition_id, directory=f'condition_{index:03d}',
                    case_id=f'{batch_id}:{condition_id}', status='not_run', stage=None,
                    reason=None, case_file=None, result_file=None, metrics_file=None, energy_gates=None,
                    baseline=reference_metrics.get(condition_id),
                    mass_flow_A_kg_s=flow_a, mass_flow_B_kg_s=flow_b)
               for index, (condition_id, _, flow_a, flow_b) in enumerate(inputs, 1)]
    record = dict(batch_id=batch_id, status='running', reason=None,
                  conditions=history, objectives=None)
    results = []

    def publish():
        write_text(root / 'batch.json',
                   json.dumps(record, ensure_ascii=False, allow_nan=False, indent=2) + '\n')

    publish()
    try:
        for index, ((condition_id, config, flow_a, flow_b), row) in enumerate(zip(inputs, history)):
            control.check_cancelled()
            directory = root / row['directory']
            row.update(status='running', stage='input')
            publish()
            try:
                directory.mkdir()
                write_text(directory / 'input.json', json.dumps(asdict(config),
                    ensure_ascii=False, allow_nan=False, indent=2) + '\n')
                row['stage'] = 'prepare'
                case = prepare_fixed_mass_flow_case(config, mass_flow_A_kg_s=flow_a,
                    mass_flow_B_kg_s=flow_b, case_id=row['case_id'])
                row['stage'] = 'save_case'
                save_case(case, directory / 'case.yaml')
                row['case_file'] = f"{row['directory']}/case.yaml"
                publish()
                if baseline is not None:
                    row['stage'] = 'comparison'
                    _check_baseline_case(references[condition_id], case, flow_a, flow_b)
                control.check_cancelled()
                row['stage'] = 'solve'
                progress = (None if control.progress is None else
                            lambda percent, i=index: control.report_progress(
                                int(100 * (i + percent / 100) / len(inputs))))
                field = run_case(case, replace(control, progress=progress))
                row['stage'] = 'save_result'
                save_result(field, directory / 'result.h5')
                row['result_file'] = f"{row['directory']}/result.h5"
                publish()
                if field.case_id != case.case_id:
                    raise ValueError('returned result does not belong to the prepared case')
                metadata = _full_result_metadata(field)
                dimension = case.grid['dimension']
                result_mode = (metadata['parameters']['df_mode'] if dimension == 3
                               else metadata['parameters']['run_settings']['df_mode'])
                if (field.model_refs != case.model_refs or metadata['dimension'] != dimension
                        or result_mode != config.df_mode
                        or metadata['design_mode'] != case.metadata['design_mode']):
                    raise ValueError('returned result changes prepared model or design mode')
                for name, values in case.design_fields.items():
                    if not np.array_equal(metadata['design_fields'][name], values):
                        raise ValueError(f'returned result changes prepared design field {name}')
                control.check_cancelled()
                row['stage'] = 'postprocess'
                performance = evaluate(field)
                row['stage'] = 'save_metrics'
                save_metrics(performance, directory / 'metrics.json')
                row['metrics_file'] = f"{row['directory']}/metrics.json"
                publish()
                result = (condition_id, field, performance)
                results.append(result)
                row['stage'] = 'validate'
                _condition_metrics([result], (condition_id,), 'candidate')
                row['stage'] = 'energy'
                row['energy_gates'] = _energy_gates(field)
                failed_gates = [label for label, passed in row['energy_gates'] if not passed]
                if failed_gates:
                    raise ValueError('Energy certificate failed: ' + '; '.join(failed_gates))
                row.update(status='completed', reason=None)
            except CancelledError as exc:
                row.update(status='cancelled', reason=str(exc))
                raise
            except Exception as exc:
                row.update(status='failed', reason=f'{type(exc).__name__}: {exc}')
            finally:
                publish()
            control.report_progress(int(100 * (index + 1) / len(inputs)))
        control.check_cancelled()
        if any(row['status'] != 'completed' for row in history):
            record.update(status='failed', reason='One or more conditions failed; no aggregate objectives')
        elif baseline is not None:
            try:
                record['objectives'] = aggregate_multi_condition(ids, baseline, results)
            except ValueError as exc:
                record.update(status='failed', reason=f'Aggregate rejected: {exc}')
            else:
                record['status'] = 'completed'
        else:
            record['status'] = 'completed'
    except CancelledError as exc:
        record.update(status='cancelled', reason=str(exc), objectives=None)
        raise
    except Exception as exc:
        record.update(status='failed', reason=f'{type(exc).__name__}: {exc}', objectives=None)
        raise
    finally:
        publish()
    return {**record, 'results': results}


def _condition_metrics(rows: Sequence[ConditionResult], condition_ids: tuple[str, ...],
                       label: str) -> dict[str, PerformanceResult]:
    results = {}
    for condition_id, field, performance in rows:
        prefix = f'{label} condition {condition_id}'
        if condition_id in results:
            raise ValueError(f'{prefix}: duplicate condition')
        if performance.source_result_id != field.result_id:
            raise ValueError(f'{prefix}: performance source does not match field result')
        if (field.run_status.get('execution') != 'completed'
                or field.run_status.get('converged') is not True):
            raise ValueError(f'{prefix}: run must be completed and converged')
        for name in _METRICS:
            metric = performance.metrics.get(name)
            if metric is None or metric.status != 'available':
                reason = 'missing metric' if metric is None else metric.reason
                raise ValueError(f'{prefix}: {name} unavailable: {reason}')
            if metric.value is None or not isfinite(metric.value):
                raise ValueError(f'{prefix}: {name} must be finite')
        results[condition_id] = performance
    if set(results) != set(condition_ids):
        missing = sorted(set(condition_ids) - set(results))
        extra = sorted(set(results) - set(condition_ids))
        raise ValueError(f'{label}: condition membership mismatch; missing={missing}, extra={extra}')
    return results


def aggregate_multi_condition(
    condition_ids: Sequence[str],
    baseline: Sequence[ConditionResult],
    candidate: Sequence[ConditionResult],
) -> dict[str, float]:
    """Compare one design with the fixed uniform baseline at every condition.

    Each row pairs an explicit operating-condition ID with the native field
    result and its evaluated metrics. IDs are independent of design case IDs.
    All requested conditions must occur exactly once on each side. Invalid or
    unavailable runs raise ``ValueError`` instead of contributing a penalty or
    changing the averaging denominator. The caller owns physical applicability
    and the identity of the fixed baseline design.

    The fixed heat metric is ``-Q_B``: useful B-side water heat uptake for the
    Shanghai air-A/water-B benchmark. Native ``Q_B`` is signed heat loss, so it
    is negated, never made absolute; the generic A-side ``Q`` is not consumed.
    Heat gain is maximized; the independent pressure ratio is minimized. Metric
    definitions and units must match the baseline for each condition. No Pa
    floor, pressure cap, absolute gain, or objective scalarization is applied.
    """
    ids = tuple(condition_ids)
    if not ids or any(not isinstance(item, str) or not item for item in ids):
        raise ValueError('condition_ids must contain nonempty string IDs')
    if len(set(ids)) != len(ids):
        raise ValueError('condition_ids must not contain duplicates')
    reference = _condition_metrics(baseline, ids, 'baseline')
    design = _condition_metrics(candidate, ids, 'candidate')
    heat_gains, pressure_ratios = [], []
    for condition_id in ids:
        ratios = {}
        for name in _METRICS:
            base = reference[condition_id].metrics[name]
            current = design[condition_id].metrics[name]
            base_value = -base.value if name == 'Q_B' else base.value
            current_value = -current.value if name == 'Q_B' else current.value
            if base_value <= 0:
                denominator = '-Q_B' if name == 'Q_B' else name
                raise ValueError(f'baseline condition {condition_id}: {denominator} must be positive')
            if ((base.spec.name, base.spec.unit, base.spec.definition_version)
                    != (current.spec.name, current.spec.unit, current.spec.definition_version)):
                raise ValueError(f'condition {condition_id}: {name} metric definitions differ')
            ratio = current_value / base_value
            if not isfinite(ratio):
                raise ValueError(f'condition {condition_id}: {name} ratio is not finite')
            ratios[name] = ratio
        heat_gains.append(ratios['Q_B'] - 1.0)
        pressure_ratios.append(0.5 * ratios['dP_A'] + 0.5 * ratios['dP_B'])
    scores = {
        'heat_gain_percent': 100.0 * fsum(value / len(ids) for value in heat_gains),
        'pressure_ratio': fsum(value / len(ids) for value in pressure_ratios),
    }
    if not all(isfinite(value) for value in scores.values()):
        raise ValueError('aggregate objectives must be finite')
    return scores
