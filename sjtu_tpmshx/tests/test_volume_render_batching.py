"""Exercise the real volume builder without an OpenGL context."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

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
        _vol_min_cell_mm=1., status=Mock(),
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
