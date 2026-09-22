"""Theme-colored Lucide SVG icons, rendered at the target device scale."""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_ASSETS = Path(__file__).with_name('assets') / 'icons'
_ALIASES = {
    'sliders': 'sliders-horizontal',
    'more-horizontal': 'ellipsis',
    'fit-view': 'maximize',
}


@lru_cache(maxsize=32)
def _source(name):
    return (_ASSETS / f'{_ALIASES.get(name, name)}.svg').read_bytes()


class _SvgIconEngine(QIconEngine):
    def __init__(self, source, color):
        super().__init__()
        self.source = source
        self.color = QColor(color)
        self.renderer = QSvgRenderer(source.replace(
            b'currentColor', self.color.name().encode('ascii')))

    def clone(self):
        return _SvgIconEngine(self.source, self.color)

    def isNull(self):
        return not self.renderer.isValid()

    def paint(self, painter, rect, mode, state):
        painter.save()
        opacity = self.color.alphaF()
        if mode == QIcon.Mode.Disabled:
            opacity *= 0.4
        painter.setOpacity(painter.opacity() * opacity)
        # Text-button padding can leave a non-square icon rectangle. Keep the
        # glyph's proportions instead of stretching its circle into an oval.
        side = min(rect.width(), rect.height())
        target = QRectF(0, 0, side, side)
        target.moveCenter(QRectF(rect).center())
        self.renderer.render(painter, target)
        painter.restore()

    def scaledPixmap(self, size, mode, state, scale):
        # Qt can request a zero-height icon while a responsive row relayouts.
        if size.isEmpty():
            return QPixmap()
        pixmap = QPixmap(size * scale)
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(QPoint(), size), mode, state)
        painter.end()
        return pixmap


def icon(name, color):
    """Return a scalable icon; the caller controls its logical ``iconSize``."""
    return QIcon(_SvgIconEngine(_source(name), color))
