"""Keep field controls readable and preserve display-only range changes."""
import os
from types import SimpleNamespace

import numpy as np
import pytest
from matplotlib.backend_bases import MouseEvent
from PySide6.QtWidgets import QApplication

from sjtu_tpmshx.tests.gui_workbench_support import win as win, _result
from sjtu_tpmshx.ui.plot_2d_results import ensure_result_plot, redraw_result_fields
from sjtu_tpmshx.ui.vis3d_constants import field_color_limits, field_tick_format


def test_thread_editor_has_room_for_automatic_and_explicit_values(win):
    win.combo_dim.setCurrentIndex(1)
    win._select_param_page(2)
    QApplication.processEvents()
    spin = win.spin_cpu_cores
    for value in (0, 1, os.cpu_count() or 1):
        spin.setValue(value)
        QApplication.processEvents()
        editor = spin.lineEdit()
        assert editor.width() >= editor.fontMetrics().horizontalAdvance(spin.text()) + 4
        assert spin.text() == ('自动' if value == 0 else str(value))
        assert win.run_control.cpu_threads == (value or None)


def test_preview_drag_starts_in_canvas_margin_and_survives_redraw(win):
    win.combo_dim.setCurrentIndex(1)
    for _ in range(2):
        win._draw_layout()
        QApplication.processEvents()
        canvas = win.canvas_layout
        canvas.draw()
        axes = canvas.axes[0][0]
        before = (axes.elev, axes.azim, axes.roll)
        x, y = canvas.figure.bbox.width - 10, canvas.figure.bbox.height / 2
        assert not axes.bbox.contains(x, y)
        for kind, px, py in [('button_press_event', x, y),
                             ('motion_notify_event', x - 60, y + 20),
                             ('button_release_event', x - 60, y + 20)]:
            event = MouseEvent(kind, canvas, px, py, button=1)
            event._process()
        assert (axes.elev, axes.azim, axes.roll) != before
    win.combo_dim.setCurrentIndex(0)
    win._draw_layout()
    assert win.canvas_layout._preview_axes is None


@pytest.mark.parametrize('field', ['vel', 'pres'])
def test_flow_scale_preserves_full_volume_range_across_slices(win, field):
    result = _result('3d')
    f = result.fields
    f['ucA'][:] = 20.
    f['vcA'][:] = f['wcA'][:] = 0.
    f['ucB'][:] = np.linspace(.10, .35, f['ucB'].size).reshape(f['ucB'].shape)
    f['vcB'][:] = f['wcB'][:] = 0.
    original = {key: value.copy() for key, value in f.items() if isinstance(value, np.ndarray)}
    win.write_result(result)
    win._field_phase = 1
    win._active_tab = field
    assert ensure_result_plot(win, field)
    expected = f['ucB'] if field == 'vel' else f['P_fB'] / 1000.
    limits = (float(expected.min()), float(expected.max()))
    canvas = getattr(win, 'canvas_' + field)
    for index in (0, 2):
        win._slice_index = index
        redraw_result_fields(win)
        artist = canvas.axes[0][0].collections[0]
        assert artist.get_clim() == limits
        assert artist.get_cmap().name == 'viridis'
        assert canvas.fig.axes[-1].get_ylim() == limits
        np.testing.assert_allclose(canvas.fig.axes[-1].get_yticks()[[0, -1]], limits)
    win.chk_shared_flow_scale.setChecked(True)
    combined = (min(limits[0], 20.), 20.) if field == 'vel' else (
        float(min(f['P_fA'].min(), f['P_fB'].min()) / 1000.),
        float(max(f['P_fA'].max(), f['P_fB'].max()) / 1000.))
    assert canvas.axes[0][0].collections[0].get_clim() == combined
    for key, value in original.items():
        np.testing.assert_array_equal(f[key], value)


def test_volume_and_slice_scale_use_original_cells():
    from sjtu_tpmshx.ui.panel_vis_3d import ThreeDVisPanel
    arrays = {'vmag': np.array([19., 21.]), 'vmag_B': np.array([.1, .3]),
              'P_kPa': np.array([120., 121.]), 'P_B_kPa': np.array([100., 100.001])}
    panel = SimpleNamespace(_arrays=arrays, _shared_flow_scale=False)
    limits = ThreeDVisPanel._build_global_clim(panel)
    assert limits['vmag_B'] == (.1, .3)
    assert limits['P_B_kPa'] == (100., 100.001)
    fmt = field_tick_format(limits['P_B_kPa'])
    assert len({fmt % v for v in np.linspace(*limits['P_B_kPa'], 5)}) == 5
    panel._shared_flow_scale = True
    limits = ThreeDVisPanel._build_global_clim(panel)
    assert limits['vmag_B'] == limits['vmag'] == (.1, 21.)
    assert field_color_limits([np.zeros(3)])[0][1] > 0


@pytest.mark.parametrize('mode', ['2d', '3d'])
@pytest.mark.parametrize('field,value', [('temp', 300.), ('vel', 1.), ('pres', 100000.)])
def test_nearly_uniform_fields_still_render(win, mode, field, value):
    result = _result(mode)
    keys = {'temp': ('Ta', 'Tb', 'Ts'), 'vel': ('ucA', 'ucB'),
            'pres': ('P_fA', 'P_fB')}[field]
    for key in keys:
        result.fields[key][:] = value
        result.fields[key].flat[0] = np.nextafter(value, np.inf)
    if field == 'vel':
        for key in ('vcA', 'vcB', 'wcA', 'wcB'):
            if key in result.fields:
                result.fields[key][:] = 0.
    win.write_result(result)
    win._field_phase = 0
    assert ensure_result_plot(win, field)
    contour = getattr(win, 'canvas_' + field).axes[0][0].collections[0]
    assert np.all(np.diff(contour.levels) > 0)
    assert contour.get_clim()[1] > contour.get_clim()[0]


def test_qualification_reason_preserves_rejection_and_distinguishes_nu_inputs(win):
    from sjtu_tpmshx.ui.fmt import qualification_reasons
    q = {'design': {'status': 'rejected', 'reasons': ['applicability']},
         'applicability': {'checks': [
             {'passed': False, 'side': 'B', 'source': [key, 'water', 'Gyroid'],
              'quantity': 'Re', 'group': 'final'} for key in ('nu_raw', 'nu')]}}
    assert qualification_reasons(q) == [
        'B 侧 Nu（原始输入） 水 Gyroid Re 超范围',
        'B 侧 Nu（计算输入） 水 Gyroid Re 超范围']
    assert q['design']['status'] == 'rejected'
    result = _result('3d')
    q['design']['eligible'] = False
    result.metadata['qualification'] = q
    win.write_result(result)
    win._update_result_summary()
    label = win._sb_labels['design']
    assert label.text() == '未通过 ⚠：B 侧 Nu（原始输入） 水 Gyroid Re 超范围'
    assert 'Nu（计算输入）' in label.toolTip()
