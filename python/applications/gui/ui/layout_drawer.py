"""Geometry domain preview drawer for 2D and 3D case layouts in Style P2."""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QMessageBox

from sjtu_tpmshx.model_configs.units import CELSIUS_ZERO_K

from .symbols import MPL
from .theme import get_theme, resolve_cmap
from .vis3d_constants import field_color_limits


def _remove_thumb_axes(fig, canvas) -> None:
    for ax in getattr(canvas, "_thumb_axes", ()):
        if ax in fig.axes:
            fig.delaxes(ax)
    canvas._thumb_axes = ()


def _render_2d_thumbnail_axes(window, fig) -> bool:
    """Draw the accepted 2D temperature field below the 2D domain in physical mm."""
    result = window.cache.get_result("2d")
    if result is None:
        return False
    fields = result.fields or {}
    Ta = fields.get("Ta")
    if Ta is None:
        return False

    nx, ny = Ta.shape
    L = float(fields.get("L") or 0.0)
    H = float(fields.get("H") or 0.0)
    dx = fields.get("dx_arr")
    dy = fields.get("dy_arr")
    if dx is not None and len(dx) == nx:
        x_edges = np.concatenate(([0.0], np.cumsum(np.asarray(dx, dtype=float)) * 1000.0))
    else:
        x_edges = np.linspace(0.0, L * 1000.0 if L > 0 else float(nx), nx + 1)
    if dy is not None and len(dy) == ny:
        y_edges = np.concatenate(([0.0], np.cumsum(np.asarray(dy, dtype=float)) * 1000.0))
    else:
        y_edges = np.linspace(0.0, H * 1000.0 if H > 0 else float(ny), ny + 1)

    unit = "°C" if getattr(window, "_temp_unit", "K") == "C" else "K"
    offset = CELSIUS_ZERO_K if unit == "°C" else 0.0
    temps = [fields[k] for k in ("Ta", "Tb", "Ts") if fields.get(k) is not None]
    sync = bool(
        getattr(window, "chk_sync_colorbar_T", None)
        and window.chk_sync_colorbar_T.isChecked()
    )
    if sync and len(temps) >= 1:
        lo, hi = field_color_limits(temps, shared=True)[0]
    elif len(temps) >= 2:
        lo, hi = field_color_limits(temps[:2], shared=True)[0]
    else:
        lo, hi = field_color_limits([Ta], shared=True)[0]
    lo -= offset
    hi -= offset
    data = np.asarray(Ta, dtype=float) - offset

    theme = get_theme()
    inset = fig.add_axes([0.11, 0.10, 0.76, 0.27])
    cax = fig.add_axes([0.89, 0.10, 0.020, 0.27])
    mesh = inset.pcolormesh(
        x_edges,
        y_edges,
        data.T,
        cmap=resolve_cmap("temperature"),
        vmin=lo,
        vmax=hi,
        shading="flat",
    )
    inset.set_xlim(x_edges[0], x_edges[-1])
    inset.set_ylim(y_edges[0], y_edges[-1])
    inset.set_aspect("equal", adjustable="box")
    inset.set_facecolor(theme["ax_bg"])
    inset.set_xlabel(MPL["x_mm"], color=theme["ax_text"], fontsize=9)
    inset.set_ylabel(MPL["y_mm"], color=theme["ax_text"], fontsize=9)
    inset.tick_params(colors=theme["ax_text"], labelsize=8.5)
    inset.set_title(
        "上次结果 · 流体 A",
        loc="left",
        color=theme["sub"],
        fontsize=9.5,
        pad=4,
    )
    inset.set_title(
        f"{MPL['T_fA']} [{unit}]",
        loc="right",
        color=theme["sub"],
        fontsize=9.5,
        pad=4,
    )
    for sp in inset.spines.values():
        sp.set_edgecolor(theme["border_strong"])
        sp.set_linewidth(0.8)

    cb = fig.colorbar(mesh, cax=cax)
    cb.ax.tick_params(colors=theme["ax_text"], labelsize=8)
    cb.outline.set_edgecolor(theme["border_strong"])
    cb.outline.set_linewidth(0.7)
    window.canvas_layout._thumb_axes = (inset, cax)
    return True


def _draw_last_2d_thumbnail(window) -> None:
    """Position the 2D domain and render the accepted 2D temperature thumbnail below it."""
    canvas = window.canvas_layout
    fig = canvas.fig
    _remove_thumb_axes(fig, canvas)
    if _render_2d_thumbnail_axes(window, fig):
        main_ax = canvas.axes[0][0] if getattr(canvas, "axes", None) else None
        if main_ax is not None:
            main_ax.set_position([0.11, 0.49, 0.76, 0.41])


def refresh_last_2d_thumbnail(window) -> None:
    """Refresh only the 2D accepted-result thumbnail without reading draft inputs."""
    canvas = getattr(window, "canvas_layout", None)
    if canvas is None or getattr(canvas, "_layout_mode", None) != "2d":
        return
    fig = canvas.fig
    _remove_thumb_axes(fig, canvas)
    main_ax = canvas.axes[0][0] if getattr(canvas, "axes", None) else None
    if _render_2d_thumbnail_axes(window, fig):
        if main_ax is not None:
            main_ax.set_position([0.11, 0.49, 0.76, 0.41])
    elif main_ax is not None:
        main_ax.set_position([0.11, 0.14, 0.80, 0.76])
    canvas.draw_idle()


def draw_layout(window, *, switch_tab: bool = True):
    """Draw geometry: 2D rectangle or 3D cuboid wireframe based on active dimension."""
    try:
        L = float(window.le_L.text())
        H = float(window.le_H.text())
    except ValueError:
        QMessageBox.warning(window, "输入错误", "请先填写计算域长度和横向尺寸。")
        return

    window.canvas_layout._preview_axes = None
    window.canvas_layout._thumb_axes = ()
    window.canvas_layout.fig.clear()
    Lmm, Hmm = L * 1000, H * 1000
    theme = get_theme()

    is_3d = hasattr(window, "combo_dim") and window.combo_dim.currentIndex() == 1
    if is_3d:
        try:
            Lz = float(window.le_Lz.text())
        except ValueError:
            QMessageBox.warning(window, "输入错误", "请先填写计算域厚度 Lz。")
            return
        window.canvas_layout._layout_mode = "3d"
        ax = window.canvas_layout.fig.add_subplot(111, projection="3d")
        window.canvas_layout.axes = [[ax]]
        window.canvas_layout._preview_axes = ax
        window.canvas_layout.setToolTip("左键拖动旋转；滚轮缩放")
        from .port_preview_3d import draw_layout_rect_3d

        draw_layout_rect_3d(window, ax, L, H, Lz)
        ax.set_facecolor(theme["fig_bg"])
    else:
        canvas = window.canvas_layout
        canvas._layout_mode = "2d"
        if hasattr(canvas, "_orig_wheel_event"):
            canvas.wheelEvent = canvas._orig_wheel_event
        ax = canvas.fig.add_subplot(111)
        window.canvas_layout.axes = [[ax]]
        draw_layout_rect(window, ax, L, H, Lmm, Hmm)
        ax.set_xlabel(MPL["x_mm"], color=theme["ax_text"])
        ax.set_ylabel(MPL["y_mm"], color=theme["ax_text"])
        ax.set_aspect("equal")
        ax.set_facecolor(theme["ax_bg"])
        ax.tick_params(colors=theme["ax_text"])
        for sp in ax.spines.values():
            sp.set_edgecolor(theme["ax_spine"])
        _draw_last_2d_thumbnail(window)

    window.canvas_layout.fig.set_facecolor(theme["fig_bg"])
    window.cache.mark_drawn("layout")
    if hasattr(window, "btn_export"):
        window.btn_export.setEnabled(True)
    if switch_tab:
        window.workbench.switch_tab("layout")
    from PySide6.QtCore import QTimer

    QTimer.singleShot(0, window.canvas_layout, window.canvas_layout.draw_idle)


def draw_layout_rect(window, ax, L, H, Lmm, Hmm):
    """Draw the 2D computational domain, ports, arrows, and optional zones."""
    theme = get_theme()
    from matplotlib.patches import Rectangle

    try:
        cfgA = window._fluid_config("A")
        cfgB = window._fluid_config("B")
    except ValueError:
        cfgA = dict(dir=0, in_ctr=H / 2, in_w=H, out_ctr=H / 2, out_w=H)
        cfgB = dict(dir=3, in_ctr=L / 2, in_w=L, out_ctr=L / 2, out_w=L)

    ax.add_patch(Rectangle((0, 0), Lmm, Hmm, fill=False, ec=theme["ax_text"], lw=1.8))

    def _draw_pipe(cfg, label, color, is_inlet):
        d = cfg["dir"]
        ctr = (cfg["in_ctr"] if is_inlet else cfg["out_ctr"]) * 1000
        w = (cfg["in_w"] if is_inlet else cfg["out_w"]) * 1000
        lo = ctr - w / 2
        wall = window._inlet_wall(d) if is_inlet else window._outlet_wall(d)
        tag = f"{label} {'入口' if is_inlet else '出口'}"
        if wall == "left":
            ax.add_patch(Rectangle((-1.5, lo), 1.2, w, fc=color, ec="none", alpha=0.85))
            ax.annotate(
                tag, xy=(3.5, ctr), fontsize=8, color=color, ha="left", va="center", fontweight="bold"
            )
        elif wall == "right":
            ax.add_patch(Rectangle((Lmm + 0.3, lo), 1.2, w, fc=color, ec="none", alpha=0.85))
            ax.annotate(
                tag, xy=(Lmm - 3.5, ctr), fontsize=8, color=color, ha="right", va="center", fontweight="bold"
            )
        elif wall == "bottom":
            ax.add_patch(Rectangle((lo, -1.5), w, 1.2, fc=color, ec="none", alpha=0.85))
            ax.annotate(
                tag, xy=(ctr, -3.5), fontsize=8, color=color, ha="center", va="top", fontweight="bold"
            )
        else:
            ax.add_patch(Rectangle((lo, Hmm + 0.3), w, 1.2, fc=color, ec="none", alpha=0.85))
            ax.annotate(
                tag, xy=(ctr, Hmm + 3.5), fontsize=8, color=color, ha="center", va="bottom", fontweight="bold"
            )

    _draw_pipe(cfgA, "A", theme["inlet_color"], True)
    _draw_pipe(cfgA, "A", theme["inlet_color"], False)
    _draw_pipe(cfgB, "B", theme["outlet_color"], True)
    _draw_pipe(cfgB, "B", theme["outlet_color"], False)

    cx, cy = Lmm / 2, Hmm / 2

    def _arrow(d, color):
        dx = Lmm * 0.2
        dy = Hmm * 0.2
        arrows = {
            0: (cx - dx, cy, cx + dx, cy),
            1: (cx + dx, cy, cx - dx, cy),
            2: (cx, cy - dy, cx, cy + dy),
            3: (cx, cy + dy, cx, cy - dy),
        }
        x0, y0, x1, y1 = arrows[d]
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0), arrowprops=dict(arrowstyle="->", color=color, lw=1.5))

    _arrow(cfgA["dir"], theme["inlet_color"])
    _arrow(cfgB["dir"], theme["outlet_color"])

    if window.chk_zones.isChecked():
        z_ax = window._zone_axis()
        ncols = window.zone_table.columnCount()
        if z_ax == "grid":
            for r in range(window.zone_table.rowCount()):
                items = [window.zone_table.item(r, c) for c in range(ncols)]
                if any(it is None or not it.text().strip() for it in items):
                    continue
                yf0 = float(items[0].text()) / 100
                yf1 = float(items[1].text()) / 100
                xf0 = float(items[2].text()) / 100
                xf1 = float(items[3].text()) / 100
                x0, x1 = xf0 * Lmm, xf1 * Lmm
                y0, y1 = yf0 * Hmm, yf1 * Hmm
                alpha = 0.08 if r % 2 == 0 else 0.15
                ax.add_patch(
                    Rectangle((x0, y0), x1 - x0, y1 - y0, fc=theme["zone_fill"], ec=theme["zone_fill"], alpha=alpha, lw=0.5)
                )
                ax.text(
                    (x0 + x1) / 2,
                    (y0 + y1) / 2,
                    f"{items[4].text()}/{items[5].text()}",
                    color=theme["zone_fill"],
                    fontsize=6,
                    ha="center",
                    va="center",
                    alpha=0.85,
                )
        else:
            for r in range(window.zone_table.rowCount()):
                items = [window.zone_table.item(r, c) for c in range(4)]
                if any(it is None or not it.text().strip() for it in items):
                    continue
                f0 = float(items[0].text()) / 100
                f1 = float(items[1].text()) / 100
                L_z, t_z = items[2].text(), items[3].text()
                alpha = 0.08 if r % 2 == 0 else 0.15
                if z_ax == "y":
                    p0, p1 = f0 * Hmm, f1 * Hmm
                    ax.add_patch(Rectangle((0, p0), Lmm, p1 - p0, fc=theme["zone_fill"], ec="none", alpha=alpha))
                    ax.text(
                        Lmm * 0.95,
                        (p0 + p1) / 2,
                        f"L={L_z} t={t_z}",
                        color=theme["zone_fill"],
                        fontsize=6,
                        va="center",
                        ha="right",
                        alpha=0.9,
                    )
                    if f0 > 0.001:
                        ax.axhline(y=p0, color=theme["zone_fill"], ls="--", lw=0.8, alpha=0.6)
                else:
                    p0, p1 = f0 * Lmm, f1 * Lmm
                    ax.add_patch(Rectangle((p0, 0), p1 - p0, Hmm, fc=theme["zone_fill"], ec="none", alpha=alpha))
                    ax.text(
                        (p0 + p1) / 2,
                        Hmm * 0.05,
                        f"L={L_z}\nt={t_z}",
                        color=theme["zone_fill"],
                        fontsize=6,
                        va="bottom",
                        ha="center",
                        alpha=0.9,
                    )
                    if f0 > 0.001:
                        ax.axvline(x=p0, color=theme["zone_fill"], ls="--", lw=0.8, alpha=0.6)

    zmgr = getattr(window, "_zone_handle_mgr", None)
    if zmgr is not None:
        try:
            zmgr.draw_handles(ax, Lmm, Hmm)
        except Exception:
            pass
    ax.set_xlim(-8, Lmm + 8)
    ax.set_ylim(-8, Hmm + 8)
    ax.set_title("计算域", color=theme["ax_text"], fontsize=11, fontweight="bold")
