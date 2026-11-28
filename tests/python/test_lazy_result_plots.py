"""Hidden result plots are deferred without exporting stale selections."""
from types import SimpleNamespace

import numpy as np
import pytest

from tests.python.gui_workbench_support import _result, win as win
from tm1.applications.gui.ui.plot_2d_results import redraw_result_fields
from tm1.applications.gui.ui.plot_3d_results import finalize_plots_3d


@pytest.mark.parametrize('transition', ['preset', '2d_result'])
def test_temperature_slice_does_not_retain_replaced_3d_pressure_fields(win, transition):
    import gc
    import weakref
    from tm1.applications.gui.ui.plot_3d_results import _render_2d_slices_from_3d

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
    from tm1.applications.gui.ui import result_export

    result = _result(mode)
    original = result.fields['Tb'].copy()
    win.results.publish(result)
    win._temp_unit = 'K'
    win._field_phase = 0
    if mode == '3d':
        monkeypatch.setattr(win, 'canvas_3d', SimpleNamespace(
            cleanup=lambda: None, set_fields=lambda **kw: None, set_watermark=lambda text: None,
            set_lattice_geometry=lambda *args: None,
            set_scale_sharing=lambda **kw: None,
            color_range_state=lambda: {'mode': 'global', 'ranges': {}}))
        assert finalize_plots_3d(win)
        from tm1.applications.gui.ui.plot_2d_results import ensure_result_plot
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


@pytest.mark.parametrize('select_preview', [False, True])
def test_pareto_canvas_returns_to_its_optimization_result_tab(win, select_preview):
    page = win.optimization
    tabs = page.result_tabs
    original = [(tabs.widget(i), tabs.tabText(i)) for i in range(tabs.count())]
    field_index = tabs.indexOf(page.field_canvas)

    win.workbench.detach_canvas('pareto')
    dialog = win.workbench.detached_canvases['pareto']
    assert page.pareto_canvas.window() is dialog
    assert tabs.widget(field_index) is page.field_canvas
    assert page.pareto_canvas.isVisible()
    if select_preview:
        tabs.setTabEnabled(field_index, True)
        tabs.setCurrentWidget(page.field_canvas)
        win.workbench.reattach_canvas('pareto')
    else:
        dialog.close()

    assert [(tabs.widget(i), tabs.tabText(i)) for i in range(tabs.count())] == original
    assert tabs.currentWidget() is (page.field_canvas if select_preview else page.pareto_canvas)


def test_failed_visible_redraw_clears_old_plot_and_same_tab_retries(win, monkeypatch):
    from tm1.applications.gui.ui import plot_2d_results

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


def _archive_synthetic_result(tmp_path, dimension):
    from dataclasses import replace
    from tests.python.test_module_result_mapping import _synthetic_results
    from tm1.file_io.metrics_io import save_metrics
    from tm1.file_io.result_io import load_result, save_result
    from tm1.postprocess.result_display import describe_fields

    native, performance = _synthetic_results(dimension)
    grid = dict(native.grid)
    for axis in tuple('xyz'[:dimension]):
        grid[axis + '_edges'] = np.r_[0.0, np.cumsum(grid['d' + axis])]
    archived = replace(
        native,
        grid=grid,
        field_metadata=describe_fields(native.fields, dimension),
        metadata={
            **native.metadata,
            'quantity_basis': 'per_unit_depth' if dimension == 2 else 'total',
        },
    )
    results_path = tmp_path / 'results.h5'
    metrics_path = tmp_path / 'metrics.json'
    save_result(archived, results_path)
    save_metrics(performance, metrics_path)
    return results_path, metrics_path, archived, performance, load_result(results_path)


def test_saved_3d_result_uses_selected_field_reader_for_single_view_and_full_load_for_export(
        win, tmp_path, monkeypatch):
    from dataclasses import replace
    from tm1.applications.gui.controllers import result_field_loader
    from tm1.applications.gui.ui import result_export
    from tm1.applications.result_adapter import to_compute_result
    from tm1.file_io.result_io import load_result, save_result

    results_path, metrics_path, archived, performance, expected = _archive_synthetic_result(tmp_path, 3)

    # Header mapping matches to_compute_result on all non-field data and requires metrics.json.
    full_display = to_compute_result(expected, performance)
    mode, header_display, header_id, _available = result_field_loader.build_saved_compute_result(results_path)
    assert mode == '3d'
    assert header_id == expected.result_id
    assert header_display.metadata == full_display.metadata
    assert header_display.coeffs == full_display.coeffs
    assert header_display.props == full_display.props
    assert header_display.residuals == full_display.residuals
    assert header_display.warnings == full_display.warnings
    assert header_display.Q_W == full_display.Q_W
    with pytest.raises(FileNotFoundError):
        result_field_loader.build_saved_compute_result(
            results_path, metrics_file=tmp_path / 'missing-metrics.json'
        )

    def _forbid_full_load(*_args, **_kwargs):
        raise AssertionError('full load_result must not run for single-field display')

    monkeypatch.setattr(result_field_loader, 'load_result', _forbid_full_load)
    win._temp_unit = 'K'
    win._field_phase = 0
    win.chk_sync_colorbar_T.setChecked(False)
    win.chk_shared_pressure_scale.setChecked(False)

    assert win.results.open_result_file(results_path)
    assert win.cache.result_file('3d') == results_path.resolve()
    assert win.cache.source_result_id('3d') == expected.result_id
    assert 'Ta' not in win.cache.get_result('3d').fields
    k_mid = win._slice_index
    np.testing.assert_array_equal(
        win.canvas_temp._hover_data['fields'][0],
        expected.fields['Ta'][:, :, k_mid],
    )

    win.workbench.switch_tab('vel')
    np.testing.assert_array_equal(
        win.canvas_vel._hover_data['fields'][0],
        expected.fields['vmag_A'][:, :, k_mid],
    )

    win.workbench.switch_tab('pres')
    np.testing.assert_array_equal(
        win.canvas_pres._hover_data['fields'][0],
        expected.fields['P_report_A'][:, :, k_mid] * 1e-3,
    )

    # 3D panel binds a lazy field source and reads one field at a time on demand.
    bound = {}
    monkeypatch.setattr(
        win,
        'canvas_3d',
        SimpleNamespace(
            cleanup=lambda: None,
            set_scale_sharing=lambda **kw: None,
            set_field_source=lambda **kw: bound.update(kw),
            set_lattice_geometry=lambda *args: bound.update(lattice=args),
            set_watermark=lambda text: None,
            color_range_state=lambda: {'mode': 'global', 'ranges': {}},
        ),
    )
    assert finalize_plots_3d(win)
    assert set(bound['available_fields']) == {
        'Ta', 'Tb', 'Ts', 'vmag', 'vmag_B', 'P_kPa', 'P_B_kPa', 'L_mm', 't_mm',
    }
    np.testing.assert_array_equal(bound['field_loader']('Ta'), expected.fields['Ta'])
    np.testing.assert_array_equal(
        bound['field_loader']('P_kPa'), expected.fields['P_report_A'] * 1e-3
    )
    np.testing.assert_array_equal(
        bound['field_loader']('L_mm'), expected.metadata['design_fields']['L_field_m'] * 1e3
    )

    # Full export requires every field and uses full load_result.
    monkeypatch.setattr(result_field_loader, 'load_result', load_result)
    csv_path = tmp_path / 'export.csv'
    monkeypatch.setattr(
        result_export.QFileDialog,
        'getSaveFileName',
        lambda *args: (str(csv_path), 'CSV (*.csv)'),
    )
    win.result_export.export_results()
    assert csv_path.is_file()
    with np.load(tmp_path / 'export_fields.npz') as exported:
        np.testing.assert_array_equal(exported['Ta'], expected.fields['Ta'])
        np.testing.assert_array_equal(exported['P_fA'], expected.fields['P_report_A'])
        np.testing.assert_array_equal(exported['vmag_A'], expected.fields['vmag_A'])
        np.testing.assert_array_equal(
            exported['L_mm'], expected.metadata['design_fields']['L_field_m'] * 1e3
        )

    # Replacing results.h5 in place with another result ID must reject on-demand and full reads.
    replacement = replace(
        archived,
        result_id='different-result-id',
        fields={**archived.fields, 'Tb': archived.fields['Tb'] + 50.0},
    )
    save_result(replacement, results_path)
    with pytest.raises(ValueError, match='source_result_id'):
        win.cache.read_field('Tb', '3d')
    with pytest.raises(ValueError, match='source_result_id'):
        bound['field_loader']('Tb')
    with pytest.raises(ValueError, match='source_result_id'):
        win.cache.load_all_fields('3d')


def test_saved_2d_result_uses_selected_field_reader(win, tmp_path, monkeypatch):
    from tm1.applications.gui.controllers import result_field_loader

    results_path, _metrics_path, _archived, _performance, expected = _archive_synthetic_result(tmp_path, 2)

    def _forbid_full_load(*_args, **_kwargs):
        raise AssertionError('full load_result must not run for single-field display')

    monkeypatch.setattr(result_field_loader, 'load_result', _forbid_full_load)
    win._temp_unit = 'K'
    win._field_phase = 0
    win.chk_sync_colorbar_T.setChecked(False)
    win.chk_shared_pressure_scale.setChecked(False)

    assert win.results.open_result_file(results_path)
    assert win.cache.result_file('2d') == results_path.resolve()
    assert win.cache.source_result_id('2d') == expected.result_id
    assert 'Ta' not in win.cache.get_result('2d').fields
    np.testing.assert_array_equal(win.canvas_temp._hover_data['fields'][0], expected.fields['Ta'])

    win.workbench.switch_tab('vel')
    expected_vmag = np.hypot(expected.fields['ucA'], expected.fields['vcA'])
    np.testing.assert_array_equal(win.canvas_vel._hover_data['fields'][0], expected_vmag)

    win.workbench.switch_tab('pres')
    np.testing.assert_array_equal(
        win.canvas_pres._hover_data['fields'][0], expected.fields['P_report_A'] * 1e-3
    )


def test_panel_select_field_surfaces_reader_error_in_status():
    from tests.python.test_volume_render_batching import _make_stub_panel
    from tm1.applications.gui.ui.panel_vis_3d import ThreeDVisPanel

    panel = _make_stub_panel()
    panel._sync_temp_scale = False
    shown = {'text': '', 'visible': False}
    panel.status = SimpleNamespace(
        setText=lambda text: shown.__setitem__('text', text),
        setToolTip=lambda text: None,
        show=lambda: shown.__setitem__('visible', True),
        hide=lambda: shown.__setitem__('visible', False),
    )
    widths = [np.full(n, 0.001) for n in (2, 2, 2)]
    base = np.full((2, 2, 2), 320.0)

    def _loader(key):
        if key == 'Tb':
            raise ValueError('source_result_id mismatch')
        return base

    ThreeDVisPanel.set_field_source(
        panel,
        available_fields=('Ta', 'Tb'),
        field_loader=_loader,
        dx=widths[0],
        dy=widths[1],
        dz=widths[2],
    )
    assert panel.select_field('Tb') is False
    assert panel.active_field() == 'Ta'
    assert shown['visible'] is True
    assert 'source_result_id mismatch' in shown['text']
