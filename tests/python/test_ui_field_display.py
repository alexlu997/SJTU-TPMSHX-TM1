"""Keep field controls readable and preserve display-only range changes."""
import os
from types import SimpleNamespace

import numpy as np
import pytest
from matplotlib.backend_bases import MouseEvent
from PySide6.QtWidgets import QApplication

from tests.python.gui_workbench_support import win as win, _result
from sjtu_tpmshx.applications.gui.ui.plot_2d_results import ensure_result_plot, redraw_result_fields
from sjtu_tpmshx.applications.gui.ui.theme import resolve_cmap, set_cmap
from sjtu_tpmshx.applications.gui.ui.vis3d_constants import field_color_limits, field_tick_format


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


@pytest.mark.parametrize('mode', ['2d', '3d'])
@pytest.mark.parametrize('field', ['vel', 'pres'])
def test_speed_scales_stay_separate_and_pressure_can_share_across_slices(win, mode, field):
    result = _result(mode)
    f = result.fields
    f['ucA'][:] = 20.
    f['vcA'][:] = 0.
    f['ucB'][:] = np.linspace(.10, .35, f['ucB'].size).reshape(f['ucB'].shape)
    f['vcB'][:] = 0.
    if mode == '3d':
        f['wcA'][:] = f['wcB'][:] = 0.
    f['vmag_A'][:] = np.abs(f['ucA'])
    f['vmag_B'][:] = np.abs(f['ucB'])
    original = {key: value.copy() for key, value in f.items() if isinstance(value, np.ndarray)}
    win.results.publish(result)
    win._field_phase = 1
    win.workbench.active_tab = field
    assert win.chk_shared_pressure_scale.isChecked()
    assert ensure_result_plot(win, field)
    if mode == '3d':
        assert win._slice_index == f['Ta'].shape[2] // 2
        win.workbench.rendered_slices = True
    win.workbench.switch_tab(field)
    assert win.btn_colormap.isVisibleTo(win)
    assert win.chk_shared_pressure_scale.isChecked()
    pressure_unit = 1000.
    independent = (.10, .35) if field == 'vel' else (
        float(f['P_fB'].min() / pressure_unit), float(f['P_fB'].max() / pressure_unit))
    enabled_limits = independent if field == 'vel' else (
        float(min(f['P_fA'].min(), f['P_fB'].min()) / pressure_unit),
        float(max(f['P_fA'].max(), f['P_fB'].max()) / pressure_unit))
    canvas = getattr(win, 'canvas_' + field)
    expected_cmap = resolve_cmap('vmag_B' if field == 'vel' else 'P_fB')
    assert expected_cmap == 'viridis'
    for enabled, limits in ((True, enabled_limits), (False, independent)):
        win.chk_shared_pressure_scale.setChecked(enabled)
        assert canvas.axes[0][0].collections[0].get_clim() == limits
        for index in ((0, 2) if mode == '3d' else (0,)):
            win._slice_index = index
            redraw_result_fields(win)
            artist = canvas.axes[0][0].collections[0]
            assert artist.get_clim() == limits
            assert artist.get_cmap().name == expected_cmap
            assert len(artist.levels) == (257 if mode == '3d' else 129)
            assert canvas.fig.axes[-1].get_ylim() == limits
            np.testing.assert_allclose(canvas.fig.axes[-1].get_yticks()[[0, -1]], limits)
    for key, value in original.items():
        np.testing.assert_array_equal(f[key], value)


def test_volume_scale_keeps_weak_fields_visible_and_uses_original_cells():
    from sjtu_tpmshx.applications.gui.ui.panel_vis_3d import ThreeDVisPanel
    arrays = {'vmag': np.array([19., 21.]), 'vmag_B': np.array([.1, .3]),
              'P_kPa': np.array([120., 121.]), 'P_B_kPa': np.array([100., 100.001])}
    panel = SimpleNamespace(_arrays=arrays)
    limits = ThreeDVisPanel._build_global_clim(panel)
    assert limits['vmag_B'] == (.1, .3)
    assert limits['P_B_kPa'] == (100., 100.001)
    fmt = field_tick_format(limits['P_B_kPa'])
    assert len({fmt % v for v in np.linspace(*limits['P_B_kPa'], 5)}) == 5
    assert field_color_limits([np.zeros(3)])[0][1] > 0


def test_volume_speed_scales_stay_separate_when_ranges_overlap():
    from sjtu_tpmshx.applications.gui.ui.panel_vis_3d import ThreeDVisPanel
    arrays = {'vmag': np.array([19., 21.]), 'vmag_B': np.array([18., 22.])}
    limits = ThreeDVisPanel._build_global_clim(SimpleNamespace(_arrays=arrays))
    assert limits == {'vmag': (19., 21.), 'vmag_B': (18., 22.)}
    assert all(resolve_cmap(key) == 'viridis' for key in arrays)


@pytest.mark.parametrize('group,expected_cmap', [
    (('Ta', 'Tb', 'Ts'), 'coolwarm'),
    (('P_kPa', 'P_B_kPa'), 'viridis'),
])
@pytest.mark.parametrize('small_max,shared', [(3.9, False), (4., True), (8., True)])
def test_volume_scale_shares_related_fields_at_the_original_threshold(group, expected_cmap, small_max, shared):
    from sjtu_tpmshx.applications.gui.ui.panel_vis_3d import ThreeDVisPanel
    arrays = {key: np.array([0., 10. if i == 0 else small_max]) for i, key in enumerate(group)}
    limits = ThreeDVisPanel._build_global_clim(SimpleNamespace(_arrays=arrays))
    assert limits[group[0]] == (0., 10.)
    for key in group[1:]:
        assert limits[key] == (0., 10. if shared else small_max)
    assert all(resolve_cmap(key) == expected_cmap for key in group)


@pytest.mark.parametrize('mode', ['2d', '3d'])
@pytest.mark.parametrize('field,value,spec_key', [
    ('temp', 300., 'Ta'),
    ('vel', 1., 'vmag_A'),
    ('pres', 100000., 'P_fA'),
])
def test_nearly_uniform_fields_still_render(win, mode, field, value, spec_key):
    result = _result(mode)
    keys = {'temp': ('Ta', 'Tb', 'Ts'), 'vel': ('ucA', 'ucB', 'vmag_A', 'vmag_B'),
            'pres': ('P_fA', 'P_fB')}[field]
    for key in keys:
        result.fields[key][:] = value
        result.fields[key].flat[0] = np.nextafter(value, np.inf)
    if field == 'vel':
        for key in ('vcA', 'vcB', 'wcA', 'wcB'):
            if key in result.fields:
                result.fields[key][:] = 0.
    win.results.publish(result)
    win._field_phase = 0
    assert ensure_result_plot(win, field)
    contour = getattr(win, 'canvas_' + field).axes[0][0].collections[0]
    assert contour.get_cmap().name == resolve_cmap(spec_key)
    if mode == '3d':
        assert len(contour.levels) == 257
    assert np.all(np.diff(contour.levels) > 0)
    assert contour.get_clim()[1] > contour.get_clim()[0]


@pytest.mark.parametrize('mode', ['2d', '3d'])
@pytest.mark.parametrize('unit', ['K', 'C'])
def test_shared_temperature_levels_and_ticks_stay_fixed_across_phases_and_slices(win, mode, unit):
    result = _result(mode)
    fields = result.fields
    for key, low, high in [('Ta', 400., 500.), ('Tb', 300., 320.), ('Ts', 330., 390.)]:
        fields[key][:] = np.linspace(low, high, fields[key].size).reshape(fields[key].shape)
    win.results.publish(result)
    win._temp_unit = unit
    win.workbench.active_tab = 'temp'
    win.chk_sync_colorbar_T.setChecked(True)
    offset = 273.15 if unit == 'C' else 0.
    expected = np.linspace(300. - offset, 500. - offset, 257 if mode == '3d' else 129)
    for phase in range(3):
        win._field_phase = phase
        for index in ((0, 2) if mode == '3d' else (0,)):
            win._slice_result_id = id(win.cache.get_result(mode))
            win._slice_index = index
            redraw_result_fields(win)
            contour = win.canvas_temp.axes[0][0].collections[0]
            np.testing.assert_array_equal(contour.levels, expected)
            np.testing.assert_allclose(win.canvas_temp.fig.axes[-1].get_yticks(),
                                       np.linspace(expected[0], expected[-1], 5))
            assert contour.get_clim() == (expected[0], expected[-1])
            source = fields[('Ta', 'Tb', 'Ts')[phase]]
            if mode == '3d':
                source = source[:, :, index]
            np.testing.assert_array_equal(win.canvas_temp._hover_data['fields'][0], source - offset)


def test_2d_speed_uses_original_components_even_with_historical_display_copies(win):
    result = _result('2d')
    for key in ('ucA', 'vcA', 'ucB', 'vcB'):
        result.fields[key + '_disp'] = np.zeros_like(result.fields[key])
    win.results.publish(result)
    win._field_phase = 0
    assert ensure_result_plot(win, 'vel')
    expected = np.hypot(result.fields['ucA'], result.fields['vcA'])
    np.testing.assert_allclose(win.canvas_vel._hover_data['fields'][0], expected)
    assert win.canvas_vel._hover_data['names'] == ['|u_A|']
    assert win.canvas_vel.axes[0][0].collections[0].get_clim() == field_color_limits([expected])[0]
    assert win.canvas_vel.axes[0][0].collections[0].get_cmap().name == 'viridis'


@pytest.mark.parametrize('mode', ['2d', '3d'])
def test_runtime_colormap_override_updates_selected_quantity_only(win, mode):
    result = _result(mode)
    win.results.publish(result)
    win._field_phase = 0
    try:
        set_cmap('temperature', 'cividis')
        win.workbench.active_tab = 'temp'
        redraw_result_fields(win)
        assert win.canvas_temp.axes[0][0].collections[0].get_cmap().name == 'cividis'
        win.workbench.active_tab = 'pres'
        redraw_result_fields(win)
        assert win.canvas_pres.axes[0][0].collections[0].get_cmap().name == 'viridis'
        set_cmap('temperature', None)
        win.workbench.active_tab = 'temp'
        redraw_result_fields(win)
        assert win.canvas_temp.axes[0][0].collections[0].get_cmap().name == 'coolwarm'
    finally:
        set_cmap('temperature', None)


def test_qualification_reason_preserves_rejection_and_distinguishes_nu_inputs(win):
    from sjtu_tpmshx.applications.gui.ui.fmt import qualification_reasons
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
    win.results.publish(result)
    win.results.refresh_summary()
    label = win._sb_labels['design']
    reason_label = win._sb_labels['design_reason']
    assert label.text() == '未通过 ⚠'
    assert reason_label.text() == 'B 侧 Nu（原始输入） 水 Gyroid Re 超范围'
    assert 'Nu（计算输入）' in label.toolTip()
