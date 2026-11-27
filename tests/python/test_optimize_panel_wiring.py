"""Native multi-condition GUI handoff, without running an optimization."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import types

import numpy as np
import pytest

from sjtu_tpmshx.applications.gui.ui import optimize_panel as panel
from sjtu_tpmshx.applications.gui.ui.optimize_job import OptimizationJob
from sjtu_tpmshx.applications.gui.ui.theme import resolve_cmap
from sjtu_tpmshx.applications.optimization import optimization_job as job_input
from sjtu_tpmshx.run_control.module_ports import RunControl
from tests.python.gui_io_support import win as win
from tests.python.optimization_support import condition, report


@pytest.fixture
def window(win):
    win.case_files.load_named_preset('Shanghai (3D Gyroid)')
    page = win.optimization
    page.depth.setText(win.le_Lz.text())
    win._continuous_field_spec = None
    page.conditions = None
    page.mass_requirements = None
    for edit in page.controls.values():
        edit.setValue(3)
    win.le_Nx.setText('12'); win.le_Ny.setText('8'); win.le_Nz.setText('6')
    win.combo_grid.setCurrentIndex(win.combo_grid.findData(False))
    for key, value in (('L_min', 4.), ('L_max', 8.), ('t_min', .3), ('t_max', .6)):
        page.bounds[key].setValue(value)
    return win


@pytest.mark.parametrize('save_failure', [False, True])
def test_worker_pause_requires_saved_terminal_status(window, tmp_path, monkeypatch, save_failure):
    page = window.optimization
    from sjtu_tpmshx.applications.optimization import multi_condition_optimizer as search
    from tests.python.optimization_support import _fake_batches
    from tests.python.optimization_support import _checkpoint_fault
    _fake_batches(monkeypatch)
    if save_failure:
        _checkpoint_fault(monkeypatch, search, 'optimization.json',
            lambda record, _: record['status'] == 'paused', persistent=True)
    from tests.python.gui_worker_support import _wait_for

    inputs = job_input.OptimizationInput(page.capture_case(), [condition()],
        page.field_spec(), 'sobol', 1, 0, 1, 0)
    terminal, settled = [], []
    worker = OptimizationJob(inputs, tmp_path / 'paused', RunControl(),
                             lambda report, error: terminal.append((report, error)))
    worker.settled.connect(lambda: settled.append(True))
    worker.request_pause()
    worker.start()
    _wait_for(lambda: bool(settled))
    [(result, error)] = terminal
    if save_failure:
        assert result is None and 'checkpoint write failed' in error
    else:
        assert not error and result['status'] == 'paused'
        assert panel._termination_label(result) == '已暂停'
        assert (tmp_path / 'paused/optimization-input.json').is_file()


@pytest.mark.parametrize('stale_speed', [False, True])
def test_resume_button_uses_saved_input_and_restores_idle_controls(window, tmp_path, monkeypatch, stale_speed):
    page = window.optimization
    from PySide6.QtWidgets import QFileDialog
    from sjtu_tpmshx.applications.optimization import multi_condition_optimizer as search
    from tests.python.gui_worker_support import _wait_for
    from tests.python.optimization_support import _conditions, _fake_batches
    calls = _fake_batches(monkeypatch)
    source = tmp_path / 'source'
    conditions = _conditions()[:1]
    if stale_speed:
        from sjtu_tpmshx.preprocess.api import prepare_inlet_mass_capacities
        name, config, _, _ = conditions[0]
        config.df_mode = 'experimental'
        capacity = prepare_inlet_mass_capacities(config)
        conditions = [(name, config, capacity['A']*10., capacity['B']*.1)]
        config.fluid_A.u_mps = .001
        with pytest.raises(ValueError):
            config.validate()
    expected = search.run_multi_condition_optimization(conditions, output_dir=source,
        method='sobol', n_init=2, n_iter=0, workers=1)
    monkeypatch.setattr(page, 'capture_case', lambda: pytest.fail('recovery read current widgets'))
    monkeypatch.setattr(panel, 'optimization_output_dir', lambda: tmp_path)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(source / 'optimization.json'), ''))
    page.resume_button.click()
    assert not page.resume_button.isEnabled() and page.cancel_button.isEnabled()
    _wait_for(page.is_idle)
    assert page.report['status'] == 'completed', page.status.text()
    assert page.report['field_spec'] == expected['field_spec']
    assert len(calls) == 3
    assert page.resume_button.isEnabled() and not page.pause_button.isEnabled()
    assert not page.cancel_button.isEnabled() and window._cpu_card.isEnabled()
    assert page.last_output_dir != source


def archive_candidate(window, study, output_dir):
    page = window.optimization
    from sjtu_tpmshx.data_types.compute_config import ComputeConfig, ZoneInputConfig
    from sjtu_tpmshx.file_io.case_io import save_case
    from sjtu_tpmshx.applications.optimization.multi_condition import prepare_fixed_mass_flow_case
    candidate = study['history'][0]
    row = study['conditions'][0]
    cfg = replace(ComputeConfig.from_dict(row['config']), zones=ZoneInputConfig(
        enabled=True, axis='continuous',
        config={**study['field_spec'], 'x_decision': candidate['x_decision']}))
    case = prepare_fixed_mass_flow_case(cfg, case_id='saved:one',
        mass_flow_A_kg_s=row['mass_flow_A_kg_s'], mass_flow_B_kg_s=row['mass_flow_B_kg_s'])
    directory = output_dir / candidate['directory']
    (directory / 'condition_001').mkdir(parents=True)
    save_case(case, directory / 'condition_001/case.yaml')
    batch = dict(status='completed', conditions=[dict(condition_id=row['condition_id'],
        status='completed', case_id=case.case_id, case_file='condition_001/case.yaml',
        mass_flow_A_kg_s=row['mass_flow_A_kg_s'], mass_flow_B_kg_s=row['mass_flow_B_kg_s'])])
    (directory / 'batch.json').write_text(json.dumps(batch))
    page.last_output_dir = output_dir
    return case, batch


def pick_front(page, point=0):
    from matplotlib.backend_bases import MouseEvent, PickEvent

    canvas = page.pareto_canvas
    front = canvas.figure.axes[0].lines[0]
    mouse = MouseEvent('button_press_event', canvas, 0, 0)
    event = PickEvent('pick_event', canvas, mouse, front, ind=[point])
    canvas.callbacks.process('pick_event', event)


def test_export_button_uses_archived_objectives_after_ui_edits(window, tmp_path, monkeypatch):
    page = window.optimization
    import csv
    from PySide6.QtWidgets import QFileDialog

    study = report(window, status='cancelled')
    page.report = study
    page.show_pareto(study)
    window.le_TinA.setText('450')
    target = tmp_path / 'pareto.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(target), 'CSV (*.csv)'))
    assert page.export_pareto_button.isEnabled()
    page.export_pareto_button.click()
    with target.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert float(rows[0]['pressure_ratio']) == .25
    assert float(rows[0]['heat_gain_percent']) == -2.
    assert rows[0]['run_status'] == 'cancelled'


def test_long_export_path_keeps_pareto_plot_inside_viewport(window, tmp_path, monkeypatch):
    page = window.optimization
    from PySide6.QtCore import QEventLoop, QPoint
    from PySide6.QtWidgets import QApplication, QFileDialog

    page.report = study = report(window)
    page.show_pareto(study)
    window.workbench.switch_tab('pareto')
    window.resize(1300, 900)
    window.show()
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 1000)
    initial_width = window.width()
    viewport = window._canvas_scroll.viewport()
    canvas = page.pareto_canvas
    assert canvas.isVisible()
    origin = canvas.mapTo(viewport, QPoint(0, 0))
    assert origin.x() + canvas.width() <= viewport.width()
    target = tmp_path / ('continuous_field_optimization_' * 4) / 'pareto_data.csv'
    target.parent.mkdir()
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(target), 'CSV (*.csv)'))
    try:
        page.export_pareto_button.click()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 1000)
        assert target.is_file()
        assert str(target) in page.status.text()
        assert canvas.isVisible()
        origin = canvas.mapTo(viewport, QPoint(0, 0))
        assert origin.x() + canvas.width() <= viewport.width()
        assert window.width() == initial_width
    finally:
        window.hide()


@pytest.mark.parametrize('width', [1280, 1442])
def test_optimization_bounds_show_complete_decimal_values(window, width):
    page = window.optimization
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QApplication

    previous_size = window.size()
    previous_page = page.stack.currentIndex()
    previous_tab = window.workbench.active_tab
    window.workbench.switch_tab('pareto')
    page.stack.setCurrentIndex(0)
    window.resize(width, 932)
    window.show()
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 1000)
    try:
        for spin in page.bounds.values():
            edit = spin.lineEdit()
            margins = edit.textMargins()
            available = edit.contentsRect().width() - margins.left() - margins.right() - 4
            assert edit.fontMetrics().horizontalAdvance(spin.text()) <= available, spin.text()
    finally:
        page.stack.setCurrentIndex(previous_page)
        window.workbench.switch_tab(previous_tab)
        window.resize(previous_size)
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 1000)
        window.hide()


@pytest.mark.parametrize('dimension', [0, 1])
def test_control_counts_and_selected_export_keep_frozen_design(window, tmp_path, dimension):
    page = window.optimization
    from sjtu_tpmshx.applications.optimization.export_ntop_csv import export_study_design
    window.combo_dim.setCurrentIndex(dimension)
    for axis, count in zip('xyz', (1, 2, 5)):
        page.controls[axis].setValue(count)
    spec = page.field_spec()
    assert spec['n_ctrl_x'] == 1 and spec['n_ctrl_y'] == 2
    if dimension:
        assert spec['n_ctrl_z'] == 5
    assert ('20' if dimension else '4') + ' 个变量' in page.field_layout.text()
    preset = window.case_files.capture_current_preset('controls')
    window.case_files.validate_preset(preset, complete=True)
    page.controls['x'].setValue(3)
    window.case_files.apply_user_preset(preset, show_notice=False)
    assert [edit.value() for edit in page.controls.values()] == [1, 2, 5]
    study = report(window)
    second = deepcopy(study['history'][0])
    second['index'] = 1
    second['objectives']['pressure_ratio'] = 0.15
    study['history'].append(second)
    study.update(pareto_indices=[0, 1], n_evaluated=2, n_usable=2)
    archive_candidate(window, study, tmp_path / 'archive')
    page.show_pareto(study)
    window.le_L.setText('0.2')
    pick_front(page, 1)
    assert page.selected_index == 0
    assert page.field_canvas.figure.axes[0].images[0].get_extent()[1] == pytest.approx(182.)
    assert page.export_geometry_button.isEnabled()
    frozen = deepcopy(study)
    page.controls['x'].setValue(4)
    summary = export_study_design(page.report, page.selected_index,
                                 tmp_path / 'geometry', (3, 2, 4) if dimension else (3, 2))
    assert study == frozen
    assert summary['L_domain_mm'] == pytest.approx(182.)
    assert summary['geometry_config']['n_ctrl_x'] == 1
    assert summary['source']['design_id'] == 0
    assert summary['decision_vector'] == study['history'][0]['x_decision']
    page.show_pareto(study)
    assert page.selected_index is None
    assert not page.load_button.isEnabled()
    assert not page.export_geometry_button.isEnabled()


@pytest.mark.parametrize('dimension', [0, 1])
def test_complete_case_and_field_dimension_reach_optimizer(window, dimension):
    page = window.optimization
    from sjtu_tpmshx.applications.gui.ui.window_config import config_from_window
    window.combo_dim.setCurrentIndex(dimension)
    depth = .042 if dimension else .063
    window.le_Lz.setText(str(depth))
    if not dimension:
        page.depth.setText(str(depth))
        window.le_Lz.setText('0.051')
    cfg = page.capture_case()
    ordinary = config_from_window(window, strict=True)
    assert cfg.bc_A == ordinary.bc_A and cfg.bc_B == ordinary.bc_B
    assert cfg.solver == ordinary.solver and cfg.df_mode == 'experimental'
    assert cfg.geometry.Lz_m == depth
    assert cfg.is_3d == bool(dimension)
    if not dimension:
        assert ordinary.geometry.Lz_m is None
    spec = page.field_spec()
    assert spec['symmetric_y'] is False and spec['spline_order'] == 2
    assert ('n_ctrl_z' in spec) == bool(dimension)
    assert str(54 if dimension else 18) in page.field_layout.text()


@pytest.mark.parametrize('bad', ['bad', '0', '-1', 'nan'])
def test_2d_total_flow_depth_is_explicit_and_strict(window, bad):
    page = window.optimization
    window.combo_dim.setCurrentIndex(0)
    actual_depth = window.le_Lz.text()
    page.depth.setText(bad)
    assert window.le_Lz.text() == actual_depth
    with pytest.raises(ValueError, match='2D total-flow depth'):
        page.capture_case()


@pytest.mark.parametrize('damage', ['extra', 'missing', 'duplicate', 'bool', 'nonfinite', 'empty'])
def test_import_contract_rejects_ambiguous_or_invalid_operating_inputs(damage):
    payload = {'conditions': [condition()]}
    if damage == 'extra': payload['conditions'][0]['df_mode'] = 'experimental'
    if damage == 'missing': del payload['conditions'][0]['P_in_A_Pa']
    if damage == 'duplicate': payload['conditions'].append(condition())
    if damage == 'bool': payload['conditions'][0]['mass_flow_A_kg_s'] = True
    if damage == 'nonfinite': payload['conditions'][0]['T_in_A_K'] = float('nan')
    if damage == 'empty': payload['conditions'] = []
    with pytest.raises(ValueError):
        job_input.validate_condition_table(payload)


def test_import_changes_only_operating_conditions(window, tmp_path, monkeypatch):
    page = window.optimization
    from PySide6.QtWidgets import QFileDialog
    before = asdict(page.capture_case())
    path = tmp_path / 'conditions.json'
    path.write_text(json.dumps({'conditions': [condition('a'), condition('b')]}))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(path), ''))
    page.import_conditions()
    current = page.capture_case()
    rows = job_input.condition_inputs(current, page.conditions)
    assert [r[0] for r in rows] == ['a', 'b']
    for _, cfg, flow_a, flow_b in rows:
        assert cfg.geometry == current.geometry and cfg.bc_B == current.bc_B
        assert cfg.solver == current.solver and cfg.df_mode == current.df_mode
        assert cfg.fluid_A.T_in_K == 400. and cfg.fluid_B.P_in_Pa == 120000.
        assert (flow_a, flow_b) == (.003, .015)
    assert asdict(page.capture_case()) == before
    path.write_text('{"conditions": []}')
    page.import_conditions()
    assert len(page.conditions) == 2
    page.use_current_condition()
    assert page.conditions is None and '当前工况' in page.condition_summary.text()


@pytest.mark.parametrize('dimension', [0, 1])
def test_current_condition_flow_uses_prepared_fractional_pore_area(window, dimension, monkeypatch):
    page = window.optimization
    from sjtu_tpmshx.preprocess.api import prepare_case
    window.combo_dim.setCurrentIndex(dimension)
    cfg = page.capture_case()
    rows = job_input.condition_inputs(cfg, None)
    case = prepare_case(cfg, case_id='independent-inlet-check')
    if not dimension:
        from tests.python.native.prepared_snapshot import native_prepared_state
        state = native_prepared_state(case, phase=6)
    for side, flow in zip('AB', rows[0][2:]):
        if dimension:
            prepared = case.parameters['prepared']
            axis = prepared['axes'][side]
            eps = np.take(case.design_fields['eps_'+side], -1 if axis['is_reverse'] else 0,
                          axis=axis['stream_real_axis'])
            area = np.asarray(axis['dcross1'])[:, None]*np.asarray(axis['dcross2'])[None, :]
            pore_area = np.sum(eps * prepared['openings'][side]['inlet'] * area)
            rho = prepared['properties'][side]['rho']
        else:
            prefix = f'state.flow.value.{"AB".index(side)}.flow.'
            shape = (len(state[prefix+'dx']), len(state[prefix+'dy']))
            density = state[prefix+'density'].reshape(shape)
            epsilon = state[prefix+'epsilon'].reshape(shape)
            velocity = state[prefix+'v'].reshape(shape[0], shape[1]+1)
            actual = np.sum(density[:, 0]*epsilon[:, 0]/2.*velocity[:, 0]
                            *state[prefix+'dx'])*cfg.geometry.Lz_m
            assert flow == pytest.approx(actual, rel=1e-14)
        if dimension:
            assert flow == pytest.approx(rho*pore_area*getattr(cfg, 'fluid_'+side).u_mps, rel=1e-14)


def test_worker_passes_native_contract_and_reports_cancellation(window, tmp_path, monkeypatch):
    page = window.optimization
    from sjtu_tpmshx.applications.optimization import multi_condition_optimizer as native
    cfg = page.capture_case()
    rows = [condition()]
    conditions = job_input.condition_inputs(cfg, rows)
    from tests.python.gui_worker_support import _wait_for
    host_progress, requested = [], [False]
    host = RunControl(backend='cpp', native_library='/host/solver',
        native_table_directory='/host/tables', progress=host_progress.append,
        cancel_check=lambda: requested[0])
    outputs, progress, updates, settled = [], [], [], []
    inputs = job_input.OptimizationInput(cfg, rows, page.field_spec(), 'sobol', 2, 0, 1, 3)
    worker = OptimizationJob(inputs, tmp_path, host, lambda result, error: outputs.append((result, error)))
    rows[0]['T_in_A_K'] = 500.
    worker.progress.connect(progress.append)
    worker.updated.connect(updates.append)
    worker.settled.connect(lambda: settled.append(True))
    expected = report(window, status='cancelled')
    def run(actual, **kwargs):
        assert actual == conditions and actual is not conditions
        assert kwargs['method'] == 'sobol' and kwargs['field_spec']['n_ctrl_z'] == 3
        assert kwargs['control'].cancel_check() is False
        assert kwargs['control'].backend == 'cpp'
        assert kwargs['control'].native_library == host.native_library
        assert kwargs['control'].native_table_directory == host.native_table_directory
        kwargs['control'].report_progress(17)
        kwargs['on_update']({'report': expected, 'conditions': [], 'elapsed_s': 1., 'eta_s': None})
        (tmp_path/'optimization.json').write_text(json.dumps(expected))
        requested[0] = True
        kwargs['control'].check_cancelled()
    monkeypatch.setattr(native, 'run_multi_condition_optimization', run)
    worker.start()
    _wait_for(lambda: bool(settled))
    assert progress == [17] and outputs == [(expected, '')]
    assert host_progress == [17]
    assert updates[0]['report'] == expected


def test_live_status_and_pareto_keep_run_page_and_cancel_request(window):
    page = window.optimization
    study = report(window, status='running')
    study.update(stage='proposal', iteration=1)
    page._stop_requested = False
    page.stack.setCurrentIndex(1)
    state = dict(report=study, elapsed_s=30., eta_s=90.,
        conditions=[dict(condition_id='hot', status='running', stage='prepare', reason=None)])
    page.show_live_update(state)
    assert page.kpi_gen.text() == '1/4'
    assert '数值合格 1' in page.live_details.text()
    assert 'hot：前处理' in page.live_details.text()
    assert '1.5 min' in page.kpi_eta.text()
    assert page.status.text() == '选择候选'
    assert page.show_pareto(study, running=True) is None
    assert page.stack.currentIndex() == 1
    assert page._pick_id is None
    assert not page.export_geometry_button.isEnabled()
    page._stop_requested = True
    page.show_live_update(state)
    assert '取消请求已收到' in page.status.text()
    terminal = {**study, 'status': 'failed', 'reason': 'save failed'}
    page.show_live_update({**state, 'report': terminal, 'eta_s': None})
    assert page.status.text() == '失败'
    assert 'save failed' in page.live_details.text()


def test_live_status_keeps_active_later_conditions_visible(window):
    page = window.optimization
    study = report(window, status='running')
    study.update(stage='evaluation', iteration=1)
    conditions = [dict(condition_id=f'finished-{i}', status='completed',
                       stage='qualification', reason=None) for i in range(4)]
    conditions += [dict(condition_id='fifth', status='running', stage='solve', reason=None),
                   dict(condition_id='sixth', status='failed', stage='prepare', reason='bad input')]
    page._stop_requested = False
    page.show_live_update(dict(report=study, elapsed_s=30., eta_s=None,
                                        conditions=conditions))
    lines = page.live_details.text().splitlines()
    assert lines[2:4] == ['fifth：原生求解', 'sixth：失败']
    assert '另有 2 个工况' in lines and 'bad input' in lines


@pytest.mark.parametrize('failure', ['cancelled', 'error'])
def test_presearch_stop_preserves_previous_report_and_archive(window, tmp_path, monkeypatch, failure):
    page = window.optimization
    from sjtu_tpmshx.run_control.cancellation import CancelledError
    from tests.python.gui_worker_support import _wait_for
    previous = report(window)
    archive_candidate(window, previous, tmp_path / 'previous')
    page.report = deepcopy(previous)
    page.show_pareto(previous)
    old_directory = page.last_output_dir
    monkeypatch.setattr(panel, 'optimization_output_dir', lambda: tmp_path)
    def stop(*args):
        raise CancelledError('test cancellation') if failure == 'cancelled' else RuntimeError('test error')
    monkeypatch.setattr(job_input, 'condition_inputs', stop)
    page.start()
    _wait_for(page.is_idle)
    assert page.report == previous
    assert page.last_output_dir == old_directory
    pick_front(page)
    page.load_button.click()
    assert window._continuous_field_spec['x_decision'] == previous['history'][0]['x_decision']


@pytest.mark.parametrize('save_failure', [False, True])
def test_proposal_error_restores_pareto_only_after_saved_terminal(window, tmp_path, monkeypatch, save_failure):
    page = window.optimization
    from sjtu_tpmshx.applications.optimization import multi_condition_optimizer as search
    from tests.python.gui_worker_support import _wait_for
    from tests.python.optimization_support import _fake_batches
    from tests.python.optimization_support import _checkpoint_fault
    _fake_batches(monkeypatch)
    monkeypatch.setattr(search, '_bo_versions', lambda: {})
    def fail(*args, **kwargs):
        raise RuntimeError('injected proposal failure')
    monkeypatch.setattr(search, '_propose_bo', fail)
    if save_failure:
        _checkpoint_fault(monkeypatch, search, 'optimization.json',
                          lambda record, _: record['status'] == 'failed', persistent=True)
    page.conditions = [condition()]
    page.method.setCurrentIndex(page.method.findData('qlognehvi'))
    for key, value in dict(n_init=2, n_iter=1, q_batch=1).items():
        page.parameters[key].setValue(value)
    monkeypatch.setattr(panel, 'optimization_output_dir', lambda: tmp_path)
    page.start()
    _wait_for(page.is_idle)
    assert 'injected proposal failure' in page.status.text()
    assert page.report['n_usable'] == 2
    assert page.report['status'] == ('running' if save_failure else 'failed')
    assert page.export_pareto_button.isEnabled() is not save_failure
    assert (page._pick_id is not None) is not save_failure
    assert page.stack.currentIndex() == (0 if save_failure else 2)


@pytest.mark.parametrize('cancel_during_prepare', [False, True])
def test_single_condition_prepares_in_worker_and_can_cancel_before_checkpoint(
        window, tmp_path, monkeypatch, cancel_during_prepare):
    page = window.optimization
    import threading
    from PySide6.QtCore import QThread, QTimer
    from PySide6.QtWidgets import QApplication
    from sjtu_tpmshx.preprocess import api
    from sjtu_tpmshx.applications.optimization import multi_condition_optimizer as native
    from tests.python.gui_worker_support import _wait_for
    entered, release = threading.Event(), threading.Event()
    prepare = api.prepare_case
    cfg = page.capture_case()
    resolved = api.resolve_inlet_flow_config(cfg)
    expected = report(window)
    received, ticks = [], []

    def held_prepare(actual, **kwargs):
        assert QThread.currentThread() != QApplication.instance().thread()
        assert actual == cfg and actual is not cfg
        entered.set()
        assert release.wait(5)
        return prepare(actual, **kwargs)

    def run(conditions, **kwargs):
        assert conditions[0][0] == 'current'
        assert conditions[0][1] == resolved
        np.testing.assert_allclose(conditions[0][2:],
            [cfg.fluid_A.mass_flow_kg_s, cfg.fluid_B.mass_flow_kg_s], rtol=1e-14)
        received.append(conditions)
        return expected

    monkeypatch.setattr(api, 'prepare_case', held_prepare)
    monkeypatch.setattr(native, 'run_multi_condition_optimization', run)
    monkeypatch.setattr(panel, 'optimization_output_dir', lambda: tmp_path)
    page.start()
    QTimer.singleShot(0, lambda: ticks.append(True))
    try:
        _wait_for(lambda: entered.is_set() and bool(ticks))
        assert '1 个工况' in page.status.text()
        assert not page.start_button.isEnabled()
        # Editing the live widgets cannot alter the worker's captured input.
        window.le_TinA.setText('450')
        if cancel_during_prepare:
            page.cancel()
    finally:
        release.set()
    _wait_for(page.is_idle)
    assert page.start_button.isEnabled()
    if cancel_during_prepare:
        assert not received
        assert '尚未启动优化搜索' in page.status.text()
        assert not list(tmp_path.glob('*/optimization.json'))
    else:
        assert len(received) == 1
        assert '完成' in page.status.text()


@pytest.mark.parametrize('status,exit_first', [('completed', False), ('completed', True),
                          ('failed', False), ('cancelled', False), ('error', False)])
def test_thread_terminal_state_retained_until_actual_exit(window, tmp_path, monkeypatch, status, exit_first):
    page = window.optimization
    import threading
    from sjtu_tpmshx.applications.optimization import multi_condition_optimizer as native
    from tests.python.gui_worker_support import _wait_for
    page.conditions = [condition()]
    release = threading.Event()
    original = OptimizationJob.run
    def held(worker):
        if not exit_first:
            original(worker)
            assert release.wait(10)
    monkeypatch.setattr(OptimizationJob, 'run', held)
    monkeypatch.setattr(panel, 'optimization_output_dir', lambda: tmp_path)
    expected = report(window, status=status)
    if status == 'failed':
        expected.update(baseline=dict(status='failed', reason='One or more conditions failed',
                                      directory='baseline'), reason='Uniform baseline batch failed',
                        history=[], pareto_indices=[], n_evaluated=0, n_usable=0)
    def run(*args, **kwargs):
        kwargs['control'].report_progress(25)
        if status == 'error': raise RuntimeError('test failure')
        if status == 'failed':
            directory = kwargs['output_dir'] / 'baseline'
            directory.mkdir(parents=True)
            (directory / 'batch.json').write_text(json.dumps(dict(conditions=[
                dict(condition_id='one', reason='inlet pressure outside range')])))
        return expected
    monkeypatch.setattr(native, 'run_multi_condition_optimization', run)
    page.start()
    worker = page._job
    label = 'ERROR' if status == 'error' else panel._termination_label(expected)
    if exit_first:
        _wait_for(worker.isFinished)
        assert not page.is_idle() and not window._cpu_card.isEnabled()
        page.start()
        assert page._job is worker
        worker._terminal.emit(expected, '')
        _wait_for(page.is_idle)
        assert label in page.status.text() and page.start_button.isEnabled()
        return
    try:
        _wait_for(lambda: label in page.status.text())
        assert page._job is worker and worker.isRunning()
        assert not page.start_button.isEnabled()
        assert page.progress_bar.value() == 25
        assert not page.is_idle() and not window._cpu_card.isEnabled()
        if status == 'failed':
            assert '均匀基准失败' in page.summary_banner.text()
            assert 'one：inlet pressure outside range' in page.status.text()
            assert not page.pareto_ready() and not page.load_button.isEnabled()
    finally:
        release.set()
    _wait_for(page.is_idle)
    assert page.start_button.isEnabled()


@pytest.mark.parametrize('entry,status', [('direct', 'completed'), ('worker', 'completed'),
                                         ('worker', 'cancelled'), ('worker', 'failed')])
def test_pareto_render_failure_keeps_numerical_terminal_and_disables_half_plot(
        window, tmp_path, monkeypatch, entry, status):
    page = window.optimization
    import sys
    from pathlib import Path
    from sjtu_tpmshx.applications.optimization import multi_condition_optimizer as native
    from tests.python.gui_worker_support import _wait_for
    study = report(window, status=status)
    page.report = deepcopy(study)
    page.conditions = [condition()]
    page.show_pareto(study)
    caught = []
    monkeypatch.setattr(sys, 'excepthook', lambda cls, exc, tb: caught.append(exc))
    monkeypatch.setattr(panel, 'optimization_output_dir', lambda: tmp_path)

    def result(*args, **kwargs):
        directory = Path(kwargs['output_dir'])
        directory.mkdir()
        (directory / 'optimization.json').write_text(json.dumps(study))
        return study

    def fail_draw():
        raise RuntimeError('injected Pareto rendering failure')

    monkeypatch.setattr(native, 'run_multi_condition_optimization', result)
    with monkeypatch.context() as draw:
        draw.setattr(page.pareto_canvas, 'draw', fail_draw)
        if entry == 'worker':
            page.start()
            _wait_for(page.is_idle)
            assert page.start_button.isEnabled() and not page.cancel_button.isEnabled()
            directory = Path(page.last_output_dir)
            assert json.loads((directory / 'optimization.json').read_text()) == study
        else:
            try:
                page.show_pareto(study)
            except RuntimeError as exc:
                caught.append(exc)
    assert not caught
    assert page.report == study
    label = panel._termination_label(study)
    assert page.kpi_gen.text() == label
    assert label in page.status.text() and '绘图失败' in page.status.text()
    assert 'injected Pareto rendering failure' in page.status.text()
    assert '绘图失败' in page.summary_banner.text()
    assert page.stack.currentIndex() == 2
    assert not page.pareto_ready()
    assert not page.pareto_ready() and page._pick_id is None
    assert not page.pareto_canvas.figure.axes and page.pareto_canvas.isHidden()
    assert not page.field_ready() and not page.volume_ready()
    # The retained numerical report can be drawn again after a display failure.
    page.show_pareto(study)
    assert page.pareto_ready() and not page.pareto_canvas.isHidden()
    assert label in page.status.text()
    assert '1/1 个候选数值合格' in page.status.text()
    assert '绘图失败' not in page.status.text()
    assert '绘图失败' not in page.summary_banner.text()


@pytest.mark.parametrize('failure', ['invalid_json', 'unreadable'])
def test_cancel_checkpoint_read_failure_reaches_error_terminal(window, tmp_path, monkeypatch, failure):
    page = window.optimization
    import sys
    from pathlib import Path
    from sjtu_tpmshx.run_control.cancellation import CancelledError
    from sjtu_tpmshx.applications.optimization import multi_condition_optimizer as native
    from tests.python.gui_worker_support import _wait_for
    previous = report(window)
    cancelled = report(window, status='cancelled')
    page.report = deepcopy(previous)
    page.conditions = [condition()]
    caught, checkpoint = [], []
    monkeypatch.setattr(sys, 'excepthook', lambda cls, exc, tb: caught.append(exc))
    monkeypatch.setattr(panel, 'optimization_output_dir', lambda: tmp_path)

    def cancel(*args, **kwargs):
        directory = Path(kwargs['output_dir'])
        directory.mkdir()
        path = directory / 'optimization.json'
        path.write_text('{"truncated":' if failure == 'invalid_json'
                        else json.dumps(cancelled))
        checkpoint.append(path)
        raise CancelledError('cancelled')

    original_open = Path.open
    if failure == 'unreadable':
        def deny_checkpoint_read(path, mode='r', *args, **kwargs):
            if path in checkpoint and mode == 'r':
                raise PermissionError('injected checkpoint read failure')
            return original_open(path, mode, *args, **kwargs)
        monkeypatch.setattr(Path, 'open', deny_checkpoint_read)
    monkeypatch.setattr(native, 'run_multi_condition_optimization', cancel)
    page.start()
    _wait_for(page.is_idle)
    assert not caught
    assert page.start_button.isEnabled() and not page.cancel_button.isEnabled()
    assert page.kpi_gen.text() == 'ERROR'
    assert 'ERROR' in page.status.text()
    assert ('JSONDecodeError' if failure == 'invalid_json' else 'PermissionError') in page.status.text()
    assert str(checkpoint[0].parent) in page.status.text()
    assert page.report == previous
    assert checkpoint[0].exists()


@pytest.mark.parametrize('dimension', [0, 1])
def test_pareto_keeps_relative_objectives_and_full_field_through_save_replay(window, dimension, tmp_path, monkeypatch):
    page = window.optimization
    from sjtu_tpmshx.applications.gui.ui.window_config import config_from_window
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.data_types.compute_result import ComputeResult
    window.combo_dim.setCurrentIndex(dimension)
    study = report(window)
    archived_case, _ = archive_candidate(window, study, tmp_path)
    page.report = deepcopy(study)
    page.show_pareto(study)
    ax = page.pareto_canvas.figure.axes[0]
    assert ax.get_xlabel() == 'Mean relative pressure drop [1]'
    assert ax.get_ylabel() == 'Mean useful heat gain [%]'
    np.testing.assert_array_equal(ax.lines[0].get_xdata(), [.25])
    np.testing.assert_array_equal(ax.lines[0].get_ydata(), [-2.])
    anchor = (window.le_Lcell.text(), window.le_t.text())
    original = window.case_files.capture_current_preset('before-pick')
    case_result = ComputeResult(Q_W=1.)
    mode = '3d' if dimension else '2d'
    window.cache.set_result(mode, case_result)
    with monkeypatch.context() as click:
        click.setattr('sjtu_tpmshx.preprocess.api.prepare_case',
                      lambda *args, **kwargs: pytest.fail('Pareto click recomputed preparation'))
        pick_front(page)
        assert window.case_files.capture_current_preset('before-pick') == original
        assert window.cache.get_result(mode) is case_result
        assert page.load_button.isEnabled() and page.field_ready()
        page.load_button.click()
    assert window.cache.get_result(mode) is None
    cfg = config_from_window(window, strict=True).validate()
    assert cfg.zones.axis == 'continuous', page.status.text()
    assert cfg.zones.config['x_decision'] == study['history'][0]['x_decision']
    assert ('n_ctrl_z' in cfg.zones.config) == bool(dimension)
    assert (window.le_Lcell.text(), window.le_t.text()) == anchor
    for side in 'AB':
        assert getattr(cfg, 'fluid_'+side).u_mps == archived_case.config_snapshot['fluid_'+side]['u_mps']
    preset = window.case_files.capture_current_preset('full-continuous')
    window.case_files.validate_preset(preset, complete=True)
    page.clear_continuous_field()
    window.case_files.apply_user_preset(preset, show_notice=False)
    replay = config_from_window(window, strict=True).validate()
    assert replay.zones.config == cfg.zones.config
    actual_flows = job_input.condition_inputs(page.capture_case(), page.conditions)[0][2:]
    np.testing.assert_allclose(actual_flows, [.003, .015], rtol=2e-14)
    case = prepare_case(replay, case_id='replayed-field')
    if dimension:
        assert np.any(case.design_fields['L_field_m'][:, :, 0] != case.design_fields['L_field_m'][:, :, -1])
    page.show_field_preview(study['history'][0]['x_decision'])
    previous_preview = page.field_canvas.figure.axes[0].images[0].get_array().copy()
    if dimension:
        assert 'z =' in page.field_canvas.figure.axes[0].get_title(loc='left')
    # A saved design must preview after reopening, without the optimizer's history.
    page.report = None
    page.show_field_preview()
    np.testing.assert_array_equal(page.field_canvas.figure.axes[0].images[0].get_array(), previous_preview)
    bad = deepcopy(preset)
    bad['combos']['combo_dim'] = 1-dimension
    with pytest.raises(ValueError, match='dimension'):
        window.case_files.validate_preset(bad, complete=True)


def test_stale_result_cannot_be_loaded_into_other_geometry(window):
    page = window.optimization
    page.report = report(window)
    window.le_Nx.setText('16')
    page.show_pareto(page.report)
    pick_front(page)
    page.load_button.click()
    assert '原几何' in page.status.text()
    assert window._continuous_field_spec is None


@pytest.mark.parametrize('dimension', [0, 1])
@pytest.mark.parametrize('error_type', [FileNotFoundError, OSError, RuntimeError])
def test_field_preview_reports_native_failures_and_clears_old_volume(window, monkeypatch, dimension, error_type):
    page = window.optimization
    from unittest.mock import Mock
    from sjtu_tpmshx.cpp_interface import _native_continuous

    window.combo_dim.setCurrentIndex(dimension)
    page.report = study = report(window)
    message = f'injected native field {error_type.__name__}'
    reached = []

    def fail(*args, **kwargs):
        reached.append('XYZ sample' if dimension else 'XY construction')
        raise error_type(message)

    if dimension:
        monkeypatch.setattr(_native_continuous, 'tensor_sample', fail)
    else:
        monkeypatch.setattr(_native_continuous.XYFit, '__init__', fail)
    previous_renderer = page.volume_panel
    renderer = types.SimpleNamespace(hide=Mock())
    page.volume_panel = renderer
    page.volume_data = object()
    page._volume_ready = True
    page.result_tabs.setTabEnabled(2, True)
    try:
        page.show_field_preview(study['history'][0]['x_decision'])
        assert reached == ['XYZ sample' if dimension else 'XY construction']
        assert '连续场预览失败' in page.status.text()
        assert message in page.status.text()
        assert page.volume_data is None and not page._volume_ready
        assert not page.result_tabs.isTabEnabled(2)
        renderer.hide.assert_called_once_with()
    finally:
        page.volume_panel = previous_renderer


@pytest.mark.parametrize('dimension', [0, 1])
def test_field_preview_belongs_to_optimization_and_keeps_other_figures(window, dimension):
    page = window.optimization
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QApplication
    window.combo_dim.setCurrentIndex(dimension)
    page.report = study = report(window)
    page.show_pareto(study)
    status_before_preview = page.status.text()
    assert panel._termination_label(study) in status_before_preview
    assert '1/1 个候选数值合格' in status_before_preview
    pareto_line = page.pareto_canvas.figure.axes[0].lines[0]
    geometry_axes = window.canvas_layout.figure.axes.copy()
    window.workbench.switch_tab('layout')
    drawn = window.cache.get_drawn_tabs().copy()

    page.show_field_preview(study['history'][0]['x_decision'])

    assert window.workbench.active_tab == 'pareto'
    assert page.stack.currentIndex() == 2
    assert page.result_tabs.currentWidget() is page.field_canvas
    assert window.canvas_layout.figure.axes == geometry_axes
    assert window.cache.get_drawn_tabs() == drawn
    assert page.pareto_canvas.figure.axes[0].lines[0] is pareto_line
    assert all(ax.images[0].get_cmap().name == resolve_cmap('L_mm')
               for ax in page.field_canvas.figure.axes if ax.images)
    assert page.result_tabs.isTabEnabled(2) == bool(dimension)
    volume = page.volume_data
    if dimension:
        assert volume['L_mm'].shape == volume['t_mm'].shape == (80, 40, 41)
        for name in ('L_mm', 't_mm'):
            for axis in range(3):
                assert np.any(np.diff(volume[name], axis=axis) != 0.)
        geom = page.report['conditions'][0]['config']['geometry']
        for spacing, length in (('dx', 'L_dom_m'), ('dy', 'H_dom_m'), ('dz', 'Lz_m')):
            assert volume[spacing].sum() == pytest.approx(geom[length])
        assert volume['flow_dir'] is None
    else:
        assert volume is None
    page.result_tabs.setCurrentIndex(0)
    assert page.result_tabs.currentWidget() is page.pareto_canvas
    window.resize(1280, 900)
    window.show()
    # Visit configuration before results so the plot uses the settled viewport.
    page.stack.setCurrentIndex(0)
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 1000)
    page.stack.setCurrentIndex(2)
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 1000)
    heights = []
    try:
        for _ in range(3):
            page.show_field_preview(study['history'][0]['x_decision'])
            QApplication.processEvents()
            canvas = page.field_canvas
            canvas.draw()
            for ax in canvas.figure.axes:
                if not ax.images:
                    continue
                # Two fields must use the available width without stretching
                # the physical x/y aspect ratio to fill the canvas.
                assert ax.get_position().width > .65
                x0, x1, y0, y1 = ax.images[0].get_extent()
                box = ax.get_window_extent()
                assert box.width / box.height == pytest.approx((x1-x0)/(y1-y0))
            heights.append(page.result_tabs.height())
            page.result_tabs.setCurrentIndex(0)
            QApplication.processEvents()
        # Figure pixel sizes must not feed back into ever-growing Qt tab hints.
        assert max(heights) - min(heights) <= 2
        assert max(heights) < window.height()
    finally:
        window.hide()
    assert page.status.text() == status_before_preview


@pytest.mark.parametrize('failure', ['raised', 'no_actor'])
@pytest.mark.parametrize('update', ['field_switch', 'new_design'])
def test_volume_tab_is_lazy_reuses_panel_and_keeps_failed_updates_unavailable(window, monkeypatch, failure, update):
    page = window.optimization
    from PySide6.QtWidgets import QWidget
    from unittest.mock import Mock
    from sjtu_tpmshx.applications.gui.ui import panel_vis_3d

    created = []

    class VolumePanel(QWidget):
        def __init__(self, parent):
            super().__init__(parent)
            self.set_fields = Mock()
            self.cleanup = Mock()
            self.restore_color_ranges = Mock()
            self.color_range_state = lambda: {'mode': 'global', 'ranges': {}}
            self._volume_actor = object()
            created.append(self)

    monkeypatch.setattr(panel_vis_3d, 'ThreeDVisPanel', VolumePanel)
    monkeypatch.setattr(window.workbench, 'import_error', None)
    study = report(window)
    page.report = study
    page.show_field_preview(study['history'][0]['x_decision'])
    assert not created
    try:
        page.result_tabs.setCurrentIndex(2)
        from tests.python.gui_worker_support import _wait_for
        _wait_for(lambda: not page._volume_loading)
        assert len(created) == 1 and page._volume_ready
        renderer = created[0]
        assert set(renderer.set_fields.call_args.kwargs) == {
            'L_mm', 't_mm', 'dx', 'dy', 'dz', 'flow_dir'}
        page.result_tabs.setCurrentIndex(1)
        page.result_tabs.setCurrentIndex(2)
        renderer.set_fields.assert_called_once()

        # A field switch can lose the actor after the initial load succeeded.
        # Reopening must retry despite the cached flag, and reset it on failure.
        renderer._volume_actor = None
        assert page._volume_ready
        if failure == 'raised':
            renderer.set_fields.side_effect = RuntimeError('render failed')
        if update == 'new_design':
            page.show_field_preview(study['history'][0]['x_decision'])
        else:
            page.result_tabs.setCurrentIndex(1)
        page.result_tabs.setCurrentIndex(2)
        assert renderer.set_fields.call_count == 2
        assert len(created) == 1
        assert not page._volume_ready and renderer.isHidden()
        message = 'render failed' if failure == 'raised' else '未能生成三维体图'
        assert message in page.volume_placeholder.text()

        renderer.set_fields.side_effect = lambda **kwargs: setattr(renderer, '_volume_actor', object())
        page.result_tabs.setCurrentIndex(1)
        page.result_tabs.setCurrentIndex(2)
        assert renderer.set_fields.call_count == 3
        assert page._volume_ready and page.volume_ready()
        page.show_field_preview([1.])  # invalid new candidate
        assert page.volume_data is None and not page._volume_ready
        assert not page.result_tabs.isTabEnabled(2) and renderer.isHidden()

        page.show_pareto(study)
        assert page.volume_data is None and not page._volume_ready
        assert not page.result_tabs.isTabEnabled(2)
    finally:
        page.result_tabs.setCurrentIndex(0)
        page.volume_panel = None
        for widget in created:
            page.volume_host.layout().removeWidget(widget)
            widget.deleteLater()


def test_missing_or_mismatched_archive_keeps_current_design(window, tmp_path, monkeypatch):
    page = window.optimization
    from sjtu_tpmshx.file_io.case_io import save_case
    study = report(window)
    case, batch = archive_candidate(window, study, tmp_path)
    page.report = study
    directory = tmp_path / study['history'][0]['directory']
    original = asdict(page.capture_case())
    page.show_pareto(study)
    pick_front(page)
    monkeypatch.setattr('sjtu_tpmshx.preprocess.api.prepare_case',
                        lambda *args, **kwargs: pytest.fail('Missing archive caused new preparation'))
    for damage in ('missing', 'condition', 'flow', 'case_id', 'config', 'vector', 'speed'):
        changed = deepcopy(batch)
        changed_case = case
        if damage == 'missing': changed['conditions'][0]['case_file'] = 'missing.yaml'
        if damage == 'condition': changed['conditions'][0]['condition_id'] = 'other'
        if damage == 'flow': changed['conditions'][0]['mass_flow_A_kg_s'] *= 2
        if damage == 'case_id': changed['conditions'][0]['case_id'] = 'other'
        if damage in ('config', 'vector', 'speed'):
            from sjtu_tpmshx.data_types.portable_data import mutable_data
            snapshot = mutable_data(case.config_snapshot)
            if damage == 'config': snapshot['df_mode'] = 'cfd_smooth'
            elif damage == 'vector': snapshot['zones']['config']['x_decision'][0] += .1
            else: snapshot['fluid_A']['u_mps'] *= 2
            changed_case = replace(case, config_snapshot=snapshot)
        save_case(changed_case, directory / 'condition_001/case.yaml')
        (directory / 'batch.json').write_text(json.dumps(changed))
        page.load_button.click()
        assert '载入失败' in page.status.text(), damage
        expected_reason = dict(missing='No such file', condition='归档工况', flow='归档工况',
                               case_id='归档算例', config='归档算例', vector='归档算例', speed='归档入口速度')
        assert expected_reason[damage] in page.status.text(), page.status.text()
        assert window._continuous_field_spec is None
        assert asdict(page.capture_case()) == original


@pytest.mark.parametrize('field,label,value', [
    (field, label, value)
    for field, label in [('le_L', 'Domain Length'), ('le_TinB', 'Inlet Temp B'),
                         ('le_PinB', 'Inlet Pressure B')]
    for value in ['', 'oops', 'nan', 'inf']
    if value or field != 'le_PinB'  # Optional pressure blank retains its default.
])
def test_bad_case_input_cannot_launch(window, field, label, value, monkeypatch, tmp_path):
    page = window.optimization
    from unittest.mock import Mock
    page.capture_case()  # Establish that only this test's edit is invalid.
    getattr(window, field).setText(value)
    monkeypatch.setattr(panel, 'optimization_output_dir', lambda: tmp_path)
    factory = Mock(side_effect=RuntimeError('invalid input launched'))
    monkeypatch.setattr(panel, 'OptimizationJob', factory)
    page.start()
    factory.assert_not_called()
    assert '启动失败' in page.status.text()
    assert label in page.status.text()
    assert page.is_idle() and page.start_button.isEnabled()


@pytest.mark.parametrize('side', ['A', 'B'])
def test_blank_optional_pressure_keeps_default(window, side):
    page = window.optimization
    widget = getattr(window, f'le_Pin{side}')
    widget.setText('')
    cfg = page.capture_case()
    assert getattr(cfg, f'fluid_{side}').P_in_Pa == 101325.0
    assert widget.text() == ''


@pytest.mark.parametrize('imported', [False, True])
def test_imported_flows_defer_speed_validation_to_worker(window, monkeypatch, tmp_path, imported):
    page = window.optimization
    from unittest.mock import Mock
    window.combo_inlet_modeA.setCurrentIndex(0)
    window.le_uA.setText('0.001')  # Outside the active experimental velocity window.
    page.conditions = [condition()] if imported else None
    factory = Mock(side_effect=RuntimeError('reached worker construction'))
    monkeypatch.setattr(panel, 'OptimizationJob', factory)
    monkeypatch.setattr(panel, 'optimization_output_dir', lambda: tmp_path)
    page.start()
    if imported:
        factory.assert_called_once()
        assert 'reached worker construction' in page.status.text()
    else:
        factory.assert_not_called()
        assert '启动失败' in page.status.text()


@pytest.mark.parametrize('failure', ['primary_error', 'stale_cancel', 'missing_cancel', 'stale_without_note'])
def test_worker_checkpoint_error_keeps_cause_and_rejects_stale_results(
        window, tmp_path, monkeypatch, failure):
    page = window.optimization
    from pathlib import Path
    from sjtu_tpmshx.run_control.cancellation import CancelledError
    from sjtu_tpmshx.applications.optimization import multi_condition_optimizer as native
    from tests.python.gui_worker_support import _wait_for
    previous = report(window)
    page.report = deepcopy(previous)
    page.conditions = [condition()]
    monkeypatch.setattr(panel, 'optimization_output_dir', lambda: tmp_path)
    paths = []
    stale = report(window, status='running')
    def fail(*args, **kwargs):
        directory = Path(kwargs['output_dir'])
        directory.mkdir()
        paths.append(directory)
        if failure.startswith('stale'):
            (directory/'optimization.json').write_text(json.dumps(stale))
        error = (RuntimeError('original solver failure') if failure == 'primary_error'
                 else CancelledError('original cancellation'))
        if failure != 'stale_without_note':
            error.add_note("Could not save checkpoint: OSError('checkpoint write failed')")
        raise error
    monkeypatch.setattr(native, 'run_multi_condition_optimization', fail)
    page.start()
    _wait_for(page.is_idle)
    assert page.kpi_gen.text() == 'ERROR'
    text = page.status.text()
    assert str(paths[0]) in text
    if failure == 'stale_without_note':
        assert 'cancelled' in text
    else:
        assert ('original solver failure' if failure == 'primary_error' else 'original cancellation') in text
        assert 'checkpoint write failed' in text
    assert page.report == previous
    if failure.startswith('stale'):
        assert json.loads((paths[0]/'optimization.json').read_text())['status'] == 'running'
    else:
        assert not (paths[0]/'optimization.json').exists()


def test_mass_requirements_import_and_current_condition_reset(window, tmp_path, monkeypatch):
    page = window.optimization
    from PySide6.QtWidgets import QFileDialog
    from tests.python.test_mass_design import requirements
    payload = dict(conditions=[condition()], mass_requirements=dict(
        requirements(('one',)), allow_nu_re_extrapolation=True))
    payload['mass_requirements']['conditions']['one'].update(T_out_B_min_K=310., P_out_A_min_Pa=1e5)
    path = tmp_path / 'requirements.json'
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(path), ''))
    page.import_conditions()
    assert page.method.currentData() == 'qlognei'
    assert page.mass_requirements == payload['mass_requirements']
    assert 'Nu-Re' in page.eval_preview.text()
    assert '芯体质量最小' in page.eval_preview.text()
    page.use_current_condition()
    assert page.mass_requirements is None
    assert page.method.currentData() == 'qlognehvi'


@pytest.mark.parametrize(('feasible', 'attained'), [(True, False), (True, True), (False, False)])
@pytest.mark.parametrize('allow_extrapolation', [False, True])
@pytest.mark.parametrize('outlet_limit', [False, True])
def test_mass_result_display_and_exports_keep_feasibility(window, tmp_path, feasible, attained, allow_extrapolation, outlet_limit):
    page = window.optimization
    import csv
    from sjtu_tpmshx.applications.optimization.pareto_io import export_pareto_data
    from sjtu_tpmshx.applications.optimization.export_ntop_csv import export_study_design
    from tests.python.test_mass_design import requirements
    study = report(window)
    study.update(method='qlognei', mass_requirements=dict(requirements(('one',)),
                 allow_nu_re_extrapolation=allow_extrapolation),
                 n_feasible=int(feasible), pareto_indices=[0] if feasible else [])
    row = study['history'][0]
    row.update(feasible=feasible, objectives=dict(core_mass_kg=.25,
        heat_shortfall=-.1 if feasible else .1, pressure_excess_A=-.2, pressure_excess_B=-.3),
        constraint_checks={'one': dict(Q_W=110. if feasible else 90., dP_A_Pa=8., dP_B_Pa=14.,
            residuals=[-.1 if feasible else .1, -.2, -.3], feasible=feasible)})
    if outlet_limit:
        study['mass_requirements']['conditions']['one']['T_out_B_min_K'] = 310.
        row['objectives'].update(heat_shortfall=-.1,
            outlet_temperature_shortfall_B=-.05 if feasible else .05)
        row['constraint_checks']['one'].update(Q_W=110., T_out_B_K=325.5 if feasible else 294.5,
            residuals=[-.1, -.2, -.3, -.05 if feasible else .05])
    if attained:
        study.update(stop_reason='mass_lower_bound', mass_lower_bound=dict(
            mass_kg=.25, geometry_model='tpms_geometry', x_decision=row['x_decision']))
    page.report = study
    assert page.show_pareto(study) is None
    assert page.pareto_canvas.figure.axes[0].get_ylabel() == 'Core mass [kg]'
    assert ('Nu Re extrapolation allowed' in page.pareto_canvas.figure.axes[0].get_title()) == allow_extrapolation
    assert ('Nu-Re' in page.kpi_q_caption.text()) == allow_extrapolation
    assert ('Nu-Re' in panel._termination_label(study)) == allow_extrapolation
    assert ('达到模型质量下界' in panel._termination_label(study)) == attained
    assert page.kpi_dp.text() == str(int(feasible))
    path = tmp_path / 'results.csv'
    export_pareto_data(study, path)
    with path.open(encoding='utf-8-sig') as stream:
        exported = list(csv.DictReader(stream))
    assert exported[0]['feasible'] == str(feasible)
    assert float(exported[0]['core_mass_kg']) == .25
    assert json.loads(exported[0]['mass_requirements']) == study['mass_requirements']
    if outlet_limit:
        assert float(exported[0]['outlet_temperature_shortfall_B']) == (-.05 if feasible else .05)
    if attained:
        assert json.loads(exported[0]['mass_lower_bound']) == study['mass_lower_bound']
        assert exported[0]['stop_reason'] == 'mass_lower_bound'
    if feasible:
        exported = export_study_design(study, 0, str(tmp_path / 'geometry'), (3, 3, 3))
        assert exported['source']['mass_requirements'] == study['mass_requirements']
        assert exported['source']['constraint_checks'] == row['constraint_checks']
        if attained:
            assert exported['source']['mass_lower_bound'] == study['mass_lower_bound']
            assert exported['source']['stop_reason'] == 'mass_lower_bound'
    else:
        study['pareto_indices'] = [0]
        with pytest.raises(ValueError, match='constraints'):
            export_study_design(study, 0, str(tmp_path / 'invalid'), (3, 3, 3))



def test_equal_cell_bounds_keep_thickness_controls_active(window):
    page = window.optimization
    page.bounds['L_min'].setValue(7.)
    page.bounds['L_max'].setValue(7.)
    assert page.field_spec()['L_bounds'] == [7., 7.]
    assert '27 个变量' in page.field_layout.text()
