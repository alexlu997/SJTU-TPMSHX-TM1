"""Exercise the real volume builder without an OpenGL context."""
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pyvista as pv
import pytest
from PySide6.QtWidgets import QComboBox

from sjtu_tpmshx.ui.panel_vis_3d import FIELD_META, ThreeDVisPanel


@pytest.mark.parametrize('render', [True, False])
@pytest.mark.parametrize('field', ['Ta', 'unknown'])
def test_volume_builder_defers_intermediate_render(render, field):
    requests = []
    actor, bar = Mock(), Mock()
    plotter = Mock(window_size=(1000, 800))
    plotter.render.side_effect = lambda: requests.append('render')

    def mutation(*args, render=True, **kwargs):
        if render:
            plotter.render()

    def volume(*args, render=True, **kwargs):
        mutation(render=render)
        return actor

    plotter.remove_actor.side_effect = mutation
    plotter.remove_scalar_bar.side_effect = mutation
    plotter.add_volume.side_effect = volume
    plotter.add_scalar_bar.return_value = bar  # PyVista defaults render=False
    grid = object()
    panel = SimpleNamespace(
        _grid=grid, _grid_vol=grid, _field=field, plotter=plotter,
        _volume_actor=actor,
        _clim_for=lambda field: (300., 420.), _opacity_ramp=lambda: (.2, .5),
        _build_volume_grid=lambda: (grid, 1.), _vol_min_cell_mm=1., status=Mock(),
    )
    ThreeDVisPanel._rebuild_volume(panel, render=render)

    assert requests == (['render'] if render else [])
    plotter.remove_actor.assert_called_once_with('main_volume', render=False)
    assert plotter.remove_scalar_bar.call_count == 1 + len(FIELD_META)
    if field == 'unknown':
        assert panel._volume_actor is None
        plotter.add_volume.assert_not_called()
        plotter.add_scalar_bar.assert_not_called()
        return
    assert panel._volume_actor is actor
    args, kwargs = plotter.add_volume.call_args
    assert args == (grid,)
    assert kwargs['scalars'] == 'Ta'
    assert kwargs['clim'] == (300., 420.)
    assert kwargs['opacity'] == [.2, .5]
    assert kwargs['cmap'] == FIELD_META['Ta']['cmap']
    assert kwargs['name'] == 'main_volume' and not kwargs['show_scalar_bar']
    assert plotter.add_scalar_bar.call_count == 1
    assert plotter.add_scalar_bar.call_args.kwargs['title'] == FIELD_META['Ta']['title']
    assert plotter.add_scalar_bar.call_args.kwargs['vertical'] is True
    actor.GetMapper().SetAutoAdjustSampleDistances.assert_called_once_with(True)
    bar.SetLookupTable.assert_called_once()
    panel.status.setText.assert_not_called()


@pytest.mark.parametrize('render', [False, True])
def test_slice_builder_defers_mesh_render(render):
    grid = pv.RectilinearGrid([0., 1., 2.], [0., 1.], [0., 1.])
    grid.point_data['Ta'] = np.linspace(300., 420., grid.n_points)
    plotter = Mock()

    def mutation(*args, render=True, **kwargs):
        if render:
            plotter.render()

    plotter.remove_actor.side_effect = mutation
    plotter.add_mesh.side_effect = mutation
    panel = SimpleNamespace(
        _grid=grid, _field='Ta', _slice_actor_name='slice', plotter=plotter,
        _clim_for=lambda field: (300., 420.), status=Mock(),
    )
    ThreeDVisPanel._add_slice_actor(panel, 'x', .5, render=render)
    assert plotter.add_mesh.call_args.args[0].n_points > 0
    assert plotter.render.call_count == int(render)
    panel.status.setText.assert_not_called()


def test_initial_scene_defers_mesh_and_camera_render():
    plotter = Mock()

    def mutation(*args, render=True, **kwargs):
        if render:
            plotter.render()

    plotter.add_mesh.side_effect = mutation
    plotter.view_isometric.side_effect = mutation
    panel = SimpleNamespace(
        plotter=plotter, _grid=Mock(), _L_mm=(182., 42., 42.),
        _flow_dir='+x', _flow_dir_B='+y', _arrays={'Ta': object(), 'Tb': object()},
    )
    panel._add_flow_glyph = lambda: ThreeDVisPanel._add_flow_glyph(panel)
    ThreeDVisPanel._render_initial_scene(panel)

    plotter.clear.assert_called_once_with()
    assert plotter.add_mesh.call_count == 5
    outline, *arrows = plotter.add_mesh.call_args_list
    assert outline.args == (panel._grid.outline.return_value,)
    assert outline.kwargs['line_width'] == 2
    assert [call.kwargs['name'] for call in arrows] == [
        '_flow_inlet_A', '_flow_outlet_A', '_flow_inlet_B', '_flow_outlet_B',
    ]
    assert [call.kwargs['opacity'] for call in arrows] == [.55, .55, .45, .45]
    assert all(call.args[0].n_points > 0 for call in arrows)
    assert all(not call.kwargs['show_scalar_bar'] for call in arrows)
    plotter.show_bounds.assert_called_once()
    plotter.add_axes.assert_called_once()
    plotter.view_isometric.assert_called_once_with(render=False)
    plotter.camera.zoom.assert_not_called()
    plotter.render.assert_not_called()


def test_hover_and_opacity_work_without_vtk_compatibility_aggregator(monkeypatch):
    """The bundle keeps vtkmodules, without the import-everything vtk shim."""
    import sys
    import vtkmodules.vtkRenderingCore as rendering

    monkeypatch.setitem(sys.modules, 'vtk', None)
    picker = Mock()
    picker.GetActor.return_value = None
    monkeypatch.setattr(rendering, 'vtkPropPicker', lambda: picker)
    plotter = Mock()
    actor = rendering.vtkVolume()
    panel = SimpleNamespace(
        _grid=object(), _last_hover_text='', plotter=plotter,
        _volume_actor=actor, _field='Ta', _clim_for=lambda _: (300., 420.),
        _opacity_ramp=lambda: (.2, .6), _rebuild_volume=Mock(),
    )
    event = Mock()
    event.GetEventPosition.return_value = (4, 5)
    ThreeDVisPanel._on_mouse_move(panel, event, None)
    picker.Pick.assert_called_once_with(4, 5, 0, plotter.renderer)

    ThreeDVisPanel._apply_opacity_now(panel)
    opacity = actor.GetProperty().GetScalarOpacity()
    assert opacity.GetValue(360.) == pytest.approx(.4)
    plotter.render.assert_called_once_with()
    panel._rebuild_volume.assert_not_called()


@pytest.mark.parametrize('graded', [False, True])
def test_volume_fields_are_lazy_cached_and_reset_without_changing_values(monkeypatch, graded):
    """Real VTK data and Qt selection; no graphics context is needed."""
    from scipy import interpolate

    panel = SimpleNamespace(plotter=Mock(window_size=(1000, 800)), status=Mock())
    ThreeDVisPanel._init_state(panel, 30)
    panel.combo_field = QComboBox()
    for name in ('combo_plane', 'le_coord', 'btn_apply', 'btn_clim', 'btn_shot',
                 'slider_opacity', 'btn_view_top', 'btn_view_front',
                 'btn_view_side', 'btn_view_iso', 'btn_clear'):
        setattr(panel, name, Mock())
    for name in ('_render_initial_scene', 'fit_view', '_update_coord_label',
                 '_validate_coord_input', '_update_status'):
        setattr(panel, name, Mock())
    for name in ('_build_volume_grid', '_build_global_clim', '_rebuild_volume',
                 '_clim_for', '_opacity_ramp'):
        setattr(panel, name, MethodType(getattr(ThreeDVisPanel, name), panel))
    interpolations = Mock(wraps=interpolate.RegularGridInterpolator)
    monkeypatch.setattr(interpolate, 'RegularGridInterpolator', interpolations)
    base = np.arange(24., dtype=float).reshape(4, 3, 2)
    fields = {key: base + 100. * i for i, key in enumerate(FIELD_META)}
    widths = [np.linspace(.0002, .001, n) if graded else np.full(n, .001)
              for n in base.shape]
    ThreeDVisPanel.set_fields(panel, **fields, dx=widths[0], dy=widths[1], dz=widths[2])

    # Only the initial field gets a high-resolution allocation. Low-resolution
    # fields remain complete for identical shared color limits, hover and slices.
    assert set(panel._volume_grids) == {'Ta'}
    assert set(panel._grid_vol.point_data) == {'Ta'}
    assert interpolations.call_count == 1
    edges = [np.r_[0., np.cumsum(w * 1000.)] for w in widths]
    raw = pv.RectilinearGrid(*edges)
    for key, values in fields.items():
        raw.cell_data[key] = values.flatten(order='F')
    raw = raw.cell_data_to_point_data()
    initial_values = panel._grid_vol['Ta'].copy()
    display_points = panel._grid_vol.points.copy()
    np.testing.assert_array_equal(panel._grid.points, raw.points)
    previous_clim = ThreeDVisPanel._build_global_clim(
        SimpleNamespace(_grid=raw, _arrays=fields))
    assert panel._global_clim == previous_clim
    for i, key in enumerate(fields):
        np.testing.assert_array_equal(panel._grid[key], raw[key])
        ThreeDVisPanel._on_field_changed(panel, panel.combo_field.findData(key))
        np.testing.assert_allclose(panel._grid_vol[key], initial_values + 100. * i)
        np.testing.assert_array_equal(panel._grid_vol.points, display_points)
    assert interpolations.call_count == len(fields)
    first_tb = panel._volume_grids['Tb'][0]
    ThreeDVisPanel._on_field_changed(panel, panel.combo_field.findData('Tb'))
    assert panel._grid_vol is first_tb
    assert interpolations.call_count == len(fields)
    actual_slice = panel._grid.slice(normal='z', origin=panel._grid.center)
    expected_slice = raw.slice(normal='z', origin=raw.center)
    np.testing.assert_array_equal(actual_slice['Tb'], expected_slice['Tb'])

    # Same resolution/new result and a subsequent different resolution both
    # discard old display grids while restoring a still-available selection.
    ThreeDVisPanel.set_fields(panel, **{k: v + 1 for k, v in fields.items()},
                             dx=widths[0], dy=widths[1], dz=widths[2])
    assert panel._field == 'Tb' and set(panel._volume_grids) == {'Tb'}
    assert panel._grid_vol is not first_tb
    np.testing.assert_allclose(panel._grid_vol['Tb'], initial_values + 101.)
    ThreeDVisPanel.set_fields(panel, Ta=base[:2], dx=widths[0][:2],
                             dy=widths[1], dz=widths[2])
    assert panel._field == 'Ta' and set(panel._volume_grids) == {'Ta'}
    assert panel._grid_vol.dimensions == (7, 10, 7)
    assert set(panel._arrays) == {'Ta'}
    panel.combo_field.deleteLater()


@pytest.mark.parametrize('widths', [
    ([1., 9.], [2., 5., 1.], [3., 7.]),
    ([2., 2.], [3., 3., 3.], [4.]),
])
def test_volume_interpolation_preserves_physical_affine_field(widths):
    """An analytic field supplies an oracle independent of the resampler."""
    widths = [np.asarray(w) for w in widths]
    centres = [np.cumsum(w) - w / 2 for w in widths]
    x, y, z = np.meshgrid(*centres, indexing='ij')
    panel = SimpleNamespace(
        _volume_grids={}, _field='Ta', _arrays={'Ta': 5. + 2*x - 3*y + 4*z},
        _dx_mm=widths[0], _dy_mm=widths[1], _dz_mm=widths[2],
        _L_mm=tuple(w.sum() for w in widths),
    )
    grid, _ = ThreeDVisPanel._build_volume_grid(panel)
    # Exterior half cells use constant extension; all interior display points
    # must retain the exact physical linear field, including graded axes.
    physical = [np.clip(grid.points[:, i], c[0], c[-1])
                for i, c in enumerate(centres)]
    expected = 5. + 2*physical[0] - 3*physical[1] + 4*physical[2]
    np.testing.assert_allclose(grid['Ta'], expected, rtol=0, atol=1e-12)


@pytest.mark.parametrize('method', ['_on_apply_slice_realtime', '_on_apply_slice'])
@pytest.mark.parametrize('scale_mode', ['local', 'global'])
def test_slice_change_batches_matching_volume_and_slice_ranges(method, scale_mode):
    events = []
    panel = SimpleNamespace(
        _grid=object(), _scale_mode=scale_mode, _field='Ta',
        _L_mm=(2., 2., 2.), _slice_info={'axis': 'z', 'coord_mm': .25},
        _arrays={'Ta': np.array([[[1., 10.], [3., 30.]]])},
        _global_clim={'Ta': (1., 30.)}, _slice_index=lambda axis, coord: int(coord),
        _current_axis=lambda: 'z', btn_apply=Mock(), btn_clear=Mock(),
        le_coord=Mock(), combo_plane=Mock(), _coord_debounce=Mock(),
        _show_slice_popup=Mock(), _update_status=Mock(), plotter=Mock(),
    )
    panel.le_coord.text.return_value = '1.5'
    panel.combo_plane.currentData.return_value = 'xy'
    panel._clim_for = MethodType(ThreeDVisPanel._clim_for, panel)
    panel._rebuild_volume = lambda *, render: events.append(('volume', panel._clim_for('Ta'), render))
    panel._add_slice_actor = lambda axis, coord, *, render: events.append(('slice', panel._clim_for('Ta'), render))
    getattr(ThreeDVisPanel, method)(panel)
    expected = (10., 30.) if scale_mode == 'local' else (1., 30.)
    assert events == ([('volume', expected, False)] if scale_mode == 'local' else []) + [
        ('slice', expected, False)]
    panel.plotter.render.assert_called_once_with()


def test_volume_without_upsampling_keeps_raw_grid():
    grid = object()
    widths = np.linspace(.1, 2., 70)
    panel = SimpleNamespace(
        _volume_grids={}, _field='Ta', _grid=grid,
        _arrays={'Ta': np.broadcast_to(1., (70, 70, 70))},
        _dx_mm=widths, _dy_mm=widths, _dz_mm=widths,
    )
    actual, minimum = ThreeDVisPanel._build_volume_grid(panel)
    assert actual is grid and minimum == pytest.approx(.1)
    assert panel._volume_grids == {}


def test_clear_local_slice_restores_global_volume_legend_once():
    panel = SimpleNamespace(
        _slice_info={'axis': 'z', 'coord_mm': 1.5}, _slice_actor_name='slice',
        _scale_mode='local', _global_clim={'Ta': (1., 30.)}, _arrays={'Ta': None},
        btn_clear=Mock(), _update_status=Mock(), plotter=Mock(),
    )
    ranges = []
    panel._rebuild_volume = lambda *, render: ranges.append(
        (ThreeDVisPanel._clim_for(panel, 'Ta'), render))
    ThreeDVisPanel._on_clear_slice(panel)
    assert panel._slice_info is None
    assert ranges == [((1., 30.), False)]
    panel.plotter.remove_actor.assert_called_once_with('slice', render=False)
    panel.plotter.render.assert_called_once_with()
