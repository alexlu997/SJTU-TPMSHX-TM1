"""Embedded PyVistaQt 3D viewport with unified toolbar and Qt overlays.

Provides ``ThreeDVisPanel(QWidget)`` hosting a ``pyvistaqt.QtInteractor`` with:
- One unified bottom ``VolumeToolbar`` (no cut-away ``剖切``).
- ``外表面`` (outer surface) as the default simplified display mode.
- Three orthogonal slices (``截面``) with snapped physical cell coordinates.
- Ray-cast volume rendering (``体渲染``) with debounced opacity control.
- Closed lattice phase domains (``晶格``) built on a worker thread.
- Floating Qt ``StudioColorbarCard`` and camera-projected ``PortChipOverlay``.
- One ``capture_image()`` path compositing VTK pixels and scientific overlays
  for both Copy and Save exports.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Callable, Mapping, Optional, Sequence

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import QEasingCurve, QPoint, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QImage, QKeySequence, QPainter, QRegion, QShortcut
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from tm1.applications.gui.ui.microanim import is_reduced_motion, start_animation
from tm1.applications.gui.ui.symbols import MINUS, SYM, qsym
from tm1.applications.gui.ui.theme import get_theme, get_theme_name, resolve_cmap
from tm1.applications.gui.ui.typography import (
    FONT_FAMILIES,
    SCREEN_CHART_FAMILIES,
    apply_vtk_font,
    matplotlib_font_families,
)
from tm1.applications.gui.ui.vis3d_constants import (
    FIELD_ORDER,
    field_color_limits,
    validate_color_range_state,
)
from tm1.applications.gui.ui.vis3d_lattice_worker import LatticeBuilder, LatticeRequest
from tm1.applications.gui.ui.volume_overlays import (
    COLORBAR_HEIGHT,
    COLORBAR_WIDTH,
    LatticeDomainCard,
    LatticeProgressCard,
    PortAnchor,
    PortChipOverlay,
    StudioColorbarCard,
)
from tm1.applications.gui.ui.volume_toolbar import (
    CAMERA_PRESETS,
    DISPLAY_MODES,
    VolumeToolbar,
)
from tm1.physical_models.tpms_geometry import lattice_cell_size
from tm1.postprocess.result_display import PANEL_FIELD_SPECS

_CAMERA_UPDATE_RATE = 120.0  # Adaptive motion budget, not a guaranteed FPS.

_FIELD_SYMBOL_HTML: dict[str, str] = {
    "Ta": SYM["T_fA"],
    "Tb": SYM["T_fB"],
    "Ts": SYM["T_s"],
    "vmag": SYM["vmag_A"],
    "vmag_B": SYM["vmag_B"],
    "P_kPa": qsym("P", "A"),
    "P_B_kPa": qsym("P", "B"),
    "L_mm": SYM["L"],
    "t_mm": SYM["t"],
}

_DATA_ACTOR_NAMES: tuple[str, ...] = (
    "main_surface",
    "main_lattice",
    "main_volume",
    "slice_x",
    "slice_y",
    "slice_z",
    "slice_x_edge",
    "slice_y_edge",
    "slice_z_edge",
    "_slice_cross_x",
    "_slice_cross_y",
    "_slice_cross_z",
    "_slice_probe",
    "_slice_box_fill",
    "_domain_edges",
)

_PORT_ACTOR_PREFIXES: tuple[str, ...] = (
    "_port_inlet_A",
    "_port_outlet_A",
    "_port_inlet_B",
    "_port_outlet_B",
    "_flow_inlet_A",
    "_flow_outlet_A",
    "_flow_inlet_B",
    "_flow_outlet_B",
)


# The lattice shows the phase domain of the active field. Design fields L and t use the solid wall.
_LATTICE_PHASE: dict[str, str] = {"A": "A", "B": "B", "solid": "S", "geometry": "S"}
_LATTICE_DOMAIN_NAME: dict[str, str] = {"A": "流体 A 域", "B": "流体 B 域", "S": "固体域"}
_LATTICE_STAGE_COUNT = 5
_NO_LATTICE_SOURCE = "此三维视图不提供晶格"
_GRADED_L_REASON = "梯度胞元 L 的晶格相规则尚未确定"


def _lattice_rule_html(phase: str, delta: float) -> str:
    """Return the phase rule of one domain. A zero level-set offset gives the short form."""
    phi, c, d = "<i>φ</i>", "<i>C</i>", "<i>δ</i>"
    if delta == 0.0:
        rules = {"A": f"{phi} &lt; {MINUS}{c}", "B": f"{phi} &gt; +{c}", "S": f"|{phi}| ≤ {c}"}
    else:
        rules = {
            "A": f"{phi} &lt; {d} {MINUS} {c}",
            "B": f"{phi} &gt; {d} + {c}",
            "S": f"|{phi} {MINUS} {d}| ≤ {c}",
        }
    return rules[phase]


def _hex_to_rgb01(hex_color: str) -> tuple[float, float, float]:
    raw = hex_color.lstrip("#")
    return tuple(int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def _axis_decimals(centres: np.ndarray) -> int:
    """Return the fewest decimals (>=1) that keep every cell centre label distinct."""
    for digits in range(1, 6):
        if len({f"{float(c):.{digits}f}" for c in centres}) == len(centres):
            return digits
    return 6


class ThreeDVisPanel(QWidget):
    """Embedded PyVistaQt 3D viewport with studio rendering and Qt overlays."""

    field_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        opacity_default = 30 if get_theme_name() == "dark" else 25

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._build_viewport(root, opacity_default)
        self._init_state(opacity_default)
        self._init_timers()
        self._install_shortcuts()
        self._render_placeholder()
        self._setup_observers()

    def _build_viewport(self, root: QVBoxLayout, opacity_default: int) -> None:
        """Build the full-bleed PyVista interactor and floating Style P2 overlays."""
        tokens = get_theme()

        self._viewport_host = QWidget(self)
        self._viewport_host.setObjectName("volumeViewportHost")
        host_lay = QVBoxLayout(self._viewport_host)
        host_lay.setContentsMargins(0, 0, 0, 0)
        host_lay.setSpacing(0)

        self.plotter = QtInteractor(self._viewport_host)
        self.plotter.interactor.setMinimumHeight(160)
        self._pause_rendering()  # A newly constructed panel is still hidden.
        host_lay.addWidget(self.plotter.interactor, stretch=1)
        root.addWidget(self._viewport_host, stretch=1)

        pv.set_plot_theme("dark" if get_theme_name() == "dark" else "document")
        self.plotter.set_background(tokens["canvas"])

        self.port_overlay = PortChipOverlay(tokens=tokens, parent=self._viewport_host)
        self.port_overlay.hide()

        self.colorbar = StudioColorbarCard(tokens=tokens, parent=self._viewport_host)
        self.colorbar.hide()

        self._watermark_label = QLabel(self._viewport_host)
        self._watermark_label.setObjectName("volumeWatermark")
        self._watermark_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._watermark_label.setWordWrap(True)
        self._watermark_label.hide()

        self.status = QLabel(self._viewport_host)
        self.status.setObjectName("volumeHoverStatus")
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.status.hide()

        self.toolbar = VolumeToolbar(
            geometry_mode="simple",
            display_mode="surface",
            opacity=opacity_default / 100.0,
            camera_preset="iso",
            lattice_enabled=False,
            lattice_disabled_reason=_NO_LATTICE_SOURCE,
            tokens=tokens,
            parent=self._viewport_host,
        )
        self.toolbar.geometry_mode_changed.connect(self._on_toolbar_geometry_changed)
        self.toolbar.detail_level_changed.connect(self._on_toolbar_detail_changed)
        self.toolbar.display_mode_changed.connect(self._on_toolbar_display_mode_changed)
        self.toolbar.slice_position_changed.connect(self._on_toolbar_slice_changed)
        self.toolbar.opacity_changed.connect(self._on_toolbar_opacity_changed)
        self.toolbar.camera_preset_requested.connect(self.set_view)
        self.toolbar.layout_changed.connect(self._layout_overlays)
        self.toolbar.hide()

        self.lattice_progress = LatticeProgressCard(tokens=tokens, parent=self._viewport_host)
        self.lattice_progress.cancel_requested.connect(self._cancel_lattice)
        self.lattice_progress.hide()
        self.lattice_card = LatticeDomainCard(tokens=tokens, parent=self._viewport_host)
        self.lattice_card.hide()

        self._lattice = LatticeBuilder(self)
        self._lattice.progress.connect(self._on_lattice_progress)
        self._lattice.ready.connect(self._on_lattice_ready)
        self._lattice.failed.connect(self._on_lattice_failed)

        self._apply_overlay_styles(tokens)

    def _init_state(self, opacity_default: int) -> None:
        """Initialize field, display-mode, slice, overlay, and camera state."""
        self._grid: Optional[pv.RectilinearGrid] = None
        self._volume_grids: dict[str, tuple[pv.RectilinearGrid, float]] = {}
        self._surface_meshes: dict[str, pv.PolyData] = {}
        self._grid_vol: Optional[pv.RectilinearGrid] = None
        self._vol_min_cell_mm: float = 0.0
        self._arrays: dict[str, np.ndarray] = {}
        self._field_loader: Optional[Callable[[str], np.ndarray]] = None
        self._available_fields: tuple[str, ...] = ()
        self._widths_m: Optional[tuple[np.ndarray, np.ndarray, np.ndarray]] = None
        self._dx_mm: Optional[np.ndarray] = None
        self._dy_mm: Optional[np.ndarray] = None
        self._dz_mm: Optional[np.ndarray] = None
        self._cx_mm: Optional[np.ndarray] = None
        self._cy_mm: Optional[np.ndarray] = None
        self._cz_mm: Optional[np.ndarray] = None
        self._edges_mm: Optional[tuple[np.ndarray, np.ndarray, np.ndarray]] = None
        self._L_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._global_clim: dict[str, tuple[float, float]] = {}
        self._custom_clim: dict[str, tuple[float, float]] = {}
        self._field: Optional[str] = None
        self._scale_mode: str = "global"
        self._sync_temp_scale: bool = True
        self._shared_pressure_scale: bool = True
        self._display_mode: str = "surface"
        self._slice_xyz_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
        # The scene shows ``_geometry`` and ``_detail``. The toolbar holds a pending lattice request.
        self._geometry: str = "simple"
        self._detail: str = "medium"
        self._lattice_source: Optional[tuple[str, float, str]] = None
        # Pending build: (generation, phase, detail, field key).
        self._lattice_pending: Optional[tuple[int, str, str, str]] = None
        self._lattice_mesh: Optional[pv.PolyData] = None
        self._lattice_phase: str = "A"
        self._lattice_retained: bool = False
        self._volume_actor = None
        self._data_actors: set[Any] = set()
        self._last_hover_text: str = ""
        self._base_status_text: str = ""
        self._opacity: float = opacity_default / 100.0
        self._flow_dir: Optional[str] = "+x"
        self._flow_dir_B: Optional[str] = None
        self._ports: dict[str, Any] = {}
        self._port_world_anchors: list[tuple[str, str, str, np.ndarray, np.ndarray]] = []
        self._watermark_text: Optional[str] = None
        self._cleaned_up: bool = False
        self._tween_animation: Optional[QVariantAnimation] = None
        self._tween_end_pose = None
        self._tween_preset: str = "iso"
        self._tween_previous_update_rate = None
        self._camera_fit_pending: bool = False
        self._camera_observer_tag: Optional[int] = None
        self._interaction_observer_tag: Optional[int] = None
        self._hover_observer_tag: Optional[int] = None
        self._hover_last_t: float = 0.0

    def _init_timers(self) -> None:
        """Configure opacity debounce timer for volume rendering drags."""
        self._opacity_debounce = QTimer(self)
        self._opacity_debounce.setSingleShot(True)
        self._opacity_debounce.setInterval(120)
        self._opacity_debounce.timeout.connect(self._apply_opacity_now)

    def _install_shortcuts(self) -> None:
        """Bind T/F/S/I shortcuts to the four canonical camera presets."""
        for key, preset in (("T", "xy"), ("F", "xz"), ("S", "yz"), ("I", "iso")):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda p=preset: self._grid is not None and self.set_view(p))

    def _setup_observers(self) -> None:
        """Connect VTK interaction, hover, and camera-motion observers."""
        if self.plotter.iren is not None:
            iren = self.plotter.iren.interactor
            iren.SetDesiredUpdateRate(_CAMERA_UPDATE_RATE)
            self._interaction_observer_tag = self.plotter.iren.add_observer(
                "StartInteractionEvent", self._cancel_preset_for_interaction
            )
            self._hover_observer_tag = iren.AddObserver(
                "MouseMoveEvent", self._on_mouse_move, 1.0
            )
        camera = self.plotter.renderer.GetActiveCamera()
        if camera is not None:
            self._camera_observer_tag = camera.AddObserver(
                "ModifiedEvent", self._on_camera_modified
            )

    def _apply_overlay_styles(self, tokens: Mapping[str, Any], *, export: bool = False) -> None:
        families = (
            list(matplotlib_font_families())
            if export
            else list(dict.fromkeys((*SCREEN_CHART_FAMILIES, *FONT_FAMILIES)))
        )
        family_css = ",".join(f"'{f}'" for f in families)
        self._watermark_label.setStyleSheet(
            f"QLabel#volumeWatermark {{ background: {tokens['popover']}; "
            f"color: {tokens['warn']}; border: 1px solid {tokens['border']}; "
            f"border-radius: 7px; padding: 4px 10px; font-family: {family_css}; "
            "font-size: 11.5px; font-weight: 600; }"
        )
        self.status.setStyleSheet(
            f"QLabel#volumeHoverStatus {{ background: {tokens['popover']}; "
            f"color: {tokens['sub']}; border: 1px solid {tokens['border']}; "
            f"border-radius: 7px; padding: 4px 10px; font-family: {family_css}; "
            "font-size: 11.5px; font-weight: 500; }"
        )

    # ─────────────────────────── public API ───────────────────────────

    def active_field(self) -> Optional[str]:
        """Return the active PANEL_FIELD_SPECS key on this 3D panel, or None."""
        return self._field

    def available_fields(self) -> tuple[str, ...]:
        """Return loaded PANEL_FIELD_SPECS keys in canonical display order."""
        return self._available_fields

    def _show_field_load_error(self, exc: Exception) -> None:
        self.status.setText(f"场读取失败：{exc}")
        self.status.show()
        self._layout_overlays()

    def select_field(self, field_key: str) -> bool:
        """Select an available field key and update the 3D scene and colorbar."""
        if self._grid is None:
            return False
        if field_key not in self._available_fields or field_key not in PANEL_FIELD_SPECS:
            return False
        if field_key == self._field and self._volume_actor is not None:
            return True
        if self._field_loader is not None:
            try:
                self._ensure_field_for_display(field_key)
            except (OSError, ValueError, KeyError) as exc:
                self._show_field_load_error(exc)
                return False
        elif field_key not in self._arrays:
            return False
        self._field = field_key
        try:
            self._rebuild_scene(render=True)
        except Exception:
            return False
        self.field_changed.emit(self._field)
        return True

    def display_mode(self) -> str:
        """Return the active simplified display mode (``'surface'``, ``'slice'``, or ``'volume'``)."""
        return self._display_mode

    def set_display_mode(self, mode: str) -> None:
        """Switch simplified display mode and rebuild the 3D scene in one render."""
        if mode not in DISPLAY_MODES:
            raise ValueError(f"Unsupported display mode {mode!r}; expected one of {DISPLAY_MODES}")
        self._display_mode = mode
        self.toolbar.set_display_mode(mode)
        if self._grid is not None:
            self._rebuild_scene_for_ui()

    def slice_position(self) -> tuple[float, float, float]:
        """Return the snapped orthogonal slice coordinates ``(x_mm, y_mm, z_mm)``."""
        return self._slice_xyz_mm

    def set_slice_position(self, x_mm: float, y_mm: float, z_mm: float) -> None:
        """Update the three orthogonal slice planes snapped to physical cell centres."""
        if self._grid is None:
            return
        snapped = (
            self._snap_slice_coord("x", float(x_mm)),
            self._snap_slice_coord("y", float(y_mm)),
            self._snap_slice_coord("z", float(z_mm)),
        )
        self._slice_xyz_mm = snapped
        self.toolbar.set_slice_position(*snapped)
        if self._display_mode == "slice":
            self._rebuild_scene_for_ui()

    def opacity(self) -> float:
        """Return the volume rendering opacity in ``[0.0, 1.0]``."""
        return self._opacity

    def set_opacity(self, value: float) -> None:
        """Set volume rendering opacity in ``[0.0, 1.0]`` and update the active volume."""
        self._opacity = max(0.0, min(1.0, float(value)))
        self.toolbar.set_opacity(self._opacity)
        if self._grid is not None and self._display_mode == "volume":
            self._apply_opacity_now()

    def set_scale_sharing(
        self,
        *,
        sync_temp: Optional[bool] = None,
        shared_pressure: Optional[bool] = None,
    ) -> None:
        """Update 3D temperature/pressure shared-scale settings and refresh if loaded."""
        changed = False
        if sync_temp is not None and bool(sync_temp) != self._sync_temp_scale:
            self._sync_temp_scale = bool(sync_temp)
            changed = True
        if shared_pressure is not None and bool(shared_pressure) != self._shared_pressure_scale:
            self._shared_pressure_scale = bool(shared_pressure)
            changed = True
        if changed and (self._arrays or self._field_loader is not None):
            if self._field_loader is not None and self._field is not None:
                try:
                    self._ensure_field_for_display(self._field)
                except (OSError, ValueError, KeyError) as exc:
                    self._show_field_load_error(exc)
                    return
            if self._arrays:
                self._global_clim = self._build_global_clim()
            if self._grid is not None:
                self._rebuild_scene_for_ui()

    def _shared_group_for(self, field_key: str) -> tuple[str, ...]:
        if self._sync_temp_scale and field_key in ("Ta", "Tb", "Ts"):
            return tuple(k for k in ("Ta", "Tb", "Ts") if k in self._available_fields)
        if self._shared_pressure_scale and field_key in ("P_kPa", "P_B_kPa"):
            return tuple(k for k in ("P_kPa", "P_B_kPa") if k in self._available_fields)
        return (field_key,)

    def _ensure_field(self, field_key: str) -> np.ndarray:
        if field_key in self._arrays:
            return self._arrays[field_key]
        if self._field_loader is None or field_key not in self._available_fields:
            raise KeyError(field_key)
        arr = np.ascontiguousarray(self._field_loader(field_key), dtype=np.float64)
        if self._widths_m is None:
            raise RuntimeError("set_field_source: grid is not initialized")
        expected = tuple(axis.size for axis in self._widths_m)
        if arr.shape != expected:
            raise ValueError(f"set_field_source: {field_key} shape {arr.shape} != grid {expected}")
        self._arrays[field_key] = arr
        return arr

    def _ensure_field_for_display(self, field_key: str) -> None:
        for key in self._shared_group_for(field_key):
            self._ensure_field(key)
        self._global_clim = self._build_global_clim()

    def _configure_grid_and_show(
        self,
        *,
        dx,
        dy,
        dz,
        flow_dir,
        flow_dir_B,
        ports_A,
        ports_B,
        available_fields: tuple[str, ...],
        initial_field: Optional[str] = None,
    ) -> None:
        self._reset_lattice(_NO_LATTICE_SOURCE)
        self._flow_dir = None if flow_dir is None else str(flow_dir or "+x")
        self._flow_dir_B = str(flow_dir_B) if flow_dir_B else None
        self._ports = {"A": ports_A, "B": ports_B}
        self._watermark_text = None
        self._watermark_label.hide()

        dx_m = np.asarray(dx, dtype=np.float64)
        dy_m = np.asarray(dy, dtype=np.float64)
        dz_m = np.asarray(dz, dtype=np.float64)
        self._widths_m = (dx_m, dy_m, dz_m)
        self._dx_mm = dx_m * 1000.0
        self._dy_mm = dy_m * 1000.0
        self._dz_mm = dz_m * 1000.0
        self._cx_mm = np.cumsum(self._dx_mm) - self._dx_mm / 2.0
        self._cy_mm = np.cumsum(self._dy_mm) - self._dy_mm / 2.0
        self._cz_mm = np.cumsum(self._dz_mm) - self._dz_mm / 2.0
        x_edges = np.concatenate([[0.0], np.cumsum(self._dx_mm)])
        y_edges = np.concatenate([[0.0], np.cumsum(self._dy_mm)])
        z_edges = np.concatenate([[0.0], np.cumsum(self._dz_mm)])
        self._L_mm = (float(x_edges[-1]), float(y_edges[-1]), float(z_edges[-1]))
        self._edges_mm = (x_edges, y_edges, z_edges)

        self._grid = pv.RectilinearGrid(
            *[
                np.r_[0.0, centres, length]
                for centres, length in zip((self._cx_mm, self._cy_mm, self._cz_mm), self._L_mm)
            ]
        )

        # Allocate display scalars and surfaces lazily per field.
        self._volume_grids.clear()
        self._surface_meshes.clear()
        self._grid_vol = None

        self._available_fields = available_fields
        if initial_field in available_fields:
            self._field = initial_field
        elif self._field not in available_fields:
            self._field = available_fields[0]

        if self._field_loader is not None:
            self._ensure_field_for_display(self._field)
        else:
            self._global_clim = self._build_global_clim()

        self._slice_xyz_mm = (
            self._snap_slice_coord("x", self._L_mm[0] * 0.5),
            self._snap_slice_coord("y", self._L_mm[1] * 0.5),
            self._snap_slice_coord("z", self._L_mm[2] * 0.5),
        )
        self.toolbar.set_slice_decimals(
            (
                _axis_decimals(self._cx_mm),
                _axis_decimals(self._cy_mm),
                _axis_decimals(self._cz_mm),
            )
        )
        self.toolbar.set_slice_bounds(
            (0.0, self._L_mm[0]),
            (0.0, self._L_mm[1]),
            (0.0, self._L_mm[2]),
        )
        self.toolbar.set_slice_position(*self._slice_xyz_mm)
        self.toolbar.set_display_mode(self._display_mode)
        self.toolbar.set_camera_preset("iso")
        self.toolbar.show()
        self.colorbar.show()
        self.port_overlay.show()

        self._render_initial_scene()
        self._rebuild_scene(render=False)
        self.fit_view()
        self._layout_overlays()
        self._update_port_chips()
        self.field_changed.emit(self._field)

    def set_field_source(
        self,
        *,
        available_fields: Sequence[str],
        field_loader: Callable[[str], np.ndarray],
        dx,
        dy,
        dz,
        flow_dir="+x",
        flow_dir_B=None,
        ports_A=None,
        ports_B=None,
        initial_field: Optional[str] = None,
    ) -> None:
        """Attach a lazy 3D field loader and load only the active displayed field."""
        if dx is None or dy is None or dz is None:
            raise ValueError("set_field_source: dx/dy/dz are required")
        ordered = tuple(key for key in FIELD_ORDER if key in available_fields)
        if not ordered:
            raise ValueError("set_field_source: at least one available field is required")
        self._arrays = {}
        self._global_clim = {}
        self._field_loader = field_loader
        self._configure_grid_and_show(
            dx=dx,
            dy=dy,
            dz=dz,
            flow_dir=flow_dir,
            flow_dir_B=flow_dir_B,
            ports_A=ports_A,
            ports_B=ports_B,
            available_fields=ordered,
            initial_field=initial_field,
        )

    def set_fields(
        self,
        Ta=None,
        vmag=None,
        P_kPa=None,
        L_mm=None,
        dx=None,
        dy=None,
        dz=None,
        *,
        t_mm=None,
        Tb=None,
        Ts=None,
        vmag_B=None,
        P_B_kPa=None,
        flow_dir="+x",
        flow_dir_B=None,
        ports_A=None,
        ports_B=None,
    ) -> None:
        """Attach 3D fields of shape ``(Nx, Ny, Nz)`` to the panel.

        ``dx``, ``dy``, ``dz`` are 1-D grid spacings in metres.
        ``flow_dir=None`` hides Fluid A arrows; omitting it keeps ``+x`` arrows.
        New fields show the simplified geometry. Call ``set_lattice_geometry`` to enable ``晶格``.
        """
        if dx is None or dy is None or dz is None:
            raise ValueError("set_fields: dx/dy/dz are required")
        self._field_loader = None

        candidate = {
            "Ta": Ta,
            "Tb": Tb,
            "Ts": Ts,
            "vmag": vmag,
            "vmag_B": vmag_B,
            "P_kPa": P_kPa,
            "P_B_kPa": P_B_kPa,
            "L_mm": L_mm,
            "t_mm": t_mm,
        }
        self._arrays = {
            k: np.ascontiguousarray(v, dtype=np.float64)
            for k, v in candidate.items()
            if v is not None
        }
        if not self._arrays:
            raise ValueError("set_fields: at least one field must be non-None")
        field_shape = next(iter(self._arrays.values())).shape
        if len(field_shape) != 3:
            raise ValueError(f"set_fields: 3D fields required, got {field_shape}")
        for key, arr in self._arrays.items():
            if arr.shape != field_shape:
                raise ValueError(f"set_fields: {key} shape {arr.shape} != {field_shape}")

        dx_m = np.asarray(dx, dtype=np.float64)
        dy_m = np.asarray(dy, dtype=np.float64)
        dz_m = np.asarray(dz, dtype=np.float64)
        if field_shape != (dx_m.size, dy_m.size, dz_m.size):
            raise ValueError(
                f"set_fields: field shape {field_shape} != grid ({dx_m.size}, {dy_m.size}, {dz_m.size})"
            )
        ordered = tuple(key for key in FIELD_ORDER if key in self._arrays)
        self._configure_grid_and_show(
            dx=dx_m,
            dy=dy_m,
            dz=dz_m,
            flow_dir=flow_dir,
            flow_dir_B=flow_dir_B,
            ports_A=ports_A,
            ports_B=ports_B,
            available_fields=ordered,
        )

    def set_lattice_geometry(
        self,
        topology: str,
        delta_levelset: float,
        result_id: str,
    ) -> None:
        """Enable ``晶格`` for the loaded fields with the recorded topology and level-set offset.

        Graded L keeps ``晶格`` disabled with its reason, because its phase rule is not defined.
        """
        cell_field = self._ensure_field("L_mm")
        _cell, reason = lattice_cell_size(cell_field)
        if reason:
            self._reset_lattice(_GRADED_L_REASON)
            return
        self._lattice_source = (topology, float(delta_levelset), result_id)
        self.toolbar.set_lattice_enabled(True)

    def geometry_mode(self) -> str:
        """Return the geometry that the scene shows (``'simple'`` or ``'lattice'``)."""
        return self._geometry

    def set_watermark(self, text: Optional[str]) -> None:
        """Show or clear an extrapolation warning watermark over the 3D viewport."""
        self._watermark_text = str(text).strip() if text else None
        if not self._watermark_text:
            self._watermark_label.clear()
            self._watermark_label.hide()
        else:
            self._watermark_label.setText(self._watermark_text)
            self._watermark_label.show()
        self._layout_overlays()

    def color_range_state(self) -> dict[str, Any]:
        """Return a detached copy of the current color-range mode and limits."""
        return {
            "mode": self._scale_mode,
            "ranges": {key: list(limits) for key, limits in self._custom_clim.items()},
        }

    def restore_color_ranges(self, state: dict[str, Any]) -> None:
        """Validate and apply saved color-range limits without mutating field data."""
        checked = validate_color_range_state(state)
        self._scale_mode = checked["mode"]
        self._custom_clim = {key: tuple(limits) for key, limits in checked["ranges"].items()}
        self._refresh_clim()

    def set_color_range_mode(self, mode: str) -> None:
        """Switch between ``'global'``, ``'local'``, and ``'custom'`` color ranges."""
        if mode not in ("global", "local", "custom"):
            raise ValueError(f"Unsupported color range mode {mode!r}")
        self._scale_mode = mode
        self._refresh_clim()

    def set_custom_color_range(self, field_key: str, lo: float, hi: float) -> None:
        """Set custom finite ``(lo, hi)`` color limits with ``hi > lo`` for one field."""
        if field_key not in PANEL_FIELD_SPECS:
            raise ValueError(f"Unknown field key {field_key!r}")
        low, high = float(lo), float(hi)
        if not (isfinite(low) and isfinite(high) and high > low):
            raise ValueError("Custom color range requires finite Max > Min.")
        self._custom_clim[field_key] = (low, high)
        if self._scale_mode == "custom":
            self._refresh_clim()

    def refresh_colormaps(self) -> None:
        """Re-render active 3D actors and colorbar with the current runtime colormap."""
        if self._grid is None or self._field is None:
            return
        self._rebuild_scene_for_ui()

    def apply_theme(self, tokens: Mapping[str, Any] | None = None) -> None:
        """Apply current Style P2 theme tokens to overlays and VTK scene chrome."""
        theme = dict(get_theme())
        if tokens is not None:
            theme.update(tokens)
        self.plotter.set_background(theme["canvas"])
        self.toolbar.apply_theme(theme)
        self.colorbar.apply_theme(theme)
        self.port_overlay.apply_theme(theme)
        self.lattice_progress.apply_theme(theme)
        self.lattice_card.apply_theme(theme)
        self._apply_overlay_styles(theme)
        if self._grid is not None:
            self._render_initial_scene()
            self._rebuild_scene_for_ui()
            self._layout_overlays()
            self._update_port_chips()

    def _set_export_typography(self, enabled: bool) -> None:
        """Switch axes triad and figure overlays between screen and export fonts."""
        self._apply_axes_triad_font(export=enabled)
        self.colorbar.set_export_mode(enabled)
        self.port_overlay.set_export_mode(enabled)
        self._apply_overlay_styles(get_theme(), export=enabled)

    def capture_image(self, *, scale: int = 1) -> QImage:
        """Capture VTK pixels and visible figure overlays into one owned QImage.

        Includes the VTK scene, ``PortChipOverlay``, ``StudioColorbarCard``,
        and any active extrapolation watermark. Excludes interactive toolbars.
        Forces a synchronous VTK render before reading pixels so hidden-panel
        updates and export typography reach the captured framebuffer on macOS.
        """
        was_suppressed = bool(self.plotter.suppress_rendering)
        self._set_export_typography(True)
        try:
            if was_suppressed:
                self.plotter.suppress_rendering = False
            self.plotter.render_window.Render()
            raw = (
                self.plotter.screenshot(return_img=True)
                if scale == 1
                else self.plotter.screenshot(return_img=True, scale=scale)
            )
            pixels = np.ascontiguousarray(raw)
            channels = pixels.shape[2] if pixels.ndim == 3 else 3
            image_format = (
                QImage.Format.Format_RGBA8888 if channels == 4 else QImage.Format.Format_RGB888
            )
            image = QImage(
                pixels.data,
                pixels.shape[1],
                pixels.shape[0],
                pixels.strides[0],
                image_format,
            ).copy()

            overlays = self._capture_overlays()
            host = self._viewport_host
            vp_w, vp_h = host.width(), host.height()
            if not overlays or vp_w <= 0 or vp_h <= 0:
                return image

            self._layout_overlays()
            self._update_port_chips()

            canvas = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            sx = canvas.width() / float(vp_w)
            sy = canvas.height() / float(vp_h)
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            for widget in overlays:
                painter.save()
                painter.scale(sx, sy)
                painter.translate(widget.pos())
                widget.render(
                    painter,
                    QPoint(0, 0),
                    QRegion(),
                    QWidget.RenderFlag.DrawChildren,
                )
                painter.restore()
            painter.end()
            return canvas.convertToFormat(image_format)
        finally:
            self._set_export_typography(False)
            if was_suppressed:
                self.plotter.suppress_rendering = True
            else:
                self.plotter.render_window.Render()

    def cleanup(self) -> None:
        """Release VTK observers and GL context idempotently."""
        if getattr(self, "_cleaned_up", False):
            return
        self._cleaned_up = True
        self._stop_camera_tween()
        self._lattice.close()
        self._lattice_pending = None
        if getattr(self, "_camera_observer_tag", None) is not None:
            cam = self.plotter.renderer.GetActiveCamera()
            if cam is not None:
                cam.RemoveObserver(self._camera_observer_tag)
            self._camera_observer_tag = None
        if getattr(self, "_interaction_observer_tag", None) is not None and self.plotter.iren is not None:
            self.plotter.iren.remove_observer(self._interaction_observer_tag)
            self._interaction_observer_tag = None
        if getattr(self, "_hover_observer_tag", None) is not None and self.plotter.iren is not None:
            self.plotter.iren.interactor.RemoveObserver(self._hover_observer_tag)
            self._hover_observer_tag = None
        for dlg in list(getattr(self, "_popup_dialogs", ())):
            dlg.close()
        if hasattr(self, "_popup_dialogs"):
            self._popup_dialogs.clear()
        self.plotter.close()

    # ─────────────────────────── visibility & layout ──────────────────

    def _capture_overlays(self) -> list[QWidget]:
        """Return visible figure-annotation overlays for unified image export."""
        return [
            widget
            for widget in (self.port_overlay, self.colorbar, self._watermark_label)
            if not widget.isHidden()
        ]

    def _layout_overlays(self) -> None:
        w, h = self._viewport_host.width(), self._viewport_host.height()
        if w <= 0 or h <= 0:
            return
        obstacles = []
        if not self.colorbar.isHidden():
            cb_h = min(COLORBAR_HEIGHT, max(200, h - 110))
            self.colorbar.setFixedSize(COLORBAR_WIDTH, cb_h)
            cb_x = max(12, w - COLORBAR_WIDTH - 20)
            cb_y = max(12, (h - cb_h) // 2)
            self.colorbar.setGeometry(cb_x, cb_y, COLORBAR_WIDTH, cb_h)
            obstacles.append(self.colorbar.geometry().adjusted(-8, -8, 8, 8))
        if not self.toolbar.isHidden():
            self.toolbar.adjustSize()
            tb_sz = self.toolbar.sizeHint()
            tb_w = min(tb_sz.width(), max(120, w - 24))
            tb_h = tb_sz.height()
            tb_x = max(12, (w - tb_w) // 2)
            tb_y = max(12, h - tb_h - 14)
            self.toolbar.setGeometry(tb_x, tb_y, tb_w, tb_h)
            obstacles.append(self.toolbar.geometry().adjusted(-8, -8, 8, 8))
        # Stack the top-left cards: lattice build, lattice domain, watermark, then status.
        top = 12
        for card in (self.lattice_progress, self.lattice_card, self._watermark_label):
            if not card.isHidden():
                card.adjustSize()
                size = card.sizeHint()
                card.setGeometry(14, top, min(size.width(), max(120, w - COLORBAR_WIDTH - 48)), size.height())
                obstacles.append(card.geometry().adjusted(-6, -6, 6, 6))
                top = card.geometry().bottom() + 6
        if not self.status.isHidden():
            self.status.adjustSize()
            st_sz = self.status.sizeHint()
            st_w = min(st_sz.width(), max(120, w - COLORBAR_WIDTH - 48))
            self.status.setGeometry(14, top, st_w, st_sz.height())
        self.port_overlay.setGeometry(0, 0, w, h)
        self.port_overlay.set_safe_margins(16, 16, 16, 16)
        self.port_overlay.set_obstacles(obstacles)
        self.port_overlay.raise_()
        self.colorbar.raise_()
        self.lattice_progress.raise_()
        self.lattice_card.raise_()
        self._watermark_label.raise_()
        self.status.raise_()
        self.toolbar.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_overlays()
        self._update_port_chips()

    def _pause_rendering(self) -> None:
        self._render_gated = True
        self.plotter.suppress_rendering = True
        self.plotter.render_timer.stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._cleaned_up:
            return
        self._render_gated = False
        self.plotter.suppress_rendering = False
        self.plotter.render_timer.start()
        self._layout_overlays()
        if self._camera_fit_pending:
            QTimer.singleShot(0, self, lambda: self._camera_fit_pending and self.fit_view())
        else:
            self.plotter.render()
            self._update_port_chips()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._stop_camera_tween(snap=True)
        if not self._cleaned_up:
            self._pause_rendering()

    # ─────────────────────────── hover & camera observers ─────────────

    def _clear_hover_status(self) -> None:
        if self._last_hover_text:
            if self._base_status_text:
                self.status.setText(self._base_status_text)
            self.status.hide()
            self._last_hover_text = ""

    def _on_camera_modified(self, _obj, _event) -> None:
        if self._grid is not None and self._port_world_anchors:
            self._update_port_chips()

    def _on_mouse_move(self, obj, _event) -> None:
        """Probe scalar values at cursor position on the active 3D data geometry."""
        if self._grid is None:
            return
        import time as _t_hover

        now = _t_hover.monotonic()
        if now - self._hover_last_t < 0.033:
            return
        self._hover_last_t = now
        from vtkmodules.vtkRenderingCore import vtkPropPicker

        x, y = obj.GetEventPosition()
        picker = vtkPropPicker()
        picker.Pick(x, y, 0, self.plotter.renderer)
        prop = picker.GetViewProp()
        if prop is None or prop not in self._data_actors:
            self._clear_hover_status()
            return
        wpos = picker.GetPickPosition()
        if any(
            pos < edges[0] - 1e-6 or pos > edges[-1] + 1e-6
            for edges, pos in zip(self._edges_mm, wpos)
        ):
            self._clear_hover_status()
            return
        index = tuple(
            int(np.clip(np.searchsorted(edges, pos, side="right") - 1, 0, len(edges) - 2))
            for edges, pos in zip(self._edges_mm, wpos)
        )
        parts = [
            f"坐标 ({wpos[0]:.1f}, {wpos[1]:.1f}, {wpos[2]:.1f}) mm",
            f"单元 {index}",
        ]
        for fkey, spec in PANEL_FIELD_SPECS.items():
            if fkey in self._arrays:
                val = float(self._arrays[fkey][index])
                symbol = _FIELD_SYMBOL_HTML.get(fkey, spec.symbol_html)
                parts.append(f"{symbol} = {val:{spec.fmt[1:]}} {spec.display_unit}")
        hover_text = "   •   ".join(parts)
        if hover_text != self._last_hover_text:
            self.status.setText(hover_text)
            self.status.show()
            self._layout_overlays()
            self._last_hover_text = hover_text

    # ─────────────────────────── toolbar callbacks ────────────────────

    def _on_toolbar_geometry_changed(self, mode: str) -> None:
        if mode == "lattice":
            self._request_lattice()
            return
        self._lattice.cancel()
        self._lattice_pending = None
        self._lattice_mesh = None
        self._geometry = "simple"
        self.lattice_progress.hide()
        self.lattice_card.hide()
        self.toolbar.set_detail_level(self._detail)
        self._rebuild_scene_for_ui()
        self._layout_overlays()

    def _on_toolbar_detail_changed(self, _level: str) -> None:
        self._request_lattice()

    def _on_toolbar_display_mode_changed(self, mode: str) -> None:
        self._display_mode = mode
        if self._grid is not None:
            self._rebuild_scene_for_ui()
        self._layout_overlays()
        self._update_port_chips()

    def _on_toolbar_slice_changed(self, x_mm: float, y_mm: float, z_mm: float) -> None:
        self.set_slice_position(x_mm, y_mm, z_mm)

    def _on_toolbar_opacity_changed(self, value: float) -> None:
        self._opacity = max(0.0, min(1.0, float(value)))
        if self._display_mode == "volume":
            self._opacity_debounce.start()

    # ─────────────────────────── camera framing & motion ──────────────

    def _apply_isometric_pose(self) -> None:
        """Apply studio isometric framing matching the ux/final 3D screens."""
        Lx, Ly, Lz = self._L_mm
        ctr = np.array([Lx * 0.5, Ly * 0.5, Lz * 0.5], dtype=float)
        az = np.array([-0.46, 0.42, 1.00], dtype=float)
        az /= np.linalg.norm(az)
        diag = max(1.0, float(np.linalg.norm([Lx, Ly, Lz])))
        cam = self.plotter.camera
        cam.focal_point = tuple(ctr)
        cam.position = tuple(ctr + az * (diag * 1.8))
        cam.up = (0.0, 1.0, 0.0)
        cam.view_angle = 27.0

    def set_view(self, preset: str) -> None:
        """Tween camera from its current pose to one of ``xy``, ``xz``, ``yz``, or ``iso``.

        Uses the shared reduced-motion decision in ``microanim.py``; when reduced
        motion is active or the panel is hidden, snaps directly to the target pose.
        """
        if preset not in CAMERA_PRESETS:
            raise ValueError(f"Unsupported camera preset {preset!r}; expected one of {CAMERA_PRESETS}")
        self._stop_camera_tween()
        pl = self.plotter
        cam = pl.camera
        start = (tuple(cam.position), tuple(cam.focal_point), tuple(cam.up), cam.view_angle)
        if preset == "xy":
            pl.view_xy(render=False)
        elif preset == "xz":
            pl.view_xz(render=False)
        elif preset == "yz":
            pl.view_yz(render=False)
        else:
            self._apply_isometric_pose()
        self.fit_view(render=False)
        end = (tuple(cam.position), tuple(cam.focal_point), tuple(cam.up), cam.view_angle)

        reduced = is_reduced_motion()
        if reduced or start == end or not self.isVisible():
            if self.isVisible():
                pl.render()
                self._update_port_chips()
            self.toolbar.set_camera_preset(preset)
            return

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
        pl.ren_win.SetDesiredUpdateRate(_CAMERA_UPDATE_RATE)

        def _step(ease: float) -> None:
            def _lerp(a, b):
                return tuple(a[k] + (b[k] - a[k]) * ease for k in range(3))

            cam.position = _lerp(start[0], end[0])
            cam.focal_point = _lerp(start[1], end[1])
            cam.up = _lerp(start[2], end[2])
            cam.view_angle = start[3] + (end[3] - start[3]) * ease
            window = self.window().windowHandle()
            if self.isVisible() and window is not None and window.isVisible():
                pl.render()
                self._update_port_chips()

        def _finished() -> None:
            if self._tween_animation is animation:
                self._stop_camera_tween()
                self.toolbar.set_camera_preset(preset)
                window = self.window().windowHandle()
                if self.isVisible() and window is not None and window.isVisible():
                    pl.render()
                    self._update_port_chips()

        animation.valueChanged.connect(_step)
        animation.finished.connect(_finished)
        start_animation(self, animation)

    def fit_view(self, *, render: bool = True) -> None:
        """Frame the current orientation using the actual viewport aspect."""
        if self._grid is None:
            return
        self._stop_camera_tween()
        if not self.isVisible():
            self._camera_fit_pending = True
            return
        self._camera_fit_pending = False
        self.plotter.renderer.ResetCameraScreenSpace(0.8)
        self.plotter.renderer.ResetCameraClippingRange()
        if render:
            self.plotter.render()
            self._update_port_chips()

    def _cancel_preset_for_interaction(self, _obj, _event) -> None:
        self._camera_fit_pending = False
        self.toolbar.set_camera_preset(None)
        if self._tween_animation is not None:
            self._tween_previous_update_rate = None
            self._stop_camera_tween()
            self.plotter.ren_win.SetDesiredUpdateRate(
                self.plotter.iren.interactor.GetDesiredUpdateRate()
            )

    def _stop_camera_tween(self, *, snap: bool = False) -> None:
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
            self.toolbar.set_camera_preset(self._tween_preset)

    # ─────────────────────────── opacity & color limits ───────────────

    def _opacity_ramp(self) -> tuple[float, float]:
        """Return ``(lo_alpha, hi_alpha)`` opacity endpoints for ray-cast volume mode."""
        if self._opacity <= 1e-6:
            return 0.0, 0.0
        if self._field in ("vmag", "vmag_B"):
            return 0.0, self._opacity
        return self._opacity * 0.4, self._opacity

    def _apply_opacity_now(self) -> None:
        """Apply current ``self._opacity`` to the active volume actor and render once."""
        if (
            self._display_mode == "volume"
            and self._volume_actor is not None
            and self._field is not None
        ):
            from vtkmodules.vtkCommonDataModel import vtkPiecewiseFunction

            lo, hi = self._clim_for(self._field)
            if abs(hi - lo) < 1e-12:
                hi = lo + 1.0
            pw = vtkPiecewiseFunction()
            lo_a, hi_a = self._opacity_ramp()
            pw.AddPoint(lo, lo_a)
            pw.AddPoint(hi, hi_a)
            self._volume_actor.GetProperty().SetScalarOpacity(pw)
            self.plotter.render()
            return
        self._rebuild_scene_for_ui()

    def _build_global_clim(self) -> dict[str, tuple[float, float]]:
        """Compute global color limits honoring shared temperature and pressure toggles."""
        clim = dict(zip(self._arrays, field_color_limits(list(self._arrays.values()))))
        shared_groups = []
        if self._sync_temp_scale:
            shared_groups.append(("Ta", "Tb", "Ts"))
        if self._shared_pressure_scale:
            shared_groups.append(("P_kPa", "P_B_kPa"))
        for group in shared_groups:
            keys = [key for key in group if key in self._arrays]
            if len(keys) < 2:
                continue
            lo = min(clim[key][0] for key in keys)
            hi = max(clim[key][1] for key in keys)
            clim.update((key, (lo, hi)) for key in keys)
        return clim

    def _clim_for(self, fkey: str) -> tuple[float, float]:
        """Resolve ``(lo, hi)`` limits for one field under the active range mode."""
        if self._scale_mode == "custom":
            return self._custom_clim.get(fkey, self._global_clim.get(fkey, (0.0, 1.0)))
        if (
            self._scale_mode == "global"
            or fkey not in self._arrays
            or self._display_mode != "slice"
            or self._geometry == "lattice"
        ):
            return self._global_clim.get(fkey, (0.0, 1.0))
        arr = self._arrays[fkey]
        ix = self._slice_index("x", self._slice_xyz_mm[0])
        iy = self._slice_index("y", self._slice_xyz_mm[1])
        iz = self._slice_index("z", self._slice_xyz_mm[2])
        lo = min(
            float(arr[ix, :, :].min()),
            float(arr[:, iy, :].min()),
            float(arr[:, :, iz].min()),
        )
        hi = max(
            float(arr[ix, :, :].max()),
            float(arr[:, iy, :].max()),
            float(arr[:, :, iz].max()),
        )
        if hi - lo < 1e-12:
            hi = lo + 1.0
        return lo, hi

    def _refresh_clim(self) -> None:
        if self._grid is None:
            return
        self._rebuild_scene_for_ui()

    def _rebuild_scene_for_ui(self) -> None:
        """Rebuild scene for interactive UI slots; status already shows any failure."""
        try:
            self._rebuild_scene(render=True)
        except Exception:
            return

    # ─────────────────────────── scene rendering ──────────────────────

    def _render_placeholder(self) -> None:
        pl = self.plotter
        pl.clear()
        placeholder = pl.add_text(
            "请在算例计算中选择三维并运行求解。",
            font_size=9,
            color=get_theme()["sub"],
            position="upper_edge",
            font="times",
        )
        apply_vtk_font(placeholder.GetTextProperty())
        pl.reset_camera()

    def _setup_studio_lights(self) -> None:
        Lx, Ly, Lz = self._L_mm
        ctr = (Lx * 0.5, Ly * 0.5, Lz * 0.5)
        diag = max(1.0, max(Lx, Ly, Lz))
        pl = self.plotter
        pl.remove_all_lights()
        pl.add_light(
            pv.Light(
                position=(ctr[0] - 0.77 * diag, ctr[1] + 1.43 * diag, ctr[2] + 1.10 * diag),
                focal_point=ctr,
                intensity=0.82,
                light_type="scene light",
            )
        )
        pl.add_light(
            pv.Light(
                position=(ctr[0] + 1.21 * diag, ctr[1] + 0.33 * diag, ctr[2] + 0.88 * diag),
                focal_point=ctr,
                intensity=0.32,
                light_type="scene light",
            )
        )
        pl.add_light(pv.Light(light_type="headlight", intensity=0.22))

    def _add_contact_shadow(self) -> None:
        Lx, Ly, Lz = self._L_mm
        pad = max(1.0, 0.13 * max(Lx, Lz))
        y_off = -max(0.2, 0.028 * min(Lx, Ly, Lz))
        plane = pv.Plane(
            center=(Lx * 0.5, y_off, Lz * 0.5),
            direction=(0.0, 1.0, 0.0),
            i_size=Lz + 2.0 * pad,
            j_size=Lx + 2.0 * pad,
            i_resolution=40,
            j_resolution=80,
        )
        pts = plane.points
        dx = np.maximum(np.abs(pts[:, 0] - Lx * 0.5) - Lx * 0.5 + min(4.0, Lx * 0.1), 0.0) / pad
        dz = np.maximum(np.abs(pts[:, 2] - Lz * 0.5) - Lz * 0.5 + min(4.0, Lz * 0.1), 0.0) / pad
        alpha = np.clip(1.0 - np.sqrt(dx * dx + dz * dz), 0.0, 1.0) ** 2.4
        strength = 0.14 if get_theme_name() == "light" else 0.36
        rgba = np.zeros((plane.n_points, 4), dtype=np.uint8)
        rgba[:, 3] = (alpha * strength * 255.0).astype(np.uint8)
        plane.point_data["rgba"] = rgba
        shadow_actor = self.plotter.add_mesh(
            plane,
            scalars="rgba",
            rgba=True,
            lighting=False,
            show_scalar_bar=False,
            pickable=False,
            name="_contact_shadow",
            render=False,
        )
        shadow_actor.SetUseBounds(False)

    def _apply_axes_triad_font(self, *, export: bool) -> None:
        aw = self.plotter.renderer.axes_widget
        ax_actor = aw.GetOrientationMarker()
        for getter in (
            ax_actor.GetXAxisCaptionActor2D,
            ax_actor.GetYAxisCaptionActor2D,
            ax_actor.GetZAxisCaptionActor2D,
        ):
            tp = getter().GetCaptionTextProperty()
            if export:
                apply_vtk_font(tp)
            else:
                tp.SetFontFamilyToArial()

    def _configure_axes_triad(self) -> None:
        t = get_theme()
        pl = self.plotter
        pl.add_axes(
            line_width=1.8,
            cone_radius=0.30,
            shaft_length=0.68,
            tip_length=0.28,
            xlabel="x",
            ylabel="y",
            zlabel="z",
            x_color=t["triad_x"],
            y_color=t["triad_y"],
            z_color=t["triad_z"],
            interactive=False,
        )
        aw = pl.renderer.axes_widget
        aw.SetViewport(0.010, 0.025, 0.132, 0.228)
        ax_actor = aw.GetOrientationMarker()
        ax_actor.SetNormalizedLabelPosition((1.24, 1.34, 1.26))
        col_rgb = _hex_to_rgb01(t["tert"])
        specs = (
            (ax_actor.GetXAxisCaptionActor2D, "left", "centered", (6, 0)),
            (ax_actor.GetYAxisCaptionActor2D, "centered", "bottom", (0, 8)),
            (ax_actor.GetZAxisCaptionActor2D, "centered", "top", (2, -6)),
        )
        for getter, hjust, vjust, px_off in specs:
            ca = getter()
            ca.SetPosition(*px_off)
            ca.GetTextActor().SetTextScaleModeToNone()
            tp = ca.GetCaptionTextProperty()
            tp.SetFontFamilyToArial()
            tp.SetFontSize(13)
            tp.SetItalic(True)
            tp.SetBold(False)
            tp.SetShadow(False)
            tp.SetColor(*col_rgb)
            if hjust == "left":
                tp.SetJustificationToLeft()
            else:
                tp.SetJustificationToCentered()
            if vjust == "bottom":
                tp.SetVerticalJustificationToBottom()
            elif vjust == "top":
                tp.SetVerticalJustificationToTop()
            else:
                tp.SetVerticalJustificationToCentered()

    def _render_initial_scene(self) -> None:
        pl = self.plotter
        pl.clear()
        self._volume_actor = None
        self._data_actors.clear()
        pl.set_background(get_theme()["canvas"])
        self._setup_studio_lights()
        self._add_contact_shadow()
        self._configure_axes_triad()
        self._apply_isometric_pose()

    def _faint_port_sides(self) -> tuple[str, ...]:
        if self._display_mode != "slice" or self._geometry == "lattice":
            return ()
        if self._field in ("Ta", "vmag", "P_kPa"):
            return ("B",)
        if self._field in ("Tb", "vmag_B", "P_B_kPa"):
            return ("A",)
        return ()

    def _add_flow_glyph(self) -> None:
        """Outline solved openings, draw outward arrows, and record world anchors."""
        if self._grid is None:
            return
        pl = self.plotter
        for name in _PORT_ACTOR_PREFIXES:
            pl.remove_actor(name, render=False)
        self._port_world_anchors = []

        t = get_theme()
        L = np.asarray(self._L_mm, dtype=float)
        min_dim = max(1.0, float(min(self._L_mm)))
        face_eps = max(0.05, 0.008 * min_dim)
        gap = max(0.4, 0.062 * min_dim)
        inlet_len = max(1.5, 0.42 * min_dim)
        outlet_len = max(1.8, 0.52 * min_dim)
        faint = self._faint_port_sides()

        def _add_pair(flow_dir: str, tag: str, color: str) -> None:
            from tm1.physical_models.field_coordinates_3d import _port_rectangles

            op = 0.42 if tag in faint else 1.0
            axis = "xyz".index(flow_dir[-1])
            cross = [i for i in range(3) if i != axis]
            sign = -1.0 if flow_dir.startswith("-") else 1.0
            ports = self._ports.get(tag)
            rectangles = (
                _port_rectangles(ports, L[cross[1]] * 1e-3) if ports is not None else None
            )
            for end, upper, end_label in (
                ("inlet", sign < 0, "入口"),
                ("outlet", sign > 0, "出口"),
            ):
                face = L[axis] if upper else 0.0
                nout = 1.0 if upper else -1.0
                center = L * 0.5
                center[axis] = face
                if rectangles is not None:
                    bounds = np.asarray(rectangles[end + "_rect"]).reshape(2, 2) * 1000.0
                    bounds = np.clip(bounds, 0.0, L[cross, None])
                    center[cross] = bounds.mean(axis=1)
                    cf = center.copy()
                    cf[axis] = face + nout * face_eps
                    corners = np.tile(cf, (5, 1))
                    corners[:, cross[0]] = bounds[0, [0, 1, 1, 0, 0]]
                    corners[:, cross[1]] = bounds[1, [0, 0, 1, 1, 0]]
                    pl.add_mesh(
                        pv.lines_from_points(corners),
                        color=color,
                        line_width=2.4,
                        opacity=op,
                        pickable=False,
                        name=f"_port_{end}_{tag}",
                        show_scalar_bar=False,
                        render=False,
                    )
                outward = np.zeros(3, dtype=float)
                outward[axis] = nout
                alen = outlet_len if end == "outlet" else inlet_len
                inner_pt = center + outward * gap
                outer_pt = center + outward * (gap + alen)
                start, direction = (outer_pt, -outward) if end == "inlet" else (inner_pt, outward)
                arrow = pv.Arrow(
                    start=start,
                    direction=direction,
                    scale=alen,
                    tip_length=0.31,
                    tip_radius=0.105,
                    shaft_radius=0.034,
                )
                pl.add_mesh(
                    arrow,
                    color=color,
                    opacity=op,
                    lighting=True,
                    ambient=0.35,
                    diffuse=0.70,
                    pickable=False,
                    name=f"_flow_{end}_{tag}",
                    show_scalar_bar=False,
                    render=False,
                )
                self._port_world_anchors.append(
                    (f"{tag}-{end}", f"{tag} {end_label}", tag, inner_pt, outer_pt)
                )

        if self._flow_dir is not None:
            _add_pair(self._flow_dir, "A", t["inlet_a"])
        if self._flow_dir_B and any(f in self._available_fields for f in ("Tb", "vmag_B", "P_B_kPa")):
            _add_pair(self._flow_dir_B, "B", t["inlet_b"])

    def _project_world_to_viewport(self, point_xyz: np.ndarray) -> Optional[tuple[float, float]]:
        vp_w, vp_h = self._viewport_host.width(), self._viewport_host.height()
        if vp_w <= 0 or vp_h <= 0:
            return None
        ren_w, ren_h = self.plotter.window_size
        if ren_w <= 0 or ren_h <= 0:
            return None
        from vtkmodules.vtkRenderingCore import vtkCoordinate

        coord = vtkCoordinate()
        coord.SetCoordinateSystemToWorld()
        coord.SetValue(float(point_xyz[0]), float(point_xyz[1]), float(point_xyz[2]))
        sx, sy = coord.GetComputedDoubleDisplayValue(self.plotter.renderer)
        if not (isfinite(sx) and isfinite(sy)):
            return None
        qt_x = sx * (vp_w / float(ren_w))
        qt_y = (float(ren_h) - sy) * (vp_h / float(ren_h))
        return (qt_x, qt_y)

    def _update_port_chips(self) -> None:
        if self._grid is None:
            return
        anchors: list[PortAnchor] = []
        for key, label, side, inner_xyz, outer_xyz in self._port_world_anchors:
            inner_2d = self._project_world_to_viewport(inner_xyz)
            outer_2d = self._project_world_to_viewport(outer_xyz)
            if outer_2d is None:
                continue
            anchors.append(
                PortAnchor(key=key, label=label, side=side, outer=outer_2d, inner=inner_2d)
            )
        self.port_overlay.set_anchors(anchors)

    def _build_volume_grid(self) -> tuple[pv.RectilinearGrid, float]:
        """Cache physical cell-centre display scalars for VTK interpolation."""
        if self._field in self._volume_grids:
            return self._volume_grids[self._field]
        field = self._arrays[self._field]
        grid = self._grid.copy(deep=False)
        grid.point_data[self._field] = np.pad(field, 1, mode="edge").flatten(order="F")
        result = grid, float(min(np.diff(axis).min() for axis in (grid.x, grid.y, grid.z)))
        self._volume_grids[self._field] = result
        return result

    def _build_surface_mesh(self, vol_grid: pv.RectilinearGrid) -> pv.PolyData:
        """Cache the extracted outer-surface mesh for the active field."""
        if self._field in self._surface_meshes:
            return self._surface_meshes[self._field]
        surf = vol_grid.extract_surface(algorithm="dataset_surface")
        self._surface_meshes[self._field] = surf
        return surf

    def _clear_data_actors(self) -> None:
        pl = self.plotter
        for name in _DATA_ACTOR_NAMES:
            pl.remove_actor(name, render=False)
        self._volume_actor = None
        self._data_actors.clear()

    def _box_edge_color(self) -> str:
        t = get_theme()
        return t["fg"] if get_theme_name() == "light" else t["sub"]

    def _add_domain_edges(self, opacity: float, line_width: float = 1.2) -> None:
        Lx, Ly, Lz = self._L_mm
        edges = pv.Box(bounds=(0.0, Lx, 0.0, Ly, 0.0, Lz)).extract_feature_edges()
        self.plotter.add_mesh(
            edges,
            color=self._box_edge_color(),
            opacity=opacity,
            line_width=line_width,
            pickable=False,
            name="_domain_edges",
            show_scalar_bar=False,
            render=False,
        )

    def _render_surface_actors(
        self, vol_grid: pv.RectilinearGrid, cmap: str, clim: tuple[float, float]
    ) -> None:
        surf = self._build_surface_mesh(vol_grid)
        actor = self.plotter.add_mesh(
            surf,
            scalars=self._field,
            cmap=cmap,
            clim=clim,
            ambient=0.52,
            diffuse=0.52,
            specular=0.04,
            show_scalar_bar=False,
            name="main_surface",
            render=False,
        )
        self._volume_actor = actor
        self._data_actors.add(actor)
        edge_op = 0.40 if get_theme_name() == "light" else 0.72
        self._add_domain_edges(edge_op, line_width=1.2)

    def _render_slice_actors(
        self, vol_grid: pv.RectilinearGrid, cmap: str, clim: tuple[float, float]
    ) -> None:
        pl = self.plotter
        t = get_theme()
        Lx, Ly, Lz = self._L_mm
        sx, sy, sz = self._slice_xyz_mm
        origin = (sx, sy, sz)
        edge_col = self._box_edge_color()
        edge_op = 0.55 if get_theme_name() == "light" else 0.80

        first_actor = None
        for axis_name, normal in (("x", (1.0, 0.0, 0.0)), ("y", (0.0, 1.0, 0.0)), ("z", (0.0, 0.0, 1.0))):
            slc = vol_grid.slice(normal=normal, origin=origin)
            actor = pl.add_mesh(
                slc,
                scalars=self._field,
                cmap=cmap,
                clim=clim,
                lighting=False,
                show_edges=False,
                show_scalar_bar=False,
                name=f"slice_{axis_name}",
                render=False,
            )
            self._data_actors.add(actor)
            if first_actor is None:
                first_actor = actor
            boundary = slc.extract_feature_edges(
                boundary_edges=True, feature_edges=False, manifold_edges=False
            )
            pl.add_mesh(
                boundary,
                color=edge_col,
                opacity=edge_op,
                line_width=1.2,
                pickable=False,
                show_scalar_bar=False,
                name=f"slice_{axis_name}_edge",
                render=False,
            )

        for axis_name, pts in (
            ("x", np.array([[0.0, sy, sz], [Lx, sy, sz]])),
            ("y", np.array([[sx, 0.0, sz], [sx, Ly, sz]])),
            ("z", np.array([[sx, sy, 0.0], [sx, sy, Lz]])),
        ):
            pl.add_mesh(
                pv.lines_from_points(pts),
                color=t["canvas"],
                opacity=0.72,
                line_width=1.1,
                pickable=False,
                show_scalar_bar=False,
                name=f"_slice_cross_{axis_name}",
                render=False,
            )

        box = pv.Box(bounds=(0.0, Lx, 0.0, Ly, 0.0, Lz))
        pl.add_mesh(
            box,
            color=t["fg"],
            opacity=0.03,
            lighting=False,
            show_scalar_bar=False,
            pickable=False,
            name="_slice_box_fill",
            render=False,
        )
        self._add_domain_edges(0.36 if get_theme_name() == "light" else 0.65, line_width=1.1)

        probe_r = max(0.35, 0.026 * min(Lx, Ly, Lz))
        pl.add_mesh(
            pv.Sphere(radius=probe_r, center=origin),
            color=t["accent"],
            lighting=False,
            pickable=False,
            show_scalar_bar=False,
            name="_slice_probe",
            render=False,
        )
        self._volume_actor = first_actor

    def _render_volume_actors(
        self, vol_grid: pv.RectilinearGrid, cmap: str, clim: tuple[float, float]
    ) -> None:
        actor = self.plotter.add_volume(
            vol_grid,
            scalars=self._field,
            cmap=cmap,
            clim=clim,
            opacity=list(self._opacity_ramp()),
            shade=False,
            name="main_volume",
            render=False,
            show_scalar_bar=False,
        )
        actor.GetProperty().SetInterpolationTypeToLinear()
        vol_mapper = actor.GetMapper()
        vol_mapper.SetAutoAdjustSampleDistances(True)
        vol_mapper.SetSampleDistance(max(0.005, self._vol_min_cell_mm))
        self._volume_actor = actor
        self._data_actors.add(actor)
        self._add_domain_edges(0.32 if get_theme_name() == "light" else 0.58, line_width=1.0)

    def _render_lattice_actors(self, cmap: str, clim: tuple[float, float]) -> None:
        # A phase domain can be empty, for example at a large level-set offset. Show only the box edges.
        if self._lattice_mesh.n_cells:
            actor = self.plotter.add_mesh(
                self._lattice_mesh,
                scalars=self._field,
                cmap=cmap,
                clim=clim,
                ambient=0.30,
                diffuse=0.75,
                specular=0.12,
                specular_power=24.0,
                show_scalar_bar=False,
                name="main_lattice",
                render=False,
            )
            self._volume_actor = actor
            self._data_actors.add(actor)
        self._add_domain_edges(0.40 if get_theme_name() == "light" else 0.72, line_width=1.2)
        self.lattice_card.set_domain_info(
            _LATTICE_DOMAIN_NAME[self._lattice_phase],
            _lattice_rule_html(self._lattice_phase, self._lattice_source[1]),
            self._lattice_mesh.n_cells,
            cached=self._lattice_retained,
        )
        self.lattice_card.show()

    # ─────────────────────────── lattice geometry ─────────────────────

    def _reset_lattice(self, reason: str) -> None:
        """Stop lattice work, show the simplified geometry and disable ``晶格`` with a reason."""
        self._lattice.cancel()
        self._lattice_pending = None
        self._lattice_source = None
        self._lattice_mesh = None
        self._geometry = "simple"
        self.lattice_progress.hide()
        self.lattice_card.hide()
        self.toolbar.set_lattice_enabled(False, reason)

    def _request_lattice(self) -> None:
        """Submit the active field and detail. The current scene stays until the mesh is ready."""
        topology, delta, result_id = self._lattice_source
        phase = _LATTICE_PHASE[PANEL_FIELD_SPECS[self._field].phase]
        dx, dy, dz = self._widths_m
        detail = self.toolbar.detail_level()
        request = LatticeRequest(
            result_id=result_id,
            field_name=self._field,
            topology=topology,
            phase=phase,
            dx=dx,
            dy=dy,
            dz=dz,
            field=self._ensure_field(self._field),
            L_mm=self._ensure_field("L_mm"),
            t_mm=self._ensure_field("t_mm"),
            delta=delta,
            detail=detail,
        )
        self._lattice_pending = (self._lattice.submit(request), phase, detail, self._field)

    def _on_lattice_progress(self, generation: int, step: int, stage: str) -> None:
        if self._lattice_pending is None or generation != self._lattice_pending[0]:
            return
        domain = _LATTICE_DOMAIN_NAME[self._lattice_pending[1]]
        self.lattice_progress.set_stage(domain, stage, step, _LATTICE_STAGE_COUNT)
        self.lattice_progress.show()
        self._layout_overlays()

    def _on_lattice_ready(self, generation: int, mesh: pv.PolyData, retained: bool) -> None:
        if self._lattice_pending is None or generation != self._lattice_pending[0]:
            return
        _generation, self._lattice_phase, self._detail, _field = self._lattice_pending
        self._lattice_pending = None
        self._lattice_mesh = mesh
        self._lattice_retained = retained
        self._geometry = "lattice"
        self.lattice_progress.hide()
        self._rebuild_scene_for_ui()
        self._layout_overlays()

    def _on_lattice_failed(self, generation: int, error: str) -> None:
        if self._lattice_pending is None or generation != self._lattice_pending[0]:
            return
        self._restore_shown_lattice()
        self.status.setText(f"晶格构建失败：{error}")
        self.status.show()
        self._layout_overlays()

    def _cancel_lattice(self) -> None:
        """Stop the pending build. Keep the scene and the field that are on the screen."""
        self._lattice.cancel()
        self._restore_shown_lattice()
        self._layout_overlays()

    def _restore_shown_lattice(self) -> None:
        self._lattice_pending = None
        self.lattice_progress.hide()
        self.toolbar.set_geometry_mode(self._geometry)
        self.toolbar.set_detail_level(self._detail)
        if self._geometry == "lattice" and self._lattice_mesh.active_scalars_name != self._field:
            self._field = self._lattice_mesh.active_scalars_name
            self._rebuild_scene_for_ui()
            self.field_changed.emit(self._field)

    def _sync_colorbar(self, cmap: str, clim: tuple[float, float]) -> None:
        if self._field not in PANEL_FIELD_SPECS:
            return
        spec = PANEL_FIELD_SPECS[self._field]
        symbol_html = _FIELD_SYMBOL_HTML.get(self._field, spec.symbol_html)
        self.colorbar.set_spec(symbol_html, spec.display_unit, clim[0], clim[1], colormap=cmap)
        self.colorbar.show()

    def _rebuild_scene(self, render: bool = True) -> None:
        """Rebuild the active simplified 3D actors and colorbar in one render batch."""
        if self._grid is None or self._field is None:
            return
        if self._lattice_pending is not None or self._geometry == "lattice":
            wanted = self._lattice_pending[3] if self._lattice_pending else self._lattice_mesh.active_scalars_name
            if wanted != self._field:
                self._request_lattice()
        lattice = self._geometry == "lattice" and self._lattice_mesh.active_scalars_name == self._field
        if self._geometry == "lattice" and not lattice and self._volume_actor is not None:
            return  # Keep the lattice on the screen until the mesh for the new field is ready.
        self._clear_data_actors()
        if self._field not in PANEL_FIELD_SPECS:
            if render:
                self.plotter.render()
            return

        self._grid_vol, self._vol_min_cell_mm = self._build_volume_grid()
        cmap = resolve_cmap(self._field)
        clim = self._clim_for(self._field)

        try:
            if lattice:
                self._render_lattice_actors(cmap, clim)
            elif self._geometry == "lattice":
                # A cleared scene during a field change shows the simplified scene until the mesh is ready.
                self.lattice_card.hide()
                self._render_surface_actors(self._grid_vol, cmap, clim)
            elif self._display_mode == "surface":
                self._render_surface_actors(self._grid_vol, cmap, clim)
            elif self._display_mode == "slice":
                self._render_slice_actors(self._grid_vol, cmap, clim)
            else:
                self._render_volume_actors(self._grid_vol, cmap, clim)
        except Exception as exc:
            self._clear_data_actors()
            self.colorbar.hide()
            self.lattice_card.hide()
            self.status.setText(f"三维渲染失败：{exc}")
            self.status.show()
            self._layout_overlays()
            if render:
                self.plotter.render()
            raise

        self._add_flow_glyph()
        self._sync_colorbar(cmap, clim)
        self._update_status()
        if render:
            self.plotter.render()
            self._update_port_chips()

    # ─────────────────────────── slice & status helpers ───────────────

    def _slice_index(self, axis: str, coord_mm: float) -> int:
        """Map a physical coordinate in mm to the nearest cell centre index."""
        centres = {"x": self._cx_mm, "y": self._cy_mm, "z": self._cz_mm}[axis]
        return int(np.argmin(np.abs(centres - coord_mm)))

    def _snap_slice_coord(self, axis: str, coord_mm: float) -> float:
        """Return the physical cell centre closest to ``coord_mm`` along ``axis``."""
        centres = {"x": self._cx_mm, "y": self._cy_mm, "z": self._cz_mm}[axis]
        return float(centres[self._slice_index(axis, coord_mm)])

    def _update_status(self) -> None:
        if self._grid is None or self._field is None or self._field not in PANEL_FIELD_SPECS:
            return
        spec = PANEL_FIELD_SPECS[self._field]
        symbol = _FIELD_SYMBOL_HTML.get(self._field, spec.symbol_html)
        lo, hi = self._clim_for(self._field)
        Lx, Ly, Lz = self._L_mm
        parts = [
            f"场：{symbol}",
            f"范围：{lo:.2f}–{hi:.2f} {spec.display_unit}",
            f"计算域：{Lx:.0f} × {Ly:.0f} × {Lz:.0f} mm",
        ]
        if self._display_mode == "slice" and self._geometry == "simple":
            sx, sy, sz = self._slice_xyz_mm
            parts.append(f"截面：({sx:.1f}, {sy:.1f}, {sz:.1f}) mm")
        text = "   •   ".join(parts)
        self._base_status_text = text
        self.status.setText(text)
        self.status.setToolTip(text)
        self.status.hide()
        self._last_hover_text = ""
