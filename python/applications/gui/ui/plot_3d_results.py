"""Render cached 3D ComputeResult fields in PyVistaQt and 2D slice canvases.

The display layer consumes SI fields and derives kPa/temperature display units
without modifying solver output. Panel readiness is separate from data presence.
"""
from __future__ import annotations
import numpy as np
from matplotlib.ticker import ScalarFormatter

# Theme — resolved at call time via get_theme() and resolve_cmap()
from sjtu_tpmshx.applications.gui.ui.theme import get_theme as _get_theme
from sjtu_tpmshx.applications.gui.ui.theme import resolve_cmap
from .vis3d_constants import field_color_limits
from .matplotlib_canvas import style_colorbar

from sjtu_tpmshx.data_types.validator import convert_temperature_float
from sjtu_tpmshx.postprocess.result_display import RESULT_FIELD_SPECS, extrapolation_watermark
from sjtu_tpmshx.run_control.logutil import get_logger

_log = get_logger(__name__)






def finalize_plots_3d(window) -> bool:
    """Populate the requested 3D panel from the accepted result.

    Returns
    -------
    bool
        True iff the embedded PyVistaQt panel was successfully populated.
        False means the 3D solve completed but visualisation failed
        (panel init exception, ``set_fields`` exception, or offscreen
        mode without a panel). The caller should NOT auto-switch to the
        3D tab in that case.

    """
    res = window.cache.get_result('3d')
    if res is None:
        _log.warning("[3D vis] no cached 3D result — solver produced no "
                     "stashed ComputeResult; nothing to visualise.")
        return False
    # Arrays stay in SI units; display pressure is converted to kPa here.
    f = res.fields
    # Skeleton placeholder retires once real 3D data lands.
    sk = getattr(window, '_3d_skeleton', None)
    if sk is not None:
        try: sk.stop()
        except Exception: pass

    _3d_vis_ok = True

    # ── 1. PyVistaQt 3D panel ──
    panel = getattr(window, 'canvas_3d', None)
    if panel is None:
        window.workbench.create_volume_panel()
        panel = window.canvas_3d
    if panel is None:
        _log.warning("[3D vis] Cannot display the volume: %s", window.workbench.import_error)
        _3d_vis_ok = False
    if panel is not None:
        try:
            p_scale = RESULT_FIELD_SPECS['P_fA'].display_scale
            P_B_kPa = None
            if f.get('P_fB') is not None:
                P_B_kPa = np.ascontiguousarray(f['P_fB'] * p_scale)
            # Map fluid-A dir index (0=+x,1=-x,2=+y,3=-y,4=+z,5=-z) to
            # '±axis' string so the panel can orient inlet/outlet glyphs.
            _dirs = ['+x', '-x', '+y', '-y', '+z', '-z']
            _dir_idx = f.get('dir_A', 0)
            _dir_str = _dirs[int(_dir_idx) % 6]
            _dir_b = f.get('dir_B')
            _dir_str_B = None if _dir_b is None else _dirs[int(_dir_b) % 6]
            # When sB was None, Tb is a uniform prescribed array (T_inB
            # everywhere) and would render as a flat single-color cube,
            # misleading the user into thinking they have a B field.
            # Filter it out at the panel boundary so the combo skips Tb.
            _has_B = _dir_b is not None
            _Tb_for_panel = f.get('Tb') if _has_B else None
            _vmag_B_for_panel = f.get('vmag_B') if _has_B else None
            _P_B_for_panel = P_B_kPa if _has_B else None
            panel.set_fields(
                Ta=f['Ta'],
                Tb=_Tb_for_panel,
                Ts=f.get('Ts'),
                vmag=f['vmag_A'],
                vmag_B=_vmag_B_for_panel,
                P_kPa=np.ascontiguousarray(f['P_fA'] * p_scale),
                P_B_kPa=_P_B_for_panel,
                L_mm=f['L_mm'],
                t_mm=f.get('t_mm'),
                dx=f['dx'], dy=f['dy'], dz=f['dz'],
                flow_dir=_dir_str,
                flow_dir_B=_dir_str_B if _has_B else None,
                ports_A=f.get('ports_A'), ports_B=f.get('ports_B'),
            )
            # Surrogate-extrapolation watermark from the run's recorded model.
            _txt = extrapolation_watermark(
                res.metadata, res.extrap_reasons, multiline=True)
            if _txt:
                try:
                    panel.set_watermark(_txt)
                except Exception:
                    pass
            else:
                try:
                    panel.set_watermark(None)
                except Exception:
                    pass
        except Exception as e:
            import traceback; traceback.print_exc()
            _log.warning(f"[3D vis] set_fields failed: {e}")
            _3d_vis_ok = False

    return _3d_vis_ok


def _render_2d_slices_from_3d(window, res, field=None):
    """Render one requested z-slice field (all fields for direct callers).

    Use the recorded nonuniform grid spacing and the selected physical z cell.
    """
    # B3 C5: res is the ComputeResult — arrays live in res.fields.
    f = res.fields
    Ta = f['Ta']; Tb = f['Tb']; Ts = f['Ts']
    P_Pa = f['P_fA']; vmag_A = f['vmag_A']
    dx = f['dx']; dy = f['dy']
    Nx, Ny, Nz = Ta.shape
    # A new result starts at its middle cell. Subsequent slice changes use
    # the actual nonuniform z centres, never an evenly-spaced display proxy.
    if getattr(window, '_slice_result_id', None) != id(res):
        window._slice_result_id = id(res)
        window._slice_index = Nz // 2
    k_mid = int(np.clip(getattr(window, '_slice_index', Nz // 2), 0, Nz - 1))
    dz = np.asarray(f['dz'])
    z_mm = float((np.cumsum(dz) - dz / 2)[k_mid] * 1000)
    z_info = f'z = {z_mm:.2f} mm ({k_mid + 1}/{Nz})'
    slice_slider = getattr(window, '_slice_slider', None)
    if slice_slider is not None:
        slice_slider.blockSignals(True)
        slice_slider.setRange(0, Nz - 1)
        slice_slider.setValue(k_mid)
        slice_slider.blockSignals(False)
        window._slice_label.setText(z_info)
    phase = getattr(window, '_field_phase', None)
    unit = '°C' if getattr(window, '_temp_unit', 'K') == 'C' else 'K'

    # Shared cumsum coord grid (mm) — handles non-uniform dx/dy
    xc = (np.cumsum(dx) - dx / 2) * 1000.0
    yc = (np.cumsum(dy) - dy / 2) * 1000.0

    # Fluid B optional (cross-flow). Detect by presence of P_fB
    P_Pa_B = f.get('P_fB')
    vmag_B = f.get('vmag_B')
    dP_B = res.dP_B_Pa
    has_B = P_Pa_B is not None
    p_spec_a, p_spec_b = RESULT_FIELD_SPECS['P_fA'], RESULT_FIELD_SPECS['P_fB']
    v_spec_a, v_spec_b = RESULT_FIELD_SPECS['vmag_A'], RESULT_FIELD_SPECS['vmag_B']
    t_specs = [RESULT_FIELD_SPECS[key] for key in ('Ta', 'Tb', 'Ts')]

    p_slice_a = None
    p_slice_b = None
    if field in (None, 'pres'):
        p_slice_a = P_Pa[:, :, k_mid] * p_spec_a.display_scale
        p_slice_b = P_Pa_B[:, :, k_mid] * p_spec_b.display_scale if has_B else None

    plot_jobs = [
        ('canvas_temp', _plot_3d_temperature,
            (Ta[:, :, k_mid], Tb[:, :, k_mid], Ts[:, :, k_mid], xc, yc, z_info)),
        ('canvas_pres', _plot_3d_pressure,
            (p_slice_a, p_slice_b, xc, yc, res.dP_A_Pa, dP_B, z_info)),
        ('canvas_vel', _plot_3d_velocity_slice,
            (vmag_A[:, :, k_mid],
             vmag_B[:, :, k_mid] if has_B else None,
             xc, yc, z_info)),
    ]
    for attr, fn, args in plot_jobs:
        key = attr.removeprefix('canvas_')
        if field is not None and field != key:
            continue
        canvas = getattr(window, attr, None)
        if canvas is None:
            continue
        try:
            kwargs = {'phase': phase}
            if attr == 'canvas_temp':
                kwargs['unit'] = unit
                sync = getattr(window, 'chk_sync_colorbar_T', None)
                kwargs['sync'] = sync is None or sync.isChecked()
                full_t = [Ta, Tb, Ts]
                limits = field_color_limits(full_t, kwargs['sync'])
                if unit == '°C':
                    limits = [
                        (convert_temperature_float(lo, 'K', 'C'), convert_temperature_float(hi, 'K', 'C'))
                        for lo, hi in limits
                    ]
                kwargs['color_limits'] = limits
            else:
                if key == 'pres':
                    control = getattr(window, 'chk_shared_pressure_scale', None)
                    shared = control is None or control.isChecked()
                    raw_fields = [P_Pa] + ([P_Pa_B] if has_B else [])
                    scale = p_spec_a.display_scale
                    kwargs['color_limits'] = [
                        (lo * scale, hi * scale)
                        for lo, hi in field_color_limits(raw_fields, shared)
                    ]
                    kwargs['shared'] = shared
                else:
                    full_fields = [vmag_A] + ([vmag_B] if has_B else [])
                    kwargs['color_limits'] = field_color_limits(full_fields)
            fn(canvas, *args, **kwargs)
            if attr == 'canvas_temp':
                fields = [Ta[:, :, k_mid], Tb[:, :, k_mid], Ts[:, :, k_mid]]
                if unit == '°C':
                    fields = [convert_temperature_float(a, 'K', 'C') for a in fields]
                names, field_unit, field_fmt = [spec.symbol for spec in t_specs], unit, '.2f'
            elif attr == 'canvas_pres':
                fields = [p_slice_a]
                names, field_unit, field_fmt = [p_spec_a.symbol], p_spec_a.display_unit, '.5f'
                if has_B:
                    fields.append(p_slice_b)
                    names.append(p_spec_b.symbol)
            else:
                fields = [vmag_A[:, :, k_mid]]
                names, field_unit, field_fmt = [v_spec_a.symbol], v_spec_a.display_unit, '.2f'
                if has_B:
                    fields.append(vmag_B[:, :, k_mid])
                    names.append(v_spec_b.symbol)
            indices = range(len(fields)) if phase is None else [min(phase, len(fields) - 1)]
            canvas._hover_data = {
                'fields': [fields[i] for i in indices],
                'names': [names[i] for i in indices], 'unit': field_unit,
                'fmt': field_fmt,
                'Nx': Nx, 'Ny': Ny, 'L': float(np.sum(dx)), 'H': float(np.sum(dy)),
                'dx_arr': dx, 'dy_arr': dy, 'slice_index': k_mid,
            }
            window.cache.mark_drawn(key)
        except Exception as e:
            import traceback; traceback.print_exc()
            _log.warning(f"[3D->2D {attr}] {e}")

    # Keep the run's model-extrapolation watermark visible on 2D slice canvases.
    _wm_text = extrapolation_watermark(res.metadata, res.extrap_reasons)
    if _wm_text:
        from sjtu_tpmshx.applications.gui.ui.theme import get_theme as _gt
        _tw = _gt().get('warn', '#B45309')
        for attr in ('canvas_temp', 'canvas_pres', 'canvas_vel'):
            if field is not None and attr != f'canvas_{field}':
                continue
            _cv = getattr(window, attr, None)
            if _cv is None:
                continue
            try:
                _cv.fig.text(0.5, 0.005, _wm_text,
                             color=_tw, fontsize=8, ha='center', va='bottom',
                             fontweight='bold', alpha=0.85)
                _cv.draw_idle()
            except Exception:
                pass


def _begin_canvas_plot(canvas, nrows=1, ncols=1):
    """Clear the canvas and return the Axes or array produced by subplots."""
    _T = _get_theme()
    canvas.fig.clear()
    canvas.fig.patch.set_facecolor(_T['fig_bg'])
    axes = canvas.fig.subplots(nrows, ncols)
    canvas.axes = [axes if hasattr(axes, '__iter__') else [axes]]
    return axes


def _style_axis(ax, xlabel='x [mm]', ylabel='y [mm]', title='',
                title_size=13, label_size=11, tick_size=11):
    _T = _get_theme()
    ax.set_facecolor(_T['ax_bg'])
    if title:
        ax.set_title(title, fontsize=title_size, fontweight='bold',
                     color=_T['ax_text'])
    ax.set_xlabel(xlabel, fontsize=label_size, color=_T['ax_text'])
    ax.set_ylabel(ylabel, fontsize=label_size, color=_T['ax_text'])
    ax.tick_params(labelsize=tick_size, colors=_T['ax_text'])
    for sp in ax.spines.values():
        sp.set_edgecolor(_T['ax_spine'])


def _plot_3d_temperature(canvas, Ta_slice, Tb_slice, Ts_slice, xc, yc, z_info,
                         phase=None, unit='K', sync=True, color_limits=None):
    """Show the selected temperature slices with a shared range by default."""
    _T = _get_theme()
    if unit == '°C':
        Ta_slice, Tb_slice, Ts_slice = (
            convert_temperature_float(a, 'K', 'C') for a in (Ta_slice, Tb_slice, Ts_slice)
        )
    indices = list(range(3)) if phase is None else [phase]
    axes = np.atleast_1d(_begin_canvas_plot(canvas, len(indices), 1))
    Y, X = np.meshgrid(yc, xc)
    fields = [Ta_slice, Tb_slice, Ts_slice]
    limits = color_limits or (field_color_limits(fields, shared=True) if sync else
                             field_color_limits(fields[:2], shared=True) + field_color_limits(fields[2:]))
    specs = [RESULT_FIELD_SPECS[key] for key in ('Ta', 'Tb', 'Ts')]
    datasets = [
        (Ta_slice, specs[0], f'{specs[0].symbol_tex} [{unit}]', '流体 A'),
        (Tb_slice, specs[1], f'{specs[1].symbol_tex} [{unit}]', '流体 B'),
        (Ts_slice, specs[2], f'{specs[2].symbol_tex} [{unit}]', '固体'),
    ]
    for ax, index in zip(axes, indices):
        field, spec, left_title, right_title = datasets[index]
        vmin, vmax = limits[index]
        cf = ax.contourf(X, Y, field, levels=np.linspace(vmin, vmax, 257),
                         cmap=resolve_cmap(spec.key), vmin=vmin, vmax=vmax)
        cb = canvas.fig.colorbar(cf, ax=ax, shrink=0.85, aspect=18, ticks=np.linspace(vmin, vmax, 5),
                                format=ScalarFormatter(useOffset=False))
        style_colorbar(cb, _T)
        _style_axis(ax, title='')
        ax.set_title(left_title, loc='left', fontsize=12, fontweight='bold', color=_T['ax_text'])
        ax.set_title(right_title, loc='right', fontsize=9.5, color=_T['mpl_subtitle'])
        # Equal aspect preserves geometric proportion (e.g. Shanghai 182×42 mm
        # is not square; default 'auto' stretches it to fill the axis box and
        # makes the contour shapes disagree with the 3D volume rendering).
        try:
            ax.set_aspect('equal')
        except Exception:
            pass
    if not canvas.fig.get_constrained_layout():
        canvas.fig.subplots_adjust(left=0.11, right=0.97, top=0.86, bottom=0.14,
                                    hspace=0.45)
    canvas.draw()


def _plot_3d_pressure(canvas, P_slice_A_kPa, P_slice_B_kPa, xc, yc, dP_A, dP_B, z_info,
                      phase=None, color_limits=None, shared=True):
    """Show absolute pressure slices supplied in kPa with shared A/B limits by default."""
    theme = _get_theme()
    specs = [RESULT_FIELD_SPECS['P_fA']]
    fields = [P_slice_A_kPa]
    if P_slice_B_kPa is not None:
        specs.append(RESULT_FIELD_SPECS['P_fB'])
        fields.append(P_slice_B_kPa)
    limits = color_limits or field_color_limits(fields, shared)
    indices = range(len(fields)) if phase is None else [min(phase, len(fields) - 1)]
    axes = np.atleast_1d(_begin_canvas_plot(canvas, 1, len(indices)))
    Y, X = np.meshgrid(yc, xc)
    for ax, index in zip(axes, indices):
        spec = specs[index]
        lo, hi = limits[index]
        cf = ax.contourf(X, Y, fields[index], levels=np.linspace(lo, hi, 257),
                         cmap=resolve_cmap(spec.key), vmin=lo, vmax=hi)
        cb = canvas.fig.colorbar(cf, ax=ax, shrink=.9, aspect=25)
        style_colorbar(cb, theme)
        scale = 'A/B 共用色标' if shared else '独立色标'
        _style_axis(ax, title='', title_size=11)
        ax.set_title(f'{spec.symbol_tex} abs [{spec.display_unit}]', loc='left',
                     fontsize=11, fontweight='bold', color=theme['ax_text'])
        ax.set_title(f'流体 {spec.phase} · {scale}', loc='right',
                     fontsize=9, color=theme['mpl_subtitle'])
        ax.set_aspect('equal')
    if not canvas.fig.get_constrained_layout():
        canvas.fig.subplots_adjust(left=.11, right=.96, top=.86, bottom=.14, wspace=.25)
    canvas.draw()


def _plot_3d_velocity_slice(canvas, vmag_slice_A, vmag_slice_B, xc, yc, z_info,
                            phase=None, color_limits=None):
    """Show each fluid's full speed range with filled contours."""
    theme = _get_theme()
    specs = [RESULT_FIELD_SPECS['vmag_A']]
    fields = [vmag_slice_A]
    if vmag_slice_B is not None:
        specs.append(RESULT_FIELD_SPECS['vmag_B'])
        fields.append(vmag_slice_B)
    limits = color_limits or field_color_limits(fields)
    indices = range(len(fields)) if phase is None else [min(phase, len(fields) - 1)]
    axes = np.atleast_1d(_begin_canvas_plot(canvas, 1, len(indices)))
    Y, X = np.meshgrid(yc, xc)
    for ax, index in zip(axes, indices):
        spec = specs[index]
        lo, hi = limits[index]
        cf = ax.contourf(X, Y, fields[index], levels=np.linspace(lo, hi, 257),
                         cmap=resolve_cmap(spec.key), vmin=lo, vmax=hi)
        cb = canvas.fig.colorbar(cf, ax=ax, shrink=.9, aspect=25)
        style_colorbar(cb, theme)
        _style_axis(ax, title='', title_size=11)
        ax.set_title(f'{spec.symbol_tex} [{spec.display_unit}]', loc='left',
                     fontsize=11, fontweight='bold', color=theme['ax_text'])
        ax.set_title(f'流体 {spec.phase} · 独立色标', loc='right',
                     fontsize=9, color=theme['mpl_subtitle'])
        ax.set_aspect('equal')
    if not canvas.fig.get_constrained_layout():
        canvas.fig.subplots_adjust(left=.11, right=.96, top=.86, bottom=.14, wspace=.25)
    canvas.draw()
