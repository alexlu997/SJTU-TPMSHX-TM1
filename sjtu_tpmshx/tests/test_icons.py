"""Check the displayed SVG content, tint and device-pixel rendering."""
from pathlib import Path

import pytest

pytest.importorskip('PySide6')

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QColor, QIcon  # noqa: E402

from sjtu_tpmshx.ui.icons import icon, _source, _SvgIconEngine  # noqa: E402
from sjtu_tpmshx.ui.theme import _THEMES  # noqa: E402


def _opaque_pixels(image):
    return [image.pixelColor(x, y)
            for y in range(image.height()) for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 0]


def test_all_bundled_icons_and_aliases_have_visible_content():
    assets = Path(__file__).parents[1] / 'ui' / 'assets' / 'icons'
    names = [path.stem for path in assets.glob('*.svg')]
    assert names
    for name in names + ['sliders', 'more-horizontal', 'fit-view']:
        image = icon(name, '#497ced').pixmap(QSize(20, 20)).toImage()
        assert not image.isNull(), name
        assert _opaque_pixels(image), name


def test_responsive_row_empty_icon_request_does_not_start_an_inactive_painter(capfd):
    engine = _SvgIconEngine(_source('chevron-down'), '#497ced')
    pixmap = engine.scaledPixmap(QSize(16, 0), QIcon.Mode.Normal, QIcon.State.Off, 1.0)
    assert pixmap.isNull()
    assert 'QPainter' not in capfd.readouterr().err


def test_icon_keeps_its_proportions_in_a_narrow_button_content_rect():
    glyph = icon('square', '#497ced').pixmap(QSize(12, 24)).toImage()
    points = [(x, y) for y in range(glyph.height()) for x in range(glyph.width())
              if glyph.pixelColor(x, y).alpha() > 0]
    xs, ys = zip(*points)
    assert abs((max(xs) - min(xs)) - (max(ys) - min(ys))) <= 1


@pytest.mark.parametrize('theme_name', ['light', 'dark'])
@pytest.mark.parametrize('scale', [1.0, 1.5, 2.0, 3.0])
def test_theme_tint_and_high_dpi_rendering(theme_name, scale):
    color = QColor(_THEMES[theme_name]['fg'])
    glyph = icon('square', color)
    pixmap = glyph.pixmap(QSize(20, 20), scale)
    assert pixmap.size() == QSize(round(20 * scale), round(20 * scale))
    assert pixmap.devicePixelRatio() == scale
    assert pixmap.deviceIndependentSize().width() == 20
    pixels = _opaque_pixels(pixmap.toImage())
    assert any(pixel.alpha() == 255 for pixel in pixels)
    # Fully opaque stroke pixels retain the exact requested theme color.
    assert all(pixel.rgb() == color.rgb() for pixel in pixels if pixel.alpha() == 255)
    disabled = glyph.pixmap(QSize(20, 20), scale, QIcon.Mode.Disabled).toImage()
    assert 0 < max(pixel.alpha() for pixel in _opaque_pixels(disabled)) <= 103
