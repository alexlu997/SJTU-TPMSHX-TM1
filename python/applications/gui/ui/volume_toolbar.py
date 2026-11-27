"""Unified 3D viewport bottom toolbar for simplified and lattice geometry modes."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDoubleValidator, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSlider,
    QWidget,
)

from .symbols import SYM
from .theme import get_theme

GEOMETRY_MODES: tuple[str, ...] = ("simple", "lattice")
DISPLAY_MODES: tuple[str, ...] = ("surface", "slice", "volume")
DETAIL_LEVELS: tuple[str, ...] = ("low", "medium", "high")
PHASE_DOMAINS: tuple[str, ...] = ("A", "B", "S")
CAMERA_PRESETS: tuple[str, ...] = ("xy", "xz", "yz", "iso")

_GEOMETRY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("simple", "简化"),
    ("lattice", "晶格"),
)
_DISPLAY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("surface", "外表面"),
    ("slice", "截面"),
    ("volume", "体渲染"),
)
_DETAIL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("low", "低"),
    ("medium", "中"),
    ("high", "高"),
)
_PHASE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("A", "流体 A"),
    ("B", "流体 B"),
    ("S", "固体"),
)
_CAMERA_OPTIONS: tuple[tuple[str, str], ...] = (
    ("xy", SYM["xy"]),
    ("xz", SYM["xz"]),
    ("yz", SYM["yz"]),
    ("iso", "等轴"),
)


def _enable_tnum(widget: QWidget) -> None:
    font = widget.font()
    font.setFeature(QFont.Tag("tnum"), 1)
    widget.setFont(font)


class _VerticalHairline(QWidget):
    """Single-device-pixel vertical separator between toolbar groups."""

    def __init__(
        self,
        color_hex: str,
        height: int = 18,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color = QColor(color_hex)
        self.setFixedSize(1, height)

    def set_color(self, color_hex: str) -> None:
        self._color = QColor(color_hex)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(self._color, 0.5))
        painter.drawLine(QPointF(0.25, 0.0), QPointF(0.25, float(self.height())))
        painter.end()


class _SegmentButton(QAbstractButton):
    """One clickable option pill inside a segmented control.

    Uses an internal QLabel so rich-text ISO symbols render identically to
    plain Chinese labels, and keeps tooltips active when disabled.
    """

    def __init__(
        self,
        key: str,
        label_text: str,
        tokens: Mapping[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self._tokens = dict(tokens)
        self._selected = False
        self._hovered = False

        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 0, 9, 0)
        layout.setSpacing(0)

        self._label = QLabel(label_text)
        if "<" in label_text:
            self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        _enable_tnum(self._label)
        layout.addWidget(self._label)

        self._update_style()

    def set_selected(self, selected: bool) -> None:
        if self._selected != selected:
            self._selected = selected
            self._update_style()

    def set_option_enabled(self, enabled: bool, tooltip: str = "") -> None:
        self.setEnabled(enabled)
        self.setToolTip(tooltip)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )
        self._update_style()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        self._tokens.update(tokens)
        self._update_style()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def sizeHint(self):
        return self.layout().sizeHint()

    def _update_style(self) -> None:
        t = self._tokens
        if not self.isEnabled():
            color = t["tert"]
            weight = 400
        elif self._selected:
            color = t["fg"]
            weight = 600
        else:
            color = t["sub"]
            weight = 400
        self._label.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: {weight}; background: transparent;"
        )
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        t = self._tokens
        if self._selected and self.isEnabled():
            painter.setBrush(QColor(t["seg_on"]))
            painter.setPen(QPen(QColor(t["border"]), 0.5))
            painter.drawRoundedRect(rect, 5.0, 5.0)
        elif self._hovered and self.isEnabled():
            painter.setBrush(QColor(t["hover"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 5.0, 5.0)
        painter.end()


class _SegmentedGroup(QWidget):
    """Labeled segmented capsule with discrete options."""

    option_activated = Signal(str)

    def __init__(
        self,
        prefix: str,
        options: Sequence[tuple[str, str]],
        current: str | None,
        tokens: Mapping[str, Any],
        *,
        emit_on_reclick: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = dict(tokens)
        self._current = current
        self._emit_on_reclick = emit_on_reclick
        self._buttons: dict[str, _SegmentButton] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self._prefix = QLabel(prefix)
        outer.addWidget(self._prefix)

        self._capsule = QFrame()
        self._capsule.setObjectName("volToolbarCap")
        cap_lay = QHBoxLayout(self._capsule)
        cap_lay.setContentsMargins(2, 2, 2, 2)
        cap_lay.setSpacing(2)

        for key, text in options:
            btn = _SegmentButton(key, text, self._tokens)
            btn.set_selected(key == current)
            btn.clicked.connect(lambda _=False, opt_key=key: self._on_clicked(opt_key))
            cap_lay.addWidget(btn)
            self._buttons[key] = btn

        outer.addWidget(self._capsule)
        self.apply_theme(self._tokens)

    def current(self) -> str | None:
        return self._current

    def set_current(self, key: str | None) -> None:
        self._current = key
        for opt_key, btn in self._buttons.items():
            btn.set_selected(opt_key == key)

    def set_option_enabled(self, key: str, enabled: bool, tooltip: str = "") -> None:
        self._buttons[key].set_option_enabled(enabled, tooltip)

    def set_option_visible(self, key: str, visible: bool) -> None:
        self._buttons[key].setVisible(visible)

    def button(self, key: str) -> _SegmentButton:
        return self._buttons[key]

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        self._tokens.update(tokens)
        t = self._tokens
        self._prefix.setStyleSheet(
            f"color: {t['tert']}; font-size: 11.5px; font-weight: 400; background: transparent;"
        )
        self._capsule.setStyleSheet(
            f"QFrame#volToolbarCap {{ background: {t['sunken']}; border: none; border-radius: 7px; }}"
        )
        for btn in self._buttons.values():
            btn.apply_theme(t)

    def _on_clicked(self, key: str) -> None:
        if not self._buttons[key].isEnabled():
            return
        if key == self._current and not self._emit_on_reclick:
            return
        self.set_current(key)
        self.option_activated.emit(key)


class VolumeToolbar(QFrame):
    """Unified floating bottom toolbar for both 3D geometry modes.

    Group order:
    - Always first: ``几何 [简化 | 晶格]``
    - In ``simple`` mode: ``显示 [外表面 | 截面 | 体渲染]``, followed by
      ``截面 x/y/z mm`` only for ``slice`` or ``不透明度`` only for ``volume``.
    - In ``lattice`` mode: ``细节 [低 | 中 | 高]``, followed by ``相 [流体 A | 流体 B | 固体]``
      when ``show_phase_selector`` is True.
    - Always last: ``视角 [xy | xz | yz | 等轴]``

    Groups that do not apply to the active mode are hidden, never disabled.
    """

    geometry_mode_changed = Signal(str)
    display_mode_changed = Signal(str)
    slice_position_changed = Signal(float, float, float)
    opacity_changed = Signal(float)
    detail_level_changed = Signal(str)
    phase_changed = Signal(str)
    camera_preset_requested = Signal(str)
    layout_changed = Signal()

    def __init__(
        self,
        *,
        geometry_mode: str = "simple",
        display_mode: str = "surface",
        slice_xyz_mm: tuple[float, float, float] = (0.0, 0.0, 0.0),
        slice_bounds_mm: (
            tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None
        ) = None,
        opacity: float = 0.25,
        detail_level: str = "medium",
        phase: str = "A",
        available_phases: Sequence[str] = PHASE_DOMAINS,
        show_phase_selector: bool = True,
        camera_preset: str | None = "iso",
        lattice_enabled: bool = True,
        lattice_disabled_reason: str = "",
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._validate_choice(geometry_mode, GEOMETRY_MODES, "geometry_mode")
        self._validate_choice(display_mode, DISPLAY_MODES, "display_mode")
        self._validate_choice(detail_level, DETAIL_LEVELS, "detail_level")
        self._validate_choice(phase, PHASE_DOMAINS, "phase")
        if camera_preset is not None:
            self._validate_choice(camera_preset, CAMERA_PRESETS, "camera_preset")

        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)

        self._geometry_mode = geometry_mode
        self._display_mode = display_mode
        self._slice_bounds_mm = slice_bounds_mm
        self._slice_xyz_mm = self._clamp_slice(slice_xyz_mm)
        self._opacity = self._clamp_opacity(opacity)
        self._detail_level = detail_level
        self._phase = phase
        self._show_phase_selector = show_phase_selector
        self._lattice_enabled = lattice_enabled
        self._lattice_disabled_reason = lattice_disabled_reason
        if not lattice_enabled and self._geometry_mode == "lattice":
            self._geometry_mode = "simple"

        self.setObjectName("volumeToolbar")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)

        # 1. Geometry mode group (always visible)
        self._geom_group = _SegmentedGroup(
            "几何", _GEOMETRY_OPTIONS, self._geometry_mode, self._tokens
        )
        self._geom_group.option_activated.connect(self._on_geometry_activated)
        layout.addWidget(self._geom_group)

        self._sep_geom = self._make_sep()
        layout.addWidget(self._sep_geom)

        # 2a. Simplified display mode group
        self._display_group = _SegmentedGroup(
            "显示", _DISPLAY_OPTIONS, self._display_mode, self._tokens
        )
        self._display_group.option_activated.connect(self._on_display_activated)
        layout.addWidget(self._display_group)

        self._sep_display = self._make_sep()
        layout.addWidget(self._sep_display)

        # 2b. Orthogonal slice x/y/z coordinate group (slice display only)
        self._slice_group = self._build_slice_group()
        layout.addWidget(self._slice_group)

        self._sep_slice = self._make_sep()
        layout.addWidget(self._sep_slice)

        # 2c. Volume opacity group (volume display only)
        self._opacity_group = self._build_opacity_group()
        layout.addWidget(self._opacity_group)

        self._sep_opacity = self._make_sep()
        layout.addWidget(self._sep_opacity)

        # 3a. Lattice detail group
        self._detail_group = _SegmentedGroup(
            "细节", _DETAIL_OPTIONS, self._detail_level, self._tokens
        )
        self._detail_group.option_activated.connect(self._on_detail_activated)
        layout.addWidget(self._detail_group)

        self._sep_detail = self._make_sep()
        layout.addWidget(self._sep_detail)

        # 3b. Lattice phase choice group
        self._phase_group = _SegmentedGroup(
            "相", _PHASE_OPTIONS, self._phase, self._tokens
        )
        self._phase_group.option_activated.connect(self._on_phase_activated)
        layout.addWidget(self._phase_group)

        self._sep_phase = self._make_sep()
        layout.addWidget(self._sep_phase)

        # 4. Camera preset group (always visible, always last)
        self._camera_group = _SegmentedGroup(
            "视角",
            _CAMERA_OPTIONS,
            camera_preset,
            self._tokens,
            emit_on_reclick=True,
        )
        self._camera_group.option_activated.connect(self._on_camera_activated)
        layout.addWidget(self._camera_group)

        self._separators: tuple[_VerticalHairline, ...] = (
            self._sep_geom,
            self._sep_display,
            self._sep_slice,
            self._sep_opacity,
            self._sep_detail,
            self._sep_phase,
        )

        self.set_available_phases(available_phases)
        self.set_lattice_enabled(lattice_enabled, lattice_disabled_reason)
        self.apply_theme(self._tokens)
        self._sync_visibility()

    def geometry_mode(self) -> str:
        """Return the active geometry mode (``'simple'`` or ``'lattice'``)."""
        return self._geometry_mode

    def set_geometry_mode(self, mode: str) -> None:
        """Set the geometry mode without emitting ``geometry_mode_changed``."""
        self._validate_choice(mode, GEOMETRY_MODES, "geometry_mode")
        if mode == "lattice" and not self._lattice_enabled:
            return
        self._geometry_mode = mode
        self._geom_group.set_current(mode)
        self._sync_visibility()

    def display_mode(self) -> str:
        """Return the simplified display mode (``'surface'``, ``'slice'``, or ``'volume'``)."""
        return self._display_mode

    def set_display_mode(self, mode: str) -> None:
        """Set the simplified display mode without emitting ``display_mode_changed``."""
        self._validate_choice(mode, DISPLAY_MODES, "display_mode")
        self._display_mode = mode
        self._display_group.set_current(mode)
        self._sync_visibility()

    def slice_position(self) -> tuple[float, float, float]:
        """Return the current slice coordinates ``(x_mm, y_mm, z_mm)``."""
        return self._slice_xyz_mm

    def set_slice_position(self, x_mm: float, y_mm: float, z_mm: float) -> None:
        """Set slice coordinates in mm without emitting ``slice_position_changed``."""
        self._slice_xyz_mm = self._clamp_slice((x_mm, y_mm, z_mm))
        self._write_slice_edits()

    def set_slice_bounds(
        self,
        x_bounds: tuple[float, float],
        y_bounds: tuple[float, float],
        z_bounds: tuple[float, float],
    ) -> None:
        """Set inclusive ``(min_mm, max_mm)`` limits for the three slice inputs."""
        self._slice_bounds_mm = (
            (float(x_bounds[0]), float(x_bounds[1])),
            (float(y_bounds[0]), float(y_bounds[1])),
            (float(z_bounds[0]), float(z_bounds[1])),
        )
        self._slice_xyz_mm = self._clamp_slice(self._slice_xyz_mm)
        self._write_slice_edits()

    def opacity(self) -> float:
        """Return the volume rendering opacity in ``[0.0, 1.0]``."""
        return self._opacity

    def set_opacity(self, value: float) -> None:
        """Set volume opacity in ``[0.0, 1.0]`` without emitting ``opacity_changed``."""
        self._opacity = self._clamp_opacity(value)
        pct = int(round(self._opacity * 100))
        self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(pct)
        self._opacity_slider.blockSignals(False)
        self._opacity_value_label.setText(f"{pct}%")

    def detail_level(self) -> str:
        """Return the lattice detail level (``'low'``, ``'medium'``, or ``'high'``)."""
        return self._detail_level

    def set_detail_level(self, level: str) -> None:
        """Set the lattice detail level without emitting ``detail_level_changed``."""
        self._validate_choice(level, DETAIL_LEVELS, "detail_level")
        self._detail_level = level
        self._detail_group.set_current(level)

    def phase(self) -> str:
        """Return the active lattice phase domain (``'A'``, ``'B'``, or ``'S'``)."""
        return self._phase

    def set_phase(self, phase: str) -> None:
        """Set the active lattice phase without emitting ``phase_changed``."""
        self._validate_choice(phase, PHASE_DOMAINS, "phase")
        self._phase = phase
        self._phase_group.set_current(phase)

    def set_available_phases(self, phases: Sequence[str]) -> None:
        """Show only the phase options available in the active result."""
        allowed = tuple(phases)
        for p in allowed:
            self._validate_choice(p, PHASE_DOMAINS, "phase")
        for key in PHASE_DOMAINS:
            self._phase_group.set_option_visible(key, key in allowed)
        if allowed and self._phase not in allowed:
            self._phase = allowed[0]
            self._phase_group.set_current(self._phase)
        self._sync_visibility()

    def set_phase_selector_visible(self, visible: bool) -> None:
        """Show or hide the inline lattice phase selector group."""
        self._show_phase_selector = visible
        self._sync_visibility()

    def camera_preset(self) -> str | None:
        """Return the highlighted camera preset or ``None`` after free orbit."""
        return self._camera_group.current()

    def set_camera_preset(self, preset: str | None) -> None:
        """Highlight a camera preset without emitting ``camera_preset_requested``."""
        if preset is not None:
            self._validate_choice(preset, CAMERA_PRESETS, "camera_preset")
        self._camera_group.set_current(preset)

    def lattice_enabled(self) -> bool:
        """Return True when the lattice geometry option can be selected."""
        return self._lattice_enabled

    def lattice_disabled_reason(self) -> str:
        """Return the tooltip reason shown when the lattice option is disabled."""
        return self._lattice_disabled_reason

    def set_lattice_enabled(self, enabled: bool, reason: str = "") -> None:
        """Enable or disable the ``晶格`` choice and set its disabled tooltip reason."""
        self._lattice_enabled = enabled
        self._lattice_disabled_reason = "" if enabled else reason
        self._geom_group.set_option_enabled(
            "lattice", enabled, tooltip=self._lattice_disabled_reason
        )
        if not enabled and self._geometry_mode == "lattice":
            self._geometry_mode = "simple"
            self._geom_group.set_current("simple")
            self._sync_visibility()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens to all toolbar groups."""
        self._tokens.update(tokens)
        t = self._tokens

        self._geom_group.apply_theme(t)
        self._display_group.apply_theme(t)
        self._detail_group.apply_theme(t)
        self._phase_group.apply_theme(t)
        self._camera_group.apply_theme(t)
        for sep in self._separators:
            sep.set_color(t["border"])

        self._slice_prefix.setStyleSheet(
            f"color: {t['tert']}; font-size: 11.5px; font-weight: 400; background: transparent;"
        )
        for axis_lbl in self._slice_axis_labels:
            axis_lbl.setStyleSheet(
                f"color: {t['sub']}; font-size: 12px; font-weight: 500; background: transparent;"
            )
        self._slice_unit.setStyleSheet(
            f"color: {t['tert']}; font-size: 11.5px; font-weight: 400; background: transparent;"
        )
        edit_qss = (
            f"QLineEdit {{ background: {t['canvas']}; border: 1px solid {t['inp_border']}; "
            f"border-radius: 5px; min-height: 24px; max-height: 24px; padding: 0 5px; "
            f"font-size: 12px; color: {t['fg']}; }}"
            f"QLineEdit:focus {{ border: 1px solid {t['accent']}; }}"
        )
        for edit in self._slice_edits:
            edit.setStyleSheet(edit_qss)

        self._opacity_prefix.setStyleSheet(
            f"color: {t['tert']}; font-size: 11.5px; font-weight: 400; background: transparent;"
        )
        self._opacity_value_label.setStyleSheet(
            f"color: {t['sub']}; font-size: 12px; font-weight: 500; background: transparent;"
        )
        self._opacity_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ border: none; height: 4px; "
            f"background: {t['sunken']}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 2px; }}"
            f"QSlider::add-page:horizontal {{ background: {t['border']}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ background: {t['popover']}; "
            f"border: 1.5px solid {t['accent']}; width: 11px; height: 11px; "
            f"margin: -4.5px 0; border-radius: 6.5px; }}"
        )
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(QColor(self._tokens["popover"]))
        painter.setPen(QPen(QColor(self._tokens["border"]), 0.5))
        painter.drawRoundedRect(rect, 9.0, 9.0)
        painter.end()

    def _make_sep(self) -> _VerticalHairline:
        return _VerticalHairline(self._tokens["border"], height=18)

    def _build_slice_group(self) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        self._slice_prefix = QLabel("截面")
        lay.addWidget(self._slice_prefix)
        lay.addSpacing(2)

        self._slice_axis_labels: list[QLabel] = []
        self._slice_edits: list[QLineEdit] = []
        for idx, axis_key in enumerate(("x", "y", "z")):
            lbl = QLabel(SYM[axis_key])
            lbl.setTextFormat(Qt.TextFormat.RichText)
            self._slice_axis_labels.append(lbl)
            lay.addWidget(lbl)

            edit = QLineEdit(f"{self._slice_xyz_mm[idx]:.1f}")
            edit.setObjectName(f"sliceInput_{axis_key}")
            edit.setFixedWidth(44)
            edit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            edit.setValidator(QDoubleValidator(-1e6, 1e6, 3, edit))
            _enable_tnum(edit)
            edit.editingFinished.connect(self._on_slice_edited)
            self._slice_edits.append(edit)
            lay.addWidget(edit)

            if idx < 2:
                lay.addSpacing(2)

        self._slice_unit = QLabel("mm")
        lay.addWidget(self._slice_unit)
        return box

    def _build_opacity_group(self) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)

        self._opacity_prefix = QLabel("不透明度")
        lay.addWidget(self._opacity_prefix)

        pct = int(round(self._opacity * 100))
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setObjectName("volumeOpacitySlider")
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(pct)
        self._opacity_slider.setFixedWidth(84)
        self._opacity_slider.setFixedHeight(20)
        self._opacity_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self._opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)
        lay.addWidget(self._opacity_slider)

        self._opacity_value_label = QLabel(f"{pct}%")
        self._opacity_value_label.setFixedWidth(32)
        self._opacity_value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        _enable_tnum(self._opacity_value_label)
        lay.addWidget(self._opacity_value_label)
        return box

    def _sync_visibility(self) -> None:
        is_simple = self._geometry_mode == "simple"
        show_slice = is_simple and self._display_mode == "slice"
        show_opacity = is_simple and self._display_mode == "volume"
        show_detail = not is_simple
        show_phase = (not is_simple) and self._show_phase_selector

        self._display_group.setVisible(is_simple)
        self._sep_display.setVisible(is_simple)

        self._slice_group.setVisible(show_slice)
        self._sep_slice.setVisible(show_slice)

        self._opacity_group.setVisible(show_opacity)
        self._sep_opacity.setVisible(show_opacity)

        self._detail_group.setVisible(show_detail)
        self._sep_detail.setVisible(show_detail)

        self._phase_group.setVisible(show_phase)
        self._sep_phase.setVisible(show_phase)

        self.updateGeometry()
        self.adjustSize()
        self.layout_changed.emit()

    def _on_geometry_activated(self, mode: str) -> None:
        self._geometry_mode = mode
        self._sync_visibility()
        self.geometry_mode_changed.emit(mode)

    def _on_display_activated(self, mode: str) -> None:
        self._display_mode = mode
        self._sync_visibility()
        self.display_mode_changed.emit(mode)

    def _on_detail_activated(self, level: str) -> None:
        self._detail_level = level
        self.detail_level_changed.emit(level)

    def _on_phase_activated(self, phase: str) -> None:
        self._phase = phase
        self.phase_changed.emit(phase)

    def _on_camera_activated(self, preset: str) -> None:
        self.camera_preset_requested.emit(preset)

    def _on_slice_edited(self) -> None:
        parsed: list[float] = []
        for idx, edit in enumerate(self._slice_edits):
            try:
                parsed.append(float(edit.text()))
            except ValueError:
                parsed.append(self._slice_xyz_mm[idx])
        clamped = self._clamp_slice((parsed[0], parsed[1], parsed[2]))
        changed = clamped != self._slice_xyz_mm
        self._slice_xyz_mm = clamped
        self._write_slice_edits()
        if changed:
            self.slice_position_changed.emit(*clamped)

    def _on_opacity_slider_changed(self, pct: int) -> None:
        self._opacity = self._clamp_opacity(pct / 100.0)
        self._opacity_value_label.setText(f"{pct}%")
        self.opacity_changed.emit(self._opacity)

    def _write_slice_edits(self) -> None:
        for edit, val in zip(self._slice_edits, self._slice_xyz_mm):
            edit.blockSignals(True)
            edit.setText(f"{val:.1f}")
            edit.blockSignals(False)

    def _clamp_slice(
        self, xyz: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        vals = [float(xyz[0]), float(xyz[1]), float(xyz[2])]
        if self._slice_bounds_mm is not None:
            for idx, (lo, hi) in enumerate(self._slice_bounds_mm):
                vals[idx] = max(lo, min(hi, vals[idx]))
        return (vals[0], vals[1], vals[2])

    @staticmethod
    def _clamp_opacity(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _validate_choice(value: str, allowed: tuple[str, ...], name: str) -> None:
        if value not in allowed:
            raise ValueError(f"Unsupported {name} {value!r}; expected one of {allowed}")
