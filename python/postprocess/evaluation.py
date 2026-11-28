"""Build public reports from the recorded field result and the native query."""
from collections.abc import Mapping
from uuid import uuid4

from tm1.cpp_interface import result_evaluation
from tm1.data_types.metric_spec import MetricSpec
from tm1.data_types.performance_result import MetricValue, PerformanceResult
from tm1.data_types.persistence_validation import validate_result_declarations


def _declaration_dimension(result, query):
    metadata = result.metadata
    dimension = result.grid.get('dimension', metadata.get('dimension'))
    # The C interface represents primary sides, integer dimensions and C strings.
    # Other host values keep their original comparison and exception semantics.
    def label(value):
        return type(value) is str and '\0' not in value and value.isascii()

    pressure = result.pressure_evidence
    if (query == result_evaluation.QUALIFICATION or type(dimension) is not int or dimension not in (2, 3)
            or type(metadata.get('dimension', dimension)) is not int
            or metadata.get('dimension', dimension) not in (2, 3)
            or any(key in row and not label(row[key]) for row, key in
                   ((metadata, 'mode'), (metadata, 'quantity_basis'), (result.boundary_fluxes, 'mass_unit')))
            or any(side not in ('A', 'B') or not isinstance(row, Mapping)
                   or ('unit' in row and not label(row['unit'])) for side, row in pressure.items())
            or any(not label(key) or not isinstance(row, Mapping) or not label(row.get('unit', ''))
                   for key, row in result.field_metadata.items())):
        return validate_result_declarations(result)
    return dimension


def _raw_field_names(fields):
    return tuple(name for name in fields if not name.endswith('_display'))


def _saved_gates(detail):
    for name in ('simple_ok', 'ltne_ok', 'outer_converged', 'fields_finite', 'envelope_ok', 'richardson_ok'):
        if name in detail:
            yield name, detail[name]


def _validated_query(result, query, metric_spec=None):
    try:
        report, rows = result_evaluation.query_result(
            result, query, _declaration_dimension, _raw_field_names, _saved_gates, metric_spec=metric_spec)
        if query == result_evaluation.PHYSICAL_BALANCE:
            return _restore_balance_fields(report, result)
        qualification = _restore_qualification_fields(report['qualification'], result)
        metrics = {name: MetricValue(value, metric_spec or MetricSpec(*spec), status, reason)
                   for name, value, spec, status, reason in rows}
        return PerformanceResult(str(uuid4()), result.result_id, metrics, qualification)
    except Exception:
        # Archived mappings retain their declaration error order on failure.
        validate_result_declarations(result)
        raise


def evaluate(result, metric_spec=None):
    return _validated_query(result, result_evaluation.METRICS, metric_spec)


def evaluate_applicability(result):
    report, _ = result_evaluation.query_result(
        result, result_evaluation.APPLICABILITY, _declaration_dimension, _raw_field_names, _saved_gates)
    return _restore_applicability_fields(report, result.metadata.get('applicability_evidence'))


def evaluate_physical_balance(result):
    return _validated_query(result, result_evaluation.PHYSICAL_BALANCE)


def evaluate_qualification(result, metrics):
    report, _ = result_evaluation.query_result(
        result, result_evaluation.QUALIFICATION, _declaration_dimension, _raw_field_names, _saved_gates, metrics=metrics)
    return _restore_qualification_fields(report, result)


def _restore_applicability_fields(report, evidence):
    if evidence is None or 'checks' not in report:
        return report
    for group, rows in report['checks'].items():
        restored = []
        for source, row in zip(evidence[group], rows, strict=True):
            output = dict(source)
            for name in ('allowed_bounds', 'allowance_fraction', 'status', 'within_limit',
                         'relative_extrapolation', 'reason'):
                if name in row:
                    output[name] = tuple(row[name]) if name == 'allowed_bounds' else row[name]
            restored.append(output)
        report['checks'][group] = restored
    report['missing'] = _restore_missing(report.get('missing', []), evidence)
    report['scope_notes'] = evidence['scope_notes']
    return report


def _restore_missing(rows, evidence):
    output = []
    for row in rows:
        if 'source' in row:
            match = next(value for value in evidence['required']
                if value['group'] == row['group'] and value['side'] == row['side']
                and tuple(value['source']) == tuple(row['source']))
            output.append(dict(match))
        else:
            output.append(row)
    return output


def _restore_qualification_fields(report, result):
    convergence = report['convergence']
    detail = result.metadata.get('diagnostics', {}).get('convergence_detail', {})
    convergence['gates'] = {name: detail[name] for name in convergence['gates']}
    convergence['thermal_state'] = result.boundary_fluxes.get('state')
    convergence['pressure_states'] = {side: result.field_metadata.get('P_report_' + side, {}).get('state')
        for side, value in result.pressure_evidence.items() if value is not None}
    report['execution']['state'] = result.run_status.get('execution')
    if 'balance' in report['physical']:
        _restore_balance_fields(report['physical']['balance'], result)
    application = report['applicability']
    evidence = result.metadata.get('applicability_evidence')
    if 'checks' in application:
        if evidence is None:
            application['missing'], application['scope_notes'] = (), ()
        else:
            inputs = [row for group in ('inlet', 'final') for row in evidence[group]]
            for row, source in zip(application['checks'], inputs, strict=True):
                row['source'] = source['source']
            application['missing'] = _restore_missing(application['missing'], evidence)
            application['scope_notes'] = evidence['scope_notes']
    return report


def _restore_balance_fields(report, result):
    report['physical_dimension'] = result.grid.get('dimension', result.metadata.get('dimension'))
    report['state'] = result.boundary_fluxes.get('state', 'not_recorded')
    report['outer_index'] = result.run_status.get('outer_index')
    return report
