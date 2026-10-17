"""Check the actual 3D panel and PNG export in a separate Qt process."""
from pathlib import Path
import os
import subprocess
import sys

import pytest


def _render_panel(destination):
    from unittest.mock import patch
    import json

    import numpy as np
    from PIL import Image
    import pyvista as pv
    from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog

    platform = 'cocoa' if sys.platform == 'darwin' else 'windows'
    app = QApplication(['render-check', '-platform', platform])
    from sjtu_tpmshx.ui.panel_vis_3d import ThreeDVisPanel

    assert app.platformName() == platform
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    report = {'qt_platform': platform, 'pyvista': pv.__version__, 'images': {}}
    panel = ThreeDVisPanel()
    try:
        panel.resize(960, 720)
        panel.show()
        x, y, z = np.indices((8, 6, 4), dtype=float)
        panel.set_fields(Ta=300 + x + 2*y + 3*z, Ts=340 - 2*x + y - z,
                         dx=np.full(8, .001), dy=np.full(6, .001), dz=np.full(4, .001))
        assert panel._volume_actor is not None
        loop = QEventLoop()
        QTimer.singleShot(250, loop.quit)
        loop.exec()
        assert not panel.plotter.suppress_rendering
        report['render_window'] = panel.plotter.ren_win.GetClassName()
        background = np.asarray(panel.plotter.renderer.GetBackground()) * 255
        width, height = panel.plotter.window_size
        for scale in (1, 2):
            path = output / f'volume-{scale}.png'
            pixels = panel.plotter.screenshot(str(path), return_img=True, scale=scale)
            assert pixels.shape == (height*scale, width*scale, 3)
            assert pixels.dtype == np.uint8
            with Image.open(path) as decoded:
                np.testing.assert_array_equal(np.asarray(decoded), pixels)
            # A nonblank image alone can pass when the framebuffer contains noise.
            assert np.max(np.abs(pixels[:10, :10].astype(float) - background)) <= 2
            center = pixels[height*scale//4:3*height*scale//4,
                            width*scale//4:3*width*scale//4]
            assert float(center.std()) > 5
            assert np.max(np.abs(center.astype(float) - background)) > 20
            report['images'][str(scale)] = {'shape': list(pixels.shape),
                                           'decoded_pixels_match': True}
            if scale == 1:
                first = pixels
        panel.combo_field.setCurrentIndex(panel.combo_field.findData('Ts'))
        assert panel._field == 'Ts'
        QTimer.singleShot(100, loop.quit)
        loop.exec()
        changed = panel.plotter.screenshot(str(output / 'solid.png'), return_img=True)
        center = np.s_[height//4:3*height//4, width//4:3*width//4]
        difference = int(np.count_nonzero(first[center] != changed[center]))
        assert difference > 100
        report['changed_center_values'] = difference
        export = output / 'application-export.png'
        with patch.object(QFileDialog, 'getSaveFileName',
                          return_value=(str(export), 'PNG images (*.png)')):
            panel._on_screenshot()
        with Image.open(export) as decoded:
            np.testing.assert_array_equal(np.asarray(decoded), changed)
        report['application_export_pixels_match'] = True
    finally:
        panel.cleanup()
        assert panel._cleaned_up and panel.plotter._closed
        panel.cleanup()
        panel.close()
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    report['closed'] = True
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


@pytest.mark.skipif(sys.platform not in ('darwin', 'win32'),
                    reason='Actual native Qt rendering requires a supported desktop platform')
def test_actual_volume_scaled_screenshot_and_application_export():
    platform = 'cocoa' if sys.platform == 'darwin' else 'windows'
    environment = {**os.environ, 'QT_QPA_PLATFORM': platform, 'PYVISTA_OFF_SCREEN': 'false'}
    if sys.platform == 'win32':
        environment['QT_OPENGL'] = 'desktop'
    result = subprocess.run(
        [sys.executable, '-c',
         'import sys; from sjtu_tpmshx.tests.test_real_3d_render import _render_panel; '
         '_render_panel(sys.argv[1])', str(Path('.cache/ci/fast/render').resolve())],
        env=environment,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
