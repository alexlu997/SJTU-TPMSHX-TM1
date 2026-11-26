"""Interactive Matplotlib Pareto front and mass-objective plot in Style P2."""
from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Any, Mapping, Sequence

import matplotlib as mpl
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from sjtu_tpmshx.applications.gui.ui.symbols import MPL, signed, val_unit

_PT = 72.0 / 100.0
_PICK_RADIUS_PX = 16.0
_HOVER_RADIUS_PX = 14.0

_MODE_HEAT_PRESSURE = "heat_pressure"
_MODE_MASS = "mass"
_VALID_MODES = (_MODE_HEAT_PRESSURE, _MODE_MASS)

_PHASE_LABELS: dict[str, str] = {
    "initial": "初始候选",
    "iteration": "迭代候选",
}

_MASS_X_LABEL = r"← 可行     最大归一化约束残差 $\mathrm{[\%]}$"
_MASS_Y_LABEL = r"← 更轻     芯体质量 $\mathit{m}\ \mathrm{[kg]}$"

_DEFAULT_TOKENS: dict[str, Any] = {
    "canvas": "#F8F7F4",
    "popover": "#FFFFFF",
    "border": "#D9D8D4",
    "border_strong": "#C1BFBA",
    "inp_border": "#807F79",
    "fg": "#181715",
    "sub": "#474643",
    "tert": "#686663",
    "accent": "#0E6275",
    "accent_fg": "#0B5161",
    "accent_soft": "#E5F0F2",
    "ok": "#176B3E",
    "ok_soft": "#E7F2EB",
    "err": "#B43025",
}


@dataclass(frozen=True)
class ParetoPoint:
    """Plain-value history point rendered by ``ParetoView``.

    In ``heat_pressure`` mode, ``x`` is mean relative pressure drop
    ``dP/dP0 [1]`` and ``y`` is mean useful heat gain ``dQ/Q0 [%]``.
    In ``mass`` mode, ``x`` is ``100 * max_normalized_residual [%]``
    with the feasible boundary at zero and ``y`` is core mass ``[kg]``.
    """

    index: int
    x: float
    y: float
    phase: str = "initial"
    on_front: bool = False
    is_baseline: bool = False
    feasible: bool = True


def _is_dark(tokens: Mapping[str, Any]) -> bool:
    return QColor(tokens["canvas"]).lightness() < 128


def _mpl_rc_overrides(tokens: Mapping[str, Any]) -> dict[str, Any]:
    if sys.platform == "darwin":
        latin = "Helvetica Neue"
        families = ["PingFang SC", "Helvetica Neue", "DejaVu Sans"]
    elif sys.platform == "win32":
        latin = "Arial"
        families = ["Microsoft YaHei", "Arial", "DejaVu Sans"]
    else:
        latin = "DejaVu Sans"
        families = ["Noto Sans CJK SC", "DejaVu Sans"]
    return {
        "figure.dpi": 100,
        "savefig.dpi": 100,
        "font.family": families,
        "font.size": 12 * _PT,
        "axes.labelsize": 11.5 * _PT,
        "xtick.labelsize": 11 * _PT,
        "ytick.labelsize": 11 * _PT,
        "text.color": tokens["fg"],
        "axes.labelcolor": tokens["sub"],
        "xtick.color": tokens["tert"],
        "ytick.color": tokens["tert"],
        "axes.edgecolor": tokens["border_strong"],
        "figure.facecolor": tokens["canvas"],
        "axes.facecolor": tokens["canvas"],
        "axes.unicode_minus": True,
        "mathtext.fontset": "custom",
        "mathtext.it": f"{latin}:italic",
        "mathtext.rm": latin,
        "mathtext.bf": f"{latin}:bold",
        "mathtext.default": "regular",
    }


def _frac_rect(x: float, y: float, w: float, h: float, total_w: float, total_h: float) -> list[float]:
    return [x / total_w, 1.0 - (y + h) / total_h, w / total_w, h / total_h]


def _padded_bounds(
    values: Sequence[float],
    *,
    lo_pad: float,
    hi_pad: float,
    min_span: float,
    include: Sequence[float] = (),
) -> tuple[float, float]:
    all_vals = [float(v) for v in values] + [float(v) for v in include]
    lo = min(all_vals)
    hi = max(all_vals)
    span = hi - lo
    if span < min_span:
        mid = 0.5 * (lo + hi)
        lo = mid - 0.5 * min_span
        hi = mid + 0.5 * min_span
        span = min_span
    return lo - lo_pad * span, hi + hi_pad * span


def _phase_label(phase: str) -> str:
    return _PHASE_LABELS.get(phase, phase)


class _ScopedFigureCanvas(FigureCanvasQTAgg):
    """Figure canvas that applies Style P2 Matplotlib typography on each draw."""

    def __init__(self, figure: Figure, owner: ParetoView) -> None:
        self._owner = owner
        super().__init__(figure)
        self.setStyleSheet("background: transparent;")

    def draw(self) -> None:
        with mpl.rc_context(_mpl_rc_overrides(self._owner._tokens)):
            super().draw()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        if w > 50 and h > 50:
            self._owner._redraw(w, h)


class ParetoView(QWidget):
    """Interactive Style P2 Pareto front and mass-objective scatter view.

    Clicking a plotted point updates selection and emits ``point_picked``
    with the history index. It never loads or modifies a case.
    """

    point_picked = Signal(int)

    def __init__(
        self,
        *,
        mode: str = _MODE_HEAT_PRESSURE,
        tokens: Mapping[str, Any] | None = None,
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if mode not in _VALID_MODES:
            raise ValueError(f"Unknown ParetoView mode {mode!r}; expected {_VALID_MODES}")
        self._mode = mode
        self._tokens: dict[str, Any] = dict(_DEFAULT_TOKENS)
        if tokens is not None:
            self._tokens.update(tokens)
        self._compact = compact
        self._points: list[ParetoPoint] = []
        self._selected_index: int | None = None
        self._hovered_index: int | None = None
        self._ax = None
        self._hover_annot = None

        self._figure = Figure(dpi=100)
        self._figure.patch.set_facecolor(self._tokens["canvas"])
        self._canvas = _ScopedFigureCanvas(self._figure, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._canvas)

        self._canvas.mpl_connect("button_press_event", self._on_press)
        self._canvas.mpl_connect("motion_notify_event", self._on_motion)
        self._canvas.mpl_connect("figure_leave_event", self._on_leave)

    @property
    def figure(self) -> Figure:
        """Return the underlying Matplotlib figure for export or copy."""
        return self._figure

    @property
    def canvas(self) -> FigureCanvasQTAgg:
        """Return the embedded Qt Matplotlib canvas."""
        return self._canvas

    @property
    def mode(self) -> str:
        """Return the active plot mode (``heat_pressure`` or ``mass``)."""
        return self._mode

    def selected_index(self) -> int | None:
        """Return the currently selected history index, or None."""
        return self._selected_index

    def set_data(
        self,
        points: Sequence[ParetoPoint],
        *,
        selected_index: int | None = None,
        mode: str | None = None,
    ) -> None:
        """Replace plotted history records and redraw the chart."""
        if mode is not None:
            if mode not in _VALID_MODES:
                raise ValueError(f"Unknown ParetoView mode {mode!r}; expected {_VALID_MODES}")
            self._mode = mode
        self._points = list(points)
        valid_ids = {pt.index for pt in self._points}
        self._selected_index = selected_index if selected_index in valid_ids else None
        self._hovered_index = None
        self._redraw()

    def set_mode(self, mode: str) -> None:
        """Switch between ``heat_pressure`` and ``mass`` modes."""
        if mode not in _VALID_MODES:
            raise ValueError(f"Unknown ParetoView mode {mode!r}; expected {_VALID_MODES}")
        if self._mode == mode:
            return
        self._mode = mode
        self._hovered_index = None
        self._redraw()

    def set_selected_index(self, index: int | None) -> None:
        """Select a history index visually without emitting ``point_picked``."""
        valid_ids = {pt.index for pt in self._points}
        target = index if index in valid_ids else None
        if target == self._selected_index:
            return
        self._selected_index = target
        if self._hovered_index == target:
            self._hovered_index = None
        self._redraw()

    def set_compact(self, compact: bool) -> None:
        """Adjust plot margins and callout font size for compact layouts."""
        if self._compact == compact:
            return
        self._compact = compact
        self._redraw()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens and redraw the chart."""
        self._tokens.update(tokens)
        self._figure.patch.set_facecolor(self._tokens["canvas"])
        self._redraw()

    def clear(self) -> None:
        """Remove all plotted points and show the empty state."""
        self._points.clear()
        self._selected_index = None
        self._hovered_index = None
        self._redraw()

    def _effective_size(self, width: int | None, height: int | None) -> tuple[int, int]:
        w = width if width is not None else self._canvas.width()
        h = height if height is not None else self._canvas.height()
        if w <= 50 or h <= 50:
            w = max(w, 640)
            h = max(h, 420)
        return w, h

    def _style_axes(self, ax) -> None:
        t = self._tokens
        ax.set_facecolor(t["canvas"])
        for name, spine in ax.spines.items():
            spine.set_visible(name in ("left", "bottom"))
            spine.set_color(t["border_strong"])
            spine.set_linewidth(0.65)
        ax.tick_params(length=3, width=0.6, colors=t["tert"], pad=5)
        ax.grid(True, color=t["border"], linewidth=0.55, alpha=0.85)
        ax.set_axisbelow(True)

    def _callout_offset(self, ax, x: float, y: float) -> tuple[tuple[float, float], str, str]:
        xlo, xhi = ax.get_xlim()
        ylo, yhi = ax.get_ylim()
        rx = (x - xlo) / max(1e-12, xhi - xlo)
        ry = (y - ylo) / max(1e-12, yhi - ylo)
        if rx >= 0.45:
            dx, ha = -24.0, "right"
        else:
            dx, ha = 24.0, "left"
        if ry > 0.94:
            dy, va = -14.0, "top"
        elif ry < 0.08:
            dy, va = 14.0, "bottom"
        else:
            dy, va = 0.0, "center"
        return (dx, dy), ha, va

    def _point_callout_text(self, pt: ParetoPoint) -> str:
        phase_s = _phase_label(pt.phase)
        if self._mode == _MODE_MASS:
            state = "可行" if pt.feasible else "未达标"
            return (
                f"方案 #{pt.index} · {phase_s} · {state}\n"
                f"质量 {val_unit(f'{pt.y:.3f}', 'kg')}   "
                f"残差 {val_unit(signed(pt.x, '+.2f'), '%')}"
            )
        return (
            f"方案 #{pt.index} · {phase_s}\n"
            f"压降比 {pt.x:.4f}   "
            f"换热 {val_unit(signed(pt.y, '+.3f'), '%')}"
        )

    def _redraw(self, width: int | None = None, height: int | None = None) -> None:
        t = self._tokens
        wp, hp = self._effective_size(width, height)
        compact = self._compact or wp < 860

        with mpl.rc_context(_mpl_rc_overrides(t)):
            self._figure.clear()
            self._figure.patch.set_facecolor(t["canvas"])
            self._ax = None
            self._hover_annot = None

            if not self._points:
                ax = self._figure.add_axes([0.0, 0.0, 1.0, 1.0])
                ax.set_facecolor(t["canvas"])
                ax.set_axis_off()
                ax.text(
                    0.5,
                    0.5,
                    "暂无评估方案",
                    ha="center",
                    va="center",
                    fontsize=13 * _PT,
                    color=t["sub"],
                )
                self._canvas.draw_idle()
                return

            left, right, top, bottom = (76, 26, 62, 52) if compact else (82, 30, 68, 56)
            ax = self._figure.add_axes(
                _frac_rect(left, top, max(80, wp - left - right), max(80, hp - top - bottom), wp, hp)
            )
            self._ax = ax

            if self._mode == _MODE_MASS:
                self._draw_mass(ax, compact=compact)
            else:
                self._draw_heat_pressure(ax, compact=compact)

            self._style_axes(ax)
            self._canvas.draw_idle()

    def _draw_heat_pressure(self, ax, *, compact: bool) -> None:
        t = self._tokens
        dark = _is_dark(t)
        pts = self._points
        xs = np.array([pt.x for pt in pts], dtype=float)
        ys = np.array([pt.y for pt in pts], dtype=float)

        baseline = next((pt for pt in pts if pt.is_baseline), None)
        include_x = [baseline.x] if baseline is not None else []
        include_y = [baseline.y] if baseline is not None else []

        xlo, xhi = _padded_bounds(xs, lo_pad=0.10, hi_pad=0.12, min_span=0.01, include=include_x)
        ylo, yhi = _padded_bounds(ys, lo_pad=0.11, hi_pad=0.13, min_span=0.5, include=include_y)
        ax.set_xlim(xlo, xhi)
        ax.set_ylim(ylo, yhi)

        if baseline is not None:
            bx, by = baseline.x, baseline.y
            ax.fill_between(
                [xlo, bx],
                by,
                yhi,
                color=t["ok_soft"],
                alpha=0.62 if dark else 0.50,
                lw=0,
                zorder=0.4,
            )
            ax.axvline(bx, color=t["inp_border"], lw=0.85, ls=(0, (4, 3)), alpha=0.72, zorder=1.2)
            ax.axhline(by, color=t["inp_border"], lw=0.85, ls=(0, (4, 3)), alpha=0.72, zorder=1.2)
            ax.text(
                xlo + 0.03 * (xhi - xlo),
                yhi - 0.026 * (yhi - ylo),
                "压降更低 · 换热更高",
                color=t["ok"],
                fontsize=11 * _PT,
                fontweight=600,
                va="top",
                ha="left",
                zorder=2,
            )

        front = sorted(
            (pt for pt in pts if pt.on_front and not pt.is_baseline),
            key=lambda pt: (pt.x, -pt.y),
        )
        if front:
            sx = [front[0].x]
            sy = [ylo]
            for k, pt in enumerate(front):
                sx.append(pt.x)
                sy.append(pt.y)
                if k < len(front) - 1:
                    sx.append(front[k + 1].x)
                    sy.append(pt.y)
            sx.append(xhi)
            sy.append(front[-1].y)
            ax.fill_between(
                sx,
                ylo,
                sy,
                color=t["accent"],
                alpha=0.072 if dark else 0.042,
                lw=0,
                zorder=0.8,
            )
            ax.plot(sx, sy, color=t["accent"], lw=1.5, alpha=0.9, zorder=3)

        sel_pt = next((pt for pt in pts if pt.index == self._selected_index), None)
        if sel_pt is not None:
            ax.plot(
                [sel_pt.x, sel_pt.x],
                [ylo, sel_pt.y],
                color=t["accent"],
                lw=0.75,
                ls=(0, (2, 3)),
                alpha=0.45,
                zorder=2.5,
            )
            ax.plot(
                [xlo, sel_pt.x],
                [sel_pt.y, sel_pt.y],
                color=t["accent"],
                lw=0.75,
                ls=(0, (2, 3)),
                alpha=0.45,
                zorder=2.5,
            )

        non_front = [pt for pt in pts if not pt.on_front and not pt.is_baseline]
        nf_init = [pt for pt in non_front if pt.phase != "iteration"]
        nf_iter = [pt for pt in non_front if pt.phase == "iteration"]
        if nf_init:
            ax.scatter(
                [pt.x for pt in nf_init],
                [pt.y for pt in nf_init],
                s=34,
                facecolors=t["canvas"],
                edgecolors=t["tert"],
                linewidths=1.3,
                alpha=0.75,
                zorder=3.2,
            )
        if nf_iter:
            ax.scatter(
                [pt.x for pt in nf_iter],
                [pt.y for pt in nf_iter],
                s=36,
                color=t["tert"],
                edgecolors=t["canvas"],
                linewidths=0.9,
                alpha=0.75,
                zorder=3.3,
            )

        if baseline is not None:
            ax.scatter(
                [baseline.x],
                [baseline.y],
                marker="D",
                s=58,
                facecolors=t["canvas"],
                edgecolors=t["sub"],
                linewidths=1.4,
                zorder=4.2,
            )
            ax.scatter([baseline.x], [baseline.y], marker="o", s=8, color=t["sub"], zorder=4.3)

        f_init = [pt for pt in front if pt.phase != "iteration"]
        f_iter = [pt for pt in front if pt.phase == "iteration"]
        if f_init:
            ax.scatter(
                [pt.x for pt in f_init],
                [pt.y for pt in f_init],
                s=52,
                facecolors=t["canvas"],
                edgecolors=t["accent"],
                linewidths=1.7,
                zorder=4.5,
            )
        if f_iter:
            ax.scatter(
                [pt.x for pt in f_iter],
                [pt.y for pt in f_iter],
                s=60,
                color=t["accent"],
                edgecolors=t["canvas"],
                linewidths=1.2,
                zorder=4.6,
            )

        if sel_pt is not None:
            self._draw_selection_callout(ax, sel_pt, compact=compact)

        if front and (sel_pt is None or front[0].index != sel_pt.index):
            ax.annotate(
                f"#{front[0].index}  最低压降",
                (front[0].x, front[0].y),
                xytext=(10, -10),
                textcoords="offset points",
                ha="left",
                va="top",
                fontsize=10.5 * _PT,
                color=t["fg"],
                fontweight=500,
                zorder=6,
            )

        if baseline is not None and (sel_pt is None or baseline.index != sel_pt.index):
            ax.annotate(
                f"均匀基准 #{baseline.index}",
                (baseline.x, baseline.y),
                xytext=(-10, -11),
                textcoords="offset points",
                ha="right",
                va="top",
                fontsize=10.5 * _PT,
                color=t["sub"],
                fontweight=500,
                zorder=6,
            )

        ax.set_xlabel(MPL["pr_ratio"], labelpad=8)
        ax.set_ylabel(MPL["hg_pct"], labelpad=8)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=6))

        handles: list[Line2D] = []
        if f_iter:
            handles.append(
                Line2D(
                    [],
                    [],
                    marker="o",
                    ls="",
                    color=t["accent"],
                    mec=t["canvas"],
                    mew=0.9,
                    ms=6.5,
                    label=f"迭代前沿 ({len(f_iter)})",
                )
            )
        if f_init:
            handles.append(
                Line2D(
                    [],
                    [],
                    marker="o",
                    ls="",
                    mfc=t["canvas"],
                    mec=t["accent"],
                    mew=1.6,
                    ms=6.0,
                    label=f"初始前沿 ({len(f_init)})",
                )
            )
        if non_front:
            handles.append(
                Line2D(
                    [],
                    [],
                    marker="o",
                    ls="",
                    color=t["tert"],
                    mec=t["canvas"],
                    mew=0.8,
                    ms=5.2,
                    label=f"非前沿 ({len(non_front)})",
                )
            )
        if baseline is not None:
            handles.append(
                Line2D(
                    [],
                    [],
                    marker="D",
                    ls="",
                    mfc=t["canvas"],
                    mec=t["sub"],
                    mew=1.4,
                    ms=6.0,
                    label=f"均匀基准 #{baseline.index}",
                )
            )
        if handles:
            ax.legend(
                handles=handles,
                frameon=True,
                facecolor=t["popover"],
                edgecolor=t["border"],
                framealpha=0.95,
                fontsize=10.5 * _PT,
                loc="lower right",
                labelcolor=t["fg"],
                handletextpad=0.4,
                borderpad=0.55,
            )

    def _draw_mass(self, ax, *, compact: bool) -> None:
        t = self._tokens
        dark = _is_dark(t)
        pts = self._points
        xs = np.array([pt.x for pt in pts], dtype=float)
        ys = np.array([pt.y for pt in pts], dtype=float)

        baseline = next((pt for pt in pts if pt.is_baseline), None)
        xlo, xhi = _padded_bounds(xs, lo_pad=0.12, hi_pad=0.12, min_span=4.0, include=[0.0])
        ylo, yhi = _padded_bounds(ys, lo_pad=0.12, hi_pad=0.14, min_span=0.05)
        ax.set_xlim(xlo, xhi)
        ax.set_ylim(ylo, yhi)

        if xlo < 0.0:
            ax.fill_between(
                [xlo, 0.0],
                ylo,
                yhi,
                color=t["ok_soft"],
                alpha=0.62 if dark else 0.50,
                lw=0,
                zorder=0.4,
            )
            ax.text(
                xlo + 0.025 * (xhi - xlo),
                yhi - 0.026 * (yhi - ylo),
                "可行域 · 满足逐项约束",
                color=t["ok"],
                fontsize=11 * _PT,
                fontweight=600,
                va="top",
                ha="left",
                zorder=2,
            )

        ax.axvline(0.0, color=t["ok"], lw=1.0, ls=(0, (4, 3)), alpha=0.85, zorder=1.3)
        ax.annotate(
            f"可行边界 {val_unit('0', '%')}",
            (0.0, yhi),
            xytext=(6, -6),
            textcoords="offset points",
            ha="left",
            va="top",
            fontsize=10 * _PT,
            color=t["ok"],
            fontweight=500,
            zorder=2.1,
        )

        if baseline is not None:
            ax.axhline(
                baseline.y,
                color=t["inp_border"],
                lw=0.8,
                ls=(0, (4, 3)),
                alpha=0.65,
                zorder=1.1,
            )

        sel_pt = next((pt for pt in pts if pt.index == self._selected_index), None)
        if sel_pt is not None:
            ax.plot(
                [sel_pt.x, sel_pt.x],
                [ylo, sel_pt.y],
                color=t["accent"],
                lw=0.75,
                ls=(0, (2, 3)),
                alpha=0.45,
                zorder=2.5,
            )
            ax.plot(
                [xlo, sel_pt.x],
                [sel_pt.y, sel_pt.y],
                color=t["accent"],
                lw=0.75,
                ls=(0, (2, 3)),
                alpha=0.45,
                zorder=2.5,
            )

        non_base = [pt for pt in pts if not pt.is_baseline]
        infeas_init = [pt for pt in non_base if not pt.feasible and pt.phase != "iteration"]
        infeas_iter = [pt for pt in non_base if not pt.feasible and pt.phase == "iteration"]
        feas_init = [pt for pt in non_base if pt.feasible and pt.phase != "iteration"]
        feas_iter = [pt for pt in non_base if pt.feasible and pt.phase == "iteration"]

        if infeas_init:
            ax.scatter(
                [pt.x for pt in infeas_init],
                [pt.y for pt in infeas_init],
                s=42,
                facecolors=t["canvas"],
                edgecolors=t["tert"],
                linewidths=1.4,
                alpha=0.82,
                zorder=3.4,
            )
        if infeas_iter:
            ax.scatter(
                [pt.x for pt in infeas_iter],
                [pt.y for pt in infeas_iter],
                s=46,
                color=t["tert"],
                edgecolors=t["canvas"],
                linewidths=1.0,
                alpha=0.82,
                zorder=3.5,
            )

        if baseline is not None:
            ax.scatter(
                [baseline.x],
                [baseline.y],
                marker="D",
                s=58,
                facecolors=t["canvas"],
                edgecolors=t["sub"],
                linewidths=1.4,
                zorder=4.2,
            )
            ax.scatter([baseline.x], [baseline.y], marker="o", s=8, color=t["sub"], zorder=4.3)

        if feas_init:
            ax.scatter(
                [pt.x for pt in feas_init],
                [pt.y for pt in feas_init],
                s=52,
                facecolors=t["canvas"],
                edgecolors=t["accent"],
                linewidths=1.7,
                zorder=4.5,
            )
        if feas_iter:
            ax.scatter(
                [pt.x for pt in feas_iter],
                [pt.y for pt in feas_iter],
                s=60,
                color=t["accent"],
                edgecolors=t["canvas"],
                linewidths=1.2,
                zorder=4.6,
            )

        if sel_pt is not None:
            self._draw_selection_callout(ax, sel_pt, compact=compact)

        feasible_all = [pt for pt in pts if pt.feasible]
        if feasible_all:
            best = min(feasible_all, key=lambda pt: pt.y)
            if sel_pt is None or best.index != sel_pt.index:
                ax.annotate(
                    f"#{best.index}  最轻可行",
                    (best.x, best.y),
                    xytext=(10, -8),
                    textcoords="offset points",
                    ha="left",
                    va="top",
                    fontsize=10.5 * _PT,
                    color=t["fg"],
                    fontweight=500,
                    zorder=6,
                )

        if baseline is not None and (sel_pt is None or baseline.index != sel_pt.index):
            ax.annotate(
                f"均匀基准 #{baseline.index}",
                (baseline.x, baseline.y),
                xytext=(-10, -11),
                textcoords="offset points",
                ha="right",
                va="top",
                fontsize=10.5 * _PT,
                color=t["sub"],
                fontweight=500,
                zorder=6,
            )

        ax.set_xlabel(_MASS_X_LABEL, labelpad=8)
        ax.set_ylabel(_MASS_Y_LABEL, labelpad=8)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=6))

        handles: list[Line2D] = []
        if feas_iter:
            handles.append(
                Line2D(
                    [],
                    [],
                    marker="o",
                    ls="",
                    color=t["accent"],
                    mec=t["canvas"],
                    mew=0.9,
                    ms=6.5,
                    label=f"可行 · 迭代 ({len(feas_iter)})",
                )
            )
        if feas_init:
            handles.append(
                Line2D(
                    [],
                    [],
                    marker="o",
                    ls="",
                    mfc=t["canvas"],
                    mec=t["accent"],
                    mew=1.6,
                    ms=6.0,
                    label=f"可行 · 初始 ({len(feas_init)})",
                )
            )
        n_infeas = len(infeas_init) + len(infeas_iter)
        if n_infeas:
            handles.append(
                Line2D(
                    [],
                    [],
                    marker="o",
                    ls="",
                    color=t["tert"],
                    mec=t["canvas"],
                    mew=0.9,
                    ms=5.8,
                    label=f"未达标 ({n_infeas})",
                )
            )
        if baseline is not None:
            handles.append(
                Line2D(
                    [],
                    [],
                    marker="D",
                    ls="",
                    mfc=t["canvas"],
                    mec=t["sub"],
                    mew=1.4,
                    ms=6.0,
                    label=f"均匀基准 #{baseline.index}",
                )
            )
        if handles:
            ax.legend(
                handles=handles,
                frameon=True,
                facecolor=t["popover"],
                edgecolor=t["border"],
                framealpha=0.95,
                fontsize=10.5 * _PT,
                loc="lower right",
                labelcolor=t["fg"],
                handletextpad=0.4,
                borderpad=0.55,
            )

    def _draw_selection_callout(self, ax, pt: ParetoPoint, *, compact: bool) -> None:
        t = self._tokens
        ax.scatter(
            [pt.x],
            [pt.y],
            s=260,
            facecolors=t["accent_soft"],
            edgecolors="none",
            alpha=0.85,
            zorder=4.4,
        )
        ax.scatter(
            [pt.x],
            [pt.y],
            s=185,
            facecolors="none",
            edgecolors=t["fg"],
            linewidths=1.45,
            zorder=5.0,
        )
        offset, ha, va = self._callout_offset(ax, pt.x, pt.y)
        ax.annotate(
            self._point_callout_text(pt),
            (pt.x, pt.y),
            xytext=offset,
            textcoords="offset points",
            ha=ha,
            va=va,
            multialignment="left",
            fontsize=(10.5 if compact else 11.0) * _PT,
            color=t["fg"],
            linespacing=1.5,
            zorder=7,
            bbox=dict(
                boxstyle="round,pad=0.52,rounding_size=0.4",
                fc=t["popover"],
                ec=t["border_strong"],
                lw=0.75,
            ),
            arrowprops=dict(
                arrowstyle="-",
                color=t["border_strong"],
                lw=0.8,
                shrinkA=0,
                shrinkB=11,
            ),
        )

    def _nearest_point(self, event, max_radius_px: float) -> ParetoPoint | None:
        if self._ax is None or event.inaxes is not self._ax or not self._points:
            return None
        if event.x is None or event.y is None:
            return None
        dpr = max(1.0, float(self._canvas.device_pixel_ratio))
        limit = max_radius_px * dpr
        coords = np.array([(pt.x, pt.y) for pt in self._points], dtype=float)
        disp = self._ax.transData.transform(coords)
        dists = np.hypot(disp[:, 0] - event.x, disp[:, 1] - event.y)
        best_pos = int(np.argmin(dists))
        if dists[best_pos] <= limit:
            return self._points[best_pos]
        return None

    def _on_press(self, event) -> None:
        if event.button != 1:
            return
        pt = self._nearest_point(event, _PICK_RADIUS_PX)
        if pt is None:
            return
        self._selected_index = pt.index
        self._hovered_index = None
        self._redraw()
        self.point_picked.emit(pt.index)

    def _on_motion(self, event) -> None:
        pt = self._nearest_point(event, _HOVER_RADIUS_PX)
        target_id = None if (pt is None or pt.index == self._selected_index) else pt.index
        if target_id == self._hovered_index:
            return
        self._hovered_index = target_id
        self._set_cursor(pt is not None)
        self._update_hover_annotation(pt if target_id is not None else None)

    def _on_leave(self, _event) -> None:
        self._set_cursor(False)
        if self._hovered_index is not None:
            self._hovered_index = None
            self._update_hover_annotation(None)

    def _set_cursor(self, pointing: bool) -> None:
        self._canvas.setCursor(
            Qt.CursorShape.PointingHandCursor if pointing else Qt.CursorShape.ArrowCursor
        )

    def _update_hover_annotation(self, pt: ParetoPoint | None) -> None:
        if self._hover_annot is not None:
            self._hover_annot.remove()
            self._hover_annot = None
        if pt is not None and self._ax is not None:
            t = self._tokens
            offset, ha, va = self._callout_offset(self._ax, pt.x, pt.y)
            self._hover_annot = self._ax.annotate(
                self._point_callout_text(pt),
                (pt.x, pt.y),
                xytext=offset,
                textcoords="offset points",
                ha=ha,
                va=va,
                multialignment="left",
                fontsize=10.5 * _PT,
                color=t["fg"],
                linespacing=1.45,
                zorder=8,
                bbox=dict(
                    boxstyle="round,pad=0.45,rounding_size=0.35",
                    fc=t["popover"],
                    ec=t["border_strong"],
                    lw=0.75,
                ),
            )
        self._canvas.draw_idle()


__all__ = ["ParetoPoint", "ParetoView"]
