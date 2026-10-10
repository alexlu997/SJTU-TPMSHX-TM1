"""Manual ranges keep field values intact and reach slice image exports."""
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from sjtu_tpmshx.ui.panel_vis_3d import ThreeDVisPanel
from sjtu_tpmshx.ui.vis3d_constants import validate_color_range_state


@pytest.fixture
def panel():
    class Panel(ThreeDVisPanel):
        def __init__(self):
            QWidget.__init__(self)
            self._init_state(self._build_toolbar(QVBoxLayout(self)))
            self.status = QLabel(self)
            self.plotter = Mock()
            self._rebuild_volume = Mock()
            self._add_slice_actor = Mock()
            self._update_status = Mock()

        showEvent = QWidget.showEvent
        hideEvent = QWidget.hideEvent

    widget = Panel()
    widget._field = 'Ta'
    widget._global_clim = {'Ta': (290., 410.), 'vmag': (0., 20.)}
    yield widget
    widget.cleanup()
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_range_cycle_preserves_field_specific_limits_and_rejects_bad_edits(panel):
    panel._grid = object()
    panel._slice_info = {'axis': 'z', 'coord_mm': 1.}
    panel._on_clim_cycle()
    assert panel._scale_mode == 'local'
    panel._on_clim_cycle()
    assert panel._scale_mode == 'custom'
    panel.le_clim_min.setText('300')
    panel.le_clim_max.setText('350')
    panel._on_custom_clim_changed()
    assert panel._clim_for('Ta') == (300., 350.)
    assert panel._clim_for('vmag') == (0., 20.)
    panel._rebuild_volume.assert_called_with(render=False)
    panel._add_slice_actor.assert_called_with('z', 1., render=False)
    for low, high in [('nan', '400'), ('0', 'inf'), ('350', '300'), ('300', '300')]:
        panel.le_clim_min.setText(low)
        panel.le_clim_max.setText(high)
        panel._on_custom_clim_changed()
        assert panel._clim_for('Ta') == (300., 350.)
        assert 'Max > Min' in panel.status.text()
    panel._field = 'vmag'
    panel._sync_clim_controls()
    assert panel.le_clim_min.text() == '0' and panel.le_clim_max.text() == '20'
    panel._on_clim_cycle()
    assert panel._clim_for('Ta') == (290., 410.)
    state = panel.color_range_state()
    state['ranges']['Ta'][0] = 123.
    assert panel._custom_clim['Ta'] == (300., 350.)


def test_popup_and_saved_image_use_manual_limits_with_colored_out_of_range_values(panel, tmp_path, monkeypatch):
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from PySide6.QtWidgets import QFileDialog

    values = np.arange(27.).reshape(3, 3, 3) + 290.
    before = values.copy()
    panel._arrays = {'Ta': values}
    panel._cx_mm = panel._cy_mm = panel._cz_mm = np.array([.5, 1.5, 2.5])
    panel._slice_index = lambda axis, coord: 1
    panel.restore_color_ranges({'mode': 'custom', 'ranges': {'Ta': [300., 310.]}})
    panel._show_slice_popup('z', 1.5)
    figure = panel._popup_dialogs[0].findChild(FigureCanvasQTAgg).figure
    contour = figure.axes[0].collections[0]
    assert contour.get_clim() == (300., 310.)
    assert contour.extend == 'both'
    assert contour.cmap(contour.norm(290.)) == contour.cmap(0.)
    assert contour.cmap(contour.norm(320.)) == contour.cmap(1.)
    output = tmp_path / 'slice.png'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(output), ''))
    panel._save_figure(figure, 'z', 1.5, 'Ta')
    assert output.stat().st_size > 1000
    np.testing.assert_array_equal(values, before)


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
