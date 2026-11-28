"""Read saved HDF5 result summaries, single fields, and full field sets for the GUI."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from tm1.data_types.compute_result import ComputeResult
from tm1.data_types.metric_spec import METRIC_KINDS, full_metric_version
from tm1.data_types.portable_data import mutable_data
from tm1.file_io.metrics_io import load_metrics
from tm1.file_io.result_io import (
    load_result,
    load_result_design_field,
    load_result_field,
    load_result_header,
)
from tm1.physical_models.zone_units import _legacy_zone_units
from tm1.postprocess.result_display import RESULT_FIELD_SPECS

_SUMMARY_METRICS = ('Q', 'dP_A', 'dP_B', 'T_out_A', 'T_out_B')
_RESIDUAL_METRICS = (
    'Q_A', 'Q_B', 'energy_imbalance_rel',
    'mass_imbalance_rel_A', 'mass_imbalance_rel_B',
    'Q_richardson_A', 'Q_richardson_B',
)
_DIRECT_RESULT_FIELDS = frozenset({
    'Ta', 'Tb', 'Ts',
    'ucA', 'vcA', 'wcA',
    'ucB', 'vcB', 'wcB',
    'h_vA', 'h_vB',
})


def build_saved_compute_result(
    result_file: str | Path,
    *,
    metrics_file: str | Path | None = None,
) -> tuple[str, ComputeResult, tuple[str, ...]]:
    """Build a lightweight ComputeResult from a saved HDF5 header without loading field arrays."""
    path = Path(result_file)
    header = load_result_header(path)
    if header.run_status.get('execution') != 'completed':
        raise ValueError('application display requires a completed result')

    dimension = header.grid['dimension']
    unit = 'W/m' if dimension == 2 else 'W'
    mode = f'{dimension}d'

    if metrics_file is None:
        sibling = path.with_name('metrics.json')
        metrics_path = sibling if sibling.is_file() else None
    else:
        metrics_path = Path(metrics_file)

    performance = None
    if metrics_path is not None:
        performance = load_metrics(metrics_path)
        if performance.source_result_id != header.result_id:
            raise ValueError('performance belongs to another result')
        consumed = _SUMMARY_METRICS + tuple(
            name for name in _RESIDUAL_METRICS if name in performance.metrics
        )
        for name in consumed:
            spec = performance.metrics[name].spec
            if METRIC_KINDS.get(name, name) == 'Q' and spec.unit != unit:
                raise ValueError(f'{name} heat-duty unit disagrees with the result dimension')
            if spec.definition_version != full_metric_version(name):
                raise ValueError(
                    f're-evaluate native results before displaying the current {name} definition'
                )

    parameters = header.metadata['parameters']
    diagnostics = mutable_data(header.metadata['diagnostics'])
    application = mutable_data(header.metadata['application'])

    fields: dict[str, Any] = {}
    available: list[str] = [
        name for name in header.available_fields if name in _DIRECT_RESULT_FIELDS
    ]
    for side in ('A', 'B'):
        if f'P_report_{side}' in header.available_fields:
            available.append(f'P_f{side}')
    if dimension == 2:
        geometry = parameters['static_properties']['geometry']
        zone = _legacy_zone_units(mutable_data(parameters['zone_config']))
        if isinstance(zone, dict):
            from tm1.physical_models.zone_config import Zone, ZoneConfig
            zone['zones'] = [Zone(**item) for item in zone['zones']]
            zone = ZoneConfig(**zone)
        for side in ('A', 'B'):
            if f'uc{side}' in header.available_fields and f'vc{side}' in header.available_fields:
                available.append(f'vmag_{side}')
        fields.update(
            dx_arr=header.grid['dx'],
            dy_arr=header.grid['dy'],
            N_x=len(header.grid['dx']),
            N_y=len(header.grid['dy']),
            L=parameters['L'],
            H=parameters['H'],
            dir_A=parameters['dir_A'],
            dir_B=parameters['dir_B'],
            zone_config=zone,
            za=None,
        )
        residuals = {
            name: diagnostics[name]
            for name in (
                'mass_imbalance_rel_A', 'mass_imbalance_rel_B',
                'Q_A', 'Q_B', 'energy_imbalance_rel',
            )
        }
        residuals.update(
            r_dP_A=float('nan'),
            r_dP_B=float('nan'),
            r_Q=float(bool(diagnostics['Q_richardson_warn'])),
            simple_A=diagnostics['residuals_A'],
            simple_B=diagnostics['residuals_B'],
        )
        zones = application['zones']
    elif dimension == 3:
        geometry = parameters['prepared']['geometry']
        for name in ('vmag_A', 'vmag_B'):
            if name in header.available_fields:
                available.append(name)
        if 'L_field_m' in header.available_design_fields:
            available.append('L_mm')
        if 't_field_m' in header.available_design_fields:
            available.append('t_mm')
        fields.update({axis: header.grid[axis] for axis in ('dx', 'dy', 'dz')})
        fields.update({
            f'ports_{side}': mutable_data(parameters[f'fluid_{side}_cfg'])
            for side in ('A', 'B')
        })
        fields.update(
            Lx=parameters['L'],
            Ly=parameters['H'],
            Lz=parameters['Lz'],
            dir_A=diagnostics['dir_A'],
            dir_B=diagnostics['dir_B'],
        )
        residuals = {
            name: diagnostics.get(name)
            for name in (
                'Q_enthalpy_A', 'Q_enthalpy_B', 'Q_solid_B', 'Q_sA', 'Q_sB', 'Q_interior',
                'energy_imbalance_rel', 'mass_imbalance_rel_A', 'mass_imbalance_rel_B',
            )
        }
        zones = None
    else:
        raise ValueError(f'unsupported result dimension: {dimension}')

    props = application['props']
    props.update(eps_A=geometry['epsilon'], D_h_m=geometry['D_h'], A_0_m2=geometry['A_0'])
    diagnostics['mode'] = mode

    metadata = mutable_data(header.metadata['model_metadata'])
    for key in ('timings_s', 'execution_record', 'recovery', 'runtime_resources', 'applicability_evidence'):
        if key in header.metadata:
            metadata[key] = mutable_data(header.metadata[key])
    if 'inlet_inputs' in parameters:
        metadata['inlet_inputs'] = mutable_data(parameters['inlet_inputs'])
    delta_levelset = (
        parameters['run_settings']['geometry']['delta_levelset']
        if dimension == 2
        else parameters['delta_levelset']
    )
    metadata['tpms'] = str(parameters['tpms_type'])
    metadata['delta_levelset'] = float(delta_levelset)
    metadata['design_mode'] = str(header.metadata['design_mode'])
    metadata.update(
        darcy_forchheimer=mutable_data(header.metadata['df_metadata']),
        quantity_basis=header.metadata['quantity_basis'],
        units={'Q': unit},
        source_result_id=header.result_id,
        case_id=header.case_id,
        backend_id=header.backend_id,
        backend_version=header.backend_version,
        model_refs=[
            dict(
                name=ref.name,
                version=ref.version,
                parameters=mutable_data(ref.parameters),
                applicability=ref.applicability,
            )
            for ref in header.model_refs
        ],
    )

    warnings = list(dict.fromkeys((
        *diagnostics.get('warnings_list', ()),
        *diagnostics.get('envelope_warnings', ()),
        *header.metadata['notices'],
    )))
    if (
        dimension == 2
        and diagnostics.get('Q_richardson_warn')
        and (diagnostics.get('richardson_info') or {}).get('extrapolated')
    ):
        notice = '主网格与 Richardson 细网格换热量差异超过 10%，请做网格精度检查。'
        if notice not in warnings:
            warnings.append(notice)

    values: dict[str, float] = {name: float('nan') for name in _SUMMARY_METRICS}
    if performance is not None:
        for name in _SUMMARY_METRICS:
            metric = performance.metrics[name]
            values[name] = metric.value if metric.status == 'available' else float('nan')
            if metric.status != 'available':
                warnings.append(f'{name}: {metric.status}: {metric.reason}')
        metadata['qualification'] = mutable_data(performance.qualification)
        metadata['metric_status'] = {name: performance.metrics[name].status for name in values}
        metadata['metric_reasons'] = {
            name: performance.metrics[name].reason
            for name in values
            if performance.metrics[name].status != 'available'
        }
        metadata['metric_definitions'] = {
            name: asdict(metric.spec) for name, metric in performance.metrics.items()
        }
        for name in _RESIDUAL_METRICS:
            if name in performance.metrics:
                metric = performance.metrics[name]
                residuals[name] = metric.value if metric.status == 'available' else float('nan')
        if 'Q_A' in residuals and 'Q_B' in residuals and residuals['Q_A'] is not None and residuals['Q_B'] is not None:
            residuals['Q_net'] = residuals['Q_A'] + residuals['Q_B']
        if 'energy_imbalance_rel' in residuals:
            residuals['enthalpy_imbalance_rel'] = residuals['energy_imbalance_rel']

    compute_result = ComputeResult(
        Q_W=values['Q'],
        dP_A_Pa=values['dP_A'],
        dP_B_Pa=values['dP_B'],
        T_out_A_K=values['T_out_A'],
        T_out_B_K=values['T_out_B'],
        converged=bool(header.run_status['converged']),
        fields=fields,
        coeffs=application['coeffs'],
        props=props,
        residuals=residuals,
        zones=zones,
        warnings=warnings,
        extrap_reasons=list(parameters['extrap_reasons']),
        diagnostics=diagnostics,
        metadata=metadata,
    )
    return mode, compute_result, tuple(dict.fromkeys(available))


def read_saved_display_field(result_file: str | Path, field_key: str, *, mode: str) -> np.ndarray:
    """Read one display field from a saved result file through the selected-field reader."""
    if field_key in _DIRECT_RESULT_FIELDS:
        return load_result_field(result_file, field_key).values
    if field_key == 'P_fA':
        return load_result_field(result_file, 'P_report_A').values
    if field_key == 'P_fB':
        return load_result_field(result_file, 'P_report_B').values
    if field_key == 'P_kPa':
        return np.ascontiguousarray(
            load_result_field(result_file, 'P_report_A').values * RESULT_FIELD_SPECS['P_fA'].display_scale
        )
    if field_key == 'P_B_kPa':
        return np.ascontiguousarray(
            load_result_field(result_file, 'P_report_B').values * RESULT_FIELD_SPECS['P_fB'].display_scale
        )
    if field_key in ('vmag', 'vmag_A'):
        if mode == '3d':
            return load_result_field(result_file, 'vmag_A').values
        u = load_result_field(result_file, 'ucA').values
        v = load_result_field(result_file, 'vcA').values
        return np.hypot(u, v)
    if field_key == 'vmag_B':
        if mode == '3d':
            return load_result_field(result_file, 'vmag_B').values
        u = load_result_field(result_file, 'ucB').values
        v = load_result_field(result_file, 'vcB').values
        return np.hypot(u, v)
    if field_key == 'L_mm':
        return load_result_design_field(result_file, 'L_field_m').values * 1e3
    if field_key == 't_mm':
        return load_result_design_field(result_file, 't_field_m').values * 1e3
    raise KeyError(field_key)


def load_all_saved_display_fields(result_file: str | Path, *, mode: str) -> dict[str, Any]:
    """Read every display field from a saved result file through the full load_result path."""
    result = load_result(result_file)
    f = result.fields
    fields: dict[str, Any] = {name: mutable_data(f[name]) for name in ('Ta', 'Tb', 'Ts')}
    fields.update({f'P_f{side}': mutable_data(f.get(f'P_report_{side}')) for side in 'AB'})
    fields.update({name: mutable_data(f.get(name)) for name in ('ucA', 'vcA', 'ucB', 'vcB')})
    if mode == '2d':
        for side in 'AB':
            u, v = fields['uc' + side], fields['vc' + side]
            fields['vmag_' + side] = None if u is None or v is None else np.hypot(u, v)
        fields['za'] = (
            _legacy_zone_units(mutable_data(result.metadata['design_fields']))
            if result.metadata['design_mode'] != 'uniform'
            else None
        )
    elif mode == '3d':
        fields.update({name: mutable_data(f.get(name)) for name in ('wcA', 'wcB', 'vmag_A', 'vmag_B')})
        design_fields = result.metadata['design_fields']
        fields.update(
            L_mm=design_fields['L_field_m'] * 1e3,
            t_mm=design_fields['t_field_m'] * 1e3,
            h_vA_field=mutable_data(f['h_vA']),
            h_vB_field=mutable_data(f['h_vB']),
        )
    else:
        raise ValueError(f'unsupported result mode: {mode}')
    return fields
