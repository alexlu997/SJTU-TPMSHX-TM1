"""ui/plot_2d_results.py — 2D compute-result rendering for SJTU-TPMSHX.

Extracted from ``runs/run_calculation.py`` in batch-3 (2026-06-13), mirroring
``ui/plot_3d_results.py``: holds the matplotlib canvas population for the
temperature / pressure / velocity tabs so the compute stage module
(``preprocess/two_d/preparation.py``) stays Qt/matplotlib-free.

Public entry points (consumed by ``ui.mixins.run_controller`` and ``main``):
    finalize_plots(window)          — render all 2D result canvases (main thread)
    redraw_temperature_panel(window)— re-render temperature tab from cache
    plot_temperature_3panel(window, r, _t) — the shared T_fA/T_fB/T_s helper
"""
import numpy as np
import matplotlib.pyplot as plt


def plot_temperature_3panel(window, r, _t):
    """Render the 3-row T_fA / T_fB / T_s contour panel on canvas_temp.

    Honours `window.chk_sync_colorbar_T` — when checked, all three panels
    share the global vmin/vmax so a colour has the same temperature meaning
    across fluids and solid. When off, fluids share vmin/vmax and solid
    auto-scales independently (the pre-toggle behaviour).
    """
    Ta, Tb, Ts = r['Ta'], r['Tb'], r['Ts']
    N_x, N_y, L, H = r['N_x'], r['N_y'], r['L'], r['H']

    window.canvas_temp.fig.clear()
    axes = window.canvas_temp.fig.subplots(3, 1)
    window.canvas_temp.axes = [list(axes)]
    window.canvas_temp.fig.patch.set_facecolor(_t['fig_bg'])

    _dx = r.get('dx_arr', np.full(N_x, L / N_x))
    _dy = r.get('dy_arr', np.full(N_y, H / N_y))
    x = (np.cumsum(_dx) - _dx / 2) * 1000
    y = (np.cumsum(_dy) - _dy / 2) * 1000
    Y, X = np.meshgrid(y, x)

    _sync = True
    try:
        _sync = bool(window.chk_sync_colorbar_T.isChecked())
    except Exception:
        pass
    if _sync:
        v_all_min = float(min(Ta.min(), Tb.min(), Ts.min()))
        v_all_max = float(max(Ta.max(), Tb.max(), Ts.max()))
        vmin_f, vmax_f = v_all_min, v_all_max
        vmin_s, vmax_s = v_all_min, v_all_max
    else:
        vmin_f = min(Ta.min(), Tb.min()); vmax_f = max(Ta.max(), Tb.max())
        vmin_s, vmax_s = None, None

    plot_items = [
        (Ta, r"$T_{f,A}$  [K]", "Fluid A"),
        (Tb, r"$T_{f,B}$  [K]", "Fluid B"),
        (Ts, r"$T_s$  [K]", "Solid"),
    ]
    for ax, (field, main_title, subtitle) in zip(axes, plot_items):
        ax.set_facecolor(_t['ax_bg'])
        if 'T_s' in main_title:
            # T_s uses turbo to match fluid T_a/T_b + 3D volume — all physics
            # fields share the same modern-rainbow LUT for cross-plot parity.
            # levels=128 (was 512): see 2026-05-20 UI sweep note in
            # run_calculation_3d.py — 512 over-samples turbo's 256-colour
            # LUT and quadruples contour triangulation cost.
            kw = dict(levels=128, cmap='turbo')
            if vmin_s is not None:
                kw.update(vmin=vmin_s, vmax=vmax_s)
        else:
            kw = dict(levels=128, cmap='turbo', vmin=vmin_f, vmax=vmax_f)
        from sjtu_tpmshx.ui.matplotlib_canvas import pad_field_to_edges, style_field_axes
        _Xp, _Yp, _Fp = pad_field_to_edges(x, y, field, L * 1000.0, H * 1000.0)
        cf = ax.contourf(_Xp, _Yp, _Fp, **kw)
        ax.set_xlim(0, L * 1000.0); ax.set_ylim(0, H * 1000.0)
        cb = window.canvas_temp.fig.colorbar(cf, ax=ax, shrink=0.9,
                                              aspect=25, format="%.0f")
        style_field_axes(ax, cb, _t, main_title, subtitle)
        if hasattr(window, '_zone_boundaries') and window._zone_boundaries:
            z_dir = getattr(window, '_zone_axis_dir', 'y')
            for b in window._zone_boundaries:
                if z_dir == 'y':
                    ax.axhline(y=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
                else:
                    ax.axvline(x=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
        for b in (getattr(window, '_zone_boundaries_x', None) or []):
            ax.axvline(x=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
        for b in (getattr(window, '_zone_boundaries_y', None) or []):
            ax.axhline(y=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)

    window.canvas_temp.fig.subplots_adjust(left=0.08, right=0.93,
                                            top=0.96, bottom=0.06, hspace=0.34)
    window.canvas_temp.draw()
    window.canvas_temp._hover_data = {
        'fields': [Ta, Tb, Ts],
        'names': ['T_fA', 'T_fB', 'T_s'],
        'unit': 'K',
        'L': L, 'H': H, 'Nx': N_x, 'Ny': N_y,
        'dx_arr': _dx, 'dy_arr': _dy,
    }


def redraw_temperature_panel(window):
    """Re-render the temperature tab using the last stored compute result.
    No-op if nothing has been computed yet."""
    r = getattr(window, '_compute_results', None)
    if r is None:
        return
    from sjtu_tpmshx.ui.theme import get_theme
    plot_temperature_3panel(window, r, get_theme())


def finalize_plots(window):
    """Ex-Main_Menu._finalize_plots(self). Render plots from stored results.
    MUST run on main thread."""
    from sjtu_tpmshx.ui.theme import get_theme
    _t = get_theme()

    if getattr(window, '_compute_warnings', None):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(
            window, "Solver Warnings",
            "\n\n".join(window._compute_warnings))
        window._compute_warnings = None
    r = window._compute_results
    # N5 (2026-07-07): prefer the display-smoothed copies on partial-BC runs;
    # the physics keys ('ucA' …) now stay raw / mass-conserving.
    def _vel(key):
        disp = r.get(key + '_disp')
        return disp if disp is not None else r[key]
    ucA, vcA, ucB, vcB = _vel('ucA'), _vel('vcA'), _vel('ucB'), _vel('vcB')
    P_fA, P_fB = r['P_fA'], r['P_fB']
    dP_A, dP_B = r['dP_A'], r['dP_B']
    N_x, N_y, L, H = r['N_x'], r['N_y'], r['L'], r['H']
    dir_A, dir_B = r['dir_A'], r['dir_B']

    dir_flow_A = window._DIR_MAP[dir_A]
    dir_flow_B = window._DIR_MAP[dir_B]

    window._r_dP_A.setText(f"{dP_A:.1f}")
    window._r_dP_B.setText(f"{dP_B:.1f}")
    window._r_Q.setText(f"{r.get('Q_total', 0):.1f}")

    mode_label = f"A:{dir_flow_A} B:{dir_flow_B}"

    # Temperature: vertical 3×1 plot (Fluid A, Fluid B, Solid) — delegated
    # to a module-level helper so the K/°C sync toggle can redraw without
    # re-running the full finalize pipeline.
    plot_temperature_3panel(window, r, _t)
    # Hover data cached by helper; the rest of this function handles
    # pressure, velocity, and layout panels. Preserve original variable
    # bindings for code below.
    _dx = r.get('dx_arr', np.full(N_x, L / N_x))
    _dy = r.get('dy_arr', np.full(N_y, H / N_y))
    x = (np.cumsum(_dx) - _dx / 2) * 1000
    y = (np.cumsum(_dy) - _dy / 2) * 1000
    Y, X = np.meshgrid(y, x)
    _sub = _t['mpl_subtitle']

    # Pressure plot — clouds only (dP shown in the KPI strip; the summary card
    # + SIMPLE convergence plot were removed from this tab).
    window.canvas_pres.plot_pressure(P_fA, P_fB, N_x, N_y, L, H, mode_label,
                                     dx_arr=r.get('dx_arr'), dy_arr=r.get('dy_arr'))
    window.canvas_pres._hover_data = {
        'fields': [P_fA, P_fB],
        'names': ['P_A', 'P_B'],
        'unit': 'Pa',
        'L': L, 'H': H, 'Nx': N_x, 'Ny': N_y,
        'dx_arr': _dx, 'dy_arr': _dy,
    }

    # Velocity plot: vertical 2×1 (Fluid A, Fluid B)
    window.canvas_vel.fig.clear()
    window.canvas_vel.fig.patch.set_facecolor(_t['fig_bg'])
    ax_vA, ax_vB = window.canvas_vel.fig.subplots(2, 1)
    # Register axes for _on_hover (list-of-rows format expected by the
    # generic hover handler at _on_hover:907)
    window.canvas_vel.axes = [[ax_vA, ax_vB]]
    UmagA = np.sqrt(ucA**2 + vcA**2)
    UmagB = np.sqrt(ucB**2 + vcB**2)
    # Colour scale aligned to the 3D velocity slice convention
    # (ui/plot_3d_results._plot_3d_velocity_slice): linear, vmin pinned at 0,
    # ONE shared vmax across the A and B panels. Rationale (3D's): a zero base
    # is physically meaningful for speed, and a shared vmax keeps the same
    # colour reading the same speed across panels — a slow cross-flow B
    # (e.g. 0.15 m/s water) then correctly reads dark next to a fast air A,
    # instead of each panel auto-stretching its own [min,max] (the old 2D
    # PowerNorm(γ=0.4) auto-scale visually amplified small in-field gradients
    # such as the central compressible-cooling speed dip, making 2D and 3D
    # look qualitatively different for the same physics).
    _vmax_v = max(float(UmagA.max()), float(UmagB.max()))
    if _vmax_v <= 0.0:
        _vmax_v = 1.0
    for ax, (field, main_title, subtitle) in zip([ax_vA, ax_vB], [
        (UmagA, r"$|\mathbf{U}_A|$  [m/s]", "Fluid A"),
        (UmagB, r"$|\mathbf{U}_B|$  [m/s]", "Fluid B"),
    ]):
        ax.set_facecolor(_t['ax_bg'])
        from sjtu_tpmshx.ui.matplotlib_canvas import pad_field_to_edges
        _Xp, _Yp, _Fp = pad_field_to_edges(x, y, field, L * 1000.0, H * 1000.0)
        cf = ax.contourf(_Xp, _Yp, _Fp, levels=128, cmap='turbo',
                         vmin=0.0, vmax=_vmax_v)
        ax.set_xlim(0, L * 1000.0); ax.set_ylim(0, H * 1000.0)
        cb = window.canvas_vel.fig.colorbar(cf, ax=ax, shrink=0.9,
                                             aspect=25, format="%.1f")
        cb.ax.tick_params(labelsize=8, colors=_t['ax_text'], length=3)
        cb.ax.yaxis.set_major_locator(plt.MaxNLocator(nbins=7))
        cb.outline.set_edgecolor(_t['ax_spine'])
        ax.set_title(main_title, fontsize=13, fontweight="bold",
                     color=_t['ax_text'], loc='left', pad=6)
        ax.text(0.99, 1.02, subtitle, transform=ax.transAxes,
                fontsize=9, color=_t['mpl_subtitle'], ha='right', va='bottom',
                fontstyle='italic')
        ax.set_xlabel("x [mm]", fontsize=10, color=_t['ax_text'])
        ax.set_ylabel("y [mm]", fontsize=10, color=_t['ax_text'])
        ax.tick_params(labelsize=9, colors=_t['ax_text'], length=4, width=0.8)
        ax.set_aspect('auto')
        ax.grid(True, alpha=0.15, linewidth=0.5, color=_t['ax_text'])
        for sp in ax.spines.values():
            sp.set_edgecolor(_t['ax_spine']); sp.set_linewidth(0.8)
        if hasattr(window, '_zone_boundaries') and window._zone_boundaries:
            z_dir = getattr(window, '_zone_axis_dir', 'y')
            for b in window._zone_boundaries:
                if z_dir == 'y':
                    ax.axhline(y=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
                else:
                    ax.axvline(x=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
        for b in (getattr(window, '_zone_boundaries_x', None) or []):
            ax.axvline(x=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
        for b in (getattr(window, '_zone_boundaries_y', None) or []):
            ax.axhline(y=b*1000, color=_t['zone_line'], ls='--', lw=0.8, alpha=0.6)
    window.canvas_vel.fig.subplots_adjust(left=0.08, right=0.93,
                                           top=0.96, bottom=0.07, hspace=0.32)
    window.canvas_vel.draw()
    window.canvas_vel._hover_data = {
        'fields': [UmagA, UmagB],
        'names': ['|U_A|', '|U_B|'],
        'unit': 'm/s',
        'L': L, 'H': H, 'Nx': N_x, 'Ny': N_y,
        'dx_arr': _dx, 'dy_arr': _dy,
    }

    window.slider.hide()
    window._update_tout(-1)

    # Surrogate extrapolation watermark — one compact label across all
    # result canvases so the reader always sees this run left the
    # validated (L, t, Re) window. Also stored on window._has_extrap so
    # the Pareto / export paths can refuse or flag it downstream.
    _reasons = list(getattr(window, '_extrap_reasons', []) or [])
    window._has_extrap = bool(_reasons)
    if _reasons:
        from sjtu_tpmshx.ui.theme import get_theme as _gt
        _tw = _gt().get('warn', '#B45309')
        _wm_text = "⚠ ConstDF-v1 extrapolated: " + " | ".join(_reasons)
        for _cv in (window.canvas_temp, window.canvas_pres, window.canvas_vel):
            try:
                _cv.fig.text(0.5, 0.005, _wm_text,
                             color=_tw, fontsize=8, ha='center', va='bottom',
                             fontweight='bold', alpha=0.85)
                _cv.draw_idle()
            except Exception:
                pass
