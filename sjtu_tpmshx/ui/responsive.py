"""responsive.py — width-aware layout containers (ui-layout-fixes, 2026-07-03).

Qt has no CSS-style container queries; ``ResponsiveRow`` is the minimal
deterministic substitute: a QWidget whose QBoxLayout flips between
side-by-side (LeftToRight) and stacked (TopToBottom) at a width threshold,
driven by ``resizeEvent``. Used for the Fluid A / Fluid B card pair, whose
hard QHBoxLayout used to clip both cards on narrow panels
(builders_fluids.py had promised this "resize-to-stack responsive pass").
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize
from PySide6.QtWidgets import QBoxLayout, QLayout, QWidget


class ResponsiveRow(QWidget):
    """Two-or-more children side by side when wide, stacked when narrow.

    ``threshold``: preferred width (px) below which children stack. Children
    also stack when their platform-dependent minimum widths do not fit.
    The flip is idempotent (direction only set when it changes), so
    repeated resize events are cheap and never thrash the layout.
    """

    def __init__(self, threshold: int = 520, spacing: int = 10,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._threshold = int(threshold)
        self.setStyleSheet("background:transparent;")
        self._lay = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(spacing)
        # A horizontal box's minimum width must not become a hard widget
        # minimum: that would prevent the resize which switches back to a stack.
        # The row still reports the widest child's minimum width to its parent.
        self._lay.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

    def layout(self):  # noqa: D102 — QWidget override, returns the box layout
        return self._lay

    def addWidget(self, w: QWidget) -> None:
        self._lay.addWidget(w)

    @property
    def direction(self) -> QBoxLayout.Direction:
        return self._lay.direction()

    def _minimum_widths(self) -> tuple[int, int]:
        items = [self._lay.itemAt(i) for i in range(self._lay.count())]
        widths = [item.minimumSize().width() for item in items]
        margins = self._lay.contentsMargins()
        edge = margins.left() + margins.right()
        gaps = max(0, sum(not item.isEmpty() for item in items) - 1)
        return (max(widths, default=0) + edge,
                sum(widths) + gaps * self._lay.spacing() + edge)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 — Qt override
        stacked_width, _ = self._minimum_widths()
        return QSize(stacked_width, self._lay.minimumSize().height())

    def _update_direction(self, width: int) -> None:
        _, horizontal_width = self._minimum_widths()
        want = (QBoxLayout.Direction.TopToBottom
                if width < max(self._threshold, horizontal_width)
                else QBoxLayout.Direction.LeftToRight)
        if self._lay.direction() != want:
            self._lay.setDirection(want)
            self.updateGeometry()

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt override
        self._update_direction(event.size().width())
        super().resizeEvent(event)

    def event(self, event) -> bool:
        handled = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest:
            # Text, fonts and visibility can change without resizing this row.
            self._update_direction(self.width())
            self.updateGeometry()
        return handled
