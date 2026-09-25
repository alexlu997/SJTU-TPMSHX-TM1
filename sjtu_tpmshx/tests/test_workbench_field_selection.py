"""Display selections preserve the solved fields and physical probe position."""
from types import SimpleNamespace
from sjtu_tpmshx.controllers.result_cache import ResultCache

import numpy as np
import pytest
from matplotlib.figure import Figure

from sjtu_tpmshx.ui.coord_inspector import _resolve_fields
from sjtu_tpmshx.ui.plot_2d_results import plot_temperature_3panel
from sjtu_tpmshx.ui.plot_3d_results import _render_2d_slices_from_3d
from sjtu_tpmshx.ui.theme import FIELD_CMAP, get_theme


def _canvas():
    return SimpleNamespace(fig=Figure(), draw=lambda: None, draw_idle=lambda: None)


def test_frozen_b_temperature_remains_selectable_in_real_phase_controls():
    from PySide6.QtWidgets import QApplication, QFrame, QPushButton
    from sjtu_tpmshx.ui.builders_canvas import refresh_field_controls

    app = QApplication.instance() or QApplication([])
    host = QFrame()
    buttons = [QPushButton(name, host) for name in ('A', 'B', 'Solid')]
    for button in buttons:
        button.setCheckable(True)
    result = SimpleNamespace(fields={'Tb': np.full((2, 2, 2), 300.), 'dir_B': None})
    window = SimpleNamespace(cache=ResultCache(), _field_phase_seg=host,
                             _field_phase_btns=buttons, _phase_styles=('', ''),
                             btn_update_geometry=QPushButton('更新几何', host))
    window.cache.set_result('3d', result)
    for tab in ('temp', 'pres', 'vel'):
        window._active_tab = tab
        window._field_phase = 1
        refresh_field_controls(window)
        assert buttons[1].isEnabled() == (tab == 'temp')
        assert buttons[1].isChecked() == (tab == 'temp')
        assert window._field_phase == (1 if tab == 'temp' else 0)
    result.fields['Tb'] = None
    window._active_tab, window._field_phase = 'temp', 1
    refresh_field_controls(window)
    assert not buttons[1].isEnabled()
    assert window._field_phase == 0
    host.close()
    app.processEvents()


@pytest.mark.parametrize('width,height', [(953, 427), (613, 294)])
def test_qt_canvas_renderer_covers_the_complete_pixel_rectangle(width, height):
    from PySide6.QtWidgets import QApplication
    from sjtu_tpmshx.ui.matplotlib_canvas import MatplotlibCanvas

    app = QApplication.instance() or QApplication([])
    canvas = MatplotlibCanvas(1, 1)
    canvas.resize(width, height)
    canvas.show()
    app.processEvents()
    canvas.draw()
    actual_height, actual_width, _ = np.asarray(canvas.buffer_rgba()).shape
    assert actual_width == round(width * canvas.device_pixel_ratio)
    assert actual_height == round(height * canvas.device_pixel_ratio)
    canvas.close()


def test_selected_temperature_phase_and_celsius_keep_source_kelvin():
    raw = np.array([[300., 310.], [400., 410.]])
    result = dict(N_x=2, N_y=2, L=.1, H=.05, dx_arr=np.array([.01, .09]),
                  dy_arr=np.array([.02, .03]), Ta=raw, Tb=raw + 20., Ts=raw + 10.)
    window = SimpleNamespace(_field_phase=1, _temp_unit='C', canvas_temp=_canvas())
    plot_temperature_3panel(window, result, get_theme())
    assert len(window.canvas_temp.axes[0]) == 1
    assert window.canvas_temp.axes[0][0].collections[0].get_cmap().name == FIELD_CMAP
    assert window.canvas_temp._hover_data['names'] == ['T_fB']
    assert window.canvas_temp._hover_data['unit'] == '°C'
    np.testing.assert_allclose(window.canvas_temp._hover_data['fields'][0], raw + 20. - 273.15)
    np.testing.assert_array_equal(result['Ta'], raw)
    np.testing.assert_array_equal(result['Tb'], raw + 20.)


def test_3d_slice_phase_and_probe_use_same_nonuniform_cell():
    from PySide6.QtWidgets import QLabel, QSlider
    raw = np.arange(12.).reshape(2, 2, 3) + 300.
    f = dict(Ta=raw.copy(), Tb=raw + 20., Ts=raw + 10.,
             P_fA=raw * 1000., P_fB=raw * 2000.,
             ucA=raw * .01, vcA=raw * .02, wcA=raw * .03,
             ucB=raw * .04, vcB=raw * .05, wcB=raw * .06,
             dx=np.array([.01, .09]), dy=np.array([.02, .03]),
             dz=np.array([.001, .002, .007]), Lx=.1, Ly=.05, Lz=.01, dir_B=1)
    result = SimpleNamespace(fields=f, dP_A_Pa=10., dP_B_Pa=20., extrap_reasons=[])
    window = SimpleNamespace(cache=ResultCache(), _slice_result_id=id(result),
                             _slice_index=2, _field_phase=1, _temp_unit='C',
                             _slice_label=QLabel(), _slice_slider=QSlider(),
                             canvas_temp=_canvas(), canvas_pres=_canvas(), canvas_vel=_canvas())
    window.cache.set_result('3d', result)
    _render_2d_slices_from_3d(window, result)
    for canvas in (window.canvas_temp, window.canvas_pres, window.canvas_vel):
        assert canvas.axes[0][0].collections[0].get_cmap().name == FIELD_CMAP
    hover = window.canvas_temp._hover_data
    assert hover['slice_index'] == 2
    assert hover['names'] == ['T_fB']
    np.testing.assert_allclose(hover['fields'][0], f['Tb'][:, :, 2] - 273.15)
    np.testing.assert_array_equal(window.canvas_pres._hover_data['fields'][0], f['P_fB'][:, :, 2] / 1000.)
    rows = _resolve_fields(window, 20., 10.)
    assert ('T_fB', f"{f['Tb'][1, 0, 2] - 273.15:.2f}", '°C') in rows
    assert window._slice_label.text() == 'z = 6.50 mm (3/3)'
    assert window._slice_slider.value() == 2
    window._slice_index = 0
    _render_2d_slices_from_3d(window, result)
    np.testing.assert_allclose(window.canvas_temp._hover_data['fields'][0], f['Tb'][:, :, 0] - 273.15)
    np.testing.assert_array_equal(result.fields['Ta'], raw)
    assert result.fields['Ta'].shape == (2, 2, 3)
