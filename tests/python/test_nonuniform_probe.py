"""Cursor readouts use the same physical mesh as the displayed fields."""
from types import SimpleNamespace
from sjtu_tpmshx.applications.gui.controllers.result_cache import ResultCache
from sjtu_tpmshx.data_types.compute_result import ComputeResult

import numpy as np
from matplotlib.figure import Figure
from PySide6.QtWidgets import QLabel

from sjtu_tpmshx.applications.gui.ui.coord_inspector import CoordInspector, _resolve_fields
from sjtu_tpmshx.applications.gui.ui.matplotlib_canvas import MatplotlibCanvas, cell_index_mm
from sjtu_tpmshx.applications.gui.ui.workbench import Workbench
from sjtu_tpmshx.applications.gui.ui.plot_2d_results import finalize_plots, plot_temperature_3panel
from sjtu_tpmshx.applications.gui.ui.theme import get_theme


def test_plot_hover_and_inspector_locate_nonuniform_cells():
    temperature = np.array([[300., 310.], [400., 410.]])
    pressure = np.array([[120000.00, 120000.01], [120001.00, 160500.00]])
    zeros = np.zeros_like(temperature)
    result = dict(N_x=2, N_y=2, L=.1, H=.05, dx_arr=np.array([.01, .09]),
                  dy_arr=np.array([.02, .03]), Ta=temperature, Tb=temperature,
                  Ts=temperature, P_fA=pressure, P_fB=pressure + 5000.,
                  ucA=zeros, vcA=zeros, ucB=zeros, vcB=zeros,
                  vmag_A=zeros, vmag_B=zeros, dir_A=0, dir_B=3)
    canvas = SimpleNamespace(fig=Figure(), draw=lambda: None, draw_idle=lambda: None)
    pres_canvas = SimpleNamespace(fig=Figure(), draw=lambda: None, draw_idle=lambda: None)
    pres_canvas.plot_pressure = lambda *args, **kwargs: MatplotlibCanvas.plot_pressure(
        pres_canvas, *args, **kwargs)
    window = SimpleNamespace(cache=ResultCache(), _temp_unit='K', _field_phase=0,
                             _DIR_MAP={0: 'x+', 3: 'y-'}, _update_tout=lambda _: None,
                             canvas_temp=canvas, canvas_pres=pres_canvas,
                             _hover_label=QLabel())
    window.workbench = Workbench(window)
    window.cache.set_result('2d', ComputeResult(fields=result))
    plot_temperature_3panel(window, result, get_theme())
    np.testing.assert_array_equal(canvas._hover_data['dx_arr'], result['dx_arr'])
    rows = _resolve_fields(window, 20., 10.)
    assert ('(i,j)', '(1,0)', '') in rows
    assert ('T_fA', '400.00', 'K') in rows
    assert ('P_A', '120.001', 'kPa') in rows
    assert ('P_B', '125.001', 'kPa') in rows
    event = SimpleNamespace(inaxes=canvas.axes[0][0], xdata=20., ydata=10., canvas=canvas)
    window.workbench.on_hover(event)
    assert '400.00\u202fK' in window._hover_label.text()

    # 2D pressure hover keeps 0.01 Pa resolution in kPa across adjacent cells.
    finalize_plots(window, field='pres')
    pres_axis = pres_canvas.axes[0][0]
    window.workbench.last_hover_time = 0.0
    window.workbench.on_hover(SimpleNamespace(
        inaxes=pres_axis, xdata=5., ydata=10., canvas=pres_canvas))
    label_00 = window._hover_label.text()
    window.workbench.last_hover_time = 0.0
    window.workbench.on_hover(SimpleNamespace(
        inaxes=pres_axis, xdata=5., ydata=30., canvas=pres_canvas))
    label_01 = window._hover_label.text()
    window.workbench.last_hover_time = 0.0
    window.workbench.on_hover(SimpleNamespace(
        inaxes=pres_axis, xdata=20., ydata=10., canvas=pres_canvas))
    label_10 = window._hover_label.text()
    assert '120.00000\u202fkPa' in label_00
    assert '120.00001\u202fkPa' in label_01
    assert '120.00100\u202fkPa' in label_10

    rendered = []
    inspector = SimpleNamespace(_pinned=False, _window=window, _last_ij=None,
                                _render_rows=rendered.append)
    for x in (9., 20.):  # Same uniform-grid cell, different physical cells.
        event.xdata = x
        CoordInspector.update_from_event(inspector, event)
    assert len(rendered) == 2
    assert ('T_fA', '400.00', 'K') in rendered[-1]
    assert ('P_A', '120.001', 'kPa') in rendered[-1]
    # Pin freezes the kPa reading while the cursor moves elsewhere.
    inspector._pinned = True
    event.xdata = 5.
    CoordInspector.update_from_event(inspector, event)
    assert len(rendered) == 2
    inspector._pinned = False
    event.xdata = 20.
    window._temp_unit = 'C'
    CoordInspector.update_from_event(inspector, event)
    assert ('T_fA', '126.85', '°C') in rendered[-1]
    window.workbench = Workbench(window)
    window.cache.set_result('2d', ComputeResult(fields={**result, 'Ta': temperature + 10.0}))
    CoordInspector.update_from_event(inspector, event)
    assert ('T_fA', '136.85', '°C') in rendered[-1]
    single = {**result, 'Ta': np.full((2, 2), 300.155, dtype=np.float32)}
    window.cache.set_result('2d', ComputeResult(fields=single))
    plot_temperature_3panel(window, single, get_theme())
    window.workbench = Workbench(window)
    event.inaxes = canvas.axes[0][0]
    window.workbench.on_hover(event)
    CoordInspector.update_from_event(inspector, event)
    assert ('T_fA', '27.00', '°C') in rendered[-1]
    assert '27.00\u202f°C' in window._hover_label.text()
    np.testing.assert_array_equal(result['P_fA'], pressure)

    for coordinate, expected in [(-1., 0), (0., 0), (9.9, 0), (10., 1), (100., 1), (101., 1)]:
        assert cell_index_mm(coordinate, result['dx_arr']) == expected
