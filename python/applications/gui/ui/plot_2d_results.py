"""Draw cached 2D fields and slices from the accepted 3D result."""
import numpy as np
from matplotlib.ticker import ScalarFormatter

from sjtu_tpmshx.model_configs.units import CELSIUS_ZERO_K
from sjtu_tpmshx.postprocess.result_display import RESULT_FIELD_SPECS, extrapolation_watermark

from .theme import resolve_cmap
from .vis3d_constants import field_color_limits

def _phase_indices(window, count):
    """Direct renderer callers keep all panels; the workbench selects one."""
    phase = getattr(window, '_field_phase', None)
    return list(range(count)) if phase is None else [min(phase, count - 1)]


def _style_workbench_axes(ax, cb, theme, title, subtitle):
    from .matplotlib_canvas import style_field_axes
    style_field_axes(ax, cb, theme, title, subtitle)
    ax.tick_params(labelsize=11)
    ax.xaxis.label.set_fontsize(11)
    ax.yaxis.label.set_fontsize(11)



def ensure_result_plot(window, field):
    """Populate a result canvas once per result/display selection."""
    if window.cache.is_drawn(field):
        return True
    result_3d = window.cache.get_result('3d')
    if result_3d is None and window.cache.get_result('2d') is None:
        return False
    detail = '请查看计算日志。'
    try:
        if result_3d is not None:
            from .plot_3d_results import _render_2d_slices_from_3d
            _render_2d_slices_from_3d(window, result_3d, field=field)
        else:
            finalize_plots(window, field=field)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Could not render %s", field)
        detail = str(exc)
    else:
        if window.cache.is_drawn(field):
            return True
    # A failed selection must not leave the preceding field/probe visible.
    window.cache.replace_drawn_tabs(set(window.cache.get_drawn_tabs()) - {field})
    canvas = getattr(window, f'canvas_{field}', None)
    if canvas is not None:
        canvas.fig.clear()
        canvas._hover_data = None
        canvas.draw_idle()
    if hasattr(window, 'statusBar'):
        window.statusBar().showMessage(f"场图显示失败：{detail}", 8000)
    return False


def redraw_result_fields(window):
    """Invalidate hidden fields; redraw only visible or detached result plots."""
    fields = {'temp', 'pres', 'vel'}
    window.cache.replace_drawn_tabs(set(window.cache.get_drawn_tabs()) - fields)
    visible = set(window.workbench.split_tabs or
                  (window.workbench.active_tab,))
    visible.update(key for key, dialog in
                   window.workbench.detached_canvases.items()
                   if dialog.isVisible())
    for field in visible & fields:
        ensure_result_plot(window, field)


def _draw_zone_overlays(ax, zones, theme):
    """Draw strip or grid zone boundaries on one 2D field plot."""
    if not zones:
        return
    style = dict(color=theme['zone_line'], ls='--', lw=0.8, alpha=0.6)
    boundaries = zones.get('boundaries')
    if boundaries is not None:
        z_dir = zones.get('axis_dir') or 'y'
        for b in boundaries:
            if z_dir == 'y':
                ax.axhline(y=b * 1000, **style)
            else:
                ax.axvline(x=b * 1000, **style)
    boundaries_x = zones.get('boundaries_x')
    if boundaries_x is not None:
        for b in boundaries_x:
            ax.axvline(x=b * 1000, **style)
    boundaries_y = zones.get('boundaries_y')
    if boundaries_y is not None:
        for b in boundaries_y:
            ax.axhline(y=b * 1000, **style)


def plot_temperature_3panel(window, r, _t, zones=None):
    """Draw the selected T_fA / T_fB / T_s field, or all three for direct callers.

    Supply ``zones`` to draw strip or grid zone overlays on each panel.
    When ``window.chk_sync_colorbar_T`` is selected, all three panels use one
    shared color range. When it is cleared, Fluid A and Fluid B share one range
    and Solid uses its own range.
    """
    unit = '°C' if getattr(window, '_temp_unit', 'K') == 'C' else 'K'
    offset = CELSIUS_ZERO_K if unit == '°C' else 0.0
    Ta, Tb, Ts = (r[key] - offset for key in ('Ta', 'Tb', 'Ts'))
    N_x, N_y, L, H = r['N_x'], r['N_y'], r['L'], r['H']

    window.canvas_temp.fig.clear()
    selected = _phase_indices(window, 3)
    axes = np.atleast_1d(window.canvas_temp.fig.subplots(len(selected), 1))
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
    temperatures = [r[key] for key in ('Ta', 'Tb', 'Ts')]
    limits = (field_color_limits(temperatures, shared=True) if _sync else
              field_color_limits(temperatures[:2], shared=True) + field_color_limits(temperatures[2:]))
    limits = [(lo - offset, hi - offset) for lo, hi in limits]

    specs = [RESULT_FIELD_SPECS[key] for key in ('Ta', 'Tb', 'Ts')]
    plot_items = [
        (Ta, specs[0], "Fluid A"),
        (Tb, specs[1], "Fluid B"),
        (Ts, specs[2], "Solid"),
    ]
    for ax, index in zip(axes, selected):
        field, spec, subtitle = plot_items[index]
        ax.set_facecolor(_t['ax_bg'])
        lo, hi = limits[index]
        from sjtu_tpmshx.applications.gui.ui.matplotlib_canvas import pad_field_to_edges
        _Xp, _Yp, _Fp = pad_field_to_edges(x, y, field, L * 1000.0, H * 1000.0)
        cf = ax.contourf(_Xp, _Yp, _Fp, levels=np.linspace(lo, hi, 129),
                         cmap=resolve_cmap(spec.key), vmin=lo, vmax=hi)
        ax.set_xlim(0, L * 1000.0); ax.set_ylim(0, H * 1000.0)
        cb = window.canvas_temp.fig.colorbar(cf, ax=ax, shrink=0.9,
                                              aspect=25, ticks=np.linspace(lo, hi, 5),
                                              format=ScalarFormatter(useOffset=False))
        _style_workbench_axes(ax, cb, _t, f"{spec.symbol_tex}  [{unit}]", subtitle)
        _draw_zone_overlays(ax, zones, _t)

    if not window.canvas_temp.fig.get_constrained_layout():
        window.canvas_temp.fig.subplots_adjust(left=0.11, right=0.96,
                                                top=0.89, bottom=0.14, hspace=0.34)
    window.canvas_temp.draw()
    window.canvas_temp._hover_data = {
        'fields': [[Ta, Tb, Ts][i] for i in selected],
        'names': [specs[i].symbol for i in selected],
        'unit': unit,
        'fmt': '.2f',
        'L': L, 'H': H, 'Nx': N_x, 'Ny': N_y,
        'dx_arr': _dx, 'dy_arr': _dy,
    }




def finalize_plots(window, field="temp"):
    """Render one field from stored 2D results, on the main thread."""
    from sjtu_tpmshx.applications.gui.ui.theme import get_theme
    _t = get_theme()

    result = window.cache.get_result('2d')
    r = result.fields
    zones = result.zones
    P_fA, P_fB = r['P_fA'], r['P_fB']
    N_x, N_y, L, H = r['N_x'], r['N_y'], r['L'], r['H']
    dir_A, dir_B = r['dir_A'], r['dir_B']

    dir_flow_A = window._DIR_MAP[dir_A]
    dir_flow_B = window._DIR_MAP[dir_B]


    mode_label = f"A:{dir_flow_A} B:{dir_flow_B}"

    # Temperature: selected fluid/solid field — delegated
    # to a module-level helper so the K/°C sync toggle can redraw without
    # re-running the full finalize pipeline.
    if field == "temp":
        plot_temperature_3panel(window, r, _t, zones=zones)
    # Hover data cached by helper; the rest of this function handles
    # pressure, velocity, and layout panels. Preserve original variable
    # bindings for code below.
    _dx = r.get('dx_arr', np.full(N_x, L / N_x))
    _dy = r.get('dy_arr', np.full(N_y, H / N_y))
    x = (np.cumsum(_dx) - _dx / 2) * 1000
    y = (np.cumsum(_dy) - _dy / 2) * 1000

    # Pressure plot — clouds only (dP stays in Pa in the readout strip).
    selected = _phase_indices(window, 2)
    if field == "pres":
        spec_a, spec_b = RESULT_FIELD_SPECS['P_fA'], RESULT_FIELD_SPECS['P_fB']
        p_disp = (P_fA * spec_a.display_scale, P_fB * spec_b.display_scale)
        p_specs = (spec_a, spec_b)
        control = getattr(window, 'chk_shared_pressure_scale', None)
        shared = control is None or control.isChecked()
        if len(selected) == 2:
            window.canvas_pres.plot_pressure(p_disp[0], p_disp[1], N_x, N_y, L, H, mode_label,
                                             dx_arr=r.get('dx_arr'), dy_arr=r.get('dy_arr'), shared=shared)
        else:
            from .matplotlib_canvas import pad_field_to_edges
            canvas = window.canvas_pres
            canvas.fig.clear()
            canvas.fig.patch.set_facecolor(_t['fig_bg'])
            ax = canvas.fig.subplots()
            canvas.axes = [[ax]]
            index = selected[0]
            spec = p_specs[index]
            values = p_disp[index]
            Xp, Yp, Fp = pad_field_to_edges(x, y, values, L * 1000, H * 1000)
            lo, hi = field_color_limits(p_disp, shared)[index]
            cf = ax.contourf(Xp, Yp, Fp, levels=np.linspace(lo, hi, 129),
                             cmap=resolve_cmap(spec.key), vmin=lo, vmax=hi)
            ax.set_xlim(0, L * 1000); ax.set_ylim(0, H * 1000)
            cb = canvas.fig.colorbar(cf, ax=ax, shrink=.9, aspect=25,
                                    format=ScalarFormatter(useOffset=False))
            tag = spec.phase
            _style_workbench_axes(ax, cb, _t, f'{spec.symbol_tex} abs [{spec.display_unit}]',
                                  'A/B shared' if shared else f'Fluid {tag} full range')
            if not canvas.fig.get_constrained_layout():
                canvas.fig.subplots_adjust(left=.11, right=.96, top=.89, bottom=.14)
            canvas.draw()
        window.canvas_pres._hover_data = {
            'fields': [p_disp[i] for i in selected],
            'names': [p_specs[i].symbol for i in selected],
            'unit': spec_a.display_unit,
            'fmt': '.5f',
            'L': L, 'H': H, 'Nx': N_x, 'Ny': N_y,
            'dx_arr': _dx, 'dy_arr': _dy,
        }

    # Velocity: the selected fluid; direct legacy callers retain both.
    if field == "vel":
        window.canvas_vel.fig.clear()
        window.canvas_vel.fig.patch.set_facecolor(_t['fig_bg'])
        axes_v = np.atleast_1d(window.canvas_vel.fig.subplots(len(selected), 1))
        # Register axes for _on_hover (list-of-rows format expected by the
        # generic hover handler at _on_hover:907)
        window.canvas_vel.axes = [list(axes_v)]
        spec_a, spec_b = RESULT_FIELD_SPECS['vmag_A'], RESULT_FIELD_SPECS['vmag_B']
        v_specs = (spec_a, spec_b)
        UmagA, UmagB = r['vmag_A'], r['vmag_B']
        limits = field_color_limits([UmagA, UmagB])
        velocity_items = [
            (UmagA, spec_a, "Fluid A"),
            (UmagB, spec_b, "Fluid B"),
        ]
        for ax, index in zip(axes_v, selected):
            values, spec, subtitle = velocity_items[index]
            ax.set_facecolor(_t['ax_bg'])
            from sjtu_tpmshx.applications.gui.ui.matplotlib_canvas import pad_field_to_edges
            _Xp, _Yp, _Fp = pad_field_to_edges(x, y, values, L * 1000.0, H * 1000.0)
            lo, hi = limits[index]
            cf = ax.contourf(_Xp, _Yp, _Fp, levels=np.linspace(lo, hi, 129),
                             cmap=resolve_cmap(spec.key), vmin=lo, vmax=hi)
            ax.set_xlim(0, L * 1000.0); ax.set_ylim(0, H * 1000.0)
            cb = window.canvas_vel.fig.colorbar(cf, ax=ax, shrink=0.9,
                                                 aspect=25, format=ScalarFormatter(useOffset=False))
            _style_workbench_axes(ax, cb, _t, f"{spec.symbol_tex}  [{spec.display_unit}]",
                                  subtitle + ' full range')
            ax.grid(True, alpha=0.15, linewidth=0.5, color=_t['ax_text'])
            _draw_zone_overlays(ax, zones, _t)
        if not window.canvas_vel.fig.get_constrained_layout():
            window.canvas_vel.fig.subplots_adjust(left=0.11, right=0.96,
                                                   top=0.89, bottom=0.14, hspace=0.32)
        window.canvas_vel.draw()
        window.canvas_vel._hover_data = {
            'fields': [[UmagA, UmagB][i] for i in selected],
            'names': [v_specs[i].symbol for i in selected],
            'unit': spec_a.display_unit,
            'fmt': '.2f',
            'L': L, 'H': H, 'Nx': N_x, 'Ny': N_y,
            'dx_arr': _dx, 'dy_arr': _dy,
        }

    window._update_tout(-1)

    # Keep the applicability warning visible with every field plot.
    _wm_text = extrapolation_watermark(result.metadata, result.extrap_reasons)
    if _wm_text:
        from sjtu_tpmshx.applications.gui.ui.theme import get_theme as _gt
        _tw = _gt().get('warn', '#B45309')
        _cv = getattr(window, f"canvas_{field}")
        try:
            engine = _cv.fig.get_layout_engine()
            if engine is not None and hasattr(engine, "set"):
                engine.set(rect=(0.0, 0.05, 1.0, 1.0))
            elif not _cv.fig.get_constrained_layout():
                _cv.fig.subplots_adjust(bottom=0.18)
            _cv.fig.text(0.5, 0.008, _wm_text,
                         color=_tw, fontsize=8, ha='center', va='bottom',
                         fontweight='bold', alpha=0.85)
            _cv.draw_idle()
        except Exception:
            pass

    window.cache.mark_drawn(field)
