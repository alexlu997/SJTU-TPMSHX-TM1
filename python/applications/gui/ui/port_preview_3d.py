"""Draw the 3D case geometry and its inlet and outlet ports."""
import numpy as np

from .theme import get_theme


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

    FLUID_COLORS = {
        'A': _t['inlet_color'],
        'B': _t['outlet_color'],
    }
    face_alpha = 0.30
    arrow_scale = max(Lmm, Hmm, Lzmm) * 0.14

    def _draw_fluid(cfg, label_tag):
        """Draw fluid A or B inlet/outlet ports colored by fluid with Chinese span callouts."""
        from tm1.data_types.validator import cross_axes_for_dir
        d = cfg['dir']
        normal = d // 2
        cross_names = cross_axes_for_dir(d)
        cross = ['XYZ'.index(axis) for axis in cross_names]
        extents = [Lmm, Hmm, Lzmm]
        color = FLUID_COLORS[label_tag]
        for end, zh_end in (('in', '入口'), ('out', '出口')):
            at_high_face = (d % 2 == 1) if end == 'in' else (d % 2 == 0)
            face = extents[normal] if at_high_face else 0.
            outward = 1.0 if at_high_face else -1.0
            ctr = cfg[f'{end}_ctr'] * 1000
            width = cfg[f'{end}_w'] * 1000
            ctr2 = cfg.get(f'{end}_z_ctr')
            width2 = cfg.get(f'{end}_z_w')
            ctr2 = extents[cross[1]] / 2 if ctr2 is None else ctr2 * 1000
            width2 = extents[cross[1]] if width2 is None else width2 * 1000
            lo, hi = max(0., ctr - width / 2), min(extents[cross[0]], ctr + width / 2)
            lo2, hi2 = max(0., ctr2 - width2 / 2), min(extents[cross[1]], ctr2 + width2 / 2)
            verts = []
            for first, second in ((lo, lo2), (hi, lo2), (hi, hi2), (lo, hi2)):
                point = [0., 0., 0.]
                point[normal], point[cross[0]], point[cross[1]] = face, first, second
                verts.append(point)
            _face_patch(verts, color, face_alpha)

            # External flow arrow (inlet points IN toward face; outlet points OUT away from face)
            arrow_start = [0., 0., 0.]
            arrow_start[normal], arrow_start[cross[0]], arrow_start[cross[1]] = (
                face + outward * (arrow_scale if end == 'in' else arrow_scale * 0.15),
                (lo + hi) / 2.0,
                (lo2 + hi2) / 2.0,
            )
            vec = [0., 0., 0.]
            vec[normal] = (-outward if end == 'in' else outward) * arrow_scale * 0.85
            drag_artists.append(ax.quiver(
                arrow_start[0], arrow_start[1], arrow_start[2],
                vec[0], vec[1], vec[2],
                color=color, arrow_length_ratio=0.35, linewidth=1.8,
            ))

            # Callout label positioned cleanly outside the port face with physical mm spans
            pos = [0., 0., 0.]
            pos[normal] = face + outward * (arrow_scale * 1.35)
            pos[cross[0]] = (lo + hi) / 2.0
            pos[cross[1]] = (lo2 + hi2) / 2.0
            a1, a2 = cross_names[0].lower(), cross_names[1].lower()
            span_line = f"{a1} {lo:g}–{hi:g} · {a2} {lo2:g}–{hi2:g}"
            drag_artists.append(ax.text(
                *pos, f"{label_tag} {zh_end}\n{span_line}",
                color=color, fontsize=8.5, fontweight='semibold',
                ha='center', va='center',
                bbox=dict(
                    boxstyle='round,pad=0.3',
                    facecolor=_t['popover'],
                    edgecolor=color,
                    linewidth=0.8,
                    alpha=0.92,
                ),
            ))

    try:
        fA = window._fluid_config('A')
        _draw_fluid(fA, 'A')
    except Exception as _fa_err:
        if hasattr(window, 'dialogs'):
            window.dialogs.notify(
                f"Layout: Fluid A skipped — {_fa_err}", kind="warn", duration_ms=4000
            )

    try:
        fB = window._fluid_config('B')
        _draw_fluid(fB, 'B')
    except Exception as _fb_err:
        if hasattr(window, 'dialogs'):
            window.dialogs.notify(
                f"Layout: Fluid B skipped — {_fb_err}", kind="warn", duration_ms=4000
            )

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

    from .symbols import MPL

    # Axis labels — ISO italic quantities with upright units
    ax.set_xlabel(MPL["x_mm"], color=_t['ax_text'], fontsize=11,
                  fontweight='bold', labelpad=10)
    ax.set_ylabel(MPL["y_mm"], color=_t['ax_text'], fontsize=11,
                  fontweight='bold', labelpad=10)
    ax.set_zlabel(MPL["z_mm"], color=_t['ax_text'], fontsize=11,
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

    ax.set_title('计算域', color=_t['ax_text'], fontsize=11, fontweight='bold', pad=10)

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
