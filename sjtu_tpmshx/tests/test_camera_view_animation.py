"""Camera preset transitions without constructing a VTK/OpenGL interactor."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid
from pyvista.plotting.plotter import BasePlotter

from sjtu_tpmshx.ui.panel_vis_3d import ThreeDVisPanel


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
            position=(2., 3., 4.), focal_point=(0., 0., 0.), up=(0., 1., 0.))
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
    animation = panel._tween_animation
    assert animation.duration() == 300
    # Advance the real driver's paused timeline as two delayed display updates.
    assert animation.state() == QAbstractAnimation.State.Paused
    animation.setCurrentTime(150)
    expected = tuple(a + (b - a) * .875 for a, b in zip(start[0], _POSES[preset][0]))
    assert panel.plotter.camera.position == pytest.approx(expected)
    animation.setCurrentTime(450)  # A late update goes straight to the end.
    assert _pose(panel.plotter.camera) == _POSES[preset]
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
    panel.show()
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
