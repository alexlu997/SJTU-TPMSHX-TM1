"""Consecutive Qt worker runs keep summary, plots and exports on one result."""
from copy import deepcopy
import csv
import json
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D
from sjtu_tpmshx.tests.test_lazy_result_plots import _result
from sjtu_tpmshx.tests.test_worker_result_handoff import (
    _configure, _wait_for, win as win,
)
from sjtu_tpmshx.ui.mixins.run_results import RunResultsMixin
from sjtu_tpmshx.ui.plot_3d_results import finalize_plots_3d


@pytest.fixture
def snapshot_window(win, monkeypatch):
    # Keep the real Qt lifecycle and Matplotlib renderers; only native VTK and
    # numerical work are replaced. Every result carries distinguishable fields.
    monkeypatch.setattr(win, '_finalize_plots',
                        lambda: RunResultsMixin._finalize_plots(win))
    monkeypatch.setattr('sjtu_tpmshx.ui.plot_3d_results.finalize_plots_3d',
                        finalize_plots_3d)
    monkeypatch.setattr(win, 'canvas_3d', SimpleNamespace(
        set_fields=lambda **kwargs: None, set_watermark=lambda text: None))
    win._temp_unit = 'K'
    win._field_phase = 0
    return win


def _publish(win, monkeypatch, mode, marker):
    _configure(win, monkeypatch, mode)
    win._active_preset_name = f'accepted-{marker}'
    result = _result(mode)
    result.Q_W = float(marker)
    result.T_out_A_K, result.T_out_B_K = 350. + marker, 300. + marker
    result.fields['Ta'] += marker
    result.metadata['snapshot_marker'] = marker
    monkeypatch.setattr(Pipeline2D if mode == '2d' else Pipeline3D,
                        'run', lambda pipe: result)
    win.run_calculation()
    _wait_for(win.compute.is_idle)
    return result


def _assert_export(win, monkeypatch, path, result):
    from sjtu_tpmshx.ui.mixins import io_actions
    monkeypatch.setattr(io_actions.QFileDialog, 'getSaveFileName',
                        lambda *args: (str(path), 'CSV (*.csv)'))
    win._export_results()
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
    summary = deepcopy(win._diag_summary)
    footer = {name: (label.text(), label.toolTip())
              for name, label in win._sb_labels.items()}
    drawn = win.cache.get_drawn_tabs()
    availability = win._canvas_tab_availability()
    plotted = win.canvas_temp._hover_data['fields'][0].copy()
    history_count = len(win._recent_runs)
    _assert_export(win, monkeypatch, tmp_path / 'accepted.csv', accepted)

    _configure(win, monkeypatch, attempt_mode)
    entered, release = threading.Event(), threading.Event()

    def unfinished(pipe):
        entered.set()
        assert release.wait(10)
        if outcome == 'error':
            raise RuntimeError('new attempt failed before publication')
        pipe._check_cancel()
        raise AssertionError('the cancelled run must not publish')

    monkeypatch.setattr(Pipeline2D if attempt_mode == '2d' else Pipeline3D,
                        'run', unfinished)
    win._active_preset_name = 'failed-draft'
    try:
        win.run_calculation()
        _wait_for(entered.is_set)
        assert win._diag_summary == summary
        assert win.cache.has_results(accepted_mode)
        if outcome == 'cancel':
            win._on_cancel_compute()
    finally:
        release.set()
    _wait_for(win.compute.is_idle)

    assert win._diag_summary == summary
    assert {name: (label.text(), label.toolTip())
            for name, label in win._sb_labels.items()} == footer
    assert win._tout_K_cache == (accepted.T_out_A_K, accepted.T_out_B_K)
    assert win.cache.has_results(accepted_mode)
    assert not win.cache.has_results(order[0])
    assert win.cache.get_drawn_tabs() == drawn
    assert win._canvas_tab_availability() == availability
    np.testing.assert_array_equal(win.canvas_temp._hover_data['fields'][0], plotted)
    assert win.btn_export.isEnabled()
    assert len(win._recent_runs) == history_count
    assert win._run_provenance is None
    assert win._run_status_card.state == ('error' if outcome == 'error' else 'cancelled')
    assert '最近完成' in win._run_status_card.note.text()
    _assert_export(win, monkeypatch, tmp_path / 'after_attempt.csv', accepted)


@pytest.mark.parametrize('new_mode', ['2d', '3d'])
def test_new_publication_replaces_snapshot_even_if_renderer_raises(
        snapshot_window, monkeypatch, tmp_path, new_mode):
    win = snapshot_window
    old_mode = '3d' if new_mode == '2d' else '2d'
    _publish(win, monkeypatch, old_mode, 111)

    def broken_renderer():
        raise RuntimeError('display failed after accepted numerical result')

    monkeypatch.setattr(win, '_render_compute_result', broken_renderer)
    accepted = _publish(win, monkeypatch, new_mode, 333)
    assert win._run_status_card.state == 'error'
    assert win.cache.has_results(new_mode)
    assert not win.cache.has_results(old_mode)
    assert win._diag_summary['Q_W'] == accepted.Q_W
    unit = 'W' if new_mode == '3d' else 'W/m'
    assert win._sb_labels['q'].text() == f'{accepted.Q_W:.{2 if new_mode == "3d" else 1}f} {unit}'
    assert 'preset: accepted-333' in win._sb_labels['q'].toolTip()
    assert 'accepted-111' not in win._sb_labels['q'].toolTip()
    assert win._sb_labels['tout'].text() == '683.00 / 633.00'
    assert win.btn_export.isEnabled()
    assert not win._3d_view_ready
    assert not win._rendered_3d_slices
    assert not win.canvas_temp.fig.axes
    assert win.canvas_temp._hover_data is None
    _assert_export(win, monkeypatch, tmp_path / 'render_failed.csv', accepted)
