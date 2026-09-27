"""Hidden result plots are deferred without exporting stale selections."""
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.tests.gui_workbench_support import _result, win as win
from sjtu_tpmshx.ui.plot_2d_results import redraw_result_fields
from sjtu_tpmshx.ui.plot_3d_results import finalize_plots_3d


@pytest.mark.parametrize('mode', ['2d', '3d'])
def test_first_plot_lazy_switch_and_export_use_current_selection(win, monkeypatch, tmp_path, mode):
    from sjtu_tpmshx.ui.mixins import io_actions

    result = _result(mode)
    original = result.fields['Tb'].copy()
    win.write_result(result)
    win._temp_unit = 'K'
    win._field_phase = 0
    if mode == '3d':
        monkeypatch.setattr(win, 'canvas_3d', SimpleNamespace(
            set_fields=lambda **kw: None, set_watermark=lambda text: None))
        assert finalize_plots_3d(win)
    else:
        win._finalize_plots()
    assert win.cache.get_drawn_tabs() == {'temp'}
    win._switch_tab('pres')
    assert win.cache.get_drawn_tabs() == {'temp', 'pres'}
    pressure_axis = win.canvas_pres.fig.axes[0]
    win._switch_tab('temp')
    win._switch_tab('pres')
    assert win.canvas_pres.fig.axes[0] is pressure_axis, 'cached fields must not redraw'

    # Change the displayed fluid and (for 3D) real nonuniform-grid slice.
    win._field_phase = 1
    if mode == '3d':
        win._slice_index = 0
    redraw_result_fields(win)
    assert win.cache.get_drawn_tabs() == {'pres'}
    expected = result.fields['P_fB']
    if mode == '3d':
        expected = expected[:, :, 0] / 1000.
    np.testing.assert_array_equal(win.canvas_pres._hover_data['fields'][0], expected)
    assert win.canvas_pres._hover_data['unit'] == ('kPa' if mode == '3d' else 'Pa')

    # Export a field never opened in the workbench. The picker must include
    # it and save this run's selected phase/slice, not a previous canvas.
    options = []
    def pick(parent, title, label, items, *args):
        if title == 'Export Figure':
            options.extend(items)
            return '速度', True
        return '150 (screen)', True

    path = tmp_path / 'velocity.png'
    monkeypatch.setattr(io_actions.QInputDialog, 'getItem', pick)
    monkeypatch.setattr(io_actions.QFileDialog, 'getSaveFileName',
                        lambda *args: (str(path), 'PNG (*.png)'))
    win._export_figure()
    assert {'温度', '压力', '速度'} <= set(options)
    assert path.exists()
    assert win.cache.get_drawn_tabs() == {'pres', 'vel'}
    velocity = np.sqrt(result.fields['ucB']**2 + result.fields['vcB']**2
                       + (result.fields['wcB']**2 if mode == '3d' else 0.))
    if mode == '3d':
        velocity = velocity[:, :, 0]
    np.testing.assert_allclose(win.canvas_vel._hover_data['fields'][0], velocity)

    win._temp_unit = 'C'
    redraw_result_fields(win)
    win._switch_tab('temp')
    temperature = original[:, :, 0] if mode == '3d' else original
    np.testing.assert_allclose(win.canvas_temp._hover_data['fields'][0], temperature - 273.15)
    np.testing.assert_array_equal(result.fields['Tb'], original)

    # A prior velocity figure still exists, but is invalidated. A failed
    # redraw must not save that obsolete figure under a new filename.
    failed_path = tmp_path / 'failed.png'
    monkeypatch.setattr(io_actions.QFileDialog, 'getSaveFileName',
                        lambda *args: (str(failed_path), 'PNG (*.png)'))
    def fail_draw():
        raise RuntimeError('render failure')
    monkeypatch.setattr(win.canvas_vel, 'draw', fail_draw)
    errors = []
    monkeypatch.setattr(io_actions.QMessageBox, 'warning', lambda *args: errors.append(args))
    win._export_figure()
    assert errors
    assert not failed_path.exists()
    assert 'vel' not in win.cache.get_drawn_tabs()


def test_split_and_detached_fields_refresh_but_hidden_fields_stay_deferred(win):
    win.write_result(_result('2d'))
    win._finalize_plots()
    win._switch_tab('temp')
    win._split_with_current('pres')
    assert win.cache.get_drawn_tabs() == {'temp', 'pres'}
    win._field_phase = 1
    redraw_result_fields(win)
    assert win.cache.get_drawn_tabs() == {'temp', 'pres'}
    assert win.canvas_temp._hover_data['names'] == ['T_fB']
    assert win.canvas_pres._hover_data['names'] == ['P_B']
    win._switch_tab('temp')
    win._detach_canvas('pres')
    win._field_phase = 0
    redraw_result_fields(win)
    assert win.cache.get_drawn_tabs() == {'temp', 'pres'}
    assert win.canvas_pres._hover_data['names'] == ['P_A']
    win._reattach_canvas('pres')


def test_failed_visible_redraw_clears_old_plot_and_same_tab_retries(win, monkeypatch):
    from sjtu_tpmshx.ui import plot_2d_results

    win.write_result(_result('2d'))
    win._finalize_plots()
    win._switch_tab('temp')
    assert win.canvas_temp.fig.axes
    assert win.canvas_temp._hover_data['names'] == ['T_fA']
    render = plot_2d_results.finalize_plots
    attempts = []

    def fail_once(window, field='temp'):
        attempts.append(field)
        if len(attempts) == 1:
            raise RuntimeError('failed before replacing the old figure')
        return render(window, field=field)

    monkeypatch.setattr(plot_2d_results, 'finalize_plots', fail_once)
    win._field_phase = 1
    redraw_result_fields(win)
    assert not win.canvas_temp.fig.axes
    assert win.canvas_temp._hover_data is None
    assert 'temp' not in win.cache.get_drawn_tabs()
    assert '场图显示失败' in win.statusBar().currentMessage()
    win._switch_tab('temp')
    assert attempts == ['temp', 'temp']
    assert 'temp' in win.cache.get_drawn_tabs()
    assert win.canvas_temp._hover_data['names'] == ['T_fB']
