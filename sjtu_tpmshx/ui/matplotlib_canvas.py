"""Matplotlib canvas for SJTU-TPMSHX result visualization.

Extracted from main.py (Task B.2). Light-only as of D-1 (dark mode and
the runtime toggle were removed; `_current_theme` and `_dp_card_colors`
went away with apply_theme).
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.ticker import FormatStrFormatter
from .theme import get_theme


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


# ── Axis label helper ─────────────────────────────────────────
def _label_axes(axes, L, H, mode=""):
    _t = get_theme()
    # Determine arrow directions from mode string like "A:+x B:-y"
    dir_arrows = {'+x': r'\rightarrow', '-x': r'\leftarrow',
                  '+y': r'\uparrow',    '-y': r'\downarrow'}
    a_arrow = r'\rightarrow'; b_arrow = r'\leftarrow'
    if mode:
        for key, arrow in dir_arrows.items():
            if f"A:{key}" in mode: a_arrow = arrow
            if f"B:{key}" in mode: b_arrow = arrow
    titles = [
        r"$T_{f,A}$ [K] — Fluid A ($" + a_arrow + r"$)",
        r"$T_{f,B}$ [K] — Fluid B ($" + b_arrow + r"$)",
        r"$T_s$ [K] — Solid",
    ]
    for ax, title in zip(axes, titles):
        ax.set_title(title, fontsize=11, fontweight="bold", color=_t['ax_text'], pad=6)
        ax.set_xlabel(r"$x$ [m]", fontsize=10, color=_t['ax_text'])
        ax.set_ylabel(r"$y$ [m]", fontsize=10, color=_t['ax_text'],
                      rotation=90, labelpad=4)
        ax.tick_params(labelsize=9, colors=_t['ax_text'])
        ax.xaxis.set_major_formatter(FormatStrFormatter("%.3f"))
        ax.yaxis.set_major_formatter(FormatStrFormatter("%.3f"))
        for spine in ax.spines.values():
            spine.set_edgecolor(_t['ax_spine'])


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
        self.X = self.Y = self.L = self.H = self.mode = None
        self.min_temp = self.max_temp = None
        self.min_s    = self.max_s    = None
        self.time_text = None

    def plot_zones(self, zones, dx, dy, mode=""):
        """Plot 3×3 grid: rows = Fluid A / Fluid B / Solid, cols = inlet / uniform / outlet.

        Parameters
        ----------
        zones : dict with keys like 'TfA_in', 'TfA_uni', 'TfA_out', etc.
                Each value is a 2D array or None.
        """
        _t = get_theme()
        self.fig.clear()
        axes = self.fig.subplots(3, 3)
        self.axes = [list(r) for r in axes]
        self.fig.patch.set_facecolor(_t['fig_bg'])

        row_labels = ['Fluid A', 'Fluid B', 'Solid']
        col_labels = ['Inlet Trans.', 'Uniform Zone', 'Outlet Trans.']
        field_keys = [
            ['TfA_in', 'TfA_uni', 'TfA_out'],
            ['TfB_in', 'TfB_uni', 'TfB_out'],
            ['Ts_in',  'Ts_uni',  'Ts_out'],
        ]

        # Global colour range for fluid fields
        all_f = [zones.get(k) for row in field_keys[:2] for k in row if zones.get(k) is not None]
        if all_f:
            vmin_f = min(f.min() for f in all_f)
            vmax_f = max(f.max() for f in all_f)
        else:
            vmin_f, vmax_f = 300, 400

        for r in range(3):
            for c in range(3):
                ax = self.axes[r][c]
                ax.set_facecolor(_t['ax_bg'])
                key = field_keys[r][c]
                field = zones.get(key)
                if field is None or field.size == 0:
                    ax.text(0.5, 0.5, 'N/A', color='grey', ha='center', va='center',
                            transform=ax.transAxes, fontsize=12)
                    ax.set_xticks([]); ax.set_yticks([])
                else:
                    Nxf, Nyf = field.shape
                    x = np.linspace(0, Nxf * dx * 1000, Nxf)
                    y = np.linspace(0, Nyf * dy * 1000, Nyf)
                    Y, X = np.meshgrid(y, x)
                    if r < 2:  # fluid
                        # levels=256 = turbo's full 256-colour LUT (128 under-
                        # sampled it by half); still half the wasteful 512
                        # (2026-05-20 perf note) so banding is finer, not slower.
                        kw = dict(levels=256, cmap='turbo', vmin=vmin_f, vmax=vmax_f)
                    else:      # solid — unified turbo for cross-field parity
                        kw = dict(levels=256, cmap='turbo')
                    try:
                        cf = ax.contourf(X, Y, field, **kw)
                        cb = self.fig.colorbar(cf, ax=ax, shrink=0.8, aspect=15, format="%.0f")
                        cb.ax.tick_params(labelsize=6, colors=_t['ax_text'])
                    except Exception:
                        pass
                    ax.set_xlabel("x [mm]", fontsize=7, color=_t['ax_text'])
                    ax.set_ylabel("y [mm]", fontsize=7, color=_t['ax_text'])
                    ax.tick_params(labelsize=6, colors=_t['ax_text'])

                # Titles
                if r == 0:
                    ax.set_title(col_labels[c], fontsize=9, fontweight="bold",
                                 color=_t['ax_text'], pad=4)
                if c == 0:
                    ax.annotate(row_labels[r], xy=(-0.35, 0.5),
                                xycoords='axes fraction', fontsize=9,
                                fontweight='bold', color=_t['ax_text'],
                                ha='center', va='center', rotation=90)

                for spine in ax.spines.values():
                    spine.set_edgecolor(_t['ax_spine'])

        self.fig.subplots_adjust(left=0.08, right=0.95, top=0.90, bottom=0.06,
                                 wspace=0.40, hspace=0.35)
        self.fig.text(0.5, 0.96, f"Temperature Fields  |  {mode}",
                      ha="center", fontsize=11, fontweight="bold", color=_t['ax_text'])
        self.draw()

    def plot_temperature(self, T_fA, T_fB, T_s,
                         dx, dy, N_t, N_x, N_y, L, H, dt, mode="Counterflow"):
        _t = get_theme()
        self.fig.clear()
        self.axes = [self.fig.subplots(1, 3)]
        self.fig.patch.set_facecolor(_t['fig_bg'])
        self.L, self.H, self.mode = L, H, mode

        self.min_temp = min(T_fA.min(), T_fB.min())
        self.max_temp = max(T_fA.max(), T_fB.max())
        self.min_s    = T_s.min()
        self.max_s    = T_s.max()

        x = np.linspace(0, L, N_x)
        y = np.linspace(0, H, N_y)
        self.Y, self.X = np.meshgrid(y, x)

        kw_f = dict(levels=256, cmap="turbo", vmin=self.min_temp, vmax=self.max_temp)
        kw_s = dict(levels=256, cmap="turbo", vmin=self.min_s,    vmax=self.max_s)

        datasets = [
            (T_fA[-1], r"$T_{f,A}$ [K] — Fluid A", kw_f),
            (T_fB[-1], r"$T_{f,B}$ [K] — Fluid B", kw_f),
            (T_s[-1],  r"$T_s$ [K] — Solid",        kw_s),
        ]
        for ax, (field, title, kw) in zip(self.axes[0], datasets):
            ax.set_facecolor(_t['ax_bg'])
            cf = ax.contourf(self.X, self.Y, field, **kw)
            cb = self.fig.colorbar(cf, ax=ax, shrink=0.85, aspect=18, format="%.1f")
            cb.ax.tick_params(labelsize=7.5, colors=_t['ax_text'])
            cb.ax.yaxis.label.set_color(_t['ax_text'])
            for spine in ax.spines.values():
                spine.set_edgecolor(_t['ax_spine'])

        _label_axes(self.axes[0], L, H, mode)
        self.fig.subplots_adjust(left=0.05, right=0.95, top=0.88, bottom=0.10, wspace=0.38)
        self.time_text = self.fig.text(
            0.5, 0.95, rf"$t = {dt * (N_t - 1):.4f}$ s  (steady state)",
            ha="center", fontsize=13, fontweight="bold", color=_t['ax_text'])
        self.draw()

    def plot_pressure(self, P_fA, P_fB, N_x, N_y, L, H, mode="",
                       dx_arr=None, dy_arr=None):
        _t = get_theme()
        from matplotlib.gridspec import GridSpec

        self.fig.clear()
        self.fig.patch.set_facecolor(_t['fig_bg'])

        # 2 pressure cloud plots only. The "Pressure Drop Summary" card and the
        # SIMPLE convergence mini-plot were removed for the 2D view: dP is
        # already shown in the top KPI strip and the residual trace was clutter.
        # dP_A/B + residuals_A/B stay in the signature for call-site stability.
        gs = GridSpec(2, 1, figure=self.fig, height_ratios=[1, 1],
                      hspace=0.32, left=0.08, right=0.93, top=0.94, bottom=0.08)

        _dx = dx_arr if dx_arr is not None else np.full(N_x, L / N_x)
        _dy = dy_arr if dy_arr is not None else np.full(N_y, H / N_y)
        x = (np.cumsum(_dx) - _dx / 2) * 1000
        y = (np.cumsum(_dy) - _dy / 2) * 1000
        Y, X = np.meshgrid(y, x)

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
            cf = ax.contourf(_Xp, _Yp, _Fp, levels=256, cmap="turbo")
            ax.set_xlim(0, _Lmm); ax.set_ylim(0, _Hmm)
            cb = self.fig.colorbar(cf, ax=ax, shrink=0.9, aspect=25, format="%.0f")
            style_field_axes(ax, cb, _t, main_title, subtitle)

        # (Pressure Drop Summary card + SIMPLE convergence mini-plot deleted
        # from the 2D pressure view. dP is shown in the top KPI strip; SIMPLE
        # residuals are still tracked by the solver for convergence/bootstrap,
        # just no longer plotted here.)
        _ = mode

        self.draw()
