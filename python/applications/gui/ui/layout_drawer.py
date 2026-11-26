"""Geometry domain preview drawer for 2D and 3D case layouts in Style P2."""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from .symbols import MPL
from .theme import get_theme, resolve_cmap


def _draw_last_2d_thumbnail(window) -> None:
    """Render a compact 2D temperature thumbnail inset when a 2D result is cached."""
    result = window.cache.get_result("2d")
    if result is None:
        return
    Ta = result.fields.get("Ta")
    if Ta is None:
        return
    theme = get_theme()
    fig = window.canvas_layout.fig
    fig.subplots_adjust(top=0.92, bottom=0.34)
    inset = fig.add_axes([0.70, 0.04, 0.24, 0.20])
    inset.imshow(
        Ta.T,
        origin="lower",
        aspect="auto",
        cmap=resolve_cmap("temperature"),
    )
    inset.set_xticks([])
    inset.set_yticks([])
    inset.set_title("上次结果", color=theme["sub"], fontsize=8.5, pad=3)
    for sp in inset.spines.values():
        sp.set_edgecolor(theme["border_strong"])
        sp.set_linewidth(0.8)


def draw_layout(window, *, switch_tab: bool = True):
    """Draw geometry: 2D rectangle or 3D cuboid wireframe based on active dimension."""
    try:
        L = float(window.le_L.text())
        H = float(window.le_H.text())
    except ValueError:
        QMessageBox.warning(window, "输入错误", "请先填写计算域长度和横向尺寸。")
        return

    window.canvas_layout._preview_axes = None
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
        ax = window.canvas_layout.fig.add_subplot(111, projection="3d")
        window.canvas_layout.axes = [[ax]]
        window.canvas_layout._preview_axes = ax
        window.canvas_layout.setToolTip("左键拖动旋转；滚轮缩放")
        from .port_preview_3d import draw_layout_rect_3d

        draw_layout_rect_3d(window, ax, L, H, Lz)
        ax.set_facecolor(theme["fig_bg"])
    else:
        canvas = window.canvas_layout
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
                tag, xy=(-3, ctr), fontsize=8, color=color, ha="right", va="center", fontweight="bold"
            )
        elif wall == "right":
            ax.add_patch(Rectangle((Lmm + 0.3, lo), 1.2, w, fc=color, ec="none", alpha=0.85))
            ax.annotate(
                tag, xy=(Lmm + 3, ctr), fontsize=8, color=color, ha="left", va="center", fontweight="bold"
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

    ax.text(cx, cy, "计算域", color=theme["ax_text"], ha="center", va="center", fontsize=10, fontweight="bold", alpha=0.28)

    zmgr = getattr(window, "_zone_handle_mgr", None)
    if zmgr is not None:
        try:
            zmgr.draw_handles(ax, Lmm, Hmm)
        except Exception:
            pass
    ax.set_xlim(-8, Lmm + 8)
    ax.set_ylim(-8, Hmm + 8)
    ax.set_title("计算域", color=theme["ax_text"], fontsize=11, fontweight="bold")
