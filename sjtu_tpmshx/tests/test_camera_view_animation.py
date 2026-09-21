"""Camera preset transitions without constructing a VTK/OpenGL interactor."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from shiboken6 import isValid
from pyvista.plotting.plotter import BasePlotter

from sjtu_tpmshx.ui.panel_vis_3d import ThreeDVisPanel
from sjtu_tpmshx.ui.responsive import ResponsiveRow


_POSES = {
    'top': ((0., 0., 10.), (0., 0., 0.), (0., 1., 0.)),
    'front': ((0., 10., 0.), (0., 0., 0.), (0., 0., 1.)),
    'side': ((10., 0., 0.), (0., 0., 0.), (0., 0., 1.)),
    'iso': ((10., 10., 10.), (0., 0., 0.), (0., 0., 1.)),
}


def _pose(camera):
    return camera.position, camera.focal_point, camera.up


class _CameraPanel(ThreeDVisPanel):
    def __init__(self):
        QWidget.__init__(self)
        self._tween_animation = None
        self._tween_end_pose = None
        self._tween_previous_update_rate = None
        self._popup_dialogs = []
        self._render_gated = False
        self._grid = object()
        self._sync_view_button = Mock()
        self.rendered = []
        self.rendered_rates = []
        self.plotter = Mock()
        self.plotter.render_timer = QTimer(self)
        self.plotter.render_timer.start(200)
        self._pause_rendering()
        self.update_rate = .0001
        self.plotter.ren_win.GetDesiredUpdateRate.side_effect = lambda: self.update_rate
        self.plotter.ren_win.SetDesiredUpdateRate.side_effect = lambda rate: setattr(self, 'update_rate', rate)
        self.plotter.iren.interactor.GetDesiredUpdateRate.return_value = 120.0
        self.plotter.camera = SimpleNamespace(
            position=(2., 3., 4.), focal_point=(0., 0., 0.), up=(0., 1., 0.),
            view_angle=30.)
        self.plotter.renderer.ResetCameraScreenSpace.side_effect = (
            lambda _margin: setattr(self.plotter.camera, 'view_angle', 20.))
        def render():
            self.rendered.append(_pose(self.plotter.camera))
            self.rendered_rates.append(self.update_rate)
        self.plotter.render.side_effect = render
        for name, preset in (('view_xy', 'top'), ('view_xz', 'front'),
                             ('view_yz', 'side'), ('view_isometric', 'iso')):
            def view(*, render=True, key=preset):
                cam = self.plotter.camera
                cam.position, cam.focal_point, cam.up = _POSES[key]
                if render:
                    self.plotter.render()
            getattr(self.plotter, name).side_effect = view


@pytest.fixture
def camera_panel(monkeypatch):
    monkeypatch.delenv('QT_REDUCED_MOTION', raising=False)
    panel = _CameraPanel()
    panel.show()
    QApplication.processEvents()
    panel.rendered.clear()
    panel.rendered_rates.clear()
    yield panel
    panel.cleanup()
    panel.close()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('preset, method', [
    ('top', 'view_xy'), ('front', 'view_xz'), ('side', 'view_yz'), ('iso', 'view_isometric')])
def test_camera_target_does_not_render_and_late_frame_reaches_timed_endpoint(camera_panel, preset, method):
    panel = camera_panel
    start = _pose(panel.plotter.camera)
    panel._set_view(preset)
    getattr(panel.plotter, method).assert_called_once_with(render=False)
    assert not panel.rendered, 'sampling the target must not flash its pose'
    assert panel.update_rate == 120.0
    assert _pose(panel.plotter.camera) == start
    assert panel.plotter.camera.view_angle == 30., 'the fitted target must not flash its zoom'
    animation = panel._tween_animation
    assert animation.duration() == 300
    # Advance the real driver's paused timeline as two delayed display updates.
    assert animation.state() == QAbstractAnimation.State.Paused
    animation.setCurrentTime(150)
    expected = tuple(a + (b - a) * .875 for a, b in zip(start[0], _POSES[preset][0]))
    assert panel.plotter.camera.position == pytest.approx(expected)
    assert panel.plotter.camera.view_angle == pytest.approx(21.25)
    animation.setCurrentTime(450)  # A late update goes straight to the end.
    assert _pose(panel.plotter.camera) == _POSES[preset]
    assert panel.plotter.camera.view_angle == 20.
    assert len(panel.rendered) == 3, 'two motion updates and one restored-quality still frame'
    assert panel.rendered_rates == [120.0, 120.0, .0001]
    assert panel.update_rate == .0001
    assert panel._tween_animation is None
    panel._sync_view_button.assert_called_once_with(preset)


def test_new_preset_and_reduced_motion_cancel_previous_timeline(camera_panel, monkeypatch):
    panel = camera_panel
    panel._set_view('top')
    old = panel._tween_animation
    old.setCurrentTime(100)
    intermediate = _pose(panel.plotter.camera)
    renders_before_reentry = len(panel.rendered)
    panel._set_view('front')
    assert old.state() == QAbstractAnimation.State.Stopped
    assert _pose(panel.plotter.camera) == intermediate
    assert len(panel.rendered) == renders_before_reentry
    assert panel._tween_previous_update_rate == .0001
    assert panel.update_rate == 120.0
    replacement = panel._tween_animation
    monkeypatch.setenv('QT_REDUCED_MOTION', '1')
    panel._set_view('side')
    assert replacement.state() == QAbstractAnimation.State.Stopped
    assert panel._tween_animation is None
    assert panel.update_rate == .0001
    assert panel.rendered_rates[-1] == .0001
    assert _pose(panel.plotter.camera) == _POSES['side']
    panel._sync_view_button.assert_called_once_with('side')
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(old) and not isValid(replacement)


def test_hide_snaps_without_render_and_cleanup_stops_before_plotter_close(camera_panel):
    panel = camera_panel
    panel._set_view('front')
    animation = panel._tween_animation
    animation.setCurrentTime(50)
    n_rendered = len(panel.rendered)
    panel.hide()
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert panel._tween_animation is None
    assert _pose(panel.plotter.camera) == _POSES['front']
    assert len(panel.rendered) == n_rendered
    assert panel.update_rate == .0001
    panel._sync_view_button.assert_called_once_with('front')
    assert panel.plotter.suppress_rendering is True
    assert not panel.plotter.render_timer.isActive()

    panel.show()
    assert panel.plotter.suppress_rendering is False
    assert panel.plotter.render_timer.isActive()
    assert panel.plotter.render_timer.interval() == 200
    panel._set_view('iso')
    animation = panel._tween_animation
    n_rendered = len(panel.rendered)
    panel.plotter.close.side_effect = lambda: (
        pytest.fail('camera timeline still active during GL cleanup')
        if animation.state() != QAbstractAnimation.State.Stopped else None)
    panel.cleanup()
    assert panel._tween_animation is None
    assert panel.update_rate == .0001
    assert len(panel.rendered) == n_rendered
    panel.cleanup()
    panel.plotter.close.assert_called_once_with()


def test_drag_takes_over_preset_without_restoring_still_budget_or_rendering(camera_panel):
    panel = camera_panel
    panel._set_view('top')
    old = panel._tween_animation
    old.setCurrentTime(100)
    intermediate = _pose(panel.plotter.camera)
    n_rendered = len(panel.rendered)
    panel._cancel_preset_for_interaction(None, 'StartInteractionEvent')
    assert old.state() == QAbstractAnimation.State.Stopped
    assert panel._tween_animation is None
    assert panel._tween_previous_update_rate is None
    assert _pose(panel.plotter.camera) == intermediate
    assert panel.update_rate == 120.0
    assert len(panel.rendered) == n_rendered
    old.finished.emit()  # A stale completion must not overwrite the drag budget.
    assert panel.update_rate == 120.0
    assert len(panel.rendered) == n_rendered


def test_hidden_initialization_suppresses_real_plotter_render_until_show(monkeypatch):
    # Exercise PyVista's actual public suppress_rendering property and render
    # gate, replacing only the VTK/OpenGL objects with lightweight stand-ins.
    class Plotter(SimpleNamespace):
        suppress_rendering = BasePlotter.suppress_rendering
        render = BasePlotter.render

    def make_plotter(parent):
        plotter = Plotter(
            interactor=QWidget(parent), iren=None,
            render_timer=QTimer(parent), render_window=SimpleNamespace(Render=Mock()),
            renderers=SimpleNamespace(on_plotter_render=Mock()), _first_time=False,
            _suppress_rendering=False, _on_render_callbacks=[],
            set_background=Mock(), close=Mock())
        plotter.render_timer.timeout.connect(plotter.render)
        plotter.render_timer.start(200)
        return plotter

    monkeypatch.setattr('sjtu_tpmshx.ui.panel_vis_3d.QtInteractor', make_plotter)
    monkeypatch.setattr(ThreeDVisPanel, '_build_toolbar', lambda self, root: 50)
    monkeypatch.setattr(ThreeDVisPanel, '_init_timers', lambda self: None)
    monkeypatch.setattr(ThreeDVisPanel, '_setup_hover', lambda self: None)
    monkeypatch.setattr(ThreeDVisPanel, '_render_placeholder', lambda self: self.plotter.render())
    panel = ThreeDVisPanel()
    plotter = panel.plotter
    assert not panel.isVisible()
    assert panel._render_gated and plotter.suppress_rendering
    assert not plotter.render_timer.isActive()
    plotter.render_window.Render.assert_not_called()
    panel.status.setText('Field: Temperature A | Range: 300–420 K | Domain: 182 × 42 × 42 mm | ' * 3)
    panel.resize(500, 420)
    panel.show()
    QApplication.processEvents()
    assert panel.width() == 500, 'status metadata must not enlarge the viewport'
    assert not panel._render_gated and not plotter.suppress_rendering
    assert plotter.render_timer.isActive() and plotter.render_timer.interval() == 200
    plotter.render_window.Render.assert_called_once_with()
    panel.hide()
    plotter.render()  # A queued render after hide must also be suppressed.
    assert panel._render_gated and plotter.suppress_rendering
    assert not plotter.render_timer.isActive()
    plotter.render_window.Render.assert_called_once_with()
    panel.show()
    assert plotter.render_timer.isActive() and plotter.render_timer.interval() == 200
    assert plotter.render_window.Render.call_count == 2
    panel.cleanup()
    panel.close()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('size', [(1200, 300), (500, 900), (1200, 800)])
@pytest.mark.parametrize('extent', [(42., 42., 42.), (182., 42., 42.), (350., 30., 15.)])
def test_native_camera_fit_frames_viewport_without_changing_orientation(size, extent):
    """Actual VTK projection, without requiring an OpenGL context."""
    from itertools import product
    import numpy as np
    from vtkmodules.vtkFiltersSources import vtkCubeSource
    from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper, vtkRenderer
    from vtkmodules.vtkRenderingOpenGL2 import vtkGenericOpenGLRenderWindow

    window = vtkGenericOpenGLRenderWindow()
    window.SetSize(*size)
    renderer = vtkRenderer()
    window.AddRenderer(renderer)
    cube = vtkCubeSource()
    cube.SetBounds(0, extent[0], 0, extent[1], 0, extent[2])
    mapper = vtkPolyDataMapper()
    mapper.SetInputConnection(cube.GetOutputPort())
    actor = vtkActor()
    actor.SetMapper(mapper)
    renderer.AddActor(actor)
    camera = renderer.GetActiveCamera()
    camera.SetPosition(1, 1, 1)
    camera.SetFocalPoint(0, 0, 0)
    camera.SetViewUp(0, 0, 1)
    renderer.ResetCamera()
    direction, up = camera.GetDirectionOfProjection(), camera.GetViewUp()
    panel = SimpleNamespace(
        _grid=object(), _stop_camera_tween=Mock(), isVisible=lambda: True,
        plotter=SimpleNamespace(renderer=renderer, render=Mock()))
    ThreeDVisPanel.fit_view(panel)
    assert camera.GetDirectionOfProjection() == pytest.approx(direction)
    assert camera.GetViewUp() == pytest.approx(up)
    points = []
    for point in product(*[(0., length) for length in extent]):
        renderer.SetWorldPoint(*point, 1.)
        renderer.WorldToDisplay()
        points.append(renderer.GetDisplayPoint()[:2])
    projected = np.asarray(points) / size
    assert np.all(projected >= .05) and np.all(projected <= .95)
    assert .65 <= np.ptp(projected, axis=0).max() <= .85
    assert not panel._camera_fit_pending
    panel.plotter.render.assert_called_once_with()


def test_hidden_fit_waits_for_show_and_resize_preserves_manual_view(camera_panel):
    panel = camera_panel
    panel._grid = object()
    panel.hide()
    panel.fit_view()
    assert panel._camera_fit_pending
    panel.plotter.renderer.ResetCameraScreenSpace.assert_not_called()
    panel.show()
    QApplication.processEvents()
    panel.plotter.renderer.ResetCameraScreenSpace.assert_called_once_with(.8)
    assert not panel._camera_fit_pending
    panel.plotter.camera.position = (12., 7., 9.)
    panel.resize(700, 380)
    QApplication.processEvents()
    assert panel.plotter.camera.position == (12., 7., 9.)
    assert panel.plotter.renderer.ResetCameraScreenSpace.call_count == 1


def test_fit_toolbar_uses_current_orientation():
    from sjtu_tpmshx.ui.builders_canvas import canvas_zoom_reset
    panel = SimpleNamespace(fit_view=Mock(), _set_view=Mock())
    canvas_zoom_reset(SimpleNamespace(_active_tab='3d', canvas_3d=panel))
    panel.fit_view.assert_called_once_with()
    panel._set_view.assert_not_called()


@pytest.mark.parametrize('width', [500, 650, 1100])
@pytest.mark.parametrize('wide_hints', [False, True])
def test_volume_toolbar_groups_fit_narrow_and_wide_panels(width, wide_hints):
    class Toolbar(ThreeDVisPanel):
        def __init__(self):
            QWidget.__init__(self)
            self._build_toolbar(QVBoxLayout(self))

        showEvent = QWidget.showEvent
        hideEvent = QWidget.hideEvent

    panel = Toolbar()
    panel.resize(width, 230)
    panel.combo_field.blockSignals(True)
    panel.combo_field.addItem('Temperature A')
    panel.lbl_coord.setText('Z coord (0–182.0 mm):')
    if wide_hints:
        # A native style can require wider controls even at the same font size.
        # Each semantic group fits 500 px; the old unbreakable pairs do not.
        for control, minimum in (
                (panel.combo_field, 280), (panel.combo_plane, 220),
                (panel.lbl_coord, 260), (panel.btn_view_top, 62),
                (panel.btn_view_front, 62), (panel.btn_view_side, 62),
                (panel.btn_view_iso, 62), (panel.btn_shot, 240)):
            control.setMinimumWidth(minimum)
    panel.show()
    for _ in range(3):
        QApplication.processEvents()
    group_hints = {
        row.objectName(): {
            'direction': row.direction.name,
            'width': row.width(),
            'minimum': row.minimumSizeHint().width(),
            'children': [
                (row.layout().itemAt(i).minimumSize().width(),
                 row.layout().itemAt(i).sizeHint().width())
                for i in range(row.layout().count())
            ],
        }
        for row in panel.findChildren(ResponsiveRow)
    }
    assert panel.width() == width, (
        'toolbar minimum hints must allow the requested width', group_hints)
    controls = [panel.combo_field, panel.combo_plane, panel.le_coord,
                panel.slider_opacity, panel.btn_apply, panel.btn_clear,
                panel.btn_clim, panel.btn_view_top, panel.btn_view_front,
                panel.btn_view_side, panel.btn_view_iso, panel.btn_shot,
                *panel.findChildren(QLabel)]
    for control in controls:
        rect = control.rect().translated(control.mapTo(panel, QPoint()))
        assert panel.rect().contains(rect), (width, control, rect, group_hints)
        assert control.width() >= control.minimumSizeHint().width(), (
            width, control, control.width(), control.minimumSizeHint().width(),
            group_hints)
    panel.close()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
