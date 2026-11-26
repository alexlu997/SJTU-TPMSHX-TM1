"""Cursor readouts use the same physical mesh as the displayed fields."""
from types import SimpleNamespace
from sjtu_tpmshx.applications.gui.controllers.result_cache import ResultCache
from sjtu_tpmshx.data_types.compute_result import ComputeResult

import numpy as np
from matplotlib.figure import Figure
from PySide6.QtWidgets import QLabel

from sjtu_tpmshx.applications.gui.ui.coord_inspector import CoordInspector, _resolve_fields
from sjtu_tpmshx.applications.gui.ui.matplotlib_canvas import cell_index_mm
from sjtu_tpmshx.applications.gui.ui.mixins.tab_view import TabViewMixin
from sjtu_tpmshx.applications.gui.ui.plot_2d_results import plot_temperature_3panel
from sjtu_tpmshx.applications.gui.ui.theme import get_theme


def test_plot_hover_and_inspector_locate_nonuniform_cells():
    temperature = np.array([[300., 310.], [400., 410.]])
    pressure = np.array([[101325., 102000.], [150250., 160500.]])
    result = dict(N_x=2, N_y=2, L=.1, H=.05, dx_arr=np.array([.01, .09]),
                  dy_arr=np.array([.02, .03]), Ta=temperature, Tb=temperature,
                  Ts=temperature, P_fA=pressure, P_fB=pressure + 5000.)
    canvas = SimpleNamespace(fig=Figure(), draw=lambda: None)
    window = SimpleNamespace(cache=ResultCache(), _temp_unit='K', canvas_temp=canvas,
                             _hover_label=QLabel())
    window.cache.set_result('2d', ComputeResult(fields=result))
    plot_temperature_3panel(window, result, get_theme())
    np.testing.assert_array_equal(canvas._hover_data['dx_arr'], result['dx_arr'])
    rows = _resolve_fields(window, 20., 10.)
    assert ('(i,j)', '(1,0)', '') in rows
    assert ('T_fA', '400.00', 'K') in rows
    assert ('P_A', '150.250', 'kPa') in rows
    assert ('P_B', '155.250', 'kPa') in rows
    event = SimpleNamespace(inaxes=canvas.axes[0][0], xdata=20., ydata=10., canvas=canvas)
    TabViewMixin._on_hover(window, event)
    assert '400.00 K' in window._hover_label.text()

    rendered = []
    inspector = SimpleNamespace(_pinned=False, _window=window, _last_ij=None,
                                _render_rows=rendered.append)
    for x in (9., 20.):  # Same uniform-grid cell, different physical cells.
        event.xdata = x
        CoordInspector.update_from_event(inspector, event)
    assert len(rendered) == 2
    assert ('T_fA', '400.00', 'K') in rendered[-1]
    assert ('P_A', '150.250', 'kPa') in rendered[-1]
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
    window.cache.set_result('2d', ComputeResult(fields={**result, 'Ta': temperature + 10.0}))
    CoordInspector.update_from_event(inspector, event)
    assert ('T_fA', '136.85', '°C') in rendered[-1]
    np.testing.assert_array_equal(result['P_fA'], pressure)

    for coordinate, expected in [(-1., 0), (0., 0), (9.9, 0), (10., 1), (100., 1), (101., 1)]:
        assert cell_index_mm(coordinate, result['dx_arr']) == expected
