"""Matplotlib canvas for SJTU-TPMSHX result visualization.

Extracted from main.py (Task B.2). Figures use the active theme tokens.
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from .theme import FIELD_CMAP, get_theme


def cell_index_mm(position_mm, widths_m):
    """Locate a physical point in a cell, clamping at the domain edges."""
    index = np.searchsorted(np.cumsum(widths_m), position_mm / 1000., side='right')
    return int(np.clip(index, 0, len(widths_m) - 1))


# ── Contour edge-fill helper ──────────────────────────────────
def pad_field_to_edges(x_mm, y_mm, field, L_mm, H_mm):
    """Extend cell-center coords + field to the domain boundary so contourf
    fills the full [0, L]×[0, H] frame instead of leaving a half-cell blank
    margin around the data (UI report point 2, 2026-05-22).

    The result panels build coords as ``x = cumsum(dx) - dx/2`` (cell
    centres), so contourf only paints between centres and the dark axis
    background shows through a ~half-cell border — most visible at corners.
    Here the boundary nodes (0 and L/H) are prepended/appended and the edge
    cell values replicated outward (mode='edge'). Display-only: solver data
    is untouched. ``field`` is (Nx, Ny) to match ``meshgrid(y, x)`` → (X, Y)
    with X varying along axis 0. Returns (X, Y, F) ready for ax.contourf."""
    xp = np.concatenate(([0.0], np.asarray(x_mm, float), [float(L_mm)]))
    yp = np.concatenate(([0.0], np.asarray(y_mm, float), [float(H_mm)]))
    Fp = np.pad(np.asarray(field, float), ((1, 1), (1, 1)), mode='edge')
    Yp, Xp = np.meshgrid(yp, xp)
    return Xp, Yp, Fp


def style_field_axes(ax, cb, _t, main_title, subtitle):
    """Shared temperature/pressure axes, colorbar and title formatting."""
    cb.ax.tick_params(labelsize=8, colors=_t['ax_text'], length=3)
    cb.ax.yaxis.set_major_locator(plt.MaxNLocator(nbins=7))
    cb.outline.set_edgecolor(_t['ax_spine'])
    # Inline title
    ax.set_title(main_title, fontsize=13, fontweight="bold",
                 color=_t['ax_text'], loc='left', pad=6)
    ax.text(0.99, 1.02, subtitle, transform=ax.transAxes,
            fontsize=9, color=_t['mpl_subtitle'], ha='right', va='bottom',
            fontstyle='italic')
    ax.set_xlabel("x [mm]", fontsize=10, color=_t['ax_text'])
    ax.set_ylabel("y [mm]", fontsize=10, color=_t['ax_text'])
    ax.tick_params(labelsize=9, colors=_t['ax_text'], length=4, width=0.8)
    ax.set_aspect('auto')
    ax.grid(True, alpha=0.12, linewidth=0.4, color=_t['ax_text'])
    for spine in ax.spines.values():
        spine.set_edgecolor(_t['ax_spine']); spine.set_linewidth(0.8)


# ── Matplotlib canvas ─────────────────────────────────────────
class MatplotlibCanvas(FigureCanvas):
    def __init__(self, nrows=1, ncols=3, figsize=(15, 4.5)):
        # Use Figure() directly instead of plt.subplots() so the figure is
        # NOT registered with pyplot's global figure manager (Gcf). pyplot
        # registration would keep the figure alive for the lifetime of the
        # process even after this canvas is destroyed (theme switch / window
        # close), pinning ~MB of cached arrays per figure. — 2026-04-29
        self.fig = Figure(figsize=figsize)
        axes_raw = self.fig.subplots(nrows, ncols)
        _t = get_theme()
        self.fig.patch.set_facecolor(_t['fig_bg'])
        # Normalise to 2-D list [[ax, ...], ...]
        if nrows == 1 and ncols == 1:
            self.axes = [[axes_raw]]
        elif nrows == 1:
            self.axes = [list(axes_raw)]
        elif ncols == 1:
            self.axes = [[ax] for ax in axes_raw]
        else:
            self.axes = [list(r) for r in axes_raw]
        for row in self.axes:
            for ax in row:
                ax.set_facecolor(_t['ax_bg'])
        super().__init__(self.fig)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Qt sizes are whole pixels. The inches→pixels round trip can land
        # just below one (953 becomes 952.9999999999999), and Agg truncates
        # it, leaving a stale one-pixel edge when Qt paints the full widget.
        pixels = np.array([event.size().width(), event.size().height()])
        inches = pixels * self.device_pixel_ratio / self.figure.dpi
        self.figure.set_size_inches(np.nextafter(inches, np.inf), forward=False)

    def plot_pressure(self, P_fA, P_fB, N_x, N_y, L, H, mode="",
                       dx_arr=None, dy_arr=None):
        _t = get_theme()
        from matplotlib.gridspec import GridSpec

        self.fig.clear()
        self.fig.patch.set_facecolor(_t['fig_bg'])

        # 2 pressure cloud plots only. The "Pressure Drop Summary" card and the
        gs = GridSpec(2, 1, figure=self.fig, height_ratios=[1, 1],
                      hspace=0.32, left=0.08, right=0.93, top=0.94, bottom=0.08)

        _dx = dx_arr if dx_arr is not None else np.full(N_x, L / N_x)
        _dy = dy_arr if dy_arr is not None else np.full(N_y, H / N_y)
        x = (np.cumsum(_dx) - _dx / 2) * 1000
        y = (np.cumsum(_dy) - _dy / 2) * 1000

        axes_p = [self.fig.add_subplot(gs[0]), self.fig.add_subplot(gs[1])]
        self.axes = [axes_p]

        p_data = [
            (P_fA, r"$P_A$  [Pa]", "Fluid A"),
            (P_fB, r"$P_B$  [Pa]", "Fluid B"),
        ]
        _Lmm, _Hmm = L * 1000.0, H * 1000.0
        for ax, (field, main_title, subtitle) in zip(axes_p, p_data):
            ax.set_facecolor(_t['ax_bg'])
            _Xp, _Yp, _Fp = pad_field_to_edges(x, y, field, _Lmm, _Hmm)
            cf = ax.contourf(_Xp, _Yp, _Fp, levels=256, cmap=FIELD_CMAP)
            ax.set_xlim(0, _Lmm); ax.set_ylim(0, _Hmm)
            cb = self.fig.colorbar(cf, ax=ax, shrink=0.9, aspect=25, format="%.0f")
            style_field_axes(ax, cb, _t, main_title, subtitle)

        # Scalar pressure drop lives in the result footer.
        _ = mode

        self.draw()
