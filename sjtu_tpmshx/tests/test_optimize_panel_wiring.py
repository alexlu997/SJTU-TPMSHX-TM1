"""Native multi-condition GUI handoff, without running an optimization."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import types

import numpy as np
import pytest

from sjtu_tpmshx.ui import optimize_panel as panel
from sjtu_tpmshx.ui.theme import FIELD_CMAP
from sjtu_tpmshx.tests.test_io_actions import win as win


@pytest.fixture
def window(win):
    win._load_named_preset('Shanghai (3D Gyroid)')
    win._continuous_field_spec = None
    win._opt_conditions = None
    win._selected_pareto_x = None
    win.le_Nx.setText('12'); win.le_Ny.setText('8'); win.le_Nz.setText('6')
    win.combo_grid.setCurrentIndex(win.combo_grid.findData(False))
    for key, value in (('L_min', 4.), ('L_max', 8.), ('t_min', .3), ('t_max', .6)):
        win._opt_space_params[key].setValue(value)
    return win


def condition(name='one'):
    return dict(condition_id=name, T_in_A_K=400., P_in_A_Pa=130000., mass_flow_A_kg_s=.003,
                T_in_B_K=295., P_in_B_Pa=120000., mass_flow_B_kg_s=.015)


def report(window, *, status='completed'):
    cfg = panel._gather_cfg(window)
    spec = panel._field_spec(window)
    count = 27 if cfg.is_3d else 9
    # Different z controls ensure flattening or mean backfill cannot pass.
    x = np.r_[np.linspace(5., 7., count), np.linspace(.35, .55, count)].tolist()
    return dict(status=status, reason=None, dimension=3 if cfg.is_3d else 2,
        method='qlognehvi', field_spec=spec,
        conditions=[dict(condition_id='one', config=asdict(cfg), mass_flow_A_kg_s=.003,
                         mass_flow_B_kg_s=.015)],
        history=[dict(index=0, x_decision=x, directory='design_0000', status='completed',
                      objectives=dict(heat_gain_percent=-2., pressure_ratio=.25))],
        pareto_indices=[0], n_evaluated=1, n_usable=1, design_budget=4)


def archive_candidate(window, study, output_dir):
    from sjtu_tpmshx.domain.compute_config import ComputeConfig, ZoneInputConfig
    from sjtu_tpmshx.io.case_io import save_case
    from sjtu_tpmshx.optimization.multi_condition import prepare_fixed_mass_flow_case
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
    window._last_opt_output_dir = str(output_dir)
    return case, batch


@pytest.mark.parametrize('dimension', [0, 1])
def test_complete_case_and_field_dimension_reach_optimizer(window, dimension):
    from sjtu_tpmshx.ui.window_config import config_from_window
    window.combo_dim.setCurrentIndex(dimension)
    depth = .042 if dimension else .063
    window.le_Lz.setText(str(depth))
    cfg = panel._gather_cfg(window)
    ordinary = config_from_window(window, strict=True)
    assert cfg.bc_A == ordinary.bc_A and cfg.bc_B == ordinary.bc_B
    assert cfg.solver == ordinary.solver and cfg.df_mode == 'experimental'
    assert cfg.geometry.Lz_m == depth
    assert cfg.is_3d == bool(dimension)
    if not dimension:
        assert ordinary.geometry.Lz_m is None
    spec = panel._field_spec(window)
    assert spec['symmetric_y'] is False and spec['spline_order'] == 2
    assert ('n_ctrl_z' in spec) == bool(dimension)
    assert str(54 if dimension else 18) in window._opt_field_layout.text()


@pytest.mark.parametrize('bad', ['bad', '0', '-1', 'nan'])
def test_2d_total_flow_depth_is_explicit_and_strict(window, bad):
    window.combo_dim.setCurrentIndex(0)
    window._opt_depth.setText(bad)
    assert window.le_Lz.text() == bad
    with pytest.raises(ValueError, match='2D total-flow depth'):
        panel._gather_cfg(window)


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
        panel.validate_condition_table(payload)


def test_import_changes_only_operating_conditions(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    before = asdict(panel._gather_cfg(window))
    path = tmp_path / 'conditions.json'
    path.write_text(json.dumps({'conditions': [condition('a'), condition('b')]}))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(path), ''))
    panel.import_conditions(window)
    current = panel._gather_cfg(window)
    rows = panel._condition_inputs(current, window._opt_conditions)
    assert [r[0] for r in rows] == ['a', 'b']
    for _, cfg, flow_a, flow_b in rows:
        assert cfg.geometry == current.geometry and cfg.bc_B == current.bc_B
        assert cfg.solver == current.solver and cfg.df_mode == current.df_mode
        assert cfg.fluid_A.T_in_K == 400. and cfg.fluid_B.P_in_Pa == 120000.
        assert (flow_a, flow_b) == (.003, .015)
    assert asdict(panel._gather_cfg(window)) == before
    path.write_text('{"conditions": []}')
    panel.import_conditions(window)
    assert len(window._opt_conditions) == 2
    panel.use_current_condition(window)
    assert window._opt_conditions is None and '单工况' in window._opt_condition_summary.text()


@pytest.mark.parametrize('dimension', [0, 1])
def test_current_condition_flow_uses_prepared_fractional_pore_area(window, dimension):
    from sjtu_tpmshx.preprocess.api import prepare_case
    window.combo_dim.setCurrentIndex(dimension)
    cfg = panel._gather_cfg(window)
    rows = panel._condition_inputs(cfg, None)
    case = prepare_case(cfg, case_id='independent-inlet-check')
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
            direction = case.parameters['cfg'+side]['dir']
            eps = np.take(case.design_fields['eps_arr'], -1 if direction % 2 else 0,
                          axis=direction//2)/2
            widths = case.grid['dy' if direction < 2 else 'dx']
            pore_area = np.sum(eps*widths*case.parameters['boundary_openings'][side]['in_profile_frac'])*.042
            rho = case.parameters['static_properties'][side]['rho']
        assert flow == pytest.approx(rho*pore_area*getattr(cfg, 'fluid_'+side).u_mps, rel=1e-14)


def test_worker_passes_native_contract_and_reports_cancellation(window, tmp_path, monkeypatch):
    from sjtu_tpmshx.domain.cancellation import CancelledError
    from sjtu_tpmshx.optimization import multi_condition_optimizer as native
    cfg = panel._gather_cfg(window)
    rows = [condition()]
    conditions = panel._condition_inputs(cfg, rows)
    Worker = panel._make_worker_class()
    worker = Worker(cfg, rows, panel._field_spec(window), 'sobol', 2, 0, 1, 3, str(tmp_path))
    rows[0]['T_in_A_K'] = 500.
    outputs, progress = [], []
    worker.finished_with_result.connect(outputs.append)
    worker.progress_signal.connect(progress.append)
    expected = report(window, status='cancelled')
    def run(actual, **kwargs):
        assert actual == conditions and actual is not conditions
        assert kwargs['method'] == 'sobol' and kwargs['field_spec']['n_ctrl_z'] == 3
        assert kwargs['control'].cancel_check() is False
        kwargs['control'].report_progress(17)
        (tmp_path/'optimization.json').write_text(json.dumps(expected))
        raise CancelledError('cancelled')
    monkeypatch.setattr(native, 'run_multi_condition_optimization', run)
    worker.run()
    assert progress == [17] and outputs == [expected]


@pytest.mark.parametrize('cancel_during_prepare', [False, True])
def test_single_condition_prepares_in_worker_and_can_cancel_before_checkpoint(
        window, tmp_path, monkeypatch, cancel_during_prepare):
    import threading
    from PySide6.QtCore import QThread, QTimer
    from PySide6.QtWidgets import QApplication
    from sjtu_tpmshx.preprocess import api
    from sjtu_tpmshx.optimization import multi_condition_optimizer as native
    from sjtu_tpmshx.tests.test_worker_result_handoff import _wait_for
    entered, release = threading.Event(), threading.Event()
    prepare = api.prepare_case
    cfg = panel._gather_cfg(window)
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
        assert conditions[0][1] == cfg
        assert all(flow > 0 for flow in conditions[0][2:])
        received.append(conditions)
        return expected

    monkeypatch.setattr(api, 'prepare_case', held_prepare)
    monkeypatch.setattr(native, 'run_multi_condition_optimization', run)
    monkeypatch.setattr(panel, 'optimization_output_dir', lambda: tmp_path)
    panel.run_optimize(window)
    QTimer.singleShot(0, lambda: ticks.append(True))
    try:
        _wait_for(lambda: entered.is_set() and bool(ticks))
        assert '1 个工况' in window._opt_status.text()
        assert not window._opt_btn.isEnabled()
        # Editing the live widgets cannot alter the worker's captured input.
        window.le_TinA.setText('450')
        if cancel_during_prepare:
            panel.cancel_optimize(window)
    finally:
        release.set()
    _wait_for(lambda: window._opt_worker is None)
    assert window._opt_btn.isEnabled()
    if cancel_during_prepare:
        assert not received
        assert '尚未启动优化搜索' in window._opt_status.text()
        assert not list(tmp_path.glob('*/optimization.json'))
    else:
        assert len(received) == 1
        assert '完成' in window._opt_status.text()


@pytest.mark.parametrize('status', ['completed', 'failed', 'cancelled', 'error'])
def test_thread_terminal_state_retained_until_actual_exit(window, tmp_path, monkeypatch, status):
    import threading
    from sjtu_tpmshx.optimization import multi_condition_optimizer as native
    from sjtu_tpmshx.tests.test_worker_result_handoff import _wait_for
    window._opt_conditions = [condition()]
    release = threading.Event()
    Worker = panel._make_worker_class()
    original = Worker.run
    def held(worker):
        original(worker)
        assert release.wait(10)
    monkeypatch.setattr(Worker, 'run', held)
    monkeypatch.setattr(panel, '_make_worker_class', lambda: Worker)
    monkeypatch.setattr(panel, 'optimization_output_dir', lambda: tmp_path)
    expected = report(window, status=status)
    def run(*args, **kwargs):
        kwargs['control'].report_progress(25)
        if status == 'error': raise RuntimeError('test failure')
        return expected
    monkeypatch.setattr(native, 'run_multi_condition_optimization', run)
    panel.run_optimize(window)
    worker = window._opt_worker
    label = 'ERROR' if status == 'error' else panel._termination_label(expected)
    try:
        _wait_for(lambda: label in window._opt_status.text())
        assert window._opt_worker is worker and worker.isRunning()
        assert not window._opt_btn.isEnabled()
        assert window._opt_progress.value() == 25
    finally:
        release.set()
    _wait_for(lambda: window._opt_worker is None)
    assert window._opt_btn.isEnabled()


@pytest.mark.parametrize('dimension', [0, 1])
def test_pareto_keeps_relative_objectives_and_full_field_through_save_replay(window, dimension, tmp_path, monkeypatch):
    from sjtu_tpmshx.ui.window_config import config_from_window
    from sjtu_tpmshx.preprocess.api import prepare_case
    window.combo_dim.setCurrentIndex(dimension)
    study = report(window)
    archived_case, _ = archive_candidate(window, study, tmp_path)
    window._last_opt_report = deepcopy(study)
    panel.show_pareto(window, study)
    ax = window.canvas_pareto.figure.axes[0]
    assert ax.get_xlabel() == 'Mean relative pressure drop [1]'
    assert ax.get_ylabel() == 'Mean useful heat gain [%]'
    np.testing.assert_array_equal(ax.lines[0].get_xdata(), [.25])
    np.testing.assert_array_equal(ax.lines[0].get_ydata(), [-2.])
    anchor = (window.le_Lcell.text(), window.le_t.text())
    with monkeypatch.context() as click:
        click.setattr('sjtu_tpmshx.preprocess.api.prepare_case',
                      lambda *args, **kwargs: pytest.fail('Pareto click recomputed preparation'))
        panel.on_pareto_pick(window, types.SimpleNamespace(ind=np.array([0])))
    cfg = config_from_window(window, strict=True).validate()
    assert cfg.zones.axis == 'continuous', window._opt_status.text()
    assert cfg.zones.config['x_decision'] == study['history'][0]['x_decision']
    assert ('n_ctrl_z' in cfg.zones.config) == bool(dimension)
    assert (window.le_Lcell.text(), window.le_t.text()) == anchor
    for side in 'AB':
        assert getattr(cfg, 'fluid_'+side).u_mps == archived_case.config_snapshot['fluid_'+side]['u_mps']
    preset = window._capture_current_preset('full-continuous')
    window._validate_preset(preset, complete=True)
    panel.clear_continuous_field(window)
    window._apply_user_preset(preset, show_notice=False)
    replay = config_from_window(window, strict=True).validate()
    assert replay.zones.config == cfg.zones.config
    actual_flows = panel._condition_inputs(panel._gather_cfg(window), window._opt_conditions)[0][2:]
    np.testing.assert_allclose(actual_flows, [.003, .015], rtol=2e-14)
    case = prepare_case(replay, case_id='replayed-field')
    if dimension:
        assert np.any(case.design_fields['L_field_m'][:, :, 0] != case.design_fields['L_field_m'][:, :, -1])
    panel.show_field_preview(window, study['history'][0]['x_decision'])
    previous_preview = window.canvas_opt_field.figure.axes[0].images[0].get_array().copy()
    if dimension:
        assert 'z =' in window.canvas_opt_field.figure.axes[0].get_title(loc='left')
    # A saved design must preview after reopening, without the optimizer's history.
    window._last_opt_report = None
    panel.show_field_preview(window)
    np.testing.assert_array_equal(window.canvas_opt_field.figure.axes[0].images[0].get_array(), previous_preview)
    bad = deepcopy(preset)
    bad['combos']['combo_dim'] = 1-dimension
    with pytest.raises(ValueError, match='dimension'):
        window._validate_preset(bad, complete=True)


def test_stale_result_cannot_be_loaded_into_other_geometry(window):
    window._last_opt_report = report(window)
    window.le_Nx.setText('16')
    panel.load_pareto_solution(window, window._last_opt_report['history'][0]['x_decision'])
    assert window._continuous_field_spec is None


@pytest.mark.parametrize('dimension', [0, 1])
def test_field_preview_belongs_to_optimization_and_keeps_other_figures(window, dimension):
    from PySide6.QtWidgets import QApplication
    window.combo_dim.setCurrentIndex(dimension)
    window._last_opt_report = study = report(window)
    panel.show_pareto(window, study)
    pareto_line = window.canvas_pareto.figure.axes[0].lines[0]
    geometry_axes = window.canvas_layout.figure.axes.copy()
    window._switch_tab('layout')
    drawn = window.cache.get_drawn_tabs().copy()

    panel.show_field_preview(window, study['history'][0]['x_decision'])

    assert window._active_tab == 'pareto'
    assert window._opt_stack.currentIndex() == 2
    assert window._opt_result_tabs.currentWidget() is window.canvas_opt_field
    assert window.canvas_layout.figure.axes == geometry_axes
    assert window.cache.get_drawn_tabs() == drawn
    assert window.canvas_pareto.figure.axes[0].lines[0] is pareto_line
    assert all(ax.images[0].get_cmap().name == FIELD_CMAP
               for ax in window.canvas_opt_field.figure.axes if ax.images)
    assert window._opt_result_tabs.isTabEnabled(2) == bool(dimension)
    volume = window._opt_3d_data
    if dimension:
        assert volume['L_mm'].shape == volume['t_mm'].shape == (80, 40, 41)
        for name in ('L_mm', 't_mm'):
            for axis in range(3):
                assert np.any(np.diff(volume[name], axis=axis) != 0.)
        geom = window._last_opt_report['conditions'][0]['config']['geometry']
        for spacing, length in (('dx', 'L_dom_m'), ('dy', 'H_dom_m'), ('dz', 'Lz_m')):
            assert volume[spacing].sum() == pytest.approx(geom[length])
        assert volume['flow_dir'] is None
    else:
        assert volume is None
    window._opt_result_tabs.setCurrentIndex(0)
    assert window._opt_result_tabs.currentWidget() is window.canvas_pareto
    window.resize(1280, 900)
    window.show()
    heights = []
    try:
        for _ in range(3):
            panel.show_field_preview(window, study['history'][0]['x_decision'])
            QApplication.processEvents()
            canvas = window.canvas_opt_field
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
            heights.append(window._opt_result_tabs.height())
            window._opt_result_tabs.setCurrentIndex(0)
            QApplication.processEvents()
        # Figure pixel sizes must not feed back into ever-growing Qt tab hints.
        assert max(heights) - min(heights) <= 2
        assert max(heights) < window.height()
    finally:
        window.hide()
    assert '当前算例' in window._opt_status.text()


@pytest.mark.parametrize('failure', ['raised', 'no_actor'])
@pytest.mark.parametrize('update', ['field_switch', 'new_design'])
def test_volume_tab_is_lazy_reuses_panel_and_keeps_failed_updates_unavailable(window, monkeypatch, failure, update):
    from PySide6.QtWidgets import QWidget
    from unittest.mock import Mock
    from sjtu_tpmshx.ui import panel_vis_3d

    created = []

    class VolumePanel(QWidget):
        def __init__(self, parent):
            super().__init__(parent)
            self.set_fields = Mock()
            self.cleanup = Mock()
            self._volume_actor = object()
            created.append(self)

    monkeypatch.setattr(panel_vis_3d, 'ThreeDVisPanel', VolumePanel)
    monkeypatch.setattr(window, '_vis3d_import_error', None)
    study = report(window)
    window._last_opt_report = study
    panel.show_field_preview(window, study['history'][0]['x_decision'])
    assert not created
    try:
        window._opt_result_tabs.setCurrentIndex(2)
        assert len(created) == 1 and window._opt_3d_ready
        renderer = created[0]
        assert set(renderer.set_fields.call_args.kwargs) == {
            'L_mm', 't_mm', 'dx', 'dy', 'dz', 'flow_dir'}
        window._opt_result_tabs.setCurrentIndex(1)
        window._opt_result_tabs.setCurrentIndex(2)
        renderer.set_fields.assert_called_once()

        # A field switch can lose the actor after the initial load succeeded.
        # Reopening must retry despite the cached flag, and reset it on failure.
        renderer._volume_actor = None
        assert window._opt_3d_ready
        if failure == 'raised':
            renderer.set_fields.side_effect = RuntimeError('render failed')
        if update == 'new_design':
            panel.show_field_preview(window, study['history'][0]['x_decision'])
        else:
            window._opt_result_tabs.setCurrentIndex(1)
        window._opt_result_tabs.setCurrentIndex(2)
        assert renderer.set_fields.call_count == 2
        assert len(created) == 1
        assert not window._opt_3d_ready and renderer.isHidden()
        message = 'render failed' if failure == 'raised' else '未能生成三维体图'
        assert message in window._opt_3d_placeholder.text()

        renderer.set_fields.side_effect = lambda **kwargs: setattr(renderer, '_volume_actor', object())
        window._opt_result_tabs.setCurrentIndex(1)
        window._opt_result_tabs.setCurrentIndex(2)
        assert renderer.set_fields.call_count == 3
        assert window._opt_3d_ready and window._opt_3d_figure_ready()
        panel.show_field_preview(window, [1.])  # invalid new candidate
        assert window._opt_3d_data is None and not window._opt_3d_ready
        assert not window._opt_result_tabs.isTabEnabled(2) and renderer.isHidden()

        panel.show_pareto(window, study)
        assert window._opt_3d_data is None and not window._opt_3d_ready
        assert not window._opt_result_tabs.isTabEnabled(2)
    finally:
        window._opt_result_tabs.setCurrentIndex(0)
        window.canvas_opt_3d = None
        for widget in created:
            window._opt_3d_host.layout().removeWidget(widget)
            widget.deleteLater()


def test_missing_or_mismatched_archive_keeps_current_design(window, tmp_path, monkeypatch):
    from sjtu_tpmshx.io.case_io import save_case
    study = report(window)
    case, batch = archive_candidate(window, study, tmp_path)
    window._last_opt_report = study
    directory = tmp_path / study['history'][0]['directory']
    original = asdict(panel._gather_cfg(window))
    x = study['history'][0]['x_decision']
    monkeypatch.setattr('sjtu_tpmshx.preprocess.api.prepare_case',
                        lambda *args, **kwargs: pytest.fail('Missing archive caused new preparation'))
    for damage in ('missing', 'condition', 'flow', 'case_id', 'config', 'vector', 'speed'):
        changed = deepcopy(batch)
        changed_case = case
        selected = list(x)
        if damage == 'missing': changed['conditions'][0]['case_file'] = 'missing.yaml'
        if damage == 'condition': changed['conditions'][0]['condition_id'] = 'other'
        if damage == 'flow': changed['conditions'][0]['mass_flow_A_kg_s'] *= 2
        if damage == 'case_id': changed['conditions'][0]['case_id'] = 'other'
        if damage in ('config', 'speed'):
            from sjtu_tpmshx.domain.portable_data import mutable_data
            snapshot = mutable_data(case.config_snapshot)
            if damage == 'config': snapshot['df_mode'] = 'cfd_smooth'
            else: snapshot['fluid_A']['u_mps'] *= 2
            changed_case = replace(case, config_snapshot=snapshot)
        if damage == 'vector': selected[0] += .1
        save_case(changed_case, directory / 'condition_001/case.yaml')
        (directory / 'batch.json').write_text(json.dumps(changed))
        panel.load_pareto_solution(window, selected)
        assert '载入失败' in window._opt_status.text(), damage
        expected_reason = dict(missing='No such file', condition='归档工况', flow='归档工况',
                               case_id='归档算例', config='归档算例', vector='Pareto', speed='归档入口速度')
        assert expected_reason[damage] in window._opt_status.text(), window._opt_status.text()
        assert window._continuous_field_spec is None
        assert asdict(panel._gather_cfg(window)) == original


@pytest.mark.parametrize('field', ['le_L', 'le_TinB', 'le_PinB'])
@pytest.mark.parametrize('value', ['', 'oops', 'nan', 'inf'])
def test_bad_case_input_cannot_launch(window, field, value, monkeypatch):
    getattr(window, field).setText(value)
    monkeypatch.setattr(panel, '_make_worker_class', lambda: pytest.fail('invalid input launched'))
    panel.run_optimize(window)
    assert '启动失败' in window._opt_status.text()
    assert window._opt_launching is False and window._opt_btn.isEnabled()
