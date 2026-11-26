"""Inputs, recovery, and archived designs for a continuous-field study."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import json
from pathlib import Path

import numpy as np

from sjtu_tpmshx.data_types.compute_config import ComputeConfig, ZoneInputConfig
from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.run_control.paused_run import PausedRun


def positive_number(value, label):
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(f'{label}: enter a finite positive number') from None
    if not np.isfinite(result) or result <= 0:
        raise ValueError(f'{label}: enter a finite positive number')
    return result


def validate_condition_table(payload):
    keys = {'condition_id'} | {f'{name}_{side}_{unit}' for side in 'AB'
        for name, unit in (('T_in', 'K'), ('P_in', 'Pa'), ('mass_flow', 'kg_s'))}
    if not isinstance(payload, dict) or set(payload) not in ({'conditions'}, {'conditions', 'mass_requirements'}):
        raise ValueError('Condition JSON needs conditions and optional mass_requirements')
    rows = payload['conditions']
    if not isinstance(rows, list) or not rows:
        raise ValueError('Condition JSON requires a nonempty conditions list')
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != keys:
            raise ValueError('Each condition requires condition_id and A/B T_in_K, P_in_Pa, mass_flow_kg_s')
        name = row['condition_id']
        if not isinstance(name, str) or not name.strip() or name in ids:
            raise ValueError('Condition IDs must be unique nonempty strings')
        ids.add(name)
        for key in keys - {'condition_id'}:
            if type(row[key]) not in (int, float):
                raise ValueError(f'{name}: {key} must be a positive number')
            positive_number(row[key], f'{name}: {key}')
    if 'mass_requirements' in payload:
        from sjtu_tpmshx.applications.optimization.mass_design import validate_mass_requirements
        validate_mass_requirements(payload['mass_requirements'], ids)
    return deepcopy(rows)


def condition_inputs(cfg, rows):
    """Build the condition inputs from the case and its mass flow rates."""
    if rows:
        return [(row['condition_id'], replace(cfg, **{
            f'fluid_{side}': replace(getattr(cfg, f'fluid_{side}'),
                T_in_K=row[f'T_in_{side}_K'], P_in_Pa=row[f'P_in_{side}_Pa'], mass_flow_kg_s=None)
            for side in 'AB'}), row['mass_flow_A_kg_s'], row['mass_flow_B_kg_s']) for row in rows]
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.preprocess.inlet_flow import total_inlet_mass_capacity
    case = prepare_case(cfg, case_id='gui-current-condition')
    from sjtu_tpmshx.data_types.portable_data import mutable_data
    cfg = ComputeConfig.from_dict(mutable_data(case.config_snapshot))
    flows = [total_inlet_mass_capacity(case.design_fields, case.parameters, case.grid, side)
             * getattr(cfg, f'fluid_{side}').u_mps for side in 'AB']
    return [('current', cfg, *flows)]


@dataclass
class OptimizationInput:
    """The configuration and search settings at launch."""

    config: ComputeConfig
    rows: list[dict] | None
    field_spec: dict
    method: str
    n_init: int
    n_iter: int
    q_batch: int
    seed: int
    mass_requirements: dict | None = None
    resume_file: Path | None = None

    def validate(self):
        if self.rows is None:
            self.config.validate()
        else:
            validate_condition_table({'conditions': self.rows})
        if self.mass_requirements is not None:
            from .mass_design import validate_mass_requirements

            self.mass_requirements = validate_mass_requirements(
                self.mass_requirements, [row['condition_id'] for row in self.rows])
            if self.method not in ('qlognei', 'sobol'):
                raise ValueError('芯体减重请选择 qLogNEI 或 Sobol；导入的性能要求始终有效')
        elif self.method == 'qlognei':
            raise ValueError('请先导入含 mass_requirements 的工况 JSON，给出密度和每个工况的性能限值')
        return self

    @classmethod
    def from_checkpoint(cls, filename):
        from .multi_condition import saved_condition_config

        checkpoint = Path(filename)
        frozen = json.loads(checkpoint.with_name('optimization-input.json').read_text(encoding='utf-8'))
        rows = frozen['conditions']
        return cls(saved_condition_config(rows[0]), rows, frozen['field_spec'], frozen['method'],
                   frozen['n_init'], frozen['n_iter'], frozen['q_batch'], frozen['seed'],
                   frozen.get('mass_requirements'), checkpoint)

    def run(self, output_dir, control, on_update, pause_check):
        from .multi_condition_optimizer import (
            resume_multi_condition_optimization, run_multi_condition_optimization,
        )

        try:
            control.check_cancelled()
            if self.resume_file is not None:
                return resume_multi_condition_optimization(
                    self.resume_file, output_dir=output_dir, control=control,
                    on_update=on_update, pause_check=pause_check)
            conditions = condition_inputs(self.config, self.rows)
            control.check_cancelled()
            return run_multi_condition_optimization(
                conditions, output_dir=output_dir, method=self.method, n_init=self.n_init,
                n_iter=self.n_iter, q_batch=self.q_batch, seed=self.seed, field_spec=self.field_spec,
                mass_requirements=self.mass_requirements, control=control,
                on_update=on_update, pause_check=pause_check)
        except (CancelledError, PausedRun) as exc:
            if getattr(exc, '__notes__', None):
                raise
            checkpoint = Path(output_dir) / 'optimization.json'
            if not checkpoint.exists():
                if isinstance(exc, CancelledError):
                    return None
                raise ValueError('Paused search has no saved checkpoint') from exc
            with checkpoint.open(encoding='utf-8') as source:
                report = json.load(source)
            expected = 'paused' if isinstance(exc, PausedRun) else 'cancelled'
            if not isinstance(report, dict) or report.get('status') != expected:
                raise ValueError(f'Search checkpoint does not record {expected} status') from exc
            return report


def archived_design(report, index, output_dir, current):
    """Read the selected input and verify its geometry, field, and mass flows."""
    from sjtu_tpmshx.data_types.portable_data import mutable_data
    from sjtu_tpmshx.file_io.case_io import load_case
    from sjtu_tpmshx.preprocess.inlet_flow import total_inlet_mass_capacity

    row = report['conditions'][0]
    source = ComputeConfig.from_dict(row['config'])
    geometry = current.geometry
    if not source.is_3d and not current.is_3d:
        # Only the study uses this depth to convert a total mass flow rate.
        geometry = replace(geometry, Lz_m=source.geometry.Lz_m)
    fixed = ('solver', 'bc_A', 'bc_B', 'flags', 'df_mode', 'sco2_nu', 'extrap', 'envelope_mode')
    if source.geometry != geometry or any(getattr(source, key) != getattr(current, key) for key in fixed):
        raise ValueError('当前算例与优化来源不同，请先恢复原几何、端口和求解设置')
    if (source.fluid_A.type, source.fluid_B.type) != (current.fluid_A.type, current.fluid_B.type):
        raise ValueError('当前流体类型与优化来源不同')
    if index not in report['pareto_indices'] or report['history'][index]['status'] != 'completed':
        raise ValueError('所选连续场不属于已完成的 Pareto 方案')
    candidate = report['history'][index]
    spec = dict(deepcopy(report['field_spec']), x_decision=deepcopy(candidate['x_decision']))
    zones = ZoneInputConfig(enabled=True, axis='continuous', config=spec).validate()
    if output_dir is None:
        raise ValueError('缺少原始优化归档目录')
    directory = Path(output_dir) / candidate['directory']
    with (directory / 'batch.json').open(encoding='utf-8') as saved:
        batch = json.load(saved)
    archived = batch['conditions'][0]
    if (batch['status'] != 'completed' or archived['status'] != 'completed'
            or archived['condition_id'] != row['condition_id']
            or any(archived[f'mass_flow_{side}_kg_s'] != row[f'mass_flow_{side}_kg_s']
                   for side in 'AB')):
        raise ValueError('归档工况或总质量流量与优化 study 不一致')
    case = load_case(directory / archived['case_file'])
    config = ComputeConfig.from_dict(mutable_data(case.config_snapshot)).validate()
    expected = replace(source, zones=zones, **{
        f'fluid_{side}': replace(getattr(source, f'fluid_{side}'),
                                u_mps=getattr(config, f'fluid_{side}').u_mps, mass_flow_kg_s=None)
        for side in 'AB'})
    if case.case_id != archived['case_id'] or config != expected:
        raise ValueError('归档算例的完整连续场或固定设置与优化 study 不一致')
    for side in 'AB':
        prescribed = getattr(config, f'fluid_{side}').u_mps * total_inlet_mass_capacity(
            case.design_fields, case.parameters, case.grid, side)
        if not np.isclose(prescribed, row[f'mass_flow_{side}_kg_s'], rtol=1e-12, atol=0.):
            raise ValueError(f'归档入口速度未保持工况 {side} 总质量流量')
    return config


def baseline_failure_reasons(baseline, output_dir):
    """Read the batch reason and each recorded condition failure."""
    reasons = [baseline['reason']] if baseline['reason'] else []
    if output_dir is not None:
        path = Path(output_dir) / baseline['directory'] / 'batch.json'
        if path.is_file():
            with path.open(encoding='utf-8') as source:
                batch = json.load(source)
            for row in batch['conditions']:
                if row['reason']:
                    reasons.append(f'{row["condition_id"]}：{row["reason"]}')
    return reasons
