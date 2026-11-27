"""Manual color ranges keep field values intact and reach 3D overlays and exports."""
from unittest.mock import Mock

import numpy as np
import pyvista as pv
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from sjtu_tpmshx.applications.gui.ui.panel_vis_3d import ThreeDVisPanel
from sjtu_tpmshx.applications.gui.ui.theme import resolve_cmap, set_cmap
from sjtu_tpmshx.applications.gui.ui.vis3d_constants import validate_color_range_state
from sjtu_tpmshx.applications.gui.ui.volume_overlays import PortChipOverlay, StudioColorbarCard
from sjtu_tpmshx.applications.gui.ui.volume_toolbar import VolumeToolbar


@pytest.fixture
def panel():
    class Panel(ThreeDVisPanel):
        def __init__(self):
            QWidget.__init__(self)
            root = QVBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            self._viewport_host = QWidget(self)
            root.addWidget(self._viewport_host, stretch=1)
            self.plotter = Mock(window_size=(640, 480), suppress_rendering=False)
            self.port_overlay = PortChipOverlay(parent=self._viewport_host)
            self.colorbar = StudioColorbarCard(parent=self._viewport_host)
            self._watermark_label = QLabel(self._viewport_host)
            self._watermark_label.hide()
            self.status = QLabel(self._viewport_host)
            self.status.hide()
            self.toolbar = VolumeToolbar(
                geometry_mode='simple',
                display_mode='surface',
                lattice_enabled=False,
                parent=self._viewport_host,
            )
            self._init_state(25)
            self._apply_overlay_styles(self.colorbar._tokens)
            self._update_port_chips = Mock()
            self._add_flow_glyph = Mock()
            self._render_initial_scene = Mock()
            self.fit_view = Mock()

        showEvent = QWidget.showEvent
        hideEvent = QWidget.hideEvent

    widget = Panel()
    widget.resize(640, 480)
    widget.show()
    widget._field = 'Ta'
    widget._global_clim = {'Ta': (290., 410.), 'vmag': (0., 20.)}
    yield widget
    widget.cleanup()
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_range_modes_preserve_field_specific_limits_and_reject_bad_values(panel):
    values = np.arange(27., dtype=float).reshape(3, 3, 3) + 290.
    panel._arrays = {'Ta': values, 'vmag': np.linspace(0., 20., 27).reshape(3, 3, 3)}
    panel._cx_mm = panel._cy_mm = panel._cz_mm = np.array([0.5, 1.5, 2.5])
    panel._L_mm = (3.0, 3.0, 3.0)
    panel._grid = pv.RectilinearGrid(
        np.r_[0.0, panel._cx_mm, 3.0],
        np.r_[0.0, panel._cy_mm, 3.0],
        np.r_[0.0, panel._cz_mm, 3.0],
    )
    panel._slice_xyz_mm = (1.5, 1.5, 1.5)
    panel._display_mode = 'slice'

    panel.set_color_range_mode('local')
    assert panel._scale_mode == 'local'
    assert panel._clim_for('Ta') == (291., 315.)

    panel.set_color_range_mode('custom')
    panel.set_custom_color_range('Ta', 300., 350.)
    assert panel._clim_for('Ta') == (300., 350.)
    assert panel._clim_for('vmag') == (0., 20.)
    assert panel.colorbar.value_range() == (300., 350.)

    for low, high in [(float('nan'), 400.), (0., float('inf')), (350., 300.), (300., 300.)]:
        with pytest.raises(ValueError, match='Max > Min'):
            panel.set_custom_color_range('Ta', low, high)
        assert panel._clim_for('Ta') == (300., 350.)

    panel.set_color_range_mode('global')
    assert panel._clim_for('Ta') == (290., 410.)
    state = panel.color_range_state()
    state['ranges']['Ta'][0] = 123.
    assert panel._custom_clim['Ta'] == (300., 350.)


def test_custom_limits_and_watermark_reach_scene_colorbar_and_capture(panel, tmp_path):
    values = np.arange(27., dtype=float).reshape(3, 3, 3) + 290.
    before = values.copy()
    panel.set_fields(
        Ta=values,
        dx=np.full(3, 0.001),
        dy=np.full(3, 0.001),
        dz=np.full(3, 0.001),
    )
    panel.restore_color_ranges({'mode': 'custom', 'ranges': {'Ta': [300., 310.]}})
    base_pixels = np.full((480, 640, 3), 240, dtype=np.uint8)
    panel.plotter.screenshot.return_value = base_pixels
    try:
        set_cmap('temperature', 'cividis')
        panel.refresh_colormaps()
        surface_calls = [
            call for call in panel.plotter.add_mesh.call_args_list
            if call.kwargs.get('name') == 'main_surface'
        ]
        assert surface_calls[-1].kwargs['cmap'] == resolve_cmap('Ta') == 'cividis'
        assert surface_calls[-1].kwargs['clim'] == (300., 310.)
        assert panel.colorbar.colormap() == 'cividis'
        assert panel.colorbar.value_range() == (300., 310.)

        panel.set_watermark('⚠ cfd_full_core_3cell_fixed_v2 (experimental) extrapolated\nWall thickness out of range')
        assert not panel._watermark_label.isHidden()
        assert 'cfd_full_core_3cell_fixed_v2 (experimental)' in panel._watermark_label.text()

        captured = panel.capture_image()
        assert (captured.width(), captured.height()) == (640, 480)
        # Colorbar and watermark regions are composited over the uniform base scene.
        cb_rect = panel.colorbar.geometry()
        wm_rect = panel._watermark_label.geometry()
        cb_center = captured.pixelColor(cb_rect.center().x(), cb_rect.center().y()).getRgb()[:3]
        assert cb_center != (240, 240, 240)
        wm_changed = any(
            captured.pixelColor(x, y).getRgb()[:3] != (240, 240, 240)
            for x in range(wm_rect.left() + 4, min(wm_rect.right(), 200), 4)
            for y in range(wm_rect.top() + 4, wm_rect.bottom(), 3)
        )
        assert wm_changed

        # Hidden-panel capture temporarily unsuppresses rendering to flush updates.
        panel.plotter.suppress_rendering = True
        panel.plotter.render.reset_mock()
        hidden_captured = panel.capture_image()
        panel.plotter.render.assert_called_once_with()
        assert panel.plotter.suppress_rendering is True
        out_path = tmp_path / 'captured_3d.png'
        assert hidden_captured.save(str(out_path), 'PNG')
        assert out_path.stat().st_size > 1000

        panel.set_watermark(None)
        assert panel._watermark_label.isHidden()
        np.testing.assert_array_equal(values, before)
    finally:
        set_cmap('temperature', None)


@pytest.mark.parametrize('state', [
    {'mode': 'unknown'}, {'ranges': {'Ta': [300, 300]}},
    {'ranges': {'Ta': [float('nan'), 310]}}, {'ranges': {'unknown': [0, 1]}},
])
def test_invalid_restore_does_not_change_current_range(panel, state):
    before = panel.color_range_state()
    with pytest.raises(ValueError):
        panel.restore_color_ranges(state)
    assert panel.color_range_state() == before
    assert validate_color_range_state({}) == {'mode': 'global', 'ranges': {}}
