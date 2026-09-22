"""panel_vis_3d.py — embedded PyVistaQt 3D visualisation panel.

Provides `ThreeDVisPanel(QWidget)` — a self-contained Qt widget that hosts a
`pyvistaqt.QtInteractor`. The panel now shows the **full volume** (ray-cast
volume rendering) by default and lets the user manually add a slice plane by
specifying plane orientation + coordinate (in mm). Each slice spawns a 2D
matplotlib pop-up with the corresponding contour plot.

Fields displayed (all None-safe; combo is filtered to what `set_fields`
actually provides):
    Ta       : fluid A temperature [K]
    Tb       : fluid B temperature [K]           (cross-flow only)
    Ts       : solid temperature [K]
    vmag     : fluid A speed magnitude [m/s]
    vmag_B   : fluid B speed magnitude [m/s]     (cross-flow only)
    P_kPa    : fluid A absolute pressure [kPa]   (P_ref_abs + gauge)
    P_B_kPa  : fluid B absolute pressure [kPa]   (cross-flow only)
    L_mm     : design zoning L-field [mm]

Data entry points:
    panel.set_fields(Ta=..., Tb=..., Ts=..., vmag=..., vmag_B=...,
                     P_kPa=..., P_B_kPa=..., L_mm=...,
                     dx=..., dy=..., dz=...)

The caller can hand real 3D SIMPLE+LTNE results in via `set_fields`.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import Qt, QTimer, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QDoubleValidator, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QLineEdit, QDialog, QFileDialog, QMessageBox, QFrame, QSlider,
    QBoxLayout, QButtonGroup, QSizePolicy,
)


from sjtu_tpmshx.ui.vis3d_constants import FIELD_ORDER, FIELD_META
from sjtu_tpmshx.ui.responsive import ResponsiveRow

# ── Theme-aware QSS generators for 3D panel controls ──
from sjtu_tpmshx.ui.theme import get_theme, get_theme_name, _build_styles
from sjtu_tpmshx.ui.typography import apply_vtk_font

_CTRL_HEIGHT = 32
_CAMERA_UPDATE_RATE = 120.0  # Adaptive motion budget, not a guaranteed FPS.


def _btn_qss():
    t = get_theme()
    return f"""
QPushButton {{
    color: {t['fg']}; background: {t['card_bg']};
    border: 1px solid {t['inp_border']}; border-radius: 6px;
    padding: 4px 14px; font-size: 10pt; font-weight: 500;
}}
QPushButton:hover {{ background: {t['tab_off_hover']}; border-color: {t['accent_primary']}; }}
QPushButton:pressed {{ background: {t['inp_border']}; }}
QPushButton:checked {{ background: {t['accent_primary']}; color: white; }}
QPushButton:disabled {{ color: {t['tab_disabled_fg']}; background: {t['bg']}; border: 1px dashed {t['inp_border']}; }}
"""


def _btn_primary_qss():
    t = get_theme()
    return f"""
QPushButton {{
    color: white; background: {t['accent_primary']};
    border: 1px solid {t['chk_checked_border']}; border-radius: 6px;
    padding: 4px 16px; font-size: 10pt; font-weight: 700;
}}
QPushButton:hover {{ background: {t['splitter_hover']}; }}
QPushButton:pressed {{ background: {t['chk_checked_border']}; }}
QPushButton:disabled {{ color: white; background: {t['tab_disabled_fg']}; }}
"""


def _label_qss():
    t = get_theme()
    return (f"QLabel {{ color: {t['fg']}; font-size: 10pt; font-weight: 500; "
            "background: transparent; border: none; padding: 0 4px 0 0; margin: 0; }")


def _status_qss():
    t = get_theme()
    return (f"color: {t['mpl_subtitle']}; font-size: 9pt; font-weight: 500; "
            f"font-family: {t['sans_family']}; "
            f"background: {t['scroll_bg']}; border-top: 1px solid {t['card_border']}; "
            "padding: 6px 12px;")


def _lineedit_qss():
    t = get_theme()
    return f"""
QLineEdit {{
    color: {t['fg']}; background: {t['inp_bg']};
    border: 1px solid {t['inp_border']}; border-radius: 6px;
    padding: 4px 8px; font-size: 10pt; font-weight: 500;
}}
QLineEdit:focus {{ border-color: {t['inp_focus']}; }}
QLineEdit:disabled {{ color: {t['tab_disabled_fg']}; background: {t['scroll_bg']}; }}
QLineEdit[error="true"] {{ border: 1px solid {t['warn']}; background: {t['scroll_bg']}; }}
QLineEdit[error="true"]:focus {{ border-color: {t['warn']}; }}
"""


def _divider_qss():
    t = get_theme()
    return (f"QFrame {{ color: {t['card_border']}; background: {t['card_border']}; "
            "max-width: 1px; min-width: 1px; margin: 6px 4px; }")


def _seg_qss(corners):
    t = get_theme()
    if corners == 'left':
        radius = ("border-top-left-radius:6px; border-bottom-left-radius:6px; "
                  "border-top-right-radius:0; border-bottom-right-radius:0;")
    elif corners == 'right':
        radius = ("border-top-right-radius:6px; border-bottom-right-radius:6px; "
                  "border-top-left-radius:0; border-bottom-left-radius:0;")
    else:
        radius = "border-radius:0;"
    bl = "border-left:none; " if corners != 'left' else ""
    return f"""
QPushButton {{
    color: {t['fg']}; background: {t['card_bg']};
    border: 1px solid {t['inp_border']}; {bl}{radius}
    padding: 4px 10px; font-size: 9pt; font-weight: 500;
}}
QPushButton:hover {{ background: {t['tab_off_hover']}; }}
QPushButton:pressed {{ background: {t['inp_border']}; }}
"""


def _slider_qss():
    t = get_theme()
    return f"""
QSlider::groove:horizontal {{
    border: none; height: 5px; background: {t['card_border']};
    margin: 0px; border-radius: 2px;
}}
QSlider::add-page:horizontal {{
    background: {t['card_border']}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: transparent; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {t['accent_primary']}; border: 2px solid {t['card_bg']};
    width: 13px; height: 13px; margin: -6px 0; border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{ background: {t['splitter_hover']}; }}
"""

# Plane-selection: user picks a plane parallel to XY/YZ/XZ; the slicing normal
# is perpendicular to that plane. `coord_axis` names the axis along which the
# user's coordinate value is interpreted.
_PLANE_OPTIONS = [
    ('xy', 'XY (⊥ Z)', 'z'),   # plane parallel to XY → slice at given Z
    ('yz', 'YZ (⊥ X)', 'x'),   # plane parallel to YZ → slice at given X
    ('xz', 'XZ (⊥ Y)', 'y'),   # plane parallel to XZ → slice at given Y
]


class ThreeDVisPanel(QWidget):
    """Embedded 3D visualisation — PyVistaQt interactor + toolbar.

    Default view: volume rendering (ray-casting) of the currently selected
    field. User adds a slice via the Plane/Coord controls; slice is overlaid
    on top of the volume. Each Apply also pops up a 2D matplotlib contour
    window for the chosen slice.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        opacity_default = self._build_toolbar(root)
        self._build_viewport(root)
        self._init_state(opacity_default)
        self._init_timers()
        self._render_placeholder()
        self._setup_hover()

    def _build_toolbar(self, root):
        """Build field, slice, view, and export groups that wrap when narrow."""
        toolbar_col = QVBoxLayout()
        toolbar_col.setContentsMargins(6, 4, 6, 4)
        toolbar_col.setSpacing(4)

        opacity_default = self._build_parameter_controls(toolbar_col)
        self._build_action_controls(toolbar_col)
        root.addLayout(toolbar_col)
        return opacity_default

    def _build_parameter_controls(self, toolbar_col):
        """Build field, plane, coordinate, and opacity controls."""
        parameter_row = ResponsiveRow(threshold=900, spacing=6)
        parameter_row.setObjectName('volumeParameterControls')
        parameter_row.layout().setDirection(QBoxLayout.Direction.TopToBottom)
        selectors = ResponsiveRow(threshold=0, spacing=12)
        selectors.setObjectName('volumeFieldPlaneControls')
        parameter_row.addWidget(selectors)
        params = QHBoxLayout(); params.setSpacing(6)
        params.setContentsMargins(0, 0, 0, 0)
        params.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        selectors.layout().addLayout(params)

        # Field combo
        lbl_f = QLabel("Field:"); lbl_f.setStyleSheet(_label_qss())
        params.addWidget(lbl_f)
        combo_style = _build_styles()['COMBO']
        self.combo_field = QComboBox()
        self.combo_field.setStyleSheet(combo_style)
        self.combo_field.setMinimumWidth(140)
        self.combo_field.setFixedHeight(_CTRL_HEIGHT)
        self.combo_field.currentIndexChanged.connect(self._on_field_changed)
        self.combo_field.setEnabled(False)
        params.addWidget(self.combo_field)

        params = QHBoxLayout(); params.setSpacing(6)
        params.setContentsMargins(0, 0, 0, 0)
        params.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        selectors.layout().addLayout(params)

        # Plane combo
        lbl_p = QLabel("Plane:"); lbl_p.setStyleSheet(_label_qss())
        params.addWidget(lbl_p)
        self.combo_plane = QComboBox()
        for _pid, label, _axis in _PLANE_OPTIONS:
            self.combo_plane.addItem(label, userData=_pid)
        self.combo_plane.setStyleSheet(combo_style)
        self.combo_plane.setFixedHeight(_CTRL_HEIGHT)
        self.combo_plane.setMinimumWidth(110)
        self.combo_plane.setEnabled(False)
        self.combo_plane.currentIndexChanged.connect(self._on_plane_changed)
        params.addWidget(self.combo_plane)

        slice_controls = ResponsiveRow(threshold=0, spacing=16)
        slice_controls.setObjectName('volumeCoordOpacityControls')
        parameter_row.addWidget(slice_controls)
        params = QHBoxLayout(); params.setSpacing(6)
        params.setContentsMargins(0, 0, 0, 0)
        params.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        slice_controls.layout().addLayout(params)

        # Coord input (mm) with live range-validation
        self.lbl_coord = QLabel("Coord:")
        self.lbl_coord.setStyleSheet(_label_qss())
        params.addWidget(self.lbl_coord)
        self.le_coord = QLineEdit("10.0")
        # Range updated dynamically in `_update_coord_label`; placeholder
        # QDoubleValidator accepts any real; we clamp + flag error ourselves.
        self._coord_validator = QDoubleValidator(-1e6, 1e6, 4, self)
        self.le_coord.setValidator(self._coord_validator)
        self.le_coord.setFixedWidth(76)
        self.le_coord.setFixedHeight(_CTRL_HEIGHT)
        self.le_coord.setStyleSheet(_lineedit_qss())
        self.le_coord.setEnabled(False)
        self.le_coord.setToolTip("Slice coordinate in mm (must be inside domain)")
        self.le_coord.returnPressed.connect(self._on_apply_slice)
        self.le_coord.textChanged.connect(self._on_coord_text_changed)
        params.addWidget(self.le_coord)

        params.addStretch(1)
        params = QHBoxLayout(); params.setSpacing(6)
        params.setContentsMargins(0, 0, 0, 0)
        params.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        slice_controls.layout().addLayout(params)

        # Opacity slider — controls volume transparency (0 = invisible, 100 = opaque)
        # Defaults balance "glass cube" feel against cold-end legibility:
        # at these values the opacity ramp (lo = op*0.55) keeps cold voxels
        # visible on the slate viewport bg instead of dissolving to black.
        lbl_op = QLabel("Opacity:"); lbl_op.setStyleSheet(_label_qss())
        params.addWidget(lbl_op)
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(0, 100)
        _op_default = 30 if get_theme_name() == 'dark' else 25
        self.slider_opacity.setValue(_op_default)
        self.slider_opacity.setMinimumWidth(80)
        self.slider_opacity.setMaximumWidth(110)
        self.slider_opacity.setFixedHeight(_CTRL_HEIGHT)
        self.slider_opacity.setStyleSheet(_slider_qss())
        self.slider_opacity.setEnabled(False)
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
        self.slider_opacity.setToolTip(
            "Volume density: lower values keep long ducts readable")
        params.addWidget(self.slider_opacity)
        self.lbl_opacity_val = QLabel(f"{_op_default}%")
        self.lbl_opacity_val.setStyleSheet(_label_qss())
        self.lbl_opacity_val.setMinimumWidth(36)
        params.addWidget(self.lbl_opacity_val)
        params.addStretch(1)
        toolbar_col.addWidget(parameter_row)
        return _op_default

    def _build_action_controls(self, toolbar_col):
        """Build slice, range, view-preset, and screenshot controls."""
        def _divider():
            d = QFrame()
            d.setFrameShape(QFrame.Shape.VLine)
            d.setStyleSheet(_divider_qss())
            d.setFixedHeight(_CTRL_HEIGHT)
            return d
        action_row = ResponsiveRow(threshold=640, spacing=6)
        action_row.setObjectName('volumeActionControls')
        action_row.layout().setDirection(QBoxLayout.Direction.TopToBottom)
        actions = QHBoxLayout(); actions.setSpacing(6)
        actions.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        action_row.layout().addLayout(actions)

        # Primary action: Apply
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setStyleSheet(_btn_primary_qss())
        self.btn_apply.setFixedHeight(_CTRL_HEIGHT)
        self.btn_apply.setMinimumWidth(78)
        self.btn_apply.setEnabled(False)
        self.btn_apply.setToolTip(
            "Apply slice + pop up a 2D contour window for archival.\n"
            "(Typing a valid coord already updates the 3D slice in real time;\n"
            " use Apply to capture the current slice as a saveable plot.)")
        self.btn_apply.clicked.connect(self._on_apply_slice)
        actions.addWidget(self.btn_apply)

        actions.addWidget(_divider())

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setStyleSheet(_btn_qss())
        self.btn_clear.setFixedHeight(_CTRL_HEIGHT)
        self.btn_clear.setEnabled(False)
        self.btn_clear.setToolTip("Remove the current slice actor from the 3D view.")
        self.btn_clear.clicked.connect(self._on_clear_slice)
        actions.addWidget(self.btn_clear)

        self.btn_clim = QPushButton("Range: Full")
        self.btn_clim.setCheckable(True)
        self.btn_clim.setEnabled(False)
        self.btn_clim.setStyleSheet(_btn_qss())
        self.btn_clim.setFixedHeight(_CTRL_HEIGHT)
        self.btn_clim.setToolTip(
            "Color-bar range.\n"
            "  Full  — min/max of the entire 3D domain\n"
            "  Slice — min/max of the current slice only")
        self.btn_clim.clicked.connect(self._on_clim_toggled)
        actions.addWidget(self.btn_clim)

        actions.addStretch(1)
        view_export = ResponsiveRow(threshold=0, spacing=6)
        view_export.setObjectName('volumeViewExportControls')
        action_row.addWidget(view_export)
        actions = QHBoxLayout(); actions.setSpacing(6)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        view_export.layout().addLayout(actions)

        # View preset segmented buttons: Top / Front / Side / Iso
        # QButtonGroup (exclusive) keeps one button visually "active" so the
        # user can tell which canonical view is currently framed.
        view_seg = QHBoxLayout(); view_seg.setSpacing(0); view_seg.setContentsMargins(0, 0, 0, 0)
        self._view_btn_group = QButtonGroup(self)
        self._view_btn_group.setExclusive(True)

        def _mk_view_btn(label, corners, width, preset, tip, hotkey):
            b = QPushButton(label)
            b.setStyleSheet(_seg_qss(corners))
            b.setFixedHeight(_CTRL_HEIGHT); b.setMinimumWidth(width)
            b.setCheckable(True)
            b.setToolTip(f"{tip}   [{hotkey}]")
            b.setEnabled(False)
            b.clicked.connect(lambda: self._set_view(preset))
            view_seg.addWidget(b)
            self._view_btn_group.addButton(b)
            return b

        self.btn_view_top = _mk_view_btn(
            "Top", 'left', 46, 'top',
            "Camera → XY plane looking down -Z", "T")
        self.btn_view_front = _mk_view_btn(
            "Front", 'mid', 52, 'front',
            "Camera → XZ plane (looking at -Y face)", "F")
        self.btn_view_side = _mk_view_btn(
            "Side", 'mid', 46, 'side',
            "Camera → YZ plane (looking at -X face)", "S")
        self.btn_view_iso = _mk_view_btn(
            "Iso", 'right', 44, 'iso',
            "Camera → isometric (default)", "I")
        self.btn_view_iso.setChecked(True)   # default view on load
        actions.addLayout(view_seg)
        actions.addStretch(1)

        # Keyboard shortcuts — T/F/S/I trigger the same presets.
        # ApplicationShortcut keeps them active regardless of focused widget
        # inside the 3D panel, so power users never leave the mouse.
        for key, btn in (('T', self.btn_view_top),
                         ('F', self.btn_view_front),
                         ('S', self.btn_view_side),
                         ('I', self.btn_view_iso)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(btn.click)

        actions = QHBoxLayout(); actions.setSpacing(6)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        view_export.layout().addLayout(actions)
        actions.addWidget(_divider())

        self.btn_shot = QPushButton("Save PNG")
        self.btn_shot.setEnabled(False)
        self.btn_shot.setStyleSheet(_btn_qss())
        self.btn_shot.setFixedHeight(_CTRL_HEIGHT)
        self.btn_shot.setToolTip("Screenshot of the 3D viewport.")
        self.btn_shot.clicked.connect(self._on_screenshot)
        actions.addWidget(self.btn_shot)

        actions.addStretch(1)
        toolbar_col.addWidget(action_row)

    def _build_viewport(self, root):
        """Build the PyVista interactor and status line."""
        # ── Divider ──
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        # ── PyVistaQt interactor ──
        self.plotter = QtInteractor(self)
        self.plotter.interactor.setMinimumHeight(160)
        self._pause_rendering()  # A newly constructed panel is still hidden.
        if self.plotter.iren is not None:  # Offscreen plotters have no interactor.
            self.plotter.iren.interactor.SetDesiredUpdateRate(_CAMERA_UPDATE_RATE)
            self.plotter.iren.add_observer('StartInteractionEvent', self._cancel_preset_for_interaction)
        root.addWidget(self.plotter.interactor, stretch=1)

        pv.set_plot_theme('dark' if get_theme_name() == 'dark' else 'document')
        # Override PyVista's pure-black dark viewport with a deep-slate so
        # cold voxels (turbo low end) don't dissolve into the background.
        try:
            self.plotter.set_background(get_theme().get('vp_bg_3d', '#12161c'))
        except Exception:
            pass

        # ── Status ──
        self.status = QLabel(
            "No data loaded — set Dimensionality to '3D' in "
            "Domain panel, then click Compute.")
        self.status.setStyleSheet(_status_qss())
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status.setMinimumWidth(0)
        root.addWidget(self.status)

    def _init_state(self, opacity_default):
        """Initialize field, actor, slice, and camera state."""
        # ── State ──
        self._grid: Optional[pv.RectilinearGrid] = None
        self._volume_grids: dict = {}
        self._grid_vol = None
        self._arrays: dict[str, np.ndarray] = {}     # {key: (Nx,Ny,Nz) array}
        self._dx_mm: Optional[np.ndarray] = None
        self._dy_mm: Optional[np.ndarray] = None
        self._dz_mm: Optional[np.ndarray] = None
        self._L_mm = (0.0, 0.0, 0.0)                 # (Lx, Ly, Lz) domain mm
        self._global_clim: dict = {}
        self._field = None                           # currently selected field key
        self._scale_mode = 'global'
        self._volume_actor = None
        self._slice_actor_name = 'user_slice'
        self._slice_info = None                      # {'axis': 'x', 'coord_mm': 10.0}
        self._last_hover_text = ''
        self._base_status_text = ''
        self._popup_dialogs: list = []               # keep refs so they aren't GC'd
        self._opacity = opacity_default / 100.0       # 0..1, mirrors slider/100
        self._flow_dir = '+x'                        # Fluid A arrow direction
        self._flow_dir_B = None                      # Fluid B arrow direction
        self._tween_animation: Optional[QVariantAnimation] = None
        self._tween_end_pose = None
        self._tween_previous_update_rate = None
        self._camera_fit_pending = False

    def _init_timers(self):
        """Configure slice and opacity debounce timers."""
        # Realtime-apply debounce: user typing in coord field keeps firing
        # textChanged; we single-shot a QTimer (240 ms) so the slice rebuilds
        # only after typing pauses, instead of on every keystroke.
        self._coord_debounce = QTimer(self)
        self._coord_debounce.setSingleShot(True)
        self._coord_debounce.setInterval(240)
        self._coord_debounce.timeout.connect(self._on_apply_slice_realtime)
        # Opacity slider rebuilds the VTK piecewise function on every tick
        # during a drag — coalesce to one render after 50 ms idle.
        self._opacity_debounce = QTimer(self)
        self._opacity_debounce.setSingleShot(True)
        # 120 ms — longer than typical drag tick (16 ms @ 60 Hz) so consecutive
        # ticks coalesce reliably. Old 50 ms was shorter than fast-mouse drag
        # cadence on some Windows display chains, leaking 2-3 GPU flushes per
        # drag (user pain point).
        self._opacity_debounce.setInterval(120)
        self._opacity_debounce.timeout.connect(self._apply_opacity_now)

    # ─────────────────────────── public API ───────────────────────────

    def set_fields(self, Ta=None, vmag=None, P_kPa=None, L_mm=None,
                   dx=None, dy=None, dz=None,
                   *, Tb=None, Ts=None, vmag_B=None, P_B_kPa=None,
                   flow_dir='+x', flow_dir_B=None):
        """Attach 3D fields to the panel. Shape of every field: (Nx, Ny, Nz).

        Pass `None` for any field that is unavailable
        (e.g. cross-flow fluid B when not solved) — the combo will skip it.

        dx, dy, dz : 1-D grid spacings in metres.
        """
        if dx is None or dy is None or dz is None:
            raise ValueError("set_fields: dx/dy/dz are required")

        self._flow_dir = str(flow_dir) if flow_dir else '+x'
        self._flow_dir_B = str(flow_dir_B) if flow_dir_B else None

        candidate = {
            'Ta': Ta, 'Tb': Tb, 'Ts': Ts,
            'vmag': vmag, 'vmag_B': vmag_B,
            'P_kPa': P_kPa, 'P_B_kPa': P_B_kPa,
            'L_mm': L_mm,
        }
        self._arrays = {k: np.ascontiguousarray(v, dtype=np.float64)
                        for k, v in candidate.items() if v is not None}
        if not self._arrays:
            raise ValueError("set_fields: at least one field must be non-None")
        field_shape = next(iter(self._arrays.values())).shape
        if len(field_shape) != 3:
            raise ValueError(f"set_fields: 3D fields required, got {field_shape}")
        for key, arr in self._arrays.items():
            if arr.shape != field_shape:
                raise ValueError(
                    f"set_fields: {key} shape {arr.shape} != {field_shape}")

        # 1-D edges / centres in mm
        dx_m = np.asarray(dx, dtype=np.float64)
        dy_m = np.asarray(dy, dtype=np.float64)
        dz_m = np.asarray(dz, dtype=np.float64)
        if field_shape != (dx_m.size, dy_m.size, dz_m.size):
            raise ValueError(
                "set_fields: field shape "
                f"{field_shape} != grid ({dx_m.size}, {dy_m.size}, {dz_m.size})")
        self._dx_mm = dx_m * 1000.0
        self._dy_mm = dy_m * 1000.0
        self._dz_mm = dz_m * 1000.0
        # Pre-compute cell-centre 1D coordinate arrays once per set_fields().
        # _show_slice_popup previously recomputed these cumsum's on every popup
        # (each open ≈ O(N) per axis). Cached here so popups are O(1).
        self._cx_mm = np.cumsum(self._dx_mm) - self._dx_mm / 2
        self._cy_mm = np.cumsum(self._dy_mm) - self._dy_mm / 2
        self._cz_mm = np.cumsum(self._dz_mm) - self._dz_mm / 2
        x_edges = np.concatenate([[0.0], np.cumsum(self._dx_mm)])
        y_edges = np.concatenate([[0.0], np.cumsum(self._dy_mm)])
        z_edges = np.concatenate([[0.0], np.cumsum(self._dz_mm)])
        self._L_mm = (float(x_edges[-1]), float(y_edges[-1]), float(z_edges[-1]))

        grid = pv.RectilinearGrid(x_edges, y_edges, z_edges)
        for key, arr in self._arrays.items():
            grid.cell_data[key] = arr.flatten(order='F')
        self._grid = grid.cell_data_to_point_data()

        # Prepare high-resolution display data only when its field is shown.
        # New results (including a changed grid) must invalidate every field.
        self._volume_grids.clear()
        self._grid_vol = None

        self._global_clim = self._build_global_clim()

        # Populate combo with available fields only (preserves FIELD_ORDER).
        # Block signals across BOTH clear()+addItem AND setCurrentIndex below
        # so _on_field_changed doesn't fire mid-restore (which would cause
        # _rebuild_volume to run twice — once via the signal, once via the
        # explicit call below at line 557).
        prev_field = self._field
        self.combo_field.blockSignals(True)
        self.combo_field.clear()
        for fkey in FIELD_ORDER:
            if fkey in self._arrays:
                self.combo_field.addItem(FIELD_META[fkey]['label'], userData=fkey)
        # Restore previous field selection if still available, else first item.
        # 2026-05-20 UI sweep: two guards added —
        #   (a) only assign `self._field = prev_field` when `findData()` returns
        #       a real index (>=0); previously the assignment ran even after a
        #       findData miss, leaving `_field` stale relative to the combo.
        #   (b) fall back to "Ta" if `itemData(0)` returns None (empty combo),
        #       otherwise downstream `FIELD_META[self._field]` lookups KeyError.
        _picked = None
        if prev_field in self._arrays:
            idx = self.combo_field.findData(prev_field)
            if idx >= 0:
                self.combo_field.setCurrentIndex(idx)
                _picked = prev_field
        if _picked is None:
            _picked = self.combo_field.itemData(0) or "Ta"
        self._field = _picked
        self.combo_field.blockSignals(False)

        # Enable controls
        for w in (self.combo_field, self.combo_plane, self.le_coord,
                  self.btn_apply, self.btn_clim, self.btn_shot,
                  self.slider_opacity,
                  self.btn_view_top, self.btn_view_front, self.btn_view_side,
                  self.btn_view_iso):
            w.setEnabled(True)
        # btn_clear enabled only once a slice exists
        self.btn_clear.setEnabled(False)
        self._slice_info = None

        self._render_initial_scene()
        self._rebuild_volume(render=False)
        self.fit_view()
        self._update_coord_label()
        self._validate_coord_input()
        self._update_status()


    def set_watermark(self, text):
        """Place a warning watermark on the viewport (lower-left).

        Called after set_fields when the run left the ConstDF-v1 training
        window. Pass `None` to clear. Keeps copy compact so the 3D volume
        remains the primary visual, while the reader still can't miss the
        extrapolation flag in a screenshot or presentation slide.
        """
        pl = self.plotter
        try:
            pl.remove_actor('_extrap_watermark', render=False)
        except Exception:
            pass
        if not text:
            pl.render()
            return
        t = get_theme()
        try:
            _wm = pl.add_text(
                str(text).replace('⚠', 'Warning:'),
                # upper_left, not lower_left: the lower-left corner already holds
                # the XYZ orientation triad + the Qt status strip below, so the
                # watermark there read as a cramped pile. Top-left is clear.
                position='upper_left', font_size=8,
                color=t.get('warn', '#F59E0B'),
                name='_extrap_watermark', shadow=False,
                font='times',
            )
            apply_vtk_font(_wm.GetTextProperty())
        except Exception:
            pass
        pl.render()

    def cleanup(self):
        """Release GL context + close outstanding matplotlib popups.

        2026-05-20 UI sweep (Tier 21): idempotent — guard against a
        double cleanup() (e.g. closeEvent runs it, then PyVistaQt's own
        teardown runs again). A second `plotter.close()` on an already
        closed QtInteractor can raise inside VTK.
        """
        if getattr(self, '_cleaned_up', False):
            return
        self._cleaned_up = True
        self._stop_camera_tween()
        for dlg in list(self._popup_dialogs):
            try:
                dlg.close()
            except Exception:
                pass
        self._popup_dialogs.clear()
        try:
            self.plotter.close()
        except Exception:
            pass

    def _build_global_clim(self):
        """Build comparable color ranges for related physical fields."""
        clim = {
            f: (float(self._grid[f].min()), float(self._grid[f].max()))
            for f in self._arrays
        }

        def _share(fields):
            present = [f for f in fields if f in clim]
            if len(present) < 2:
                return
            lo = min(clim[f][0] for f in present)
            hi = max(clim[f][1] for f in present)
            if hi - lo < 1e-12:
                hi = lo + 1.0
            # Skip sharing when magnitudes differ too much: a shared range would
            # crush the smaller field into the colormap's dark/low end, where it
            # renders near-black and (with the velocity transparent-low opacity)
            # nearly invisible. Classic case: fast air A vs slow fluid B speed —
            # forcing B onto A's range made "Velocity B" a dark/empty volume
            # while its slice popup (autoscaled) looked fine. If ANY field's
            # whole range sits in the bottom 40 % of the shared span, keep each
            # field on its OWN clim so its structure is visible.
            span = hi - lo
            if any(clim[f][1] < lo + 0.4 * span for f in present):
                return
            for f in present:
                clim[f] = (lo, hi)

        _share(('Ta', 'Tb', 'Ts'))
        _share(('vmag', 'vmag_B'))
        # Pressure A/B — share clim so the same color = same kPa across the
        # P_kPa / P_B_kPa combo entries. Without this the user toggling
        # between A and B sees one autoscaled view replaced with another and
        # cannot compare magnitudes by colour alone.
        _share(('P_kPa', 'P_B_kPa'))
        return clim

    # ─────────────────────────── visibility gate ──────────────────────
    def _pause_rendering(self):
        self._render_gated = True
        # suppress_rendering also covers already queued PyVistaQt render
        # signals; stopping its idle timer avoids hidden 5 Hz work entirely.
        self.plotter.suppress_rendering = True
        self.plotter.render_timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, '_cleaned_up', False):
            return
        self._render_gated = False
        self.plotter.suppress_rendering = False
        self.plotter.render_timer.start()  # QTimer retains its original 200 ms interval.
        if getattr(self, '_camera_fit_pending', False):
            # A hidden result receives its final viewport geometry on show.
            QTimer.singleShot(0, self, lambda: self._camera_fit_pending and self.fit_view())
        else:
            self.plotter.render()

    def hideEvent(self, event):
        super().hideEvent(event)
        # Stop before snapping so the shared animation clock cannot render
        # another frame after this panel has been hidden.
        self._stop_camera_tween(snap=True)
        if not getattr(self, '_cleaned_up', False):
            self._pause_rendering()

    # ─────────────────────────── hover probe ──────────────────────────

    def _setup_hover(self):
        try:
            iren = self.plotter.iren.interactor
        except Exception:
            return
        try:
            iren.AddObserver('MouseMoveEvent', self._on_mouse_move, 1.0)
        except Exception:
            pass

    def _on_mouse_move(self, obj, event):
        """Probe scalar values at cursor position on the slice (if present)."""
        if self._grid is None:
            return
        # Throttle to ~30 Hz so fast cursor sweeps don't fire kdtree lookups
        # 60+ times/s on top of VTK's own picker work. Without this, dragging
        # the cursor across a refined 3D grid added perceptible jitter to
        # the camera spin. — 2026-04-29
        import time as _t_hover
        _now = _t_hover.monotonic()
        _last = getattr(self, '_hover_last_t', 0.0)
        if _now - _last < 0.033:   # 33 ms = ~30 Hz cap
            return
        self._hover_last_t = _now
        try:
            from vtkmodules.vtkRenderingCore import vtkPropPicker
            x, y = obj.GetEventPosition()
            picker = vtkPropPicker()
            picker.Pick(x, y, 0, self.plotter.renderer)
            if picker.GetActor() is None:
                if self._last_hover_text and self._base_status_text:
                    self.status.setText(self._base_status_text)
                    self._last_hover_text = ''
                return
            wpos = picker.GetPickPosition()
            idx = self._grid.find_closest_point(wpos)
            if idx < 0:
                return
            parts = [f"Cursor: ({wpos[0]:.1f}, {wpos[1]:.1f}, {wpos[2]:.1f}) mm"]
            for fkey in ('Ta', 'Tb', 'Ts', 'vmag', 'vmag_B',
                         'P_kPa', 'P_B_kPa'):
                if fkey in self._arrays:
                    try:
                        val = float(self._grid[fkey][idx])
                    except Exception:
                        continue
                    parts.append(f"{FIELD_META[fkey]['title']} = "
                                 f"{val:{FIELD_META[fkey]['fmt'][1:]}}")
        except Exception:
            return
        hover_text = "   •   ".join(parts)
        if hover_text != self._last_hover_text:
            self.status.setText(hover_text)
            self._last_hover_text = hover_text

    # ─────────────────────────── callbacks ────────────────────────────

    def _on_field_changed(self, idx):
        if idx < 0 or self._grid is None:
            return
        # 2026-05-20 UI sweep: itemData(idx) can return None if the combo
        # is mid-rebuild (e.g. set_fields re-populating items) or stale
        # vs `_arrays`. Skip silently rather than poisoning `self._field`
        # with None and crashing downstream `FIELD_META[None]` lookups.
        _new_field = self.combo_field.itemData(idx)
        if _new_field is None or _new_field not in self._arrays \
                or _new_field not in FIELD_META:
            return
        self._field = _new_field
        # Batch volume + slice actor mutations into a single GPU flush.
        # Without this, switching fields triggers 2-3 sequential pl.render()
        # calls (visible stutter on 100×40×30 grids — user pain point).
        self._rebuild_volume(render=False)
        if self._slice_info is not None:
            self._add_slice_actor(self._slice_info['axis'],
                                  self._slice_info['coord_mm'], render=False)
        self.plotter.render()
        self._update_status()

    def _on_plane_changed(self, idx):
        self._update_coord_label()
        self._validate_coord_input()
        # If a slice is already showing, switching plane should auto-reapply
        # (reveals the new orientation immediately, no Apply-click needed).
        if self._slice_info is not None and self.btn_apply.isEnabled():
            self._on_apply_slice_realtime()

    def _on_coord_text_changed(self, _txt: str):
        """Live-validate + debounced realtime slice on valid input."""
        self._validate_coord_input()
        if self.btn_apply.isEnabled():
            self._coord_debounce.start()     # 240 ms debounce

    def _on_apply_slice_realtime(self):
        """Realtime-apply variant: slice in-place without popping the 2D window.

        Explicit Apply button still pops the matplotlib window for archival.
        Keeps the 3D viewport fluid while the user scrubs through coords.
        """
        if self._grid is None or not self.btn_apply.isEnabled():
            return
        try:
            coord_mm = float(self.le_coord.text())
        except ValueError:
            return
        axis = self._current_axis()
        hi = {'x': self._L_mm[0], 'y': self._L_mm[1],
              'z': self._L_mm[2]}[axis]
        if coord_mm < 0.0 or coord_mm > hi:
            return
        self._slice_info = {'axis': axis, 'coord_mm': coord_mm}
        if self._scale_mode == 'local':
            self._rebuild_volume(render=False)
        self._add_slice_actor(axis, coord_mm, render=False)
        self.plotter.render()
        self.btn_clear.setEnabled(True)
        self._update_status()

    def _set_view(self, preset: str):
        """Tween camera from its current pose to a canonical preset.

        The shared elapsed-time clock advances a 300 ms timeline by real
        elapsed time; late frames skip ahead instead of extending the motion.
        Reduced-motion envs (QT_REDUCED_MOTION=1) get an instant snap.
        """
        self._stop_camera_tween()
        pl = self.plotter
        # Obtain the fitted target without first rendering a jump to it.
        cam = pl.camera
        start = (tuple(cam.position), tuple(cam.focal_point), tuple(cam.up), cam.view_angle)
        if preset == 'top':
            pl.view_xy(render=False)
        elif preset == 'front':
            pl.view_xz(render=False)
        elif preset == 'side':
            pl.view_yz(render=False)
        else:
            pl.view_isometric(render=False)
        self.fit_view(render=False)
        end = (tuple(cam.position), tuple(cam.focal_point), tuple(cam.up), cam.view_angle)

        import os as _os
        reduced = _os.environ.get('QT_REDUCED_MOTION', '').lower() in ('1', 'true')
        if reduced or start == end or not self.isVisible():
            if self.isVisible():
                pl.render()
            self._sync_view_button(preset)
            return

        # Rewind to start and tween forward.
        cam.position = start[0]
        cam.focal_point = start[1]
        cam.up = start[2]
        cam.view_angle = start[3]

        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(300)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._tween_animation = animation
        self._tween_end_pose = end
        self._tween_preset = preset
        self._tween_previous_update_rate = pl.ren_win.GetDesiredUpdateRate()
        # VTK distributes this budget to its renderers. Keep its existing
        # adaptive sampling during motion and restore the original still rate.
        pl.ren_win.SetDesiredUpdateRate(_CAMERA_UPDATE_RATE)

        def _step(ease):
            def _lerp(a, b): return tuple(a[k] + (b[k] - a[k]) * ease for k in range(3))
            cam.position = _lerp(start[0], end[0])
            cam.focal_point = _lerp(start[1], end[1])
            cam.up = _lerp(start[2], end[2])
            cam.view_angle = start[3] + (end[3] - start[3]) * ease
            # The shared clock can complete this timeline during window Hide;
            # do not render an endpoint after the native window is hidden.
            window = self.window().windowHandle()
            if self.isVisible() and window is not None and window.isVisible():
                pl.render()

        def _finished():
            if self._tween_animation is animation:
                self._stop_camera_tween()
                self._sync_view_button(preset)
                window = self.window().windowHandle()
                if self.isVisible() and window is not None and window.isVisible():
                    pl.render()  # Refresh the endpoint at the original still quality.

        animation.valueChanged.connect(_step)
        animation.finished.connect(_finished)
        from .microanim import start_animation
        start_animation(self, animation)

    def fit_view(self, *, render=True):
        """Frame the current orientation using the actual viewport aspect."""
        if getattr(self, '_grid', None) is None:
            return
        self._stop_camera_tween()
        if not self.isVisible():
            self._camera_fit_pending = True
            return
        self._camera_fit_pending = False
        # Native screen-space fitting avoids the excess space of a bounding
        # sphere, while reserving a margin for axis labels and the scalar bar.
        self.plotter.renderer.ResetCameraScreenSpace(0.8)
        self.plotter.renderer.ResetCameraClippingRange()
        if render:
            self.plotter.render()

    def _cancel_preset_for_interaction(self, _obj, _event):
        self._camera_fit_pending = False
        if self._tween_animation is not None:
            self._stop_camera_tween()
            # VTK enters the interactive budget before emitting this event;
            # stopping the preset must not replace it with the saved still rate.
            self.plotter.ren_win.SetDesiredUpdateRate(
                self.plotter.iren.interactor.GetDesiredUpdateRate())

    def _stop_camera_tween(self, *, snap=False):
        animation = self._tween_animation
        self._tween_animation = None
        if animation is not None:
            animation.stop()
            animation.deleteLater()
        rate = self._tween_previous_update_rate
        self._tween_previous_update_rate = None
        if rate is not None:
            self.plotter.ren_win.SetDesiredUpdateRate(rate)
        end = self._tween_end_pose
        self._tween_end_pose = None
        if snap and end is not None:
            cam = self.plotter.camera
            cam.position, cam.focal_point, cam.up = end[:3]
            cam.view_angle = end[3]
            self._sync_view_button(self._tween_preset)

    def _sync_view_button(self, preset: str):
        """Reflect the active view preset on the segmented button group."""
        btn_map = {
            'top': self.btn_view_top, 'front': self.btn_view_front,
            'side': self.btn_view_side, 'iso': self.btn_view_iso,
        }
        btn = btn_map.get(preset)
        if btn is not None and not btn.isChecked():
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)

    def _current_axis(self) -> str:
        plane_id = self.combo_plane.currentData()
        return dict((p, a) for (p, _l, a) in _PLANE_OPTIONS)[plane_id]

    def _validate_coord_input(self):
        """Flag the coord field when value is out of domain, disable Apply.

        Skips the unpolish/polish round-trip when the error state hasn't
        actually changed (cached on `_coord_error_state`). Old code did
        full QSS re-evaluation on every keystroke (~1 ms each); on
        consecutive keys with same state that's wasted work + a tiny
        flicker on some Windows display chains.
        """
        if self._grid is None:
            return
        ok = True
        txt = self.le_coord.text().strip()
        try:
            v = float(txt)
        except ValueError:
            ok = False
        else:
            axis = self._current_axis()
            hi = {'x': self._L_mm[0], 'y': self._L_mm[1],
                  'z': self._L_mm[2]}[axis]
            if v < 0.0 or v > hi:
                ok = False
        prev = getattr(self, '_coord_error_state', None)
        if prev is not ok:
            self.le_coord.setProperty('error', 'false' if ok else 'true')
            # Re-polish so stylesheet property selector applies
            style = self.le_coord.style()
            style.unpolish(self.le_coord); style.polish(self.le_coord)
            self._coord_error_state = ok
        self.btn_apply.setEnabled(ok and self.le_coord.isEnabled())
        if not ok and txt:
            axis = self._current_axis()
            hi = {'x': self._L_mm[0], 'y': self._L_mm[1],
                  'z': self._L_mm[2]}[axis]
            self.status.setText(
                f"Coord {txt!r} out of range — must be 0–{hi:.2f} mm.")

    def _on_opacity_changed(self, val: int):
        self._opacity = float(val) / 100.0
        self.lbl_opacity_val.setText(f"{val}%")
        # Coalesce slider drags into one render via 50 ms debounce — without
        # this every tick triggers a full VTK GPU flush (visible stutter on
        # 100×40×30 grids).
        self._opacity_debounce.start()

    def _opacity_ramp(self):
        """(lo_alpha, hi_alpha) opacity-transfer endpoints for the current field.

        Velocity (vmag / vmag_B) is a localized jet in a large stagnant bulk:
        a non-zero low floor turns the bulk into a dark-blue haze that swallows
        the jet (reads as a black blob). So velocity fades low speed to
        TRANSPARENT (lo=0) — only moving fluid is drawn, the jet stands out.
        Temperature / pressure span the whole domain, so they keep a 0.4 low
        floor to keep the cold/low half visible (else it reads as "all red").
        """
        if self._opacity <= 1e-6:
            return 0.0, 0.0
        if self._field in ('vmag', 'vmag_B'):
            return 0.0, self._opacity
        return self._opacity * 0.4, self._opacity

    def _apply_opacity_now(self):
        """Apply current `self._opacity` to the volume actor + render once."""
        if self._volume_actor is not None and self._field is not None:
            try:
                from vtkmodules.vtkCommonDataModel import vtkPiecewiseFunction
                lo, hi = self._clim_for(self._field)
                if abs(hi - lo) < 1e-12:
                    hi = lo + 1.0
                pw = vtkPiecewiseFunction()
                lo_a, hi_a = self._opacity_ramp()
                pw.AddPoint(lo, lo_a); pw.AddPoint(hi, hi_a)
                self._volume_actor.GetProperty().SetScalarOpacity(pw)
                self.plotter.render()
                return
            except Exception:
                pass
        self._rebuild_volume()

    def _on_clim_toggled(self, checked: bool):
        self._scale_mode = 'local' if checked else 'global'
        self.btn_clim.setText(f"Range: {'Slice' if checked else 'Full'}")
        # Batch — same rationale as _on_field_changed.
        self._rebuild_volume(render=False)
        if self._slice_info is not None:
            self._add_slice_actor(self._slice_info['axis'],
                                  self._slice_info['coord_mm'], render=False)
        self.plotter.render()
        self._update_status()

    def _on_apply_slice(self):
        if self._grid is None:
            return
        # Cancel any pending realtime debounce; otherwise typing → quick Apply
        # would rebuild the slice twice (once via this handler, once via the
        # 240 ms timer firing afterwards). Bug 14 (2026-04-29).
        self._coord_debounce.stop()
        try:
            coord_mm = float(self.le_coord.text())
        except ValueError:
            self.status.setText("Invalid coordinate — enter a number in mm.")
            return
        plane_id = self.combo_plane.currentData()
        axis = dict((p, a) for (p, _l, a) in _PLANE_OPTIONS)[plane_id]
        lo, hi = 0.0, {'x': self._L_mm[0], 'y': self._L_mm[1],
                       'z': self._L_mm[2]}[axis]
        if coord_mm < lo or coord_mm > hi:
            self.status.setText(
                f"Coord {coord_mm:.2f} mm outside domain [{lo:.1f}, {hi:.1f}] — clamping.")
            coord_mm = max(lo, min(coord_mm, hi))
            self.le_coord.setText(f"{coord_mm:.2f}")
        self._slice_info = {'axis': axis, 'coord_mm': coord_mm}
        if self._scale_mode == 'local':
            self._rebuild_volume(render=False)
        self._add_slice_actor(axis, coord_mm, render=False)
        self.plotter.render()
        self._show_slice_popup(axis, coord_mm)
        self.btn_clear.setEnabled(True)

    def _on_clear_slice(self):
        pl = self.plotter
        try:
            pl.remove_actor(self._slice_actor_name, render=False)
        except Exception:
            pass
        self._slice_info = None
        if self._scale_mode == 'local':
            self._rebuild_volume(render=False)
        pl.render()
        self.btn_clear.setEnabled(False)
        self._update_status()

    def _on_screenshot(self):
        ts = datetime.now().strftime('%Y%m%d-%H%M%S')
        dflt = f"volume_{self._field}_{self._scale_mode}_{ts}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save 3D view as PNG", dflt, "PNG images (*.png)")
        if not path:
            return
        self.plotter.screenshot(path)
        self.status.setText(f"Saved: {path}")

    # ─────────────────────────── rendering ────────────────────────────

    def _render_placeholder(self):
        pl = self.plotter
        pl.clear()
        placeholder = pl.add_text(
            "Set Dimensionality = 3D, configure L/H/Lz + inlet/outlet, then Compute.",
            font_size=8, color=get_theme()['ax_text'], position='upper_edge',
            font='times',
        )
        apply_vtk_font(placeholder.GetTextProperty())
        pl.reset_camera()

    def _render_initial_scene(self):
        pl = self.plotter
        pl.clear()
        t = get_theme()
        pl.add_mesh(self._grid.outline(), color=t['wireframe'], line_width=2, render=False)
        # Minimal bounds: only endpoint ticks (2 per axis) + smaller font
        # so numbers don't collide with the bounding-box edges. The full 3-tick
        # grid was overlapping the wireframe on narrow geometries like 42 mm.
        bounds = pl.show_bounds(
            grid='back', location='outer',
            xtitle='x (mm)', ytitle='y (mm)', ztitle='z (mm)',
            n_xlabels=2, n_ylabels=2, n_zlabels=2,
            all_edges=False, minor_ticks=False, use_2d=False,
            font_size=9, color=t['ax_text'], padding=0.02, font_family='times',
        )
        for axis in range(3):
            apply_vtk_font(bounds.GetTitleTextProperty(axis))
            apply_vtk_font(bounds.GetLabelTextProperty(axis))
        # Corner XYZ triad — per-label RGB (X red / Y green / Z blue) instead
        # of a single-colour axis helper. Engineers parse orientation by
        # colour convention, so a monochrome triad slows down reading.
        try:
            _vtk_ax = pl.add_axes(
                interactive=False, line_width=2,
                xlabel='X', ylabel='Y', zlabel='Z',
                x_color=t['triad_x'], y_color=t['triad_y'], z_color=t['triad_z'],
                color=t['ax_text'],       # label text colour
            )
        except TypeError:
            # Older PyVista lacks per-axis colour kwargs; fall back to mono.
            _vtk_ax = pl.add_axes(
                interactive=False, line_width=2,
                xlabel='X', ylabel='Y', zlabel='Z',
                color=t['ax_text'],
            )
        for caption in (_vtk_ax.GetXAxisCaptionActor2D(),
                        _vtk_ax.GetYAxisCaptionActor2D(),
                        _vtk_ax.GetZAxisCaptionActor2D()):
            apply_vtk_font(caption.GetCaptionTextProperty())
        self._add_flow_glyph()
        pl.view_isometric(render=False)
        # Keep the native fit for any core aspect and viewport height.

    def _add_flow_glyph(self):
        """Place faint inlet/outlet cone arrows on domain faces per flow_dir.

        Keeps the 3D view self-orienting — user can tell the inlet face at a
        glance without reading status text. Cones are thin + semi-opaque so
        they never compete with the volume data for visual weight.
        """
        if self._grid is None:
            return
        t = get_theme()
        Lx, Ly, Lz = self._L_mm
        tip_len = max(1.5, 0.12 * min(Lx, Ly, Lz))
        radius = tip_len * 0.35

        def _centres(flow_dir):
            axis = flow_dir.lstrip('+-')
            sign = -1.0 if flow_dir.startswith('-') else 1.0
            if axis == 'x':
                inlet = (0.0, Ly * 0.5, Lz * 0.5) if sign > 0 else (Lx, Ly * 0.5, Lz * 0.5)
                outlet = (Lx, Ly * 0.5, Lz * 0.5) if sign > 0 else (0.0, Ly * 0.5, Lz * 0.5)
                direction = (sign, 0, 0)
            elif axis == 'y':
                inlet = (Lx * 0.5, 0.0, Lz * 0.5) if sign > 0 else (Lx * 0.5, Ly, Lz * 0.5)
                outlet = (Lx * 0.5, Ly, Lz * 0.5) if sign > 0 else (Lx * 0.5, 0.0, Lz * 0.5)
                direction = (0, sign, 0)
            else:
                inlet = (Lx * 0.5, Ly * 0.5, 0.0) if sign > 0 else (Lx * 0.5, Ly * 0.5, Lz)
                outlet = (Lx * 0.5, Ly * 0.5, Lz) if sign > 0 else (Lx * 0.5, Ly * 0.5, 0.0)
                direction = (0, 0, sign)
            return inlet, outlet, direction

        def _add_pair(flow_dir, tag, inlet_color, outlet_color, opacity):
            inlet_center, outlet_center, direction = _centres(flow_dir)
            inlet_cone = pv.Cone(center=inlet_center, direction=direction,
                                 height=tip_len, radius=radius, resolution=32)
            outlet_cone = pv.Cone(center=outlet_center, direction=direction,
                                  height=tip_len, radius=radius, resolution=32)
            self.plotter.add_mesh(
                inlet_cone, color=inlet_color, opacity=opacity,
                name=f'_flow_inlet_{tag}', show_scalar_bar=False, lighting=True, render=False)
            self.plotter.add_mesh(
                outlet_cone, color=outlet_color, opacity=opacity,
                name=f'_flow_outlet_{tag}', show_scalar_bar=False, lighting=True, render=False)

        try:
            _add_pair(self._flow_dir, 'A',
                      t['inlet_color'], t['outlet_color'], 0.55)
            if self._flow_dir_B and any(f in self._arrays for f in ('Tb', 'vmag_B', 'P_B_kPa')):
                _add_pair(self._flow_dir_B, 'B',
                          t.get('accent_green', t['inlet_color']),
                          t.get('accent_primary', t['outlet_color']),
                          0.45)
        except Exception:
            pass

    def _clim_for(self, fkey: str):
        """Resolve (lo, hi) clim for the given field per current scale mode."""
        if self._scale_mode == 'global' or fkey not in self._arrays:
            return self._global_clim.get(fkey, (0.0, 1.0))
        # local: computed from current slice (if any) else global
        if self._slice_info is None:
            return self._global_clim.get(fkey, (0.0, 1.0))
        axis = self._slice_info['axis']
        idx = self._slice_index(axis, self._slice_info['coord_mm'])
        arr = self._arrays[fkey]
        if axis == 'x':
            slc = arr[idx, :, :]
        elif axis == 'y':
            slc = arr[:, idx, :]
        else:
            slc = arr[:, :, idx]
        lo, hi = float(slc.min()), float(slc.max())
        if hi - lo < 1e-12:
            hi = lo + 1.0
        return lo, hi

    def _build_volume_grid(self):
        """Cache the selected field's smooth display grid on first access.

        Returns (grid_with_point_data, fine_min_cell_mm). The display-only
        upsample factor is unchanged (up to 3× per axis, targeting ~300k
        cells). Interpolates original cell-centre values in physical space,
        holding the nearest centre value across the exterior half cells.
        Falls back to the raw grid if SciPy is missing or the factor is 1.
        Slices, hover and color ranges retain the real compute grid.
        """
        if self._field in self._volume_grids:
            return self._volume_grids[self._field]
        raw_min = float(min(self._dx_mm.min(), self._dy_mm.min(),
                            self._dz_mm.min()))
        try:
            from scipy.interpolate import RegularGridInterpolator
        except Exception:
            return self._grid, raw_min
        if not self._arrays:
            return self._grid, raw_min
        field = self._arrays[self._field]
        Nx, Ny, Nz = field.shape
        ncells = max(Nx * Ny * Nz, 1)
        # Cap total fine cells ~3e5 so the GPU upload + ray-cast stay light
        # enough that scroll-zoom / rotation re-renders feel responsive (the
        # trilinear upsample — not the raw cell count — is what kills banding,
        # so a smaller cap keeps smoothness while cutting the per-frame cost).
        # AutoAdjust still coarsens the ray step during active interaction.
        f = int(np.clip(round((3.0e5 / ncells) ** (1.0 / 3.0)), 1, 3))
        if f <= 1:
            return self._grid, raw_min
        Lx, Ly, Lz = self._L_mm
        nx, ny, nz = Nx * f, Ny * f, Nz * f
        axes = [np.linspace(0.0, length, n + 1)
                for length, n in zip((Lx, Ly, Lz), (nx, ny, nz))]
        centres = [np.cumsum(widths) - 0.5 * widths
                   for widths in (self._dx_mm, self._dy_mm, self._dz_mm)]
        points = np.stack(np.meshgrid(
            *(np.clip(axis, centre[0], centre[-1])
              for axis, centre in zip(axes, centres)), indexing='ij'), axis=-1)
        fine = RegularGridInterpolator(centres, field)(points)
        gv = pv.RectilinearGrid(*axes)
        gv.point_data[self._field] = fine.flatten(order='F')
        result = gv, float(min(Lx/nx, Ly/ny, Lz/nz))
        self._volume_grids[self._field] = result
        return result

    def _rebuild_volume(self, render: bool = True):
        """Redraw the volume-rendered cube for the current field.

        `render=False` lets cascade callers (field/clim/slice toggle) batch
        multiple actor mutations into a single GPU flush. Default True
        preserves drop-in behaviour for direct callers (slider drag,
        opacity apply).
        """
        if self._grid is None or self._field is None:
            return
        pl = self.plotter
        # Remove previous volume + scalar bars (but keep slice if any)
        try:
            pl.remove_actor('main_volume', render=False)
        except Exception:
            pass
        # Clear ALL existing scalar bars so we never show two for one field.
        # (PyVista's add_volume + slice without `show_scalar_bar=False`
        # previously spawned a horizontal bar at the bottom of the viewport.)
        try:
            pl.remove_scalar_bar(render=False)
        except Exception:
            pass
        for fkey in list(FIELD_META.keys()):
            try:
                pl.remove_scalar_bar(FIELD_META[fkey]['title'], render=False)
            except Exception:
                pass
        # 2026-05-20 UI sweep: guard against `self._field` being a stale
        # / unknown key (race between field-combo rebuild and external
        # callers of `_rebuild_volume`). Also clear `_volume_actor`
        # ahead of `add_volume` so an exception below does not leave a
        # dangling reference to the just-removed actor.
        self._volume_actor = None
        if self._field not in FIELD_META:
            if render:
                pl.render()
            return
        self._grid_vol, self._vol_min_cell_mm = self._build_volume_grid()
        vol_grid = self._grid_vol
        meta = FIELD_META[self._field]
        clim = self._clim_for(self._field)
        opacity_list = list(self._opacity_ramp())
        t = get_theme()
        try:
            self._volume_actor = pl.add_volume(
                vol_grid, scalars=self._field,
                cmap=meta['cmap'], clim=clim,
                opacity=opacity_list,
                # Keep scalar colours independent of scene lighting.
                shade=False,
                name='main_volume',
                render=False,
                show_scalar_bar=False,     # suppress volume's built-in bar
            )
            # Ray sampling on the UPSAMPLED grid. Smoothness now comes from the
            # trilinearly-upsampled DATA (fine cells), which DECOUPLES it from
            # the ray sample distance — so AutoAdjust can be ON: VTK coarsens
            # the ray step only DURING camera/slider interaction (responsive
            # rotation, fixes the lag) and still renders the full-quality still
            # frame on settle. Even the coarse interactive step looks smooth
            # because adjacent fine cells barely differ. `0.005` floor guards
            # degenerate grids.
            try:
                vol_mapper = self._volume_actor.GetMapper()
                min_cell = float(getattr(self, '_vol_min_cell_mm', 0.0)) or min(
                    float(self._dx_mm.min()), float(self._dy_mm.min()),
                    float(self._dz_mm.min()))
                vol_mapper.SetAutoAdjustSampleDistances(True)
                vol_mapper.SetSampleDistance(max(0.005, min_cell))
            except Exception:
                pass
            # Scalar bar — responsive placement + Times New Roman. Narrow
            # viewports (<800 px wide) slim the bar so it doesn't overlap
            # the viewport edge.
            win_w = 1.0
            try:
                wsize = pl.window_size
                win_w = max(1, int(wsize[0]))
            except Exception:
                pass
            bar_width = 0.040 if win_w >= 800 else 0.030
            bar_x = 0.905 if win_w >= 800 else 0.920
            _sbar = pl.add_scalar_bar(
                # Shorter (0.55) + lower (0.24) bar centred in the right
                # margin; smaller title (10) so the field label clears the top
                # value instead of overlapping it. Was height 0.76 / pos_y 0.12
                # / title 12 → a too-tall bar pinned to the edge with the title
                # sitting on the max-value label.
                title=meta['title'],
                n_labels=5, vertical=True,
                position_x=bar_x, position_y=0.24,
                width=bar_width, height=0.55,
                fmt=meta['fmt'],
                title_font_size=10, label_font_size=11,
                color=t['ax_text'], font_family='times',
                bold=False, italic=False,
                shadow=False, outline=False,
            )
            apply_vtk_font(_sbar.GetTitleTextProperty())
            apply_vtk_font(_sbar.GetLabelTextProperty())
            # Solid colour bar. The volume's opacity transfer function bled into
            # the scalar bar (semi-transparent over white → washed-out pastel,
            # worst at the hot end). Attach an independent OPAQUE turbo LUT over
            # the clim so the legend reads vivid, decoupled from voxel opacity.
            try:
                import pyvista as _pv
                _lut = _pv.LookupTable(cmap=meta['cmap'])
                _lut.scalar_range = clim
                _sbar.SetLookupTable(_lut)
            except Exception:
                pass
            # Push the title up off the bar so it stops crowding the top value
            # label (e.g. "Ta (K)" sitting on "422.0"). VTK default separation
            # is ~0 px; ~14 px gives clear air between title and the max tick.
            try:
                _sbar.SetVerticalTitleSeparation(14)
            except Exception:
                pass

        except Exception as e:
            # GPU/VTK volume rendering may fail on some driver combos; fall
            # back to an outlined bounding box + user slice (if any).
            self.status.setText(
                f"Volume rendering unavailable ({e!s}); use Apply to see slices.")
        if render:
            pl.render()

    def _slice_index(self, axis: str, coord_mm: float) -> int:
        """Map mm coord along `axis` to nearest cell-centre index.

        Uses pre-cached centres from set_fields() — was rebuilding the cumsum
        per call, which dominated cost on rapid coord-text typing (debounced
        but still O(N) per debounce tick).
        """
        centres = {'x': self._cx_mm, 'y': self._cy_mm, 'z': self._cz_mm}[axis]
        return int(np.argmin(np.abs(centres - coord_mm)))

    def _add_slice_actor(self, axis: str, coord_mm: float, render: bool = True):
        """Add (or replace) a single user slice actor overlaid on the volume.

        `render=False` defers the GPU flush so cascade callers can batch.
        """
        if self._grid is None:
            return
        pl = self.plotter
        try:
            pl.remove_actor(self._slice_actor_name, render=False)
        except Exception:
            pass
        normal = {'x': (1.0, 0.0, 0.0),
                  'y': (0.0, 1.0, 0.0),
                  'z': (0.0, 0.0, 1.0)}[axis]
        cx, cy, cz = self._grid.center
        origin = {'x': (coord_mm, cy, cz),
                  'y': (cx, coord_mm, cz),
                  'z': (cx, cy, coord_mm)}[axis]
        try:
            slc = self._grid.slice(normal=normal, origin=origin)
        except Exception as e:
            self.status.setText(f"Slice failed: {e}")
            return
        # 2026-05-20 UI sweep (Tier 19): mirror the FIELD_META guard
        # already present in `_rebuild_volume` so a stale / unknown
        # `_field` (combo mid-rebuild, external caller) does not
        # KeyError mid-slice and leak a partially-built actor.
        if self._field not in FIELD_META:
            try:
                self.status.setText(
                    "Slice skipped: unknown field selection.")
            except Exception:
                pass
            return
        meta = FIELD_META[self._field]
        pl.add_mesh(
            slc, scalars=self._field, cmap=meta['cmap'],
            clim=self._clim_for(self._field), lighting=False,
            show_edges=False, name=self._slice_actor_name,
            show_scalar_bar=False,     # volume owns the single scalar bar
            render=False,
        )
        if render:
            pl.render()

    def _show_slice_popup(self, axis: str, coord_mm: float):
        """Pop up a matplotlib window with the 2D contour of the slice."""
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

        # 2026-05-20 UI sweep: guard against the field combo being empty or
        # the user racing field selection between Apply-slice click and the
        # popup spawn. Previously `self._arrays[key]` / `FIELD_META[key]`
        # could KeyError or None-deref and crash the dialog mid-construction.
        key = self._field
        if key is None or key not in self._arrays or key not in FIELD_META:
            try:
                self.status.setText(
                    "No valid field selected for slice popup.")
            except Exception:
                pass
            return
        field = self._arrays[key]
        idx = self._slice_index(axis, coord_mm)
        if axis == 'x':
            slc2d = field[idx, :, :]
            horiz = self._cy_mm; vert = self._cz_mm
            h_lbl, v_lbl = 'Y [mm]', 'Z [mm]'
        elif axis == 'y':
            slc2d = field[:, idx, :]
            horiz = self._cx_mm; vert = self._cz_mm
            h_lbl, v_lbl = 'X [mm]', 'Z [mm]'
        else:
            slc2d = field[:, :, idx]
            horiz = self._cx_mm; vert = self._cy_mm
            h_lbl, v_lbl = 'X [mm]', 'Y [mm]'

        meta = FIELD_META[key]
        t = get_theme()
        dlg = QDialog(self)
        # WA_DeleteOnClose: destroy dialog widget when user closes it so the
        # matplotlib Figure + canvas are released. Previously they leaked
        # because dlg.close() only hid the widget. Bug 9 (2026-04-29).
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.setWindowTitle(
            f"Slice {axis.upper()}={coord_mm:.2f} mm  |  {meta['label']}")
        dlg.setStyleSheet(f"QDialog {{ background: {t['bg']}; color: {t['fg']}; }}")
        # Size the figure to the slice's data aspect so an equal-aspect plot of
        # a wide-short domain fills the frame instead of leaving a big vertical
        # whitespace band. Clamp extreme aspects to keep the dialog usable.
        _w = float(np.ptp(horiz)); _h = float(np.ptp(vert))
        _asp = min(max(_w / _h, 0.4), 7.0) if _h > 0 else 3.0
        _plot_w = 7.0
        _fig_w = _plot_w + 1.9                       # axes + colorbar + y-label
        _fig_h = max(_plot_w / _asp + 1.5, 2.8)      # axes + title + x-label
        fig = Figure(figsize=(_fig_w, _fig_h), dpi=110)
        fig.patch.set_facecolor(t['fig_bg'])
        canvas = FigureCanvasQTAgg(fig)
        ax = fig.add_subplot(111)
        ax.set_facecolor(t['ax_bg'])
        # contourf with 256 levels (turbo's full LUT) — iso-bands keep small
        # local features (jets, hot/cold spots) crisp for detail inspection,
        # which Gouraud smoothing softened on the coarse grid. horiz/vert are
        # cell centres; meshgrid builds the matching X/Y mesh.
        Hx, Vy = np.meshgrid(horiz, vert)
        im = ax.contourf(Hx, Vy, slc2d.T, levels=256, cmap=meta['cmap'])
        # fraction/pad keep the colorbar height matched to the (possibly short)
        # axes instead of the tall thin default bar.
        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label(meta['title'], color=t['ax_text'])
        cbar.ax.tick_params(colors=t['ax_text'])
        cbar.outline.set_edgecolor(t['ax_spine'])
        ax.set_xlabel(h_lbl, color=t['ax_text']); ax.set_ylabel(v_lbl, color=t['ax_text'])
        ax.tick_params(colors=t['ax_text'])
        for sp in ax.spines.values():
            sp.set_edgecolor(t['ax_spine'])
        ax.set_aspect('equal')
        ax.set_title(
            f"{meta['label']} — slice {axis.upper()} = {coord_mm:.2f} mm",
            color=t['ax_text'])
        fig.tight_layout()

        lay = QVBoxLayout(dlg)
        toolbar = NavigationToolbar(canvas, dlg)
        lay.addWidget(toolbar)
        lay.addWidget(canvas, stretch=1)
        btn_row = QHBoxLayout()
        btn_save = QPushButton("Save PNG")
        btn_save.setStyleSheet(_btn_qss()); btn_save.setFixedHeight(_CTRL_HEIGHT)
        btn_save.clicked.connect(
            lambda: self._save_figure(fig, axis, coord_mm, key))
        btn_close = QPushButton("Close")
        btn_close.setStyleSheet(_btn_qss()); btn_close.setFixedHeight(_CTRL_HEIGHT)
        btn_close.clicked.connect(dlg.close)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)
        dlg.resize(900, 680)

        def _on_closed():
            try:
                self._popup_dialogs.remove(dlg)
            except ValueError:
                pass
            # Release the matplotlib Figure so the canvas backend frees its
            # off-screen buffers. Without this, Figure objects accumulate
            # even after WA_DeleteOnClose destroys the QDialog wrapper.
            try:
                import matplotlib.pyplot as _plt
                _plt.close(fig)
            except Exception:
                pass
        dlg.finished.connect(lambda _=None: _on_closed())
        # Cap concurrent slice popups at 5 — close oldest if user opens
        # additional ones. Without this `_popup_dialogs` grew unbounded
        # across long sessions, leaking matplotlib Figure buffers (~5 MB
        # each on 100×100 grids).
        _MAX_POPUPS = 5
        while len(self._popup_dialogs) >= _MAX_POPUPS:
            old = self._popup_dialogs.pop(0)
            try:
                old.close()
            except Exception:
                pass
        self._popup_dialogs.append(dlg)
        dlg.show()

    def _save_figure(self, fig, axis: str, coord_mm: float, key: str):
        ts = datetime.now().strftime('%Y%m%d-%H%M%S')
        dflt = f"slice_{key}_{axis}_{coord_mm:.2f}mm_{ts}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save 2D slice", dflt,
            "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)")
        if not path:
            return
        try:
            fig.savefig(path, dpi=200, bbox_inches='tight')
            self.status.setText(f"Saved slice: {path}")
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))

    # ─────────────────────────── status helpers ───────────────────────

    def _update_coord_label(self):
        """Update the coord label to show valid range for the selected plane."""
        if self._grid is None:
            self.lbl_coord.setText("Coord:")
            return
        plane_id = self.combo_plane.currentData()
        axis = dict((p, a) for (p, _l, a) in _PLANE_OPTIONS)[plane_id]
        hi = {'x': self._L_mm[0], 'y': self._L_mm[1], 'z': self._L_mm[2]}[axis]
        self.lbl_coord.setText(f"{axis.upper()} coord (0–{hi:.1f} mm):")

    def _update_status(self):
        if self._grid is None or self._field is None:
            return
        # 2026-05-20 UI sweep (Tier 19): consistent FIELD_META guard
        # across all render-status paths. Without this, a transient
        # unknown `_field` (combo race / external set) crashed status
        # rebuilds and left the status bar stuck on a stale message.
        if self._field not in FIELD_META:
            return
        lo, hi = self._global_clim.get(self._field, (0.0, 1.0))
        Lx, Ly, Lz = self._L_mm
        color_range_label = 'Slice' if self._scale_mode == 'local' else 'Full'
        parts = [
            f"Field: {FIELD_META[self._field]['title']}",
            f"Range: {lo:.2f} – {hi:.2f}",
            f"Color Range: {color_range_label}",
            f"Domain: {Lx:.0f} × {Ly:.0f} × {Lz:.0f} mm",
        ]
        if self._slice_info is not None:
            parts.append(
                f"Slice: {self._slice_info['axis'].upper()}"
                f" = {self._slice_info['coord_mm']:.2f} mm")
        else:
            parts.append("Slice: none (click Apply)")
        text = "   •   ".join(parts)
        self._base_status_text = text
        self.status.setText(text)
        self.status.setToolTip(text)
        self._last_hover_text = ''
