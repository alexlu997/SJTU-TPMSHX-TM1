"""Layout drawing helpers for SJTU-TPMSHX GUI.

Extracted from main.py (Task B.4). All functions take `window` (a Main_Menu
instance) as first argument. `self.` in original bodies -> `window.`.
"""
import numpy as np
from PySide6.QtWidgets import QMessageBox
from .theme import get_theme


def draw_layout(window):
    """Draw geometry. 2D rectangle or 3D cuboid wireframe based on mode."""
    try:
        L = float(window.le_L.text()); H = float(window.le_H.text())
    except ValueError:
        QMessageBox.warning(window, "Input Error",
                            "Fill Domain fields first."); return

    window.canvas_layout.fig.clear()
    Lmm, Hmm = L * 1000, H * 1000
    _t = get_theme()

    # 3D mode → 3D cuboid wireframe + inlet/outlet shading
    is_3d = (hasattr(window, 'combo_dim')
             and window.combo_dim.currentIndex() == 1)
    if is_3d:
        try:
            Lz = float(window.le_Lz.text())
        except ValueError:
            QMessageBox.warning(window, "Input Error",
                                "Fill Lz field first."); return
        ax = window.canvas_layout.fig.add_subplot(111, projection='3d')
        window.canvas_layout.axes = [[ax]]
        draw_layout_rect_3d(window, ax, L, H, Lz)
        ax.set_facecolor(_t['fig_bg'])
    else:
        # Restore canvas_wheel_zoom behaviour if a prior 3D draw overrode it
        _canvas = window.canvas_layout
        if hasattr(_canvas, '_orig_wheel_event'):
            _canvas.wheelEvent = _canvas._orig_wheel_event
        ax = _canvas.fig.add_subplot(111)
        window.canvas_layout.axes = [[ax]]
        draw_layout_rect(window, ax, L, H, Lmm, Hmm)
        ax.set_xlabel('x [mm]', color=_t['ax_text'])
        ax.set_ylabel('y [mm]', color=_t['ax_text'])
        ax.set_aspect('equal')
        ax.set_facecolor(_t['ax_bg'])
        ax.tick_params(colors=_t['ax_text'])
        for sp in ax.spines.values():
            sp.set_edgecolor(_t['ax_spine'])

    window.canvas_layout.fig.set_facecolor(_t['fig_bg'])
    window.cache.mark_drawn('layout')
    if hasattr(window, 'btn_export'):
        window.btn_export.setEnabled(True)
    # Let Qt finish showing/layout of the card before Matplotlib paints.
    # Its draw_idle coalesces further resize requests; nested processEvents
    # and timed duplicate draws can repaint during an unfinished UI update.
    window._switch_tab('layout')
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, window.canvas_layout, window.canvas_layout.draw_idle)


def draw_layout_rect_3d(window, ax, L, H, Lz):
    """Draw 3D cuboid wireframe + inlet/outlet face shading for fluid A + B.

    Engineering convention: external double arrows (inlet: pointing IN,
    outlet: pointing OUT). Inline "Inlet_A/Outlet_A/Inlet_B/Outlet_B"
    labels replace title legend. Small origin triad at (0,0,0).
    """
    _t = get_theme()
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    Lmm, Hmm, Lzmm = L * 1000, H * 1000, Lz * 1000

    # Cuboid edges
    pts = np.array([
        [0, 0, 0], [Lmm, 0, 0], [Lmm, Hmm, 0], [0, Hmm, 0],
        [0, 0, Lzmm], [Lmm, 0, Lzmm], [Lmm, Hmm, Lzmm], [0, Hmm, Lzmm],
    ])
    edges = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),
             (0,4),(1,5),(2,6),(3,7)]
    for i, j in edges:
        # Bump linewidth so the cuboid skeleton stays visible against the
        # dark theme even when the wireframe colour is close to fig_bg
        # — without this, zoomed views show only the face fills.
        ax.plot(*zip(pts[i], pts[j]), color=_t['wireframe'], lw=2.0,
                alpha=0.9)

    face_patches = []
    drag_artists = []

    def _face_patch(verts, color, alpha):
        poly = Poly3DCollection([verts], alpha=alpha, facecolor=color,
                                 edgecolor=_t['ax_text'], linewidths=1.2)
        ax.add_collection3d(poly)
        face_patches.append(poly)
        drag_artists.append(poly)

    INLET_COL = _t['inlet_color']
    OUTLET_COL = _t['outlet_color']
    face_alpha = 0.35

    def _draw_fluid(cfg, label_tag, label_offset):
        """Both transverse spans use the same axis convention as the inputs."""
        from sjtu_tpmshx.domain.validator import cross_axes_for_dir
        d = cfg['dir']
        normal = d // 2
        cross = ['XYZ'.index(axis) for axis in cross_axes_for_dir(d)]
        extents = [Lmm, Hmm, Lzmm]
        for end, title, color in (('in', 'Inlet', INLET_COL),
                                  ('out', 'Outlet', OUTLET_COL)):
            at_high_face = (d % 2 == 1) if end == 'in' else (d % 2 == 0)
            face = extents[normal] if at_high_face else 0.
            ctr = cfg[f'{end}_ctr'] * 1000
            width = cfg[f'{end}_w'] * 1000
            ctr2 = cfg.get(f'{end}_z_ctr')
            width2 = cfg.get(f'{end}_z_w')
            ctr2 = extents[cross[1]] / 2 if ctr2 is None else ctr2 * 1000
            width2 = extents[cross[1]] if width2 is None else width2 * 1000
            lo, hi = max(0., ctr-width/2), min(extents[cross[0]], ctr+width/2)
            lo2, hi2 = max(0., ctr2-width2/2), min(extents[cross[1]], ctr2+width2/2)
            verts = []
            for first, second in ((lo, lo2), (hi, lo2), (hi, hi2), (lo, hi2)):
                point = [0., 0., 0.]
                point[normal], point[cross[0]], point[cross[1]] = face, first, second
                verts.append(point)
            _face_patch(verts, color, face_alpha)
            pos = [0., 0., 0.]
            pos[normal], pos[cross[0]], pos[cross[1]] = face, ctr, ctr2
            if normal != 2:
                pos[2] = hi2 + label_offset
            drag_artists.append(ax.text(
                *pos, f'{title}_{label_tag}', color=color, fontsize=9,
                fontweight='bold', ha='center'))

    try:
        fA = window._fluid_config('A')
        _draw_fluid(fA, 'A', Lzmm * 0.15)
    except Exception as _fa_err:
        try:
            window.statusBar().showMessage(
                f"Layout: Fluid A skipped — {_fa_err}", 4000)
        except Exception:
            pass

    try:
        fB = window._fluid_config('B')
        _draw_fluid(fB, 'B', Lzmm * 0.30)
    except Exception as _fb_err:
        # Non-fatal: Fluid B may be deliberately unset (e.g., single-stream
        # runs). Log to the status bar so the omission is visible but
        # doesn't interrupt the rest of the layout render.
        try:
            window.statusBar().showMessage(
                f"Layout: Fluid B skipped — {_fb_err}", 4000)
        except Exception:
            pass

    # Origin triad
    triad_len = max(Lmm, Hmm, Lzmm) * 0.06
    drag_artists.append(ax.quiver(
        0, 0, 0, triad_len, 0, 0, color=_t['triad_x'],
        arrow_length_ratio=0.3, linewidth=1.8))
    drag_artists.append(ax.quiver(
        0, 0, 0, 0, triad_len, 0, color=_t['triad_y'],
        arrow_length_ratio=0.3, linewidth=1.8))
    drag_artists.append(ax.quiver(
        0, 0, 0, 0, 0, triad_len, color=_t['triad_z'],
        arrow_length_ratio=0.3, linewidth=1.8))

    # Axis labels — bold
    ax.set_xlabel('x [mm]', color=_t['ax_text'], fontsize=11,
                  fontweight='bold', labelpad=10)
    ax.set_ylabel('y [mm]', color=_t['ax_text'], fontsize=11,
                  fontweight='bold', labelpad=10)
    ax.set_zlabel('z [mm]', color=_t['ax_text'], fontsize=11,
                  fontweight='bold', labelpad=10)

    # Ticks: only endpoints (clean up "115.5" midpoint artefact)
    # For long axes (>= 100 mm) also include a round midpoint.
    def _endpoint_ticks(L_mm):
        if L_mm >= 100:
            mid = round(L_mm / 100) * 50   # nearest 50 mm
            if 0 < mid < L_mm:
                return [0, mid, L_mm]
        return [0, L_mm]
    ax.set_xticks(_endpoint_ticks(Lmm))
    ax.set_yticks(_endpoint_ticks(Hmm))
    ax.set_zticks(_endpoint_ticks(Lzmm))
    ax.tick_params(colors=_t['ax_text'], labelsize=9)

    # Background panes: soft grey
    try:
        for pane_axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            pane_axis.pane.fill = False
            pane_axis.pane.set_edgecolor(_t['pane_edge'])
            pane_axis._axinfo['grid'].update({
                'color': _t['pane_grid'], 'linestyle': ':', 'linewidth': 0.7,
            })
    except Exception:
        pass

    ax.set_title('3D Computational Domain\ninlet: orange · outlet: blue',
                 color=_t['ax_text'], fontsize=11, fontweight='bold', pad=10)

    # ── Mouse-wheel camera zoom (override canvas_wheel_zoom which scrolls) ──
    # Save original wheelEvent once so 2D mode can restore it.
    canvas = ax.figure.canvas
    if not hasattr(canvas, '_orig_wheel_event'):
        canvas._orig_wheel_event = canvas.wheelEvent

    # Matplotlib's mplot3d redraw is slow on a large Qt canvas. During camera
    # drag, temporarily hide decorative face fills/labels/triad so interaction
    # stays closer to wireframe speed; restore them on mouse release.
    for cid in getattr(canvas, '_tpms_fast_drag_cids', []):
        try:
            canvas.mpl_disconnect(cid)
        except Exception:
            pass
    canvas._tpms_fast_drag_cids = []

    def _fast_drag_on(evt):
        if evt.inaxes is not ax:
            return
        changed = False
        for p in drag_artists:
            if p.get_visible():
                p.set_visible(False)
                changed = True
        if changed:
            canvas.draw_idle()

    def _fast_drag_off(evt):
        changed = False
        for p in drag_artists:
            if not p.get_visible():
                p.set_visible(True)
                changed = True
        if changed:
            canvas.draw_idle()

    canvas._tpms_fast_drag_cids.append(
        canvas.mpl_connect('button_press_event', _fast_drag_on))
    canvas._tpms_fast_drag_cids.append(
        canvas.mpl_connect('button_release_event', _fast_drag_off))

    # The wheel handler stores the *intended* camera distance on the axes
    # (`_tpms_intended_dist`). matplotlib's mpl3d mouse-drag handler calls
    # `view_init(...)` which on some mpl versions (3.6 → 3.10 transition)
    # silently re-resolves `_dist` back to its default at the next draw, so
    # the zoom factor is lost as soon as the user rotates. We pin the
    # intended dist on every draw via a `draw_event` hook and re-apply it
    # on `button_release_event` for redundancy.
    def _apply_dist():
        d = getattr(ax, '_tpms_intended_dist', None)
        if d is None:
            return
        for _name in ('dist', '_dist'):
            if hasattr(ax, _name):
                try:
                    setattr(ax, _name, d)
                except Exception:
                    pass

    def _qt_wheel_zoom_3d(evt):
        delta = evt.angleDelta().y()
        if delta == 0:
            evt.ignore(); return
        factor = 0.88 if delta > 0 else 1.14
        cur_dist = float(getattr(ax, '_tpms_intended_dist',
                                 getattr(ax, '_dist',
                                         getattr(ax, 'dist', 10.0))))
        # With clip_on=False set on every artist below, content can safely
        # extend past the axes bbox, so the lower bound only has to stay
        # above mpl's degenerate-projection regime.
        new_dist = max(3.0, min(30.0, cur_dist * factor))
        ax._tpms_intended_dist = new_dist
        _apply_dist()
        canvas.draw_idle()
        evt.accept()

    canvas.wheelEvent = _qt_wheel_zoom_3d

    # Restore intended dist after rotation drag releases — covers the case
    # where mpl's view_init pathway clobbers _dist mid-rotate.
    def _reapply_after_release(evt):
        _apply_dist()
        canvas.draw_idle()
    canvas._tpms_fast_drag_cids.append(
        canvas.mpl_connect('button_release_event', _reapply_after_release))

    # Pin dist on every redraw (cheap; idempotent when no zoom set).
    def _pin_dist_on_draw(_evt):
        _apply_dist()
    canvas._tpms_fast_drag_cids.append(
        canvas.mpl_connect('draw_event', _pin_dist_on_draw))

    # Aspect ratio (soft-stretch thin axes for visibility)
    # 2026-05-20 UI sweep (Tier 22): guard against a zero/degenerate
    # dimension. If the user has L/H/Lz = 0 in the fields (or a parse
    # produced 0), `max_dim / min_dim` would ZeroDivisionError and abort
    # the whole 3D layout draw. Skip the soft-stretch when any extent is
    # non-positive — the box just renders at native aspect.
    max_dim = max(Lmm, Hmm, Lzmm)
    min_dim = min(Lmm, Hmm, Lzmm)
    if min_dim > 0 and max_dim / min_dim > 3.0:
        try:
            ax.set_box_aspect((
                1.0,
                (Hmm / max_dim) ** 0.5,
                (Lzmm / max_dim) ** 0.5))
        except Exception:
            pass
    else:
        try:
            ax.set_box_aspect((Lmm, Hmm, Lzmm))
        except Exception:
            pass

    ax.view_init(elev=22, azim=-52)
    try:
        ax.figure.subplots_adjust(left=0.0, right=1.0, top=0.94, bottom=0.0)
        # Leave room for projected z-axis labels in the narrow workbench.
        ax.set_position([0.02, 0.04, 0.84, 0.84])
    except Exception:
        pass

    # Disable axes-bbox clipping for every artist drawn here so wheel-zoom
    # can push the cuboid past the (invisible) axes rectangle without
    # truncating content. This is the root cause of the "invisible frame
    # cuts off the geometry on zoom" report — mpl3d clips Poly3D, Line3D,
    # and Text to the 2D axes bbox at draw time. The 3D axes already fills
    # ~96 % of the figure (set_position above), so disabling clip here
    # only lets the cuboid bleed into the remaining figure margin instead
    # of disappearing.
    try:
        for _coll in ax.collections:
            _coll.set_clip_on(False)
        for _line in ax.lines:
            _line.set_clip_on(False)
        for _txt in ax.texts:
            _txt.set_clip_on(False)
        for _lbl in (ax.xaxis.label, ax.yaxis.label, ax.zaxis.label,
                     ax.title):
            try:
                _lbl.set_clip_on(False)
            except Exception:
                pass
    except Exception:
        pass


def draw_layout_rect(window, ax, L, H, Lmm, Hmm):
    """Ex-Main_Menu._draw_layout_rect(self, ax, L, H, Lmm, Hmm)."""
    _t = get_theme()
    from matplotlib.patches import Rectangle
    try:
        cfgA = window._fluid_config('A')
        cfgB = window._fluid_config('B')
    except ValueError:
        cfgA = dict(dir=0, in_ctr=H/2, in_w=H, out_ctr=H/2, out_w=H)
        cfgB = dict(dir=3, in_ctr=L/2, in_w=L, out_ctr=L/2, out_w=L)

    ax.add_patch(Rectangle((0, 0), Lmm, Hmm, fill=False, ec=_t['ax_text'], lw=2))

    def _draw_pipe(cfg, label, color, is_inlet):
        d = cfg['dir']
        ctr = (cfg['in_ctr'] if is_inlet else cfg['out_ctr']) * 1000
        w   = (cfg['in_w']   if is_inlet else cfg['out_w'])   * 1000
        lo = ctr - w/2
        wall = window._inlet_wall(d) if is_inlet else window._outlet_wall(d)
        tag = f"{label} {'in' if is_inlet else 'out'}"
        if wall == 'left':
            ax.add_patch(Rectangle((-1.5, lo), 1.2, w, fc=color, ec='none', alpha=0.85))
            ax.annotate(tag, xy=(-3, ctr), fontsize=7, color=color,
                        ha='right', va='center', fontweight='bold')
        elif wall == 'right':
            ax.add_patch(Rectangle((Lmm+0.3, lo), 1.2, w, fc=color, ec='none', alpha=0.85))
            ax.annotate(tag, xy=(Lmm+3, ctr), fontsize=7, color=color,
                        ha='left', va='center', fontweight='bold')
        elif wall == 'bottom':
            ax.add_patch(Rectangle((lo, -1.5), w, 1.2, fc=color, ec='none', alpha=0.85))
            ax.annotate(tag, xy=(ctr, -3.5), fontsize=7, color=color,
                        ha='center', va='top', fontweight='bold')
        else:
            ax.add_patch(Rectangle((lo, Hmm+0.3), w, 1.2, fc=color, ec='none', alpha=0.85))
            ax.annotate(tag, xy=(ctr, Hmm+3.5), fontsize=7, color=color,
                        ha='center', va='bottom', fontweight='bold')

    _draw_pipe(cfgA, 'A', _t['inlet_color'], True)
    _draw_pipe(cfgA, 'A', _t['inlet_color'], False)
    _draw_pipe(cfgB, 'B', _t['outlet_color'], True)
    _draw_pipe(cfgB, 'B', _t['outlet_color'], False)

    # Flow arrows
    cx, cy = Lmm / 2, Hmm / 2
    def _arrow(d, color):
        dx = Lmm * 0.2; dy = Hmm * 0.2
        arrows = {0: (cx-dx, cy, cx+dx, cy), 1: (cx+dx, cy, cx-dx, cy),
                  2: (cx, cy-dy, cx, cy+dy), 3: (cx, cy+dy, cx, cy-dy)}
        x0, y0, x1, y1 = arrows[d]
        ax.annotate('', xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(arrowstyle='->', color=color, lw=1.5))
    _arrow(cfgA['dir'], _t['inlet_color'])
    _arrow(cfgB['dir'], _t['outlet_color'])

    # Zone boundaries and labels
    if window.chk_zones.isChecked():
        z_ax = window._zone_axis()
        from matplotlib.patches import Rectangle as Rect
        ncols = window.zone_table.columnCount()

        if z_ax == 'grid':
            # Grid mode: 6 columns [y0%,y1%,x0%,x1%,L,t]
            for r in range(window.zone_table.rowCount()):
                items = [window.zone_table.item(r, c) for c in range(ncols)]
                if any(it is None or not it.text().strip() for it in items):
                    continue
                yf0 = float(items[0].text())/100; yf1 = float(items[1].text())/100
                xf0 = float(items[2].text())/100; xf1 = float(items[3].text())/100
                x0 = xf0*Lmm; x1 = xf1*Lmm; y0 = yf0*Hmm; y1 = yf1*Hmm
                alpha = 0.08 if r % 2 == 0 else 0.15
                ax.add_patch(Rect((x0,y0), x1-x0, y1-y0,
                                  fc=_t['zone_fill'], ec=_t['zone_fill'], alpha=alpha, lw=0.5))
                L_z, t_z = items[4].text(), items[5].text()
                # Label inside each cell, small font
                ax.text((x0+x1)/2, (y0+y1)/2, f'{L_z}/{t_z}',
                        color=_t['zone_fill'], fontsize=5, ha='center', va='center', alpha=0.8)
        else:
            # 1D mode: 4 columns [start%,end%,L,t]
            for r in range(window.zone_table.rowCount()):
                items = [window.zone_table.item(r, c) for c in range(4)]
                if any(it is None or not it.text().strip() for it in items):
                    continue
                f0 = float(items[0].text())/100; f1 = float(items[1].text())/100
                L_z, t_z = items[2].text(), items[3].text()
                alpha = 0.08 if r % 2 == 0 else 0.15

                if z_ax == 'y':
                    p0 = f0*Hmm; p1 = f1*Hmm
                    ax.add_patch(Rect((0,p0), Lmm, p1-p0,
                                      fc=_t['zone_fill'], ec='none', alpha=alpha))
                    # Label inside zone, right-aligned, avoid pipe labels
                    ax.text(Lmm*0.95, (p0+p1)/2, f'L={L_z} t={t_z}',
                            color=_t['zone_fill'], fontsize=6, va='center', ha='right', alpha=0.9)
                    if f0 > 0.001:
                        ax.axhline(y=p0, color=_t['zone_fill'], ls='--', lw=0.8, alpha=0.6)
                else:
                    p0 = f0*Lmm; p1 = f1*Lmm
                    ax.add_patch(Rect((p0,0), p1-p0, Hmm,
                                      fc=_t['zone_fill'], ec='none', alpha=alpha))
                    ax.text((p0+p1)/2, Hmm*0.05, f'L={L_z}\nt={t_z}',
                            color=_t['zone_fill'], fontsize=5, va='bottom', ha='center', alpha=0.9)
                    if f0 > 0.001:
                        ax.axvline(x=p0, color=_t['zone_fill'], ls='--', lw=0.8, alpha=0.6)

    ax.text(cx, cy, 'TPMS\nDomain', color=_t['ax_text'], ha='center', va='center',
            fontsize=10, fontweight='bold', alpha=0.3)

    # Paint draggable zone-boundary handles so users can re-partition the
    # domain directly on the canvas. Falls back silently if the handle
    # manager is not wired (e.g., first-boot before install).
    zmgr = getattr(window, '_zone_handle_mgr', None)
    if zmgr is not None:
        try:
            zmgr.draw_handles(ax, Lmm, Hmm)
        except Exception:
            pass
    ax.set_xlim(-8, Lmm + 8); ax.set_ylim(-8, Hmm + 8)
    dA = window._DIR_MAP[cfgA['dir']]; dB = window._DIR_MAP[cfgB['dir']]
    ax.set_title(f'Geometry: {Lmm:.0f}x{Hmm:.0f}mm | A:{dA} B:{dB}',
                 color=_t['ax_text'], fontsize=10)
