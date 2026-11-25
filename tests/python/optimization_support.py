"""Shared multi-condition search inputs, test batches and checkpoint faults.

The test batch evaluator replaces only the condition batch. It writes no
physical result, so search tests cannot use it as physical evidence.
"""
from dataclasses import asdict, replace
import json
from pathlib import Path

import numpy as np

from sjtu_tpmshx.applications.optimization import multi_condition_optimizer as search
from sjtu_tpmshx.data_types.compute_config import ComputeConfig, FluidConfig, GeometryConfig, SolverConfig
from sjtu_tpmshx.file_io import text_file
from sjtu_tpmshx.run_control.cancellation import CancelledError
from sjtu_tpmshx.run_control.module_ports import RunControl


def _conditions(dimension=2):
    return [(f'flow-{i}', ComputeConfig(
        geometry=GeometryConfig(Lz_m=.042), solver=SolverConfig(Nz=3 if dimension == 3 else 1),
        fluid_A=FluidConfig(type='air', u_mps=10., T_in_K=380.+i),
        fluid_B=FluidConfig(type='water', u_mps=.1, T_in_K=300.)), .01+i*.005, .03+i*.01)
        for i in range(2)]


def _manifest(path):
    return json.loads((path / 'optimization.json').read_text())


def _fake_batches(monkeypatch, *, fail_indices=(), baseline_failure=False, cancel_index=None,
                  backend='cpp', workers=1):
    calls, baseline_token = [], {}
    expected_workers = workers

    def evaluate(conditions, *, output_dir, baseline=None, control=RunControl(), workers=1,
                 on_update=None, pause_check=None, allow_nu_re_extrapolation=False,
                 resume_saved=False):
        assert control.backend == backend and workers == expected_workers
        directory = Path(output_dir)
        saved = directory / 'batch.json'
        previous = json.loads(saved.read_text()) if resume_saved and saved.exists() else None
        directory.mkdir(exist_ok=previous is not None)
        index = -1 if baseline is None else int(directory.name.removeprefix('design_'))
        reused = previous is not None and previous['status'] == 'completed'
        if not reused:
            calls.append((conditions, baseline, directory))
        (directory / 'native-evidence.txt').write_text('test evaluator evidence; no physical solve')
        control.report_progress(0)
        # A new numerical phase can restart its local percentage.
        control.report_progress(60)
        control.report_progress(20)
        if on_update is not None:
            on_update([dict(condition_id=name, status='running', stage='reuse' if reused else 'solve', reason=None)
                       for name, *_ in conditions])
        if pause_check is not None and pause_check():
            from sjtu_tpmshx.run_control.paused_run import PausedRun
            (directory / 'batch.json').write_text(json.dumps(dict(status='paused')))
            raise PausedRun(directory / 'batch.json')
        if baseline is None:
            assert all(not cfg.zones.enabled for _, cfg, _, _ in conditions)
            if not baseline_failure:
                from sjtu_tpmshx.preprocess.api import resolve_fixed_mass_flow_config
                baseline_token.update({name: dict(config_snapshot=resolve_fixed_mass_flow_config(
                    cfg, mass_flow_A_kg_s=a, mass_flow_B_kg_s=b).to_dict())
                    for name, cfg, a, b in conditions})
            result = dict(status='failed' if baseline_failure else 'completed',
                          reason='bad reference' if baseline_failure else None,
                          objectives=None, summaries=baseline_token)
        else:
            assert baseline is baseline_token
            if index == cancel_index:
                (directory / 'batch.json').write_text(json.dumps(dict(status='cancelled')))
                raise CancelledError('injected batch cancellation')
            failed = index in fail_indices
            # Deliberately retain negative gain and sub-unity pressure cost.
            result = dict(status='failed' if failed else 'completed',
                          reason='one condition failed' if failed else None,
                          objectives={'heat_gain_percent': -20.+index, 'pressure_ratio': .7+.02*index},
                          summaries={})
        (directory / 'batch.json').write_text(json.dumps({k: v for k, v in result.items() if k != 'summaries'}))
        control.report_progress(100)
        return result

    monkeypatch.setattr(search, 'evaluate_compact_condition_batch', evaluate)
    return calls


def _checkpoint_fault(monkeypatch, module, filename, when, *, persistent=False):
    original = text_file.write_text
    error = OSError('checkpoint write failed')
    attempts = []

    def write(path, text):
        if Path(path).name != filename:
            return original(path, text)
        record = json.loads(text)
        fail = when(record, len(attempts))
        if attempts and any(failed for _, failed in attempts):
            fail = persistent
        attempts.append((record, fail))
        if fail:
            raise error
        return original(path, text)

    monkeypatch.setattr(module, 'write_text', write)
    return error, attempts


def condition(name='one'):
    return dict(condition_id=name, T_in_A_K=400., P_in_A_Pa=130000., mass_flow_A_kg_s=.003,
                T_in_B_K=295., P_in_B_Pa=120000., mass_flow_B_kg_s=.015)


def report(window, *, status='completed'):
    from sjtu_tpmshx.applications.gui.ui import optimize_panel as panel
    from sjtu_tpmshx.physical_models.continuous_field import decision_dim
    cfg = panel._gather_cfg(window)
    # Optimizer reports keep the targets used for each condition.
    cfg = replace(cfg, fluid_A=replace(cfg.fluid_A, mass_flow_kg_s=.003),
                  fluid_B=replace(cfg.fluid_B, mass_flow_kg_s=.015))
    spec = panel._field_spec(window)
    count = decision_dim(spec['n_ctrl_x'], spec['n_ctrl_y'], spec['symmetric_y'],
                         n_ctrl_z=spec.get('n_ctrl_z')) // 2
    # Different z controls ensure flattening or mean backfill cannot pass.
    x = np.r_[np.linspace(5., 7., count), np.linspace(.35, .55, count)].tolist()
    return dict(status=status, reason=None, dimension=3 if cfg.is_3d else 2,
        method='qlognehvi', field_spec=spec,
        conditions=[dict(condition_id='one', config=asdict(cfg), mass_flow_A_kg_s=.003,
                         mass_flow_B_kg_s=.015)],
        history=[dict(index=0, x_decision=x, directory='design_0000', status='completed',
                      objectives=dict(heat_gain_percent=-2., pressure_ratio=.25))],
        pareto_indices=[0], n_evaluated=1, n_usable=1, design_budget=4)
