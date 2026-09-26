"""Coordinate Inspector — persistent right-dock panel showing every
field's value at the cursor point on contour canvases.

Fills the gap left by the transient bottom-of-canvas `_hover_label`:
engineers frequently need to cross-check multiple fields (Ta, Tb, Ts, u,
v, P, ε) at the same (x, y) without toggling tabs. This panel resolves
the point against the latest cached fields on every motion event
and lets users **pin** a reading so they can sweep the cursor to a
second point for comparison.

Patterned after ParaView's "Probe Location" and Grafana's Explore
inspector — right-aligned, mono-font, copy-able.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QApplication, QSizePolicy,
)

from .theme import get_theme
from .matplotlib_canvas import cell_index_mm


# ────────────────────────────────────────────────────────────────────
#  Catalogue of cached fields the inspector can read
# ────────────────────────────────────────────────────────────────────

# (key in cached 2D fields, display label, unit, fmt)
# `eps` / zone L,t come from `za`, handled specially in `_resolve_fields`.
_FIELD_TABLE = [
    ('Ta',   'T_fA',  'K',   '{:.2f}'),
    ('Tb',   'T_fB',  'K',   '{:.2f}'),
    ('Ts',   'T_s',   'K',   '{:.2f}'),
    ('ucA',  'u_A',   'm/s', '{:.4f}'),
    ('vcA',  'v_A',   'm/s', '{:.4f}'),
    ('ucB',  'u_B',   'm/s', '{:.4f}'),
    ('vcB',  'v_B',   'm/s', '{:.4f}'),
    ('P_fA', 'P_A',   'Pa',  '{:.0f}'),
    ('P_fB', 'P_B',   'Pa',  '{:.0f}'),
]


def _resolve_fields(window, x_mm, y_mm):
    """Return list of (label, value_str, unit) at the (x_mm, y_mm) point.

    Reads fields from the accepted 2D/3D ComputeResult. If results haven't
    been computed yet, returns an empty list (caller displays "— no
    compute yet —" in that case).
    """
    r = _display_fields(window)
    if r is None:
        return []
    N_x = int(r.get('N_x', 0)); N_y = int(r.get('N_y', 0))
    L = float(r.get('L', 0.0)); H = float(r.get('H', 0.0))
    if N_x <= 0 or N_y <= 0 or L <= 0 or H <= 0:
        return []

    i = cell_index_mm(x_mm, r.get('dx_arr', np.full(N_x, L / N_x)))
    j = cell_index_mm(y_mm, r.get('dy_arr', np.full(N_y, H / N_y)))

    out = [('x', f"{x_mm:.2f}", 'mm'),
           ('y', f"{y_mm:.2f}", 'mm'),
           ('(i,j)', f"({i},{j})", '')]
    if window.cache.get_result('3d') is not None:
        dz = np.asarray(r['dz'])
        k = min(getattr(window, '_slice_index', len(dz) // 2), len(dz) - 1)
        z_mm = (np.cumsum(dz) - dz / 2)[k] * 1000.
        out.append(('z', f"{z_mm:.2f}", 'mm'))

    # Honour the global K ↔ °C toggle when rendering temperature fields.
    temp_unit = getattr(window, '_temp_unit', 'K')
    want_C = (temp_unit == 'C')

    for key, label, unit, fmt in _FIELD_TABLE:
        field = r.get(key)
        if field is None:
            continue
        try:
            arr = np.asarray(field)
            if arr.ndim == 2:
                v = float(arr[i, j])
            elif arr.ndim == 3:
                k = getattr(window, '_slice_index', arr.shape[2] // 2)
                v = float(arr[i, j, min(k, arr.shape[2] - 1)])
            else:
                continue
            # Temperature conversion for display consistency with
            # header K/°C toggle.
            disp_unit = unit
            if unit == 'K' and want_C:
                v = v - 273.15
                disp_unit = '°C'
            out.append((label, fmt.format(v), disp_unit))
        except Exception:
            continue

    # Zone-local L/t/eps from za (sigmoid_field projection)
    za = r.get('za') or {}
    for z_key, z_lbl, z_unit, z_fmt in (
            ('eps_arr', 'ε',    '',   '{:.4f}'),
            ('L_field', 'L',    'mm', '{:.2f}'),
            ('t_field', 't',    'mm', '{:.3f}'),
    ):
        arr = za.get(z_key)
        if arr is None:
            continue
        try:
            a = np.asarray(arr)
            if a.ndim == 2:
                v = float(a[i, j])
            else:
                continue
            out.append((z_lbl, z_fmt.format(v), z_unit))
        except Exception:
            continue

    return out


def _display_fields(window):
    """Read the same accepted result source as the active field canvas."""
    result_3d = window.cache.get_result('3d')
    if result_3d is None:
        result_2d = window.cache.get_result('2d')
        return result_2d.fields if result_2d is not None else None
    f = result_3d.fields
    nx, ny, _ = f['Ta'].shape
    return {**f, 'N_x': nx, 'N_y': ny, 'L': f['Lx'], 'H': f['Ly'],
            'dx_arr': f['dx'], 'dy_arr': f['dy']}


# ────────────────────────────────────────────────────────────────────

class CoordInspector(QDockWidget):
    """Dockable right-side panel that updates on hover.

    The dock lives on `Qt.RightDockWidgetArea` of the main window and
    starts hidden — Ctrl+I (or the palette entry) toggles it. Dock is
    closable, resizable, and remembers its visibility via the host
    window's saveState / restoreState.
    """

    def __init__(self, window):
        super().__init__("Coordinate Inspector", window)
        self.setObjectName("CoordInspector")
        self._window = window
        self._pinned = False

        self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea
                             | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable
                         | QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)

        _t = get_theme()
        _surface = _t.get('surface_raised', _t['card_bg'])
        _border = _t.get('border_subtle', _t['card_border'])
        _sub = _t.get('sub_fg', _t['fg'])

        root = QWidget()
        root.setStyleSheet(
            f"background:{_surface}; color:{_t['fg']};"
            f"border-left:1px solid {_border};")
        v = QVBoxLayout(root)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(10)

        # Header row: title + pin button + status badge
        header = QHBoxLayout()
        header.setSpacing(6)
        title = QLabel("Inspector")
        title.setStyleSheet(
            f"color:{_t['fg']}; font-size:11pt; font-weight:700;"
            "background:transparent; border:none; letter-spacing:0.3px;")
        header.addWidget(title)
        header.addStretch(1)
        self._status = QLabel("● Live")
        self._status.setStyleSheet(
            f"color:{_t.get('accent_green', '#22C55E')};"
            "font-size:9pt; font-weight:600; background:transparent;"
            "border:none; padding:2px 0;")
        header.addWidget(self._status)
        btn_pin = QPushButton("📌")
        btn_pin.setFixedSize(26, 26)
        btn_pin.setCheckable(True)
        btn_pin.setToolTip(
            "Pin the current reading so the cursor can sweep to a second "
            "point for comparison")
        btn_pin.setStyleSheet(
            f"QPushButton{{background:transparent; border:1px solid {_border};"
            f"border-radius:4px; color:{_t['fg']}; font-size:11pt;}}"
            f"QPushButton:checked{{background:{_t.get('accent_primary', '#3B82F6')};"
            f"color:white; border-color:{_t.get('accent_primary', '#3B82F6')};}}"
            f"QPushButton:hover{{border-color:{_t.get('combo_hover_border', _border)};}}")
        btn_pin.toggled.connect(self._on_pin_toggled)
        header.addWidget(btn_pin)
        v.addLayout(header)

        # Separator line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background:{_border}; max-height:1px; border:none;")
        v.addWidget(line)

        # Readout grid — two columns: label, value. Uses fira-code for
        # numeric column so decimals align between rows.
        self._readout_host = QWidget()
        self._readout_layout = QVBoxLayout(self._readout_host)
        self._readout_layout.setContentsMargins(0, 0, 0, 0)
        self._readout_layout.setSpacing(4)
        self._readout_host.setStyleSheet("background:transparent;")
        v.addWidget(self._readout_host, 1)

        self._empty_lbl = QLabel("Hover a contour plot after a successful "
                                  "Compute to see field values here.")
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setStyleSheet(
            f"color:{_sub}; font-size:9pt; font-style:italic;"
            "background:transparent; border:none;")
        self._readout_layout.addWidget(self._empty_lbl)

        # Footer actions
        footer = QHBoxLayout()
        footer.setSpacing(6)
        btn_copy = QPushButton("Copy all")
        btn_copy.setFixedHeight(26)
        btn_copy.setStyleSheet(
            f"QPushButton{{background:transparent; color:{_t['fg']};"
            f"border:1px solid {_border}; border-radius:4px;"
            f"padding:4px 10px; font-size:9pt;}}"
            f"QPushButton:hover{{background:{_t.get('scroll_bg', '#eee')};}}")
        btn_copy.clicked.connect(self._copy_all)
        footer.addWidget(btn_copy)
        footer.addStretch(1)
        v.addLayout(footer)

        self.setWidget(root)
        self.setMinimumWidth(240)
        root.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.MinimumExpanding)

        self._last_rows: list[tuple[str, str, str]] = []

    # ── External API ────────────────────────────────────────────────
    _last_ij: tuple | None = None

    def update_from_event(self, event):
        """Called by Main_Menu._on_hover on motion_notify_event."""
        if self._pinned:
            return
        if event.inaxes is None or event.xdata is None or event.ydata is None:
            return
        # 144 Hz friendly: skip re-render when the cursor stays within
        # the same grid cell. Grid index resolution is the visual
        # information limit of the inspector, so intra-cell motion events
        # yield zero new pixels and can be dropped cheaply.
        r = _display_fields(self._window) or {}
        N_x = int(r.get('N_x', 0)); N_y = int(r.get('N_y', 0))
        L = float(r.get('L', 0.0)); H = float(r.get('H', 0.0))
        if N_x > 0 and N_y > 0 and L > 0 and H > 0:
            i = cell_index_mm(event.xdata, r.get('dx_arr', np.full(N_x, L / N_x)))
            j = cell_index_mm(event.ydata, r.get('dy_arr', np.full(N_y, H / N_y)))
            source = self._window.cache.get_result('3d')
            ij = (id(source) if source is not None else id(r),
                  getattr(self._window, '_slice_index', None),
                  getattr(self._window, '_temp_unit', 'K'), i, j)
            if ij == self._last_ij:
                return
            self._last_ij = ij
        rows = _resolve_fields(self._window, float(event.xdata),
                               float(event.ydata))
        if not rows:
            return
        self._render_rows(rows)

    def _on_pin_toggled(self, checked):
        self._pinned = bool(checked)
        # P2.1 lint (F821): _t was only assigned in the ELSE branch — pinning
        # the inspector hit an unbound _t (NameError) on the styled path.
        _t = get_theme()
        if self._pinned:
            self._status.setText("◉ Pinned")
            self._status.setStyleSheet(
                "color:" + _t.get('search_hl', '#F59E0B') + "; font-size:9pt; font-weight:600;"
                "background:transparent; border:none;")
        else:
            _t = get_theme()
            self._status.setText("● Live")
            self._status.setStyleSheet(
                f"color:{_t.get('accent_green', '#22C55E')};"
                "font-size:9pt; font-weight:600; background:transparent;"
                "border:none;")

    # ── Rendering ───────────────────────────────────────────────────
    def _clear_rows(self):
        while self._readout_layout.count():
            item = self._readout_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render_rows(self, rows):
        self._last_rows = list(rows)
        self._clear_rows()
        _t = get_theme()
        _sub = _t.get('sub_fg', _t['fg'])
        lbl_css = (
            f"color:{_sub}; font-size:9pt; font-weight:600;"
            "letter-spacing:0.2px; background:transparent; border:none;")
        val_css = (
            f"color:{_t['fg']}; font-size:10pt; font-weight:700;"
            "font-family:'Fira Code','Consolas',monospace;"
            "background:transparent; border:none;")
        unit_css = (
            f"color:{_sub}; font-size:8pt;"
            "background:transparent; border:none;")
        for label, value, unit in rows:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            l = QLabel(label); l.setStyleSheet(lbl_css)
            l.setFixedWidth(60)
            v = QLabel(value); v.setStyleSheet(val_css)
            v.setAlignment(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter)
            u = QLabel(unit); u.setStyleSheet(unit_css)
            u.setFixedWidth(36)
            row.addWidget(l)
            row.addWidget(v, 1)
            row.addWidget(u)
            holder = QWidget()
            holder.setLayout(row)
            holder.setStyleSheet("background:transparent;")
            self._readout_layout.addWidget(holder)
        self._readout_layout.addStretch(1)

    def _copy_all(self):
        if not self._last_rows:
            return
        txt = "\n".join(f"{lbl:<10s} {val:>12s}  {unit}"
                         for lbl, val, unit in self._last_rows)
        QApplication.clipboard().setText(txt)
        self._window.statusBar().showMessage(
            "Inspector readout copied to clipboard.", 3000)


# ────────────────────────────────────────────────────────────────────

def install_coord_inspector(window):
    """Construct the dock, attach to the right edge, and wire Ctrl+I."""
    dock = CoordInspector(window)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    dock.hide()
    window._coord_inspector = dock

    def _toggle():
        if dock.isVisible():
            dock.hide()
        else:
            dock.show()
            dock.raise_()

    sh = QShortcut(QKeySequence("Ctrl+I"), window)
    sh.activated.connect(_toggle)
    window._coord_inspector_shortcut = sh
    window._toggle_coord_inspector = _toggle
