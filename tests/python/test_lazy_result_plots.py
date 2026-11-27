"""Hidden result plots are deferred without exporting stale selections."""
from types import SimpleNamespace

import numpy as np
import pytest

from tests.python.gui_workbench_support import _result, win as win
from sjtu_tpmshx.applications.gui.ui.plot_2d_results import redraw_result_fields
from sjtu_tpmshx.applications.gui.ui.plot_3d_results import finalize_plots_3d


@pytest.mark.parametrize('transition', ['preset', '2d_result'])
def test_temperature_slice_does_not_retain_replaced_3d_pressure_fields(win, transition):
    import gc
    import weakref
    from sjtu_tpmshx.applications.gui.ui.plot_3d_results import _render_2d_slices_from_3d

    result = _result('3d')
    pressure = {name: weakref.ref(result.fields[name]) for name in ('P_fA', 'P_fB')}
    win.results.publish(result)
    _render_2d_slices_from_3d(win, result, field='temp')
    del result
    if transition == 'preset':
        win.case_files.invalidate_results_for_preset_load()
    else:
        win.results.publish(_result('2d'))
    gc.collect()
    assert win.cache.get_result('3d') is None
    assert [name for name, reference in pressure.items() if reference() is not None] == []


@pytest.mark.parametrize('mode', ['2d', '3d'])
def test_first_plot_lazy_switch_and_export_use_current_selection(win, monkeypatch, tmp_path, mode):
    from sjtu_tpmshx.applications.gui.ui import result_export

    result = _result(mode)
    original = result.fields['Tb'].copy()
    win.results.publish(result)
    win._temp_unit = 'K'
    win._field_phase = 0
    if mode == '3d':
        monkeypatch.setattr(win, 'canvas_3d', SimpleNamespace(
            cleanup=lambda: None, set_fields=lambda **kw: None, set_watermark=lambda text: None,
            set_scale_sharing=lambda **kw: None,
            color_range_state=lambda: {'mode': 'global', 'ranges': {}}))
        assert finalize_plots_3d(win)
        from sjtu_tpmshx.applications.gui.ui.plot_2d_results import ensure_result_plot
        win.workbench.rendered_slices = ensure_result_plot(win, 'temp')
    else:
        win.results.finalize_plots()
    assert win.cache.get_drawn_tabs() == {'temp'}
    win.workbench.switch_tab('pres')
    assert win.cache.get_drawn_tabs() == {'temp', 'pres'}
    pressure_axis = win.canvas_pres.fig.axes[0]
    win.workbench.switch_tab('temp')
    win.workbench.switch_tab('pres')
    assert win.canvas_pres.fig.axes[0] is pressure_axis, 'cached fields must not redraw'

    # Change the displayed fluid and (for 3D) real nonuniform-grid slice.
    win._field_phase = 1
    if mode == '3d':
        win._slice_index = 0
    redraw_result_fields(win)
    assert win.cache.get_drawn_tabs() == {'pres'}
    expected = result.fields['P_fB'] / 1000.
    if mode == '3d':
        expected = expected[:, :, 0]
    np.testing.assert_array_equal(win.canvas_pres._hover_data['fields'][0], expected)
    assert win.canvas_pres._hover_data['unit'] == 'kPa'

    # Export a field never opened in the workbench. The picker must include
    # it and save this run's selected phase/slice, not a previous canvas.
    options = []
    def pick(parent, title, label, items, *args):
        if title == '导出图像':
            options.extend(items)
            return '速度', True
        return '150（屏幕）', True

    path = tmp_path / 'velocity.png'
    monkeypatch.setattr(result_export.QInputDialog, 'getItem', pick)
    monkeypatch.setattr(result_export.QFileDialog, 'getSaveFileName',
                        lambda *args: (str(path), 'PNG (*.png)'))
    win.result_export.export_figure()
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
    win.workbench.switch_tab('temp')
    temperature = original[:, :, 0] if mode == '3d' else original
    np.testing.assert_allclose(win.canvas_temp._hover_data['fields'][0], temperature - 273.15)
    np.testing.assert_array_equal(result.fields['Tb'], original)

    # A prior velocity figure still exists, but is invalidated. A failed
    # redraw must not save that obsolete figure under a new filename.
    failed_path = tmp_path / 'failed.png'
    monkeypatch.setattr(result_export.QFileDialog, 'getSaveFileName',
                        lambda *args: (str(failed_path), 'PNG (*.png)'))
    def fail_draw():
        raise RuntimeError('render failure')
    monkeypatch.setattr(win.canvas_vel, 'draw', fail_draw)
    errors = []
    monkeypatch.setattr(result_export.QMessageBox, 'warning', lambda *args: errors.append(args))
    win.result_export.export_figure()
    assert errors
    assert not failed_path.exists()
    assert 'vel' not in win.cache.get_drawn_tabs()


def test_split_and_detached_fields_refresh_but_hidden_fields_stay_deferred(win):
    win.results.publish(_result('2d'))
    win.results.finalize_plots()
    win.workbench.switch_tab('temp')
    win.workbench.split_with_current('pres')
    assert win.cache.get_drawn_tabs() == {'temp', 'pres'}
    win._field_phase = 1
    redraw_result_fields(win)
    assert win.cache.get_drawn_tabs() == {'temp', 'pres'}
    assert win.canvas_temp._hover_data['names'] == ['T_fB']
    assert win.canvas_pres._hover_data['names'] == ['P_B']
    win.workbench.switch_tab('temp')
    win.workbench.detach_canvas('pres')
    win._field_phase = 0
    redraw_result_fields(win)
    assert win.cache.get_drawn_tabs() == {'temp', 'pres'}
    assert win.canvas_pres._hover_data['names'] == ['P_A']
    win.workbench.reattach_canvas('pres')


def test_failed_visible_redraw_clears_old_plot_and_same_tab_retries(win, monkeypatch):
    from sjtu_tpmshx.applications.gui.ui import plot_2d_results

    win.results.publish(_result('2d'))
    win.results.finalize_plots()
    win.workbench.switch_tab('temp')
    assert win.canvas_temp.fig.axes
    assert win.canvas_temp._hover_data['names'] == ['T_fA', 'T_fB', 'T_s']
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
    assert '场图显示失败' in win.dialogs.last_notice
    win.workbench.switch_tab('temp')
    assert attempts == ['temp', 'temp']
    assert 'temp' in win.cache.get_drawn_tabs()
    assert win.canvas_temp._hover_data['names'] == ['T_fB']
