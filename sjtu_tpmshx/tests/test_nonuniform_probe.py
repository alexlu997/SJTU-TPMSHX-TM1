"""Cursor readouts use the same physical mesh as the displayed fields."""
from types import SimpleNamespace
from sjtu_tpmshx.controllers.result_cache import ResultCache
from sjtu_tpmshx.domain.compute_result import ComputeResult

import numpy as np
from matplotlib.figure import Figure
from PySide6.QtWidgets import QLabel

from sjtu_tpmshx.ui.coord_inspector import CoordInspector, _resolve_fields
from sjtu_tpmshx.ui.matplotlib_canvas import cell_index_mm
from sjtu_tpmshx.ui.mixins.tab_view import TabViewMixin
from sjtu_tpmshx.ui.plot_2d_results import plot_temperature_3panel
from sjtu_tpmshx.ui.theme import get_theme


def test_plot_hover_and_inspector_locate_nonuniform_cells():
    temperature = np.array([[300., 310.], [400., 410.]])
    result = dict(N_x=2, N_y=2, L=.1, H=.05, dx_arr=np.array([.01, .09]),
                  dy_arr=np.array([.02, .03]), Ta=temperature, Tb=temperature,
                  Ts=temperature)
    canvas = SimpleNamespace(fig=Figure(), draw=lambda: None)
    window = SimpleNamespace(cache=ResultCache(), _temp_unit='K', canvas_temp=canvas,
                             _hover_label=QLabel())
    window.cache.set_result('2d', ComputeResult(fields=result))
    plot_temperature_3panel(window, result, get_theme())
    np.testing.assert_array_equal(canvas._hover_data['dx_arr'], result['dx_arr'])
    rows = _resolve_fields(window, 20., 10.)
    assert ('(i,j)', '(1,0)', '') in rows
    assert ('T_fA', '400.00', 'K') in rows
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
    window._temp_unit = 'C'
    CoordInspector.update_from_event(inspector, event)
    assert ('T_fA', '126.85', '°C') in rendered[-1]
    window.cache.set_result('2d', ComputeResult(fields={**result, 'Ta': temperature + 10.0}))
    CoordInspector.update_from_event(inspector, event)
    assert ('T_fA', '136.85', '°C') in rendered[-1]

    for coordinate, expected in [(-1., 0), (0., 0), (9.9, 0), (10., 1), (100., 1), (101., 1)]:
        assert cell_index_mm(coordinate, result['dx_arr']) == expected
