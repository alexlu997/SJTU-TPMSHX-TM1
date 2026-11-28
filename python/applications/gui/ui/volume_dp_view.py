"""Ranked volume-versus-pressure-drop dot plot for Quick Design in Style P2."""
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
from PySide6.QtWidgets import QVBoxLayout, QWidget

from tm1.applications.gui.ui.symbols import MPL, mpl_qd_row, val_unit
from tm1.applications.gui.ui.theme import get_theme

_PT = 72.0 / 100.0
_LIMIT_TOL = 1e-9

_TOPO_STYLE: dict[str, tuple[str, str]] = {
    "Diamond": ("D", "data_a"),
    "Gyroid": ("o", "data_b"),
}
_TAG_LABELS: dict[str, str] = {
    "min-V": "最小体积",
    "min-wt": "最轻",
    "min-dP": "最小压损",
}


@dataclass(frozen=True)
class CasePressureLimit:
    """Per-case hot and cold fractional pressure-drop limits."""

    case_id: str
    hot_limit_frac: float
    cold_limit_frac: float


@dataclass(frozen=True)
class VolumeDpDesign:
    """Plain-value Quick Design record rendered by ``VolumeDpView``."""

    index: int
    topo: str
    l_mm: float
    t_mm: float
    V_m3: float
    dP_hot_max: float
    dP_cold_max: float
    tags: Sequence[str] = ()
    feasible: bool = True
    hot_limit_frac: float | None = None
    cold_limit_frac: float | None = None
    hot_case_id: str = ""
    cold_case_id: str = ""


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
        "ytick.labelsize": 11.5 * _PT,
        "text.color": tokens["fg"],
        "axes.labelcolor": tokens["sub"],
        "xtick.color": tokens["tert"],
        "ytick.color": tokens["sub"],
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


def _topo_marker_color(topo: str, tokens: Mapping[str, Any]) -> tuple[str, str]:
    if topo in _TOPO_STYLE:
        marker, key = _TOPO_STYLE[topo]
        return marker, tokens[key]
    return "s", tokens["accent"]


def _format_tags(tags: Sequence[str]) -> str:
    return " · ".join(_TAG_LABELS.get(tag, tag) for tag in tags)


def _resolve_common_limit(
    rows: Sequence[VolumeDpDesign],
    case_limits: Sequence[CasePressureLimit],
) -> float | None:
    """Return a single limit fraction only when every supplied limit matches."""
    values: list[float] = []
    for cl in case_limits:
        values.append(float(cl.hot_limit_frac))
        values.append(float(cl.cold_limit_frac))
    for row in rows:
        if row.hot_limit_frac is not None:
            values.append(float(row.hot_limit_frac))
        if row.cold_limit_frac is not None:
            values.append(float(row.cold_limit_frac))
    if not values:
        return None
    first = values[0]
    if all(abs(v - first) <= _LIMIT_TOL for v in values):
        return first
    return None


class _ScopedFigureCanvas(FigureCanvasQTAgg):
    """Figure canvas that applies Style P2 Matplotlib typography on each draw."""

    def __init__(self, figure: Figure, owner: VolumeDpView) -> None:
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


class VolumeDpView(QWidget):
    """Ranked Quick Design dot plot of core volume and hot/cold pressure drop.

    Feasible designs are sorted by core volume ``V`` ascending. Clicking any
    row selects that design and emits ``design_picked`` with its design index.
    """

    design_picked = Signal(int)

    def __init__(
        self,
        *,
        bottom_pad: int = 56,
        tokens: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens: dict[str, Any] = dict(get_theme())
        if tokens is not None:
            self._tokens.update(tokens)
        self._bottom_pad = int(bottom_pad)
        self._rows: list[VolumeDpDesign] = []
        self._case_limits: list[CasePressureLimit] = []
        self._partial_text: str = ""
        self._selected_index: int | None = None
        self._hovered_row: int | None = None
        self._axv = None
        self._axd = None
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

    def selected_index(self) -> int | None:
        """Return the currently selected design index, or None."""
        return self._selected_index

    def set_data(
        self,
        designs: Sequence[VolumeDpDesign],
        *,
        selected_index: int | None = None,
        case_limits: Sequence[CasePressureLimit] = (),
        partial_text: str = "",
    ) -> None:
        """Replace designs, rank feasible entries by volume ascending, and redraw."""
        feasible = [d for d in designs if d.feasible]
        self._rows = sorted(feasible, key=lambda d: (d.V_m3, d.index))
        self._case_limits = list(case_limits)
        self._partial_text = partial_text
        valid_ids = {d.index for d in self._rows}
        if selected_index in valid_ids:
            self._selected_index = selected_index
        else:
            self._selected_index = self._rows[0].index if self._rows else None
        self._hovered_row = None
        self._redraw()

    def set_selected_index(self, index: int | None) -> None:
        """Select a design index visually without emitting ``design_picked``."""
        valid_ids = {d.index for d in self._rows}
        target = index if index in valid_ids else None
        if target == self._selected_index:
            return
        self._selected_index = target
        self._redraw()

    def set_bottom_pad(self, px: int) -> None:
        """Set bottom plot padding in pixels (for example 152 with a peek card, 56 without)."""
        val = max(44, int(px))
        if val == self._bottom_pad:
            return
        self._bottom_pad = val
        self._redraw()

    def apply_theme(self, tokens: Mapping[str, Any]) -> None:
        """Apply Style P2 theme tokens and redraw."""
        self._tokens.update(tokens)
        self._figure.patch.set_facecolor(self._tokens["canvas"])
        self._redraw()

    def clear(self) -> None:
        """Clear all designs and show the empty state."""
        self._rows.clear()
        self._case_limits.clear()
        self._partial_text = ""
        self._selected_index = None
        self._hovered_row = None
        self._redraw()

    def _effective_size(self, width: int | None, height: int | None) -> tuple[int, int]:
        w = width if width is not None else self._canvas.width()
        h = height if height is not None else self._canvas.height()
        if w <= 50 or h <= 50:
            w = max(w, 840)
            h = max(h, 520)
        return w, h

    def _style_axis(self, ax) -> None:
        t = self._tokens
        ax.set_facecolor(t["canvas"])
        for name, spine in ax.spines.items():
            spine.set_visible(name == "bottom")
            spine.set_color(t["border_strong"])
            spine.set_linewidth(0.65)
        ax.tick_params(axis="x", length=3, width=0.6, colors=t["tert"], pad=5)
        ax.tick_params(axis="y", length=0)
        ax.grid(True, axis="x", color=t["border"], lw=0.55, alpha=0.85)
        ax.set_axisbelow(True)

    def _redraw(self, width: int | None = None, height: int | None = None) -> None:
        t = self._tokens
        wp, hp = self._effective_size(width, height)

        with mpl.rc_context(_mpl_rc_overrides(t)):
            self._figure.clear()
            self._figure.patch.set_facecolor(t["canvas"])
            self._axv = None
            self._axd = None
            self._hover_annot = None

            if not self._rows:
                ax = self._figure.add_axes([0.0, 0.0, 1.0, 1.0])
                ax.set_facecolor(t["canvas"])
                ax.set_axis_off()
                ax.text(
                    0.5,
                    0.5,
                    "暂无可行设计",
                    ha="center",
                    va="center",
                    fontsize=13 * _PT,
                    color=t["sub"],
                )
                self._canvas.draw_idle()
                return

            rows = self._rows
            n = len(rows)
            lab_w = 212
            top = 34
            bottom = self._bottom_pad
            avail_w = max(240, wp - lab_w - 40)
            wv = avail_w * 0.34
            wd = avail_w - wv - 26
            plot_h = max(120, hp - top - bottom)

            axv = self._figure.add_axes(_frac_rect(lab_w, top, wv, plot_h, wp, hp))
            axd = self._figure.add_axes(
                _frac_rect(lab_w + wv + 26, top, wd, plot_h, wp, hp),
                sharey=axv,
            )
            self._axv = axv
            self._axd = axd

            ys = np.arange(n)
            for ax in (axv, axd):
                for y, row in zip(ys, rows):
                    if row.index == self._selected_index:
                        ax.axhspan(y - 0.5, y + 0.5, color=t["accent_soft"], lw=0, zorder=0)
                self._style_axis(ax)

            vols_l = np.array([row.V_m3 * 1e3 for row in rows], dtype=float)
            hot_pct = np.array([row.dP_hot_max * 100.0 for row in rows], dtype=float)
            cold_pct = np.array([row.dP_cold_max * 100.0 for row in rows], dtype=float)

            v_min = float(np.min(vols_l))
            v_max = float(np.max(vols_l))
            v_span = max(v_max - v_min, 0.1 * max(v_max, 1.0))
            xlo_v = max(0.0, v_min - 0.06 * v_span)
            xhi_v = v_max + 0.07 * v_span

            common_lim_frac = _resolve_common_limit(rows, self._case_limits)
            limit_pcts = [
                cl.hot_limit_frac * 100.0 for cl in self._case_limits
            ] + [
                cl.cold_limit_frac * 100.0 for cl in self._case_limits
            ] + [
                row.hot_limit_frac * 100.0 for row in rows if row.hot_limit_frac is not None
            ] + [
                row.cold_limit_frac * 100.0 for row in rows if row.cold_limit_frac is not None
            ]
            max_dp = max(
                float(np.max(hot_pct)),
                float(np.max(cold_pct)),
                max(limit_pcts) if limit_pcts else 0.0,
                1.0,
            )

            if common_lim_frac is not None:
                lim_pct = common_lim_frac * 100.0
                xhi_d = max(lim_pct * 1.2, max_dp * 1.08)
                axd.axvspan(lim_pct, xhi_d, color=t["err_soft"], alpha=0.82, lw=0, zorder=0.2)
                axd.axvline(lim_pct, color=t["err"], lw=0.95, zorder=1)
                axd.annotate(
                    f"上限 {val_unit(f'{lim_pct:g}', '%')}",
                    (lim_pct, -0.5),
                    xytext=(7, -4),
                    textcoords="offset points",
                    ha="left",
                    va="top",
                    fontsize=10.5 * _PT,
                    color=t["err"],
                    annotation_clip=False,
                )
            else:
                xhi_d = max_dp * 1.16
                self._draw_per_case_limits(axd, rows, ys, xhi_d)

            marker_size = 34 if n <= 22 else max(18, int(34 * 22 / n))
            for y, row in zip(ys, rows):
                mk, col = _topo_marker_color(row.topo, t)
                vl = row.V_m3 * 1e3
                hp_val = row.dP_hot_max * 100.0
                cp_val = row.dP_cold_max * 100.0
                axv.plot(
                    [xlo_v, vl],
                    [y, y],
                    color=t["border"],
                    lw=1.2,
                    zorder=1,
                    solid_capstyle="round",
                )
                axv.scatter(
                    [vl],
                    [y],
                    marker=mk,
                    s=marker_size,
                    color=col,
                    edgecolors=t["canvas"],
                    linewidths=0.8,
                    zorder=3,
                )
                axd.plot(
                    [cp_val, hp_val],
                    [y, y],
                    color=t["border_strong"],
                    lw=0.95,
                    zorder=2,
                )
                axd.scatter(
                    [hp_val],
                    [y],
                    marker=mk,
                    s=marker_size,
                    color=col,
                    edgecolors=t["canvas"],
                    linewidths=0.8,
                    zorder=3,
                )
                axd.scatter(
                    [cp_val],
                    [y],
                    marker=mk,
                    s=marker_size,
                    facecolors=t["canvas"],
                    edgecolors=col,
                    linewidths=1.3,
                    zorder=3,
                )

            axv.set_ylim(n - 0.5, -0.5)
            axv.set_yticks(ys)
            label_fs = (11.5 if n <= 22 else max(8.5, 11.5 * 22 / n)) * _PT
            axv.set_yticklabels(
                [mpl_qd_row(row.topo, row.l_mm, row.t_mm) for row in rows],
                fontsize=label_fs,
            )
            for tick_label, row in zip(axv.get_yticklabels(), rows):
                is_sel = row.index == self._selected_index
                tick_label.set_color(t["fg"] if is_sel else t["sub"])
                if is_sel:
                    tick_label.set_fontweight(600)

            axd.tick_params(labelleft=False)
            axv.set_xlim(xlo_v, xhi_v)
            axv.xaxis.set_major_locator(MaxNLocator(nbins=3))
            axd.set_xlim(0.0, xhi_d)
            axd.xaxis.set_major_locator(MaxNLocator(nbins=6))
            axv.set_xlabel(MPL["V_L"])
            axd.set_xlabel(MPL["dP_pct"])

            for y, row in zip(ys, rows):
                if not row.tags:
                    continue
                tag_str = _format_tags(row.tags)
                left_dot = min(row.dP_cold_max, row.dP_hot_max) * 100.0
                if left_dot > 0.22 * xhi_d:
                    axd.annotate(
                        tag_str,
                        (left_dot, y),
                        xytext=(-9, 0),
                        textcoords="offset points",
                        ha="right",
                        va="center",
                        fontsize=10.5 * _PT,
                        color=t["accent_fg"],
                        fontweight=600,
                    )
                else:
                    right_anchor = max(
                        row.dP_cold_max * 100.0,
                        row.dP_hot_max * 100.0,
                        (row.hot_limit_frac * 100.0) if row.hot_limit_frac is not None else 0.0,
                        (row.cold_limit_frac * 100.0) if row.cold_limit_frac is not None else 0.0,
                    )
                    axd.annotate(
                        tag_str,
                        (right_anchor, y),
                        xytext=(9, 0),
                        textcoords="offset points",
                        ha="left",
                        va="center",
                        fontsize=10.5 * _PT,
                        color=t["accent_fg"],
                        fontweight=600,
                    )

            seen_topos = list(dict.fromkeys(row.topo for row in rows))
            legend_topos = [name for name in ("Diamond", "Gyroid") if name in seen_topos] + [
                name for name in seen_topos if name not in ("Diamond", "Gyroid")
            ]
            handles = [
                Line2D(
                    [],
                    [],
                    marker=_topo_marker_color(name, t)[0],
                    ls="",
                    color=_topo_marker_color(name, t)[1],
                    ms=6.0,
                    label=name,
                )
                for name in legend_topos
            ]
            handles.extend(
                [
                    Line2D([], [], marker="o", ls="", color=t["sub"], ms=5.5, label="热侧"),
                    Line2D(
                        [],
                        [],
                        marker="o",
                        ls="",
                        mfc=t["canvas"],
                        mec=t["sub"],
                        mew=1.3,
                        ms=5.5,
                        label="冷侧",
                    ),
                ]
            )
            self._figure.legend(
                handles=handles,
                loc="upper right",
                bbox_to_anchor=(1.0 - 24.0 / wp, 1.0 - 4.0 / hp),
                frameon=False,
                fontsize=11.5 * _PT,
                labelcolor=t["fg"],
                handletextpad=0.35,
                ncol=len(handles),
                columnspacing=1.4,
            )

            if self._partial_text:
                self._figure.text(
                    lab_w / wp,
                    1.0 - 20.0 / hp,
                    self._partial_text,
                    ha="left",
                    va="center",
                    fontsize=10.5 * _PT,
                    color=t["warn"],
                    fontweight=500,
                )

            self._canvas.draw_idle()

    def _draw_per_case_limits(
        self,
        axd,
        rows: Sequence[VolumeDpDesign],
        ys: np.ndarray,
        xhi_d: float,
    ) -> None:
        """Render per-row governing limits or distinct per-case limit guides."""
        t = self._tokens
        has_row_limits = any(
            row.hot_limit_frac is not None or row.cold_limit_frac is not None for row in rows
        )
        if has_row_limits:
            for y, row in zip(ys, rows):
                if row.hot_limit_frac is not None:
                    hl = row.hot_limit_frac * 100.0
                    axd.plot(
                        [hl, hl],
                        [y - 0.30, y + 0.30],
                        color=t["err"],
                        lw=1.3,
                        zorder=2.4,
                    )
                if row.cold_limit_frac is not None:
                    cl = row.cold_limit_frac * 100.0
                    axd.plot(
                        [cl, cl],
                        [y - 0.26, y + 0.26],
                        color=t["err"],
                        lw=1.0,
                        ls=(0, (2, 2)),
                        zorder=2.3,
                    )
                if row.index == self._selected_index:
                    parts: list[str] = []
                    if row.hot_limit_frac is not None:
                        cid = f" ({row.hot_case_id})" if row.hot_case_id else ""
                        parts.append(f"热上限 {val_unit(f'{row.hot_limit_frac * 100:g}', '%')}{cid}")
                    if row.cold_limit_frac is not None:
                        cid = f" ({row.cold_case_id})" if row.cold_case_id else ""
                        parts.append(f"冷上限 {val_unit(f'{row.cold_limit_frac * 100:g}', '%')}{cid}")
                    if parts:
                        axd.annotate(
                            " · ".join(parts),
                            (0.0, -0.5),
                            xytext=(2, 8),
                            textcoords="offset points",
                            ha="left",
                            va="bottom",
                            fontsize=10.0 * _PT,
                            color=t["err"],
                            annotation_clip=False,
                        )
            return

        if not self._case_limits:
            axd.annotate(
                "上限 —",
                (xhi_d, -0.5),
                xytext=(-6, -4),
                textcoords="offset points",
                ha="right",
                va="top",
                fontsize=10.5 * _PT,
                color=t["tert"],
                annotation_clip=False,
            )
            return

        # Group identical numeric limits so reference lines do not collide.
        grouped: dict[float, list[str]] = {}
        for cl in self._case_limits:
            hp = round(cl.hot_limit_frac * 100.0, 6)
            cp = round(cl.cold_limit_frac * 100.0, 6)
            if abs(hp - cp) <= 1e-6:
                grouped.setdefault(hp, []).append(f"{cl.case_id}")
            else:
                grouped.setdefault(hp, []).append(f"{cl.case_id}热")
                grouped.setdefault(cp, []).append(f"{cl.case_id}冷")

        for idx, (lim_pct, labels) in enumerate(sorted(grouped.items())):
            axd.axvline(lim_pct, color=t["err"], lw=0.85, ls=(0, (3, 3)), alpha=0.8, zorder=1)
            caption = f"{'/'.join(labels)} {val_unit(f'{lim_pct:g}', '%')}"
            axd.annotate(
                caption,
                (lim_pct, -0.5),
                xytext=(4, -4 - 13 * (idx % 2)),
                textcoords="offset points",
                ha="left",
                va="top",
                fontsize=9.8 * _PT,
                color=t["err"],
                annotation_clip=False,
            )

    def _row_at_event(self, event) -> int | None:
        if event.inaxes not in (self._axv, self._axd) or not self._rows:
            return None
        if event.ydata is None:
            return None
        idx = int(round(event.ydata))
        if 0 <= idx < len(self._rows) and abs(event.ydata - idx) <= 0.5:
            return idx
        return None

    def _on_press(self, event) -> None:
        if event.button != 1:
            return
        row_idx = self._row_at_event(event)
        if row_idx is None:
            return
        design = self._rows[row_idx]
        self._selected_index = design.index
        self._hovered_row = None
        self._redraw()
        self.design_picked.emit(design.index)

    def _on_motion(self, event) -> None:
        row_idx = self._row_at_event(event)
        self._canvas.setCursor(
            Qt.CursorShape.PointingHandCursor if row_idx is not None else Qt.CursorShape.ArrowCursor
        )
        if row_idx == self._hovered_row:
            return
        self._hovered_row = row_idx
        self._update_hover(row_idx)

    def _on_leave(self, _event) -> None:
        self._canvas.setCursor(Qt.CursorShape.ArrowCursor)
        if self._hovered_row is not None:
            self._hovered_row = None
            self._update_hover(None)

    def _update_hover(self, row_idx: int | None) -> None:
        if self._hover_annot is not None:
            self._hover_annot.remove()
            self._hover_annot = None
        if row_idx is not None and self._axd is not None:
            t = self._tokens
            row = self._rows[row_idx]
            lines = [
                f"{row.topo} · L {val_unit(f'{row.l_mm:g}', 'mm')} · t {val_unit(f'{row.t_mm:g}', 'mm')}",
                (
                    f"V {val_unit(f'{row.V_m3 * 1e3:.3f}', 'L')}   "
                    f"热/冷 {val_unit(f'{row.dP_hot_max * 100:.2f} / {row.dP_cold_max * 100:.2f}', '%')}"
                ),
            ]
            if row.hot_limit_frac is not None or row.cold_limit_frac is not None:
                lim_parts: list[str] = []
                if row.hot_limit_frac is not None:
                    cid = f" {row.hot_case_id}" if row.hot_case_id else ""
                    lim_parts.append(f"热限{cid} {val_unit(f'{row.hot_limit_frac * 100:g}', '%')}")
                if row.cold_limit_frac is not None:
                    cid = f" {row.cold_case_id}" if row.cold_case_id else ""
                    lim_parts.append(f"冷限{cid} {val_unit(f'{row.cold_limit_frac * 100:g}', '%')}")
                lines.append(" · ".join(lim_parts))
            anchor_x = max(row.dP_hot_max, row.dP_cold_max) * 100.0
            xlo, xhi = self._axd.get_xlim()
            if anchor_x > 0.55 * (xhi - xlo):
                dx, ha = -14.0, "right"
            else:
                dx, ha = 14.0, "left"
            self._hover_annot = self._axd.annotate(
                "\n".join(lines),
                (anchor_x, row_idx),
                xytext=(dx, 0),
                textcoords="offset points",
                ha=ha,
                va="center",
                multialignment="left",
                fontsize=10.0 * _PT,
                color=t["fg"],
                linespacing=1.4,
                zorder=8,
                bbox=dict(
                    boxstyle="round,pad=0.42,rounding_size=0.35",
                    fc=t["popover"],
                    ec=t["border_strong"],
                    lw=0.75,
                ),
            )
        self._canvas.draw_idle()


__all__ = ["CasePressureLimit", "VolumeDpDesign", "VolumeDpView"]
