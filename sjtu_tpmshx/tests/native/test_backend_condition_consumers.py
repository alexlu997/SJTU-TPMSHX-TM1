"""Both public backends complete real batches and a bounded design search."""
from dataclasses import replace
import json

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import FluidConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.io.metrics_io import load_metrics
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.optimization.multi_condition import evaluate_condition_batch
from sjtu_tpmshx.optimization.multi_condition_optimizer import run_multi_condition_optimization
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.preprocess.inlet_flow import total_inlet_mass_capacity
from sjtu_tpmshx.tests.native import test_cpp_full_3d as native_3d
from sjtu_tpmshx.tests.native.test_native_execution import _config
from sjtu_tpmshx.tests.gui_io_support import win as win

native_path = native_3d.native_path


@pytest.mark.parametrize('backend', ['python', 'cpp'])
def test_gui_co2_mass_input_save_reopen_geometry_and_export(win, native_path, tmp_path, monkeypatch, backend):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from sjtu_tpmshx.preprocess.api import prepare_inlet_mass_capacities
    from sjtu_tpmshx.tests.test_co2_model import co2_config
    from sjtu_tpmshx.tests.integration_tm1.test_public_gui import apply_config
    from sjtu_tpmshx.tests.gui_worker_support import _wait_for
    from sjtu_tpmshx.ui.window_config import config_from_window

    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: errors.append(args[1:]))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: errors.append(args[1:]))
    def accept_grid(dialog):
        assert 'Grid preflight' in dialog.text(), dialog.text()
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, 'exec', accept_grid)
    config = co2_config(3)
    target = prepare_inlet_mass_capacities(config)['A'] * config.fluid_A.u_mps
    config.fluid_A.mass_flow_kg_s = target
    apply_config(win, config)
    native = native_3d.control(native_path)
    win.run_control = replace(win.run_control, native_library=native.native_library,
                              native_table_directory=native.native_table_directory)
    win.combo_solver_backend.setCurrentIndex(win.combo_solver_backend.findData(backend))
    assert win.compute.backend == backend
    saved = tmp_path/'co2-config.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(saved), 'JSON'))
    win.save_config()
    assert saved.is_file(), errors
    win.combo_fluidA.setCurrentIndex(2)
    win.combo_inlet_modeA.setCurrentIndex(0)
    assert win._load_config_path(saved), errors
    reopened = config_from_window(win, strict=True)
    assert reopened.fluid_A.type == 'co2' and reopened.fluid_A.mass_flow_kg_s == target
    finished = []
    win.compute.finished.connect(finished.append)
    try:
        for factor in (1., 2.):
            depth = config.geometry.Lz_m * factor
            win.le_Lz.setText(str(depth))
            for side in 'AB':
                for end in ('in', 'out'):
                    getattr(win, f'le_pipe{side}_{end}_z_ctr').setText(str(depth/2))
                    getattr(win, f'le_pipe{side}_{end}_z_w').setText(str(depth))
            win.run_calculation()
            _wait_for(win.compute.is_idle, timeout=180)
            assert len(finished) == int(factor), errors
            result = finished[-1]
            assert result.converged and result.metadata['backend_id'] == backend
            assert result.metadata['co2']['pressure_multiplier'] == 2.5
            assert result.metadata['co2']['nu_multiplier'] == 1.28
            inlet = result.metadata['inlet_inputs']['A']
            assert inlet['mass_flow_kg_s'] == target
            assert inlet['u_mps'] == pytest.approx(config.fluid_A.u_mps/factor, rel=1e-12)
            assert float(win.le_uA.text()) == pytest.approx(inlet['u_mps'], rel=1e-10)
            assert abs(result.residuals['mass_imbalance_rel_A']) <= 1e-6
            output = tmp_path/f'co2-{int(factor)}.csv'
            monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(output), 'CSV'))
            win._export_results()
            assert output.is_file() and not errors
    finally:
        win.compute.finished.disconnect(finished.append)
        if not win.compute.is_idle():
            win.compute.cancel()
            _wait_for(win.compute.is_idle, timeout=30)


@pytest.mark.parametrize('dimension', [2, 3])
def test_selected_backend_completes_batch_and_optimization(native_path, tmp_path, dimension):
    config = replace(_config(dimension, True),
        fluid_B=FluidConfig(type='water', u_mps=.2, T_in_K=300., P_in_Pa=2e6))
    config = replace(config, geometry=replace(config.geometry, Lz_m=.03))
    conditions = []
    for index in range(2):
        cfg = replace(config, fluid_A=replace(config.fluid_A, T_in_K=500.+10*index))
        case = prepare_case(cfg, case_id=f'input-{index}')
        flows = [total_inlet_mass_capacity(case.design_fields, case.parameters, case.grid, side)
                 * getattr(cfg, 'fluid_' + side).u_mps for side in 'AB']
        conditions.append((f'condition-{index}', cfg, *flows))

    results = {}
    for backend in ('python', 'cpp'):
        control = RunControl() if backend == 'python' else native_3d.control(native_path)
        directory = tmp_path / backend
        batch = evaluate_condition_batch(conditions, output_dir=directory / 'batch', control=control)
        assert batch['status'] == 'completed', batch['conditions']
        assert batch['backend'] == backend and len(batch['results']) == 2
        results[backend] = batch['results']
        for row, (_, field, metrics) in zip(batch['conditions'], batch['results']):
            restored = load_result(directory / 'batch' / row['result_file'])
            assert restored.backend_id == field.backend_id == backend
            assert restored.run_status['converged']
            assert row['energy_gates'] and all(passed for _, passed in row['energy_gates'])
            assert load_metrics(directory / 'batch' / row['metrics_file']) == metrics
            assert evaluate(restored).metrics == metrics.metrics
            for name in ('Ta', 'Tb', 'Ts'):
                np.testing.assert_array_equal(restored.fields[name], field.fields[name])

        search = run_multi_condition_optimization(conditions, output_dir=directory / 'search',
            method='sobol', n_init=1, n_iter=1, seed=7, control=control,
            field_spec={'L_bounds': [6.8, 7.2], 't_bounds': [.55, .6]})
        assert search['status'] == 'completed', search
        assert search['backend'] == backend
        assert search['n_evaluated'] == search['n_usable'] == 2
        assert search['pareto_indices']
        for entry in (search['baseline'], *search['history']):
            batch_dir = directory / 'search' / entry['directory']
            record = json.loads((batch_dir / 'batch.json').read_text())
            assert record['backend'] == backend and record['status'] == 'completed'
            for row in record['conditions']:
                assert all(passed for _, passed in row['energy_gates'])
                field = load_result(batch_dir / row['result_file'])
                assert field.backend_id == backend and field.run_status['converged']

    for python, cpp in zip(results['python'], results['cpp']):
        for name in ('Ta', 'Tb', 'Ts'):
            np.testing.assert_allclose(cpp[1].fields[name], python[1].fields[name], rtol=0., atol=.01)
        for name in ('Q_B', 'dP_A', 'dP_B'):
            actual, expected = cpp[2].metrics[name], python[2].metrics[name]
            assert actual.status == expected.status == 'available'
            assert actual.spec.unit == expected.spec.unit
            np.testing.assert_allclose(actual.value, expected.value, rtol=.001, atol=0.)
