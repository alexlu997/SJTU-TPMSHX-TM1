"""Exercise the 3D panel rendering, slices, toolbar, overlays, and reduced motion."""
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pyvista as pv
import pytest
from PySide6.QtCore import QRect, QSize

from sjtu_tpmshx.applications.gui.ui.microanim import is_reduced_motion, set_reduced_motion
from sjtu_tpmshx.applications.gui.ui.panel_vis_3d import ThreeDVisPanel
from sjtu_tpmshx.applications.gui.ui.theme import resolve_cmap, set_cmap
from sjtu_tpmshx.applications.gui.ui.volume_overlays import (
    PortAnchor,
    PortChipOverlay,
    StudioColorbarCard,
    place_port_chip,
)
from sjtu_tpmshx.applications.gui.ui.volume_toolbar import DISPLAY_MODES, VolumeToolbar
from sjtu_tpmshx.postprocess.result_display import PANEL_FIELD_SPECS


@pytest.mark.parametrize('direction, expected_in, expected_out', [
    ('+x', (0., 30., 15.), (182., 12., 28.)),
    ('-x', (182., 30., 15.), (0., 12., 28.)),
    ('+y', (30., 0., 15.), (12., 42., 28.)),
    ('-y', (30., 42., 15.), (12., 0., 28.)),
    ('+z', (30., 15., 0.), (12., 28., 42.)),
    ('-z', (30., 15., 42.), (12., 28., 0.)),
])
def test_flow_glyphs_use_independent_physical_port_locations(direction, expected_in, expected_out):
    ports = dict(in_ctr=.030, in_w=.010, out_ctr=.012, out_w=.006,
                 in_z_ctr=.015, in_z_w=.008, out_z_ctr=.028, out_z_w=.004)
    panel = SimpleNamespace(
        plotter=Mock(), _grid=object(), _L_mm=(182., 42., 42.),
        _flow_dir=None, _flow_dir_B=direction, _arrays={'Tb': object()},
        _ports={'B': ports}, _field='Tb', _display_mode='surface',
    )
    panel._faint_port_sides = MethodType(ThreeDVisPanel._faint_port_sides, panel)
    ThreeDVisPanel._add_flow_glyph(panel)
    meshes = {call.kwargs['name']: call.args[0] for call in panel.plotter.add_mesh.call_args_list}
    axis = 'xyz'.index(direction[-1])
    cross = [i for i in range(3) if i != axis]
    sign = -1.0 if direction.startswith('-') else 1.0
    for end, expected, span, upper in (
        ('inlet', expected_in, (10., 8.), sign < 0),
        ('outlet', expected_out, (6., 4.), sign > 0),
    ):
        nout = 1.0 if upper else -1.0
        rectangle = meshes[f'_port_{end}_B']
        np.testing.assert_allclose(np.asarray(rectangle.center)[cross], np.asarray(expected)[cross], atol=1e-5)
        assert (rectangle.center[axis] - expected[axis]) * nout > 0.0
        np.testing.assert_allclose(np.ptp(rectangle.points, axis=0)[cross], span)
        assert np.ptp(rectangle.points[:, axis]) == 0.
        arrow = meshes[f'_flow_{end}_B']
        assert (arrow.center[axis] - expected[axis]) * nout > 0.0
    assert [a[0] for a in panel._port_world_anchors] == ['B-inlet', 'B-outlet']
    assert [a[1] for a in panel._port_world_anchors] == ['B 入口', 'B 出口']
    assert all(call.kwargs['render'] is False for call in panel.plotter.add_mesh.call_args_list)


def test_hover_and_opacity_work_without_vtk_compatibility_aggregator(monkeypatch):
    """The bundle keeps vtkmodules, without the import-everything vtk shim."""
    import sys
    import vtkmodules.vtkRenderingCore as rendering

    monkeypatch.setitem(sys.modules, 'vtk', None)
    picker = Mock()
    picker.GetViewProp.return_value = None
    monkeypatch.setattr(rendering, 'vtkPropPicker', lambda: picker)
    plotter = Mock()
    actor = rendering.vtkVolume()
    panel = SimpleNamespace(
        _grid=object(), _last_hover_text='', _base_status_text='', _hover_last_t=0.0,
        plotter=plotter, status=Mock(), _display_mode='volume',
        _volume_actor=actor, _data_actors={actor}, _field='Ta', _clim_for=lambda _: (300., 420.),
        _opacity_ramp=lambda: (.2, .6), _rebuild_scene=Mock(), _layout_overlays=Mock(),
        _edges_mm=(np.array([0., 10.]), np.array([0., 10.]), np.array([0., 10.])),
        _arrays={'Ta': np.full((1, 1, 1), 350.)},
    )
    panel._clear_hover_status = MethodType(ThreeDVisPanel._clear_hover_status, panel)
    event = Mock()
    event.GetEventPosition.return_value = (4, 5)
    ThreeDVisPanel._on_mouse_move(panel, event, None)
    picker.Pick.assert_called_once_with(4, 5, 0, plotter.renderer)
    panel.status.setText.assert_not_called()

    # Volume hit (vtkVolume via GetViewProp) probes the cell; out-of-domain hit clears probe.
    panel._hover_last_t = 0.0
    picker.GetViewProp.return_value = actor
    picker.GetPickPosition.return_value = (5.0, 5.0, 5.0)
    ThreeDVisPanel._on_mouse_move(panel, event, None)
    assert '单元 (0, 0, 0)' in panel.status.setText.call_args.args[0]
    panel._hover_last_t = 0.0
    picker.GetPickPosition.return_value = (-1.89, 5.0, 5.0)
    ThreeDVisPanel._on_mouse_move(panel, event, None)
    panel.status.hide.assert_called_once_with()

    ThreeDVisPanel._apply_opacity_now(panel)
    opacity = actor.GetProperty().GetScalarOpacity()
    assert opacity.GetValue(360.) == pytest.approx(.4)
    plotter.render.assert_called_once_with()
    panel._rebuild_scene.assert_not_called()


@pytest.mark.parametrize('position,index', [((0., 0., 0.), (0, 0, 0)),
    ((1., 2., 3.), (1, 1, 1)), ((10., 8., 10.), (1, 2, 1))])
def test_hover_reads_original_cell_on_nonuniform_grid(monkeypatch, position, index):
    import vtkmodules.vtkRenderingCore as rendering

    data_actor = object()
    picker = Mock()
    picker.GetViewProp.return_value = data_actor
    picker.GetPickPosition.return_value = position
    monkeypatch.setattr(rendering, 'vtkPropPicker', lambda: picker)
    raw = np.arange(12.).reshape(2, 3, 2)
    panel = SimpleNamespace(
        _grid=object(), plotter=Mock(), status=Mock(), _last_hover_text='',
        _base_status_text='', _hover_last_t=0.0, _layout_overlays=Mock(),
        _data_actors={data_actor},
        _edges_mm=([0., 1., 10.], [0., 2., 7., 8.], [0., 3., 10.]),
        _arrays={'Ta': 300. + raw, 'vmag': 10. + raw,
                 'L_mm': 4. + raw * .1, 't_mm': .3 + raw * .01},
    )
    panel._clear_hover_status = MethodType(ThreeDVisPanel._clear_hover_status, panel)
    event = Mock()
    event.GetEventPosition.return_value = (4, 5)
    ThreeDVisPanel._on_mouse_move(panel, event, None)
    text = panel.status.setText.call_args.args[0]
    assert '坐标' in text and f'单元 {index}' in text
    assert f'= {300. + raw[index]:.1f} K' in text
    assert f'= {10. + raw[index]:.2f} m/s' in text
    assert f'= {4. + raw[index] * .1:.2f} mm' in text
    assert f'= {.3 + raw[index] * .01:.3f} mm' in text
    assert 'Cursor' not in text and 'Cell' not in text and 'speed A' not in text


def _bind_panel_methods(panel, names):
    for name in names:
        setattr(panel, name, MethodType(getattr(ThreeDVisPanel, name), panel))


def _make_stub_panel():
    panel = SimpleNamespace(
        plotter=Mock(window_size=(1000, 800)),
        status=Mock(),
        toolbar=Mock(),
        port_overlay=Mock(),
        _watermark_label=Mock(),
        _viewport_host=Mock(width=lambda: 1000, height=lambda: 800),
        field_changed=Mock(),
        colorbar=StudioColorbarCard(),
    )
    ThreeDVisPanel._init_state(panel, 30)
    panel.fit_view = Mock()
    panel._render_initial_scene = Mock()
    panel._layout_overlays = Mock()
    panel._update_port_chips = Mock()
    _bind_panel_methods(
        panel,
        (
            '_build_volume_grid', '_build_surface_mesh', '_build_global_clim',
            '_clear_data_actors', '_box_edge_color', '_add_domain_edges',
            '_render_surface_actors', '_render_slice_actors', '_render_volume_actors',
            '_sync_colorbar', '_rebuild_scene', '_clim_for', '_opacity_ramp',
            '_slice_index', '_snap_slice_coord', '_update_status',
            '_faint_port_sides', '_add_flow_glyph',
            'active_field', 'available_fields', 'select_field',
            'set_display_mode', 'set_slice_position', 'refresh_colormaps',
        ),
    )
    return panel


@pytest.mark.parametrize('graded', [False, True])
def test_volume_fields_are_lazy_cached_and_reset_without_changing_values(graded):
    """Default outer-surface view and volume mode lazily cache grids without mutating raw arrays."""
    panel = _make_stub_panel()
    try:
        base = np.arange(24., dtype=float).reshape(4, 3, 2)
        fields = {key: base + 100. * i for i, key in enumerate(PANEL_FIELD_SPECS)}
        widths = [np.linspace(.0002, .001, n) if graded else np.full(n, .001)
                  for n in base.shape]
        ThreeDVisPanel.set_fields(panel, **fields, dx=widths[0], dy=widths[1], dz=widths[2])

        # Default display mode is outer surface (外表面), not ray-cast volume.
        assert panel._display_mode == 'surface'
        assert set(panel._volume_grids) == {'Ta'}
        assert set(panel._surface_meshes) == {'Ta'}
        assert set(panel._grid_vol.point_data) == {'Ta'}
        assert not panel._grid.point_data
        initial_values = panel._grid_vol['Ta'].copy()
        display_points = panel._grid_vol.points.copy()
        for axis, widths_m in zip((panel._grid.x, panel._grid.y, panel._grid.z), widths):
            centres = (np.cumsum(widths_m) - widths_m / 2) * 1000.
            np.testing.assert_allclose(axis, np.r_[0., centres, widths_m.sum() * 1000.])
        previous_clim = ThreeDVisPanel._build_global_clim(
            SimpleNamespace(_arrays=fields, _sync_temp_scale=True, _shared_pressure_scale=True)
        )
        assert panel._global_clim == previous_clim
        assert panel.colorbar.colormap() == resolve_cmap('Ta')
        assert panel.colorbar.value_range() == pytest.approx(previous_clim['Ta'])

        for i, key in enumerate(fields):
            np.testing.assert_array_equal(panel._arrays[key], fields[key])
            assert panel.select_field(key)
            assert panel.active_field() == key
            assert len(panel._volume_grids) == i + 1
            surface_calls = [
                call for call in panel.plotter.add_mesh.call_args_list
                if call.kwargs.get('name') == 'main_surface'
            ]
            assert surface_calls[-1].kwargs['cmap'] == resolve_cmap(key)
            assert panel.colorbar.colormap() == resolve_cmap(key)
            np.testing.assert_allclose(panel._grid_vol[key], initial_values + 100. * i)
            np.testing.assert_array_equal(panel._grid_vol.points, display_points)
            restored = panel._grid_vol[key].reshape(panel._grid_vol.dimensions, order='F')[1:-1, 1:-1, 1:-1]
            np.testing.assert_array_equal(restored, fields[key])

        first_tb = panel._volume_grids['Tb'][0]
        assert panel.select_field('Tb')
        assert panel._grid_vol is first_tb
        assert len(panel._volume_grids) == len(fields)

        # Switching to volume mode reuses cached display grid and calls add_volume.
        panel.set_display_mode('volume')
        assert panel.plotter.add_volume.call_args.kwargs['scalars'] == 'Tb'
        assert panel.plotter.add_volume.call_args.kwargs['cmap'] == resolve_cmap('Tb')

        # New result discards old display caches while keeping a still-available selection.
        ThreeDVisPanel.set_fields(panel, **{k: v + 1 for k, v in fields.items()},
                                  dx=widths[0], dy=widths[1], dz=widths[2])
        assert panel._field == 'Tb' and set(panel._volume_grids) == {'Tb'}
        assert panel._grid_vol is not first_tb
        np.testing.assert_allclose(panel._grid_vol['Tb'], initial_values + 101.)
        ThreeDVisPanel.set_fields(panel, Ta=base[:2], dx=widths[0][:2],
                                  dy=widths[1], dz=widths[2])
        assert panel._field == 'Ta' and set(panel._volume_grids) == {'Ta'}
        assert panel._grid_vol.dimensions == (4, 5, 4)
        assert set(panel._arrays) == {'Ta'}
    finally:
        panel.colorbar.deleteLater()


@pytest.mark.parametrize('flow_options', [{}, {'flow_dir': None}])
def test_design_surface_slice_volume_keep_independent_ranges_and_optional_arrows(flow_options):
    """A real nonuniform L/t grid needs no solved fields or OpenGL context."""
    panel = _make_stub_panel()
    try:
        widths = [np.array(values) for values in
                  ([.003, .006, .004, .009], [.002, .005, .008], [.004, .007])]
        centres = [1000. * (np.cumsum(values) - values / 2) for values in widths]
        x, y, z = np.meshgrid(*centres, indexing='ij')
        fields = {'L_mm': 4. + .06 * x + .04 * y + .03 * z,
                  't_mm': .3 + .004 * x + .002 * y + .001 * z}
        ThreeDVisPanel.set_fields(panel, **fields, dx=widths[0], dy=widths[1], dz=widths[2],
                                  **flow_options)

        assert panel._available_fields == ('L_mm', 't_mm')
        assert panel._field == 'L_mm'
        arrows = [call.kwargs['name'] for call in panel.plotter.add_mesh.call_args_list
                  if call.kwargs.get('name', '').startswith('_flow_')]
        assert arrows == ([] if flow_options else ['_flow_inlet_A', '_flow_outlet_A'])
        assert panel._flow_dir == (None if flow_options else '+x')

        for key, values in fields.items():
            np.testing.assert_array_equal(panel._arrays[key], values)
            expected_range = (float(values.min()), float(values.max()))
            assert panel._global_clim[key] == pytest.approx(expected_range)
            assert panel.select_field(key)
            panel.plotter.add_mesh.reset_mock()
            panel.set_display_mode('slice')
            slice_calls = {
                call.kwargs['name']: call
                for call in panel.plotter.add_mesh.call_args_list
                if call.kwargs.get('name') in ('slice_x', 'slice_y', 'slice_z')
            }
            assert set(slice_calls) == {'slice_x', 'slice_y', 'slice_z'}
            for call in slice_calls.values():
                assert call.kwargs['scalars'] == key
                assert call.kwargs['clim'] == pytest.approx(expected_range)
                assert call.kwargs['cmap'] == resolve_cmap(key)
                assert call.args[0].n_points > 0 and key in call.args[0].point_data
            panel.set_display_mode('volume')
            volume = panel.plotter.add_volume.call_args
            assert volume.kwargs['scalars'] == key
            assert volume.kwargs['cmap'] == resolve_cmap(key)
            assert volume.kwargs['clim'] == pytest.approx(expected_range)

        try:
            set_cmap('design', 'cividis')
            panel.set_display_mode('slice')
            panel.plotter.add_mesh.reset_mock()
            panel.refresh_colormaps()
            slice_cmaps = {
                call.kwargs['cmap']
                for call in panel.plotter.add_mesh.call_args_list
                if call.kwargs.get('name') in ('slice_x', 'slice_y', 'slice_z')
            }
            assert slice_cmaps == {'cividis'}
            assert panel.colorbar.colormap() == 'cividis'
        finally:
            set_cmap('design', None)
    finally:
        panel.colorbar.deleteLater()


@pytest.mark.parametrize('widths', [
    ([1., 9.], [2., 5., 1.], [3., 7.]),
    ([2., 2.], [3., 3., 3.], [4.]),
    tuple(np.geomspace(.1, 2., 70) for _ in range(3)),
])
def test_volume_interpolation_preserves_physical_affine_field(widths):
    """An analytic field supplies an oracle independent of the resampler."""
    widths = [np.asarray(w) for w in widths]
    centres = [np.cumsum(w) - w / 2 for w in widths]
    x, y, z = np.meshgrid(*centres, indexing='ij')
    panel = SimpleNamespace(
        _volume_grids={}, _field='Ta', _arrays={'Ta': 5. + 2 * x - 3 * y + 4 * z},
        _dx_mm=widths[0], _dy_mm=widths[1], _dz_mm=widths[2],
        _L_mm=tuple(w.sum() for w in widths),
        _grid=pv.RectilinearGrid(*[np.r_[0., c, w.sum()] for c, w in zip(centres, widths)]),
    )
    grid, _ = ThreeDVisPanel._build_volume_grid(panel)
    physical = [np.clip(grid.points[:, i], c[0], c[-1]) for i, c in enumerate(centres)]
    expected = 5. + 2 * physical[0] - 3 * physical[1] + 4 * physical[2]
    np.testing.assert_allclose(grid['Ta'], expected, rtol=0, atol=1e-12)
    fractions = np.array([.17, .43, .89])[:, None]
    points = np.array([c[0] for c in centres]) + fractions * np.array([np.ptp(c) for c in centres])
    sampled = pv.PolyData(points).sample(grid)
    assert sampled['vtkValidPointMask'].all()
    np.testing.assert_allclose(
        sampled['Ta'], 5. + 2 * points[:, 0] - 3 * points[:, 1] + 4 * points[:, 2],
        rtol=0, atol=1e-10,
    )


@pytest.mark.parametrize('scale_mode', ['local', 'global'])
def test_three_orthogonal_slices_snap_to_actual_cells_and_batch_render(scale_mode):
    panel = _make_stub_panel()
    try:
        arr = np.arange(12., dtype=float).reshape(2, 3, 2) + 300.0
        ThreeDVisPanel.set_fields(
            panel,
            Ta=arr,
            dx=np.array([0.001, 0.009]),
            dy=np.array([0.002, 0.005, 0.001]),
            dz=np.array([0.003, 0.007]),
        )
        panel._scale_mode = scale_mode
        panel.set_display_mode('slice')
        panel.plotter.render.reset_mock()
        panel.plotter.add_mesh.reset_mock()

        panel.set_slice_position(6.0, 4.2, 6.2)
        assert panel._slice_xyz_mm == pytest.approx((5.5, 4.5, 6.5))
        panel.plotter.render.assert_called_once_with()

        sliced = {
            call.kwargs['name']: call
            for call in panel.plotter.add_mesh.call_args_list
            if call.kwargs.get('name') in ('slice_x', 'slice_y', 'slice_z')
        }
        assert set(sliced) == {'slice_x', 'slice_y', 'slice_z'}
        np.testing.assert_allclose(sliced['slice_x'].args[0].points[:, 0], 5.5)
        np.testing.assert_allclose(sliced['slice_y'].args[0].points[:, 1], 4.5)
        np.testing.assert_allclose(sliced['slice_z'].args[0].points[:, 2], 6.5)

        if scale_mode == 'local':
            expected_lo = min(arr[1, :, :].min(), arr[:, 1, :].min(), arr[:, :, 1].min())
            expected_hi = max(arr[1, :, :].max(), arr[:, 1, :].max(), arr[:, :, 1].max())
        else:
            expected_lo, expected_hi = float(arr.min()), float(arr.max())
        assert panel.colorbar.value_range() == pytest.approx((expected_lo, expected_hi))
    finally:
        panel.colorbar.deleteLater()


def test_unified_toolbar_omits_cutaway_and_toggles_conditional_groups():
    assert DISPLAY_MODES == ('surface', 'slice', 'volume')
    bar = VolumeToolbar(
        geometry_mode='simple',
        display_mode='surface',
        lattice_enabled=False,
        lattice_disabled_reason='pending PR 7',
    )
    try:
        assert bar.display_mode() == 'surface'
        assert not bar._display_group.isHidden()
        assert bar._slice_group.isHidden()
        assert bar._opacity_group.isHidden()
        assert bar._detail_group.isHidden()
        assert not bar.lattice_enabled()

        bar.set_display_mode('slice')
        assert not bar._slice_group.isHidden()
        assert bar._opacity_group.isHidden()

        # Editing one axis on a fine 0.04 mm grid keeps the other two axes unchanged.
        bar.set_slice_decimals((2, 2, 2))
        bar.set_slice_position(0.06, 0.06, 0.06)
        emitted = []
        bar.slice_position_changed.connect(lambda x, y, z: emitted.append((x, y, z)))
        bar._slice_edits[0].setText('0.14')
        bar._slice_edits[0].editingFinished.emit()
        assert emitted == [(0.14, 0.06, 0.06)]
        assert bar.slice_position() == (0.14, 0.06, 0.06)

        bar.set_display_mode('volume')
        assert bar._slice_group.isHidden()
        assert not bar._opacity_group.isHidden()
    finally:
        bar.close()
        bar.deleteLater()

    # Narrow-span colorbar ticks stay distinct; uniform fields show one value.
    narrow_cb = StudioColorbarCard(vmin=300.000, vmax=300.012)
    uniform_cb = StudioColorbarCard(vmin=7.0, vmax=7.0 + 7e-6)
    try:
        narrow_labels = narrow_cb.tick_labels()
        assert len(narrow_labels) >= 2 and len(set(narrow_labels)) == len(narrow_labels)
        assert uniform_cb.tick_labels() == ['7']
    finally:
        narrow_cb.deleteLater()
        uniform_cb.deleteLater()


def test_port_chip_overlay_avoids_arrow_and_colorbar_obstacles():
    vp = QSize(1200, 720)
    colorbar = QRect(1068, 130, 112, 460)
    rect = place_port_chip(
        outer=(1050.0, 360.0),
        chip_size=(76, 26),
        viewport_size=vp,
        inner=(980.0, 360.0),
        obstacles=[colorbar],
    )
    assert not rect.intersects(colorbar)

    overlay = PortChipOverlay()
    try:
        overlay.resize(vp)
        overlay.set_obstacles([colorbar])
        overlay.set_anchors([
            PortAnchor('A-inlet', 'A 入口', 'A', outer=(180.0, 420.0), inner=(260.0, 405.0)),
            PortAnchor('A-outlet', 'A 出口', 'A', outer=(1040.0, 360.0), inner=(980.0, 365.0)),
            PortAnchor('B-inlet', 'B 入口', 'B', outer=(720.0, 160.0), inner=(720.0, 225.0)),
            PortAnchor('B-outlet', 'B 出口', 'B', outer=(360.0, 560.0), inner=(360.0, 500.0)),
        ])
        geoms = overlay.chip_geometries()
        assert set(geoms) == {'A-inlet', 'A-outlet', 'B-inlet', 'B-outlet'}
        for chip_rect in geoms.values():
            assert not chip_rect.intersects(colorbar)
            assert overlay.rect().contains(chip_rect)
    finally:
        overlay.close()
        overlay.deleteLater()


def test_camera_preset_uses_shared_reduced_motion_preference():
    previous = is_reduced_motion()
    camera = SimpleNamespace(
        position=(0.0, 0.0, 100.0),
        focal_point=(0.0, 0.0, 0.0),
        up=(0.0, 1.0, 0.0),
        view_angle=27.0,
    )
    plotter = Mock()
    plotter.camera = camera
    plotter.view_xy.side_effect = lambda render=False: setattr(camera, 'position', (0.0, 0.0, 200.0))
    panel = SimpleNamespace(
        plotter=plotter,
        _L_mm=(182.0, 42.0, 42.0),
        _tween_animation=None,
        _tween_end_pose=None,
        _tween_previous_update_rate=None,
        toolbar=Mock(),
        isVisible=lambda: True,
        fit_view=Mock(),
        _stop_camera_tween=Mock(),
        _update_port_chips=Mock(),
    )
    try:
        set_reduced_motion(True)
        ThreeDVisPanel.set_view(panel, 'xy')
        assert panel._tween_animation is None
        plotter.render.assert_called_once_with()
        panel.toolbar.set_camera_preset.assert_called_once_with('xy')
        panel._update_port_chips.assert_called_once_with()
    finally:
        set_reduced_motion(previous)


def test_shared_header_colormap_refresh_updates_main_and_optimization_3d_panels(monkeypatch):
    """Colormap popover propagation refreshes both canvas_3d and optimization.volume_panel."""
    import sjtu_tpmshx.applications.gui.ui.layout_drawer as layout_drawer
    import sjtu_tpmshx.applications.gui.ui.plot_2d_results as plot_2d_results
    from sjtu_tpmshx.applications.gui.ui.builders_canvas import _apply_colormap_refresh

    monkeypatch.setattr(plot_2d_results, 'redraw_result_fields', Mock())
    monkeypatch.setattr(layout_drawer, 'refresh_last_2d_thumbnail', Mock())
    main_3d = SimpleNamespace(refresh_colormaps=Mock())
    opt_3d = SimpleNamespace(refresh_colormaps=Mock())
    window = SimpleNamespace(
        canvas_3d=main_3d,
        optimization=SimpleNamespace(volume_panel=opt_3d),
    )

    _apply_colormap_refresh(window)

    main_3d.refresh_colormaps.assert_called_once_with()
    opt_3d.refresh_colormaps.assert_called_once_with()

    # Single-fluid phase checks reject missing Fluid B without falling back to A.
    from sjtu_tpmshx.applications.gui.ui.builders_canvas import _resolve_3d_panel_field

    assert _resolve_3d_panel_field({'Ta'}, 'temperature', 'B', exact_phase=True) is None
    assert _resolve_3d_panel_field({'Ta'}, 'temperature', 'B', exact_phase=False) == 'Ta'

    # Render failure on field switch returns False, does not emit field_changed, hides colorbar.
    stub = _make_stub_panel()
    try:
        arr = np.arange(8., dtype=float).reshape(2, 2, 2) + 300.0
        ThreeDVisPanel.set_fields(
            stub, Ta=arr, Tb=arr + 10.0,
            dx=np.array([0.001, 0.001]), dy=np.array([0.001, 0.001]), dz=np.array([0.001, 0.001]),
        )
        stub.field_changed.emit.reset_mock()
        stub._render_surface_actors = Mock(side_effect=RuntimeError('gpu failure'))
        assert not stub.select_field('Tb')
        stub.field_changed.emit.assert_not_called()
        assert stub._volume_actor is None
        assert stub.colorbar.isHidden()
        assert '三维渲染失败' in stub.status.setText.call_args.args[0]
        stub.status.show.assert_called()
    finally:
        stub.colorbar.deleteLater()
