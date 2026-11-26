"""Consecutive Qt worker runs keep summary, plots and exports on one result."""
from copy import deepcopy
import csv
import json
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from tests.python.gui_workbench_support import _result
from tests.python.gui_worker_support import _stub_compute_result
from tests.python.gui_worker_support import (
    _configure, _wait_for, win as win,
)
from sjtu_tpmshx.applications.gui.ui.field_results import FieldResults
from sjtu_tpmshx.applications.gui.ui.plot_3d_results import finalize_plots_3d


@pytest.fixture
def snapshot_window(win, monkeypatch):
    # Keep the real Qt lifecycle and Matplotlib renderers; only native VTK and
    # numerical work are replaced. Every result carries distinguishable fields.
    monkeypatch.setattr(win.results, 'finalize_plots',
                        lambda: FieldResults.finalize_plots(win.results))
    monkeypatch.setattr('sjtu_tpmshx.applications.gui.ui.plot_3d_results.finalize_plots_3d',
                        finalize_plots_3d)
    monkeypatch.setattr(win, 'canvas_3d', SimpleNamespace(
        cleanup=lambda: None, color_range_state=lambda: {},
        set_fields=lambda **kwargs: None, set_watermark=lambda text: None))
    win._temp_unit = 'K'
    win._field_phase = 0
    return win


def _publish(win, monkeypatch, mode, marker):
    _configure(win, monkeypatch, mode)
    win.case_files.active_preset_name = f'accepted-{marker}'
    result = _result(mode)
    result.Q_W = float(marker)
    result.T_out_A_K, result.T_out_B_K = 350. + marker, 300. + marker
    result.fields['Ta'] += marker
    result.metadata['snapshot_marker'] = marker
    _stub_compute_result(monkeypatch, lambda config, **kwargs: result)
    win.single_run.submit()
    _wait_for(win.single_run.is_idle)
    return result


def _assert_export(win, monkeypatch, path, result):
    from sjtu_tpmshx.applications.gui.ui import result_export
    monkeypatch.setattr(result_export.QFileDialog, 'getSaveFileName',
                        lambda *args: (str(path), 'CSV (*.csv)'))
    win.result_export.export_results()
    with path.open(newline='', encoding='utf-8') as stream:
        rows = dict(csv.reader(stream))
    mode = result.diagnostics['mode']
    unit = 'W' if mode == '3d' else 'W/m'
    assert float(rows[f'Q [{unit}]']) == result.Q_W
    assert float(rows['Ta_min [K]']) == float(result.fields['Ta'].min())
    metadata = json.loads(rows['metadata'])
    assert metadata['snapshot_marker'] == result.metadata['snapshot_marker']
    assert metadata['run_provenance'] == result.metadata['run_provenance']
    archive = path.with_name(path.stem + '_fields.npz')
    if mode == '3d':
        with np.load(archive, allow_pickle=False) as data:
            np.testing.assert_array_equal(data['Ta'], result.fields['Ta'])
    else:
        assert not archive.exists()


@pytest.mark.parametrize('order', [('2d', '3d'), ('3d', '2d')])
@pytest.mark.parametrize('attempt_mode', ['2d', '3d'])
@pytest.mark.parametrize('outcome', ['error', 'cancel'])
def test_failed_attempt_retains_one_complete_accepted_snapshot(
        snapshot_window, monkeypatch, tmp_path, order, attempt_mode, outcome):
    win = snapshot_window
    _publish(win, monkeypatch, order[0], 111)
    accepted = _publish(win, monkeypatch, order[1], 222)
    accepted_mode = order[1]
    summary = deepcopy(win.results.summary())
    footer = {name: (label.text(), label.toolTip())
              for name, label in win._sb_labels.items()}
    drawn = win.cache.get_drawn_tabs()
    availability = win.workbench.canvas_tab_availability()
    plotted = win.canvas_temp._hover_data['fields'][0].copy()
    history_count = len(win.history.recent_runs)
    _assert_export(win, monkeypatch, tmp_path / 'accepted.csv', accepted)

    _configure(win, monkeypatch, attempt_mode)
    entered, release = threading.Event(), threading.Event()

    def unfinished(config, *, control, progress_cb):
        entered.set()
        assert release.wait(10)
        if outcome == 'error':
            raise RuntimeError('new attempt failed before publication')
        control.check_cancelled()
        raise AssertionError('the cancelled run must not publish')

    _stub_compute_result(monkeypatch, unfinished)
    win.case_files.active_preset_name = 'failed-draft'
    try:
        win.single_run.submit()
        _wait_for(entered.is_set)
        assert win.results.summary() == summary
        assert win.cache.has_results(accepted_mode)
        if outcome == 'cancel':
            win.single_run.cancel()
    finally:
        release.set()
    _wait_for(win.single_run.is_idle)

    assert win.results.summary() == summary
    assert {name: (label.text(), label.toolTip())
            for name, label in win._sb_labels.items()} == footer
    assert (win.cache.get_result().T_out_A_K, win.cache.get_result().T_out_B_K) == (accepted.T_out_A_K, accepted.T_out_B_K)
    assert win.cache.has_results(accepted_mode)
    assert not win.cache.has_results(order[0])
    assert win.cache.get_drawn_tabs() == drawn
    assert win.workbench.canvas_tab_availability() == availability
    np.testing.assert_array_equal(win.canvas_temp._hover_data['fields'][0], plotted)
    assert win.btn_export.isEnabled()
    assert len(win.history.recent_runs) == history_count
    assert win.single_run.provenance is None
    assert win._run_status_card.state == ('error' if outcome == 'error' else 'cancelled')
    assert '最近完成' in win._run_status_card.note.text()
    _assert_export(win, monkeypatch, tmp_path / 'after_attempt.csv', accepted)


@pytest.mark.parametrize('new_mode', ['2d', '3d'])
def test_new_publication_replaces_snapshot_even_if_renderer_raises(
        snapshot_window, monkeypatch, tmp_path, new_mode):
    win = snapshot_window
    old_mode = '3d' if new_mode == '2d' else '2d'
    _publish(win, monkeypatch, old_mode, 111)

    def broken_renderer(mode):
        raise RuntimeError('display failed after accepted numerical result')

    monkeypatch.setattr(win.results, 'render', broken_renderer)
    accepted = _publish(win, monkeypatch, new_mode, 333)
    assert win._run_status_card.state == 'error'
    assert win.cache.has_results(new_mode)
    assert not win.cache.has_results(old_mode)
    assert win.results.summary()['Q_W'] == accepted.Q_W
    unit = 'W' if new_mode == '3d' else 'W/m'
    assert win._sb_labels['q'].text() == f'{accepted.Q_W:.{2 if new_mode == "3d" else 1}f} {unit}'
    assert 'preset: accepted-333' in win._sb_labels['q'].toolTip()
    assert 'accepted-111' not in win._sb_labels['q'].toolTip()
    assert win._sb_labels['tout'].text() == '683.00 / 633.00'
    assert win.btn_export.isEnabled()
    assert not win.workbench.volume_ready
    assert not win.workbench.rendered_slices
    assert not win.canvas_temp.fig.axes
    assert win.canvas_temp._hover_data is None
    _assert_export(win, monkeypatch, tmp_path / 'render_failed.csv', accepted)


@pytest.mark.parametrize('accepted_mode,new_mode', [('2d', '3d'), ('2d', '2d'), ('3d', '2d')])
def test_export_keeps_clicked_snapshot_while_dialog_delivers_new_result(
        snapshot_window, monkeypatch, tmp_path, accepted_mode, new_mode):
    from sjtu_tpmshx.applications.gui.ui import result_export
    win = snapshot_window
    accepted = _publish(win, monkeypatch, accepted_mode, 111)
    _configure(win, monkeypatch, new_mode)
    entered, release = threading.Event(), threading.Event()
    newer = _result(new_mode)
    newer.Q_W = 222.
    newer.metadata['snapshot_marker'] = 222
    def finish_later(config, *, control, progress_cb):
        entered.set()
        assert release.wait(10)
        return newer
    _stub_compute_result(monkeypatch, finish_later)
    win.single_run.submit()
    _wait_for(entered.is_set)
    path = tmp_path / 'clicked.csv'
    def file_dialog(*args):
        release.set()
        _wait_for(win.single_run.is_idle)
        return str(path), 'CSV (*.csv)'
    monkeypatch.setattr(result_export.QFileDialog, 'getSaveFileName', file_dialog)
    try:
        win.result_export.export_results()
    finally:
        release.set()
        _wait_for(win.single_run.is_idle)
    with path.open(newline='', encoding='utf-8') as stream:
        rows = dict(csv.reader(stream))
    assert float(rows['Q [W]' if accepted_mode == '3d' else 'Q [W/m]']) == 111.
    assert json.loads(rows['metadata'])['snapshot_marker'] == 111
    assert win.cache.get_result(new_mode).Q_W == 222.
    archive = path.with_name(path.stem + '_fields.npz')
    if accepted_mode == '3d':
        with np.load(archive, allow_pickle=False) as data:
            np.testing.assert_array_equal(data['Ta'], accepted.fields['Ta'])
            assert json.loads(str(data['metadata']))['snapshot_marker'] == 111
    else:
        assert not archive.exists()


def test_named_preset_source_reaches_accepted_result_and_export(snapshot_window, monkeypatch, tmp_path):
    win = snapshot_window
    _configure(win, monkeypatch, '2d')
    preset = win.case_files.capture_current_preset('custom user design')
    win.history.load_user_preset(preset)
    result = _result('2d')
    result.metadata['snapshot_marker'] = 444
    _stub_compute_result(monkeypatch, lambda config, **kwargs: result)
    win.single_run.submit()
    _wait_for(win.single_run.is_idle)
    assert result.metadata['run_provenance']['preset_source'] == 'custom user design'
    _assert_export(win, monkeypatch, tmp_path / 'custom.csv', result)


def test_field_figure_metadata_uses_accepted_source_after_draft_changes(
        snapshot_window, monkeypatch, tmp_path):
    from sjtu_tpmshx.applications.gui.ui import result_export
    win = snapshot_window
    _publish(win, monkeypatch, '2d', 111)
    win.case_files.active_preset_name = 'new draft'
    monkeypatch.setattr(result_export.QInputDialog, 'getItem',
        lambda *args: (args[3][0], True))
    monkeypatch.setattr(result_export.QFileDialog, 'getSaveFileName',
        lambda *args: (str(tmp_path / 'field.png'), 'PNG (*.png)'))
    exported = {}
    monkeypatch.setattr(win.canvas_temp.fig, 'savefig',
        lambda path, **kwargs: exported.update(kwargs))
    win.result_export.export_figure()
    assert exported['metadata']['Subject'] == 'Preset: accepted-111'


_LEGACY_ZONE_ATTRS = (
    '_zone_axis_dir',
    '_zone_boundaries',
    '_zone_boundaries_x',
    '_zone_boundaries_y',
)


def _overlay_positions_mm(canvas):
    """Return vertical and horizontal zone-overlay positions in mm for each plot."""
    axes = [axis for row in canvas.axes for axis in row]
    assert axes
    result = []
    for ax in axes:
        vertical = [float(line.get_xdata()[0]) for line in ax.lines
                    if line.get_transform() == ax.get_xaxis_transform()]
        horizontal = [float(line.get_ydata()[0]) for line in ax.lines
                      if line.get_transform() == ax.get_yaxis_transform()]
        assert len(ax.lines) == len(vertical) + len(horizontal)
        result.append((vertical, horizontal))
    return result


@pytest.mark.parametrize('zones,expected_x,expected_y', [
    ({'axis_dir': 'y', 'boundaries': [0.01, 0.02],
      'boundaries_x': None, 'boundaries_y': None,
      'stats': [{'name': 'z0', 'n_cells': 6}]}, [], [10.0, 20.0]),
    ({'axis_dir': 'x', 'boundaries': [0.015],
      'boundaries_x': None, 'boundaries_y': None,
      'stats': [{'name': 'z0', 'n_cells': 6}]}, [15.0], []),
    ({'axis_dir': 'grid', 'boundaries': [],
      'boundaries_x': [0.01, 0.03], 'boundaries_y': [0.015],
      'stats': [{'name': 'g0', 'n_cells': 3}]}, [10.0, 30.0], [15.0]),
    ({'axis_dir': 'continuous', 'boundaries': [],
      'boundaries_x': [], 'boundaries_y': [], 'stats': []}, [], []),
])
def test_zone_overlays_read_isolated_cache_and_clear_on_unzoned_run(
        snapshot_window, zones, expected_x, expected_y):
    from sjtu_tpmshx.applications.gui.ui.plot_2d_results import ensure_result_plot

    win = snapshot_window
    zoned = _result('2d')
    zoned.zones = deepcopy(zones)
    source_ta = zoned.fields['Ta']
    source_uc = zoned.fields['ucA']
    boundaries_ref = zoned.zones['boundaries']
    boundaries_x_ref = zoned.zones['boundaries_x']
    boundaries_y_ref = zoned.zones['boundaries_y']

    win.results.publish(zoned)
    for attr in _LEGACY_ZONE_ATTRS:
        assert not hasattr(win, attr)

    cached = win.cache.get_result('2d')
    assert cached.fields['Ta'] is source_ta
    assert cached.fields['ucA'] is source_uc

    win.results.finalize_plots()
    assert ensure_result_plot(win, 'vel')
    for canvas in (win.canvas_temp, win.canvas_vel):
        for vertical, horizontal in _overlay_positions_mm(canvas):
            np.testing.assert_allclose(vertical, expected_x)
            np.testing.assert_allclose(horizontal, expected_y)

    # Change the source zones in place and by replacement after publication.
    if boundaries_ref is not None:
        boundaries_ref.append(0.035)
    if boundaries_x_ref is not None:
        boundaries_x_ref.append(0.036)
    if boundaries_y_ref is not None:
        boundaries_y_ref.append(0.025)
    zoned.zones['axis_dir'] = 'x' if zones['axis_dir'] == 'y' else 'y'
    zoned.zones['boundaries'] = [0.039]
    zoned.zones['boundaries_x'] = [0.037]
    zoned.zones['boundaries_y'] = [0.028]
    zoned.zones = None

    assert win.cache.get_result('2d').zones == zones
    win.cache.replace_drawn_tabs(set())
    assert ensure_result_plot(win, 'temp')
    assert ensure_result_plot(win, 'vel')
    for canvas in (win.canvas_temp, win.canvas_vel):
        for vertical, horizontal in _overlay_positions_mm(canvas):
            np.testing.assert_allclose(vertical, expected_x)
            np.testing.assert_allclose(horizontal, expected_y)

    # A later unzoned run clears overlays on both plots.
    unzoned = _result('2d')
    assert unzoned.zones is None
    win.results.publish(unzoned)
    for attr in _LEGACY_ZONE_ATTRS:
        assert not hasattr(win, attr)
    win.results.finalize_plots()
    assert ensure_result_plot(win, 'vel')
    for canvas in (win.canvas_temp, win.canvas_vel):
        for vertical, horizontal in _overlay_positions_mm(canvas):
            assert vertical == []
            assert horizontal == []
