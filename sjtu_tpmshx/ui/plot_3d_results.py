"""Render cached 3D ComputeResult fields in PyVistaQt and 2D slice canvases.

The display layer consumes SI fields and derives kPa/temperature display units
without modifying solver output. Panel readiness is separate from data presence.
"""
from __future__ import annotations
import numpy as np
from matplotlib.ticker import ScalarFormatter

# Theme — resolved at call time via get_theme()
from sjtu_tpmshx.ui.theme import get_theme as _get_theme
from sjtu_tpmshx.ui.theme import FIELD_CMAP
from .vis3d_constants import field_color_limits
from .matplotlib_canvas import style_colorbar

from sjtu_tpmshx.logutil import get_logger

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
    if panel is None and hasattr(window, '_lazy_init_3d_panel'):
        try:
            window._lazy_init_3d_panel()
            panel = getattr(window, 'canvas_3d', None)
        except Exception as _e_lazy:
            panel = None
            _log.warning(f"[3D vis] _lazy_init_3d_panel failed: {_e_lazy}")
    if panel is None:
        # Either lazy init failed, or offscreen mode left the placeholder
        # in place. Either way, the 3D visualisation cannot be displayed
        # and the caller must not switch the user to a blank tab.
        _log.warning("[3D vis] no PyVistaQt panel (canvas_3d is None after lazy "
                     "init) — embedded 3D view cannot be populated. Check the "
                     "[3D vis] _lazy_init_3d_panel line above for the import error.")
        _3d_vis_ok = False
    if panel is not None:
        try:
            P_B_kPa = None
            if f.get('P_fB') is not None:
                P_B_kPa = np.ascontiguousarray(f['P_fB'] / 1000.0)
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
                P_kPa=np.ascontiguousarray(f['P_fA'] / 1000.0),
                P_B_kPa=_P_B_for_panel,
                L_mm=f['L_mm'],
                dx=f['dx'], dy=f['dy'], dz=f['dz'],
                flow_dir=_dir_str,
                flow_dir_B=_dir_str_B if _has_B else None,
                ports_A=f.get('ports_A'), ports_B=f.get('ports_B'),
            )
            # Surrogate-extrapolation watermark — lower-left viewport.
            if res.extrap_reasons:
                # Dedupe + condense: fluid A/B repeat the same "Wall thickness"
                # line (drop exact dups), strip the verbose "(u=…,T=…,P=…)" tail
                # and the redundant "ConstDF-v1 " (already in the header) so the
                # watermark is 2–3 short lines, not a wall of text.
                _reasons = list(dict.fromkeys(res.extrap_reasons))
                _short = [r.split(' (')[0].rstrip('.').replace('ConstDF-v1 ', '')
                          for r in _reasons]
                _txt = "⚠ ConstDF-v1 extrapolated\n" + "\n".join(_short)
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
    P_Pa = f['P_fA']; uc = f['ucA']; vc = f['vcA']
    wc = f.get('wcA')
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
    uc_B = f.get('ucB')
    vc_B = f.get('vcB')
    wc_B = f.get('wcB')
    dP_B = res.dP_B_Pa
    has_B = P_Pa_B is not None
    if wc is None:
        wc = np.zeros_like(uc)
    if has_B and wc_B is None:
        wc_B = np.zeros_like(uc_B)

    plot_jobs = [
        ('canvas_temp', _plot_3d_temperature,
            (Ta[:, :, k_mid], Tb[:, :, k_mid], Ts[:, :, k_mid], xc, yc, z_info)),
        ('canvas_pres', _plot_3d_pressure,
            (P_Pa[:, :, k_mid],
             P_Pa_B[:, :, k_mid] if has_B else None,
             xc, yc, res.dP_A_Pa, dP_B, z_info)),
        ('canvas_vel', _plot_3d_velocity_slice,
            (uc[:, :, k_mid], vc[:, :, k_mid], wc[:, :, k_mid],
             uc_B[:, :, k_mid] if has_B else None,
             vc_B[:, :, k_mid] if has_B else None,
             wc_B[:, :, k_mid] if has_B else None,
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
                    limits = [(lo - 273.15, hi - 273.15) for lo, hi in limits]
                kwargs['color_limits'] = limits
            else:
                control = getattr(window, 'chk_shared_flow_scale', None)
                shared = control is None or control.isChecked()
                if key == 'pres':
                    full_fields = [P_Pa / 1000] + ([P_Pa_B / 1000] if has_B else [])
                else:
                    full_fields = [np.sqrt(uc**2 + vc**2 + wc**2)]
                    if has_B:
                        full_fields.append(np.sqrt(uc_B**2 + vc_B**2 + wc_B**2))
                kwargs['color_limits'] = field_color_limits(full_fields, shared, zero_min=key == 'vel')
                kwargs['shared'] = shared
            fn(canvas, *args, **kwargs)
            if attr == 'canvas_temp':
                fields = [Ta[:, :, k_mid], Tb[:, :, k_mid], Ts[:, :, k_mid]]
                if unit == '°C':
                    fields = [a - 273.15 for a in fields]
                names, field_unit = ['T_fA', 'T_fB', 'T_s'], unit
            elif attr == 'canvas_pres':
                fields, names, field_unit = [P_Pa[:, :, k_mid] / 1000], ['P_A'], 'kPa'
                if has_B:
                    fields.append(P_Pa_B[:, :, k_mid] / 1000); names.append('P_B')
            else:
                fields = [np.sqrt(uc[:, :, k_mid] ** 2 + vc[:, :, k_mid] ** 2
                                  + wc[:, :, k_mid] ** 2)]
                names, field_unit = ['|U_A|'], 'm/s'
                if has_B:
                    fields.append(np.sqrt(uc_B[:, :, k_mid] ** 2 + vc_B[:, :, k_mid] ** 2
                                          + wc_B[:, :, k_mid] ** 2))
                    names.append('|U_B|')
            indices = range(len(fields)) if phase is None else [min(phase, len(fields) - 1)]
            canvas._hover_data = {
                'fields': [fields[i] for i in indices],
                'names': [names[i] for i in indices], 'unit': field_unit,
                'Nx': Nx, 'Ny': Ny, 'L': float(np.sum(dx)), 'H': float(np.sum(dy)),
                'dx_arr': dx, 'dy_arr': dy, 'slice_index': k_mid,
            }
            window.cache.mark_drawn(key)
        except Exception as e:
            import traceback; traceback.print_exc()
            _log.warning(f"[3D->2D {attr}] {e}")

    # Surrogate-extrapolation watermark on the 2D mid-z slice canvases so the
    # Temperature / Pressure / Velocity tabs under 3D mode carry the same
    # `⚠ ConstDF-v1 extrapolated` notice the 3D viewport + 2D-native path
    # already show. Without this, a 3D run with t=0.6 mm would hide the
    # extrapolation flag on every canvas except the PyVistaQt viewport.
    if res.extrap_reasons:
        _reasons = list(res.extrap_reasons or [])
        from sjtu_tpmshx.ui.theme import get_theme as _gt
        _tw = _gt().get('warn', '#B45309')
        _wm_text = "⚠ ConstDF-v1 extrapolated: " + " | ".join(_reasons)
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
        Ta_slice, Tb_slice, Ts_slice = (a - 273.15 for a in (Ta_slice, Tb_slice, Ts_slice))
    indices = list(range(3)) if phase is None else [phase]
    axes = np.atleast_1d(_begin_canvas_plot(canvas, len(indices), 1))
    Y, X = np.meshgrid(yc, xc)
    vmin_unified = float(min(Ta_slice.min(), Tb_slice.min(), Ts_slice.min()))
    vmax_unified = float(max(Ta_slice.max(), Tb_slice.max(), Ts_slice.max()))
    if vmax_unified - vmin_unified < 1e-12:
        vmax_unified = vmin_unified + 1.0
    datasets = [
        (Ta_slice, rf'$T_{{f,A}}$ [{unit}] — Fluid A'),
        (Tb_slice, rf'$T_{{f,B}}$ [{unit}] — Fluid B'),
        (Ts_slice, rf'$T_s$ [{unit}] — Solid'),
    ]
    for ax, index in zip(axes, indices):
        field, title = datasets[index]
        vmin, vmax = vmin_unified, vmax_unified
        if not sync:
            scale_fields = (Ta_slice, Tb_slice) if index < 2 else (Ts_slice,)
            vmin = float(min(a.min() for a in scale_fields))
            vmax = float(max(a.max() for a in scale_fields))
            if vmax - vmin < 1e-12:
                vmax = vmin + 1.
        if color_limits is not None:
            vmin, vmax = color_limits[index]
        cf = ax.contourf(X, Y, field, levels=np.linspace(vmin, vmax, 257), cmap=FIELD_CMAP,
                          vmin=vmin, vmax=vmax)
        cb = canvas.fig.colorbar(cf, ax=ax, shrink=0.85, aspect=18,
                                format=ScalarFormatter(useOffset=False))
        style_colorbar(cb, _T)
        _style_axis(ax, title=title)
        # Equal aspect preserves geometric proportion (e.g. Shanghai 182×42 mm
        # is not square; default 'auto' stretches it to fill the axis box and
        # makes the contour shapes disagree with the 3D volume rendering).
        try:
            ax.set_aspect('equal')
        except Exception:
            pass
    if phase is None:
        canvas.fig.suptitle(f'Temperature — 3D {z_info}', fontsize=12,
                           fontweight='bold', color=_T['ax_text'], y=0.995)
    if not canvas.fig.get_constrained_layout():
        canvas.fig.subplots_adjust(left=0.11, right=0.97, top=0.86, bottom=0.14,
                                    hspace=0.45)
    canvas.draw()


def _plot_3d_pressure(canvas, P_slice_A, P_slice_B, xc, yc, dP_A, dP_B, z_info,
                      phase=None, color_limits=None, shared=True):
    """Show absolute pressure with shared A/B limits by default."""
    theme = _get_theme()
    fields = [P_slice_A / 1000.] + ([P_slice_B / 1000.] if P_slice_B is not None else [])
    limits = color_limits or field_color_limits(fields, shared)
    indices = range(len(fields)) if phase is None else [min(phase, len(fields) - 1)]
    axes = np.atleast_1d(_begin_canvas_plot(canvas, 1, len(indices)))
    Y, X = np.meshgrid(yc, xc)
    for ax, index in zip(axes, indices):
        lo, hi = limits[index]
        cf = ax.contourf(X, Y, fields[index], levels=np.linspace(lo, hi, 257),
                         cmap=FIELD_CMAP, vmin=lo, vmax=hi)
        cb = canvas.fig.colorbar(cf, ax=ax, shrink=.9, aspect=25)
        style_colorbar(cb, theme)
        tag = ('A', 'B')[index]
        scale = 'A/B shared' if shared else 'Full range'
        _style_axis(ax, title=f'P abs [kPa] — Fluid {tag} · {scale}', title_size=11)
        ax.set_aspect('equal')
    if not canvas.fig.get_constrained_layout():
        canvas.fig.subplots_adjust(left=.11, right=.96, top=.86, bottom=.14, wspace=.25)
    canvas.draw()


def _plot_3d_velocity_slice(canvas, uA, vA, wA, uB, vB, wB, xc, yc, z_info,
                           phase=None, color_limits=None, shared=True):
    """Show speed from zero with shared A/B limits by default."""
    theme = _get_theme()
    vectors = [(uA, vA, wA)] + ([(uB, vB, wB)] if uB is not None else [])
    fields = [np.sqrt(u**2 + v**2 + (w**2 if w is not None else 0.))
              for u, v, w in vectors]
    limits = color_limits or field_color_limits(fields, shared, zero_min=True)
    indices = range(len(fields)) if phase is None else [min(phase, len(fields) - 1)]
    axes = np.atleast_1d(_begin_canvas_plot(canvas, 1, len(indices)))
    Y, X = np.meshgrid(yc, xc)
    for ax, index in zip(axes, indices):
        lo, hi = limits[index]
        cf = ax.contourf(X, Y, fields[index], levels=np.linspace(lo, hi, 257),
                         cmap=FIELD_CMAP, vmin=lo, vmax=hi)
        cb = canvas.fig.colorbar(cf, ax=ax, shrink=.9, aspect=25)
        style_colorbar(cb, theme)
        tag = ('A', 'B')[index]
        scale = 'A/B shared' if shared else 'Full range'
        _style_axis(ax, title=f'|v| [m/s] — Fluid {tag} · {scale}', title_size=11)
        ax.set_aspect('equal')
    if not canvas.fig.get_constrained_layout():
        canvas.fig.subplots_adjust(left=.11, right=.96, top=.86, bottom=.14, wspace=.25)
    canvas.draw()
