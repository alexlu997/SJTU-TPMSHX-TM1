"""vis3d_constants.py — shared constants + helpers for 3D visualisation.

Consolidates `FIELD_META` / `FIELD_ORDER` and the `vtkImplicitPlaneRepresentation`
cosmetic toning used by both the embedded `ui/panel_vis_3d.py` and the
standalone `runs/demos/demo_vis_3d_interactive.py` so they stay in sync.
"""
from __future__ import annotations

from .theme import FIELD_CMAP

# Display order + per-field rendering metadata.
# Physical and design fields share the GUI colormap.
FIELD_ORDER = [
    'Ta', 'Tb', 'Ts',
    'vmag', 'vmag_B',
    'P_kPa', 'P_B_kPa',
    'L_mm', 't_mm',
]
FIELD_META = {
    # Titles carry NO underscore: this string also feeds the VTK colorbar,
    # which renders plain text only (no HTML/mathtext subscripts). The Qt KPI
    # strip does its own HTML subscripts; here we keep clean underscore-free
    # names (Ta/Tb/Ts) that read fine in VTK, matplotlib and Qt alike.
    'Ta':      {'cmap': FIELD_CMAP, 'title': 'Ta (K)',          'fmt': '%.1f',
                'label': 'Temperature A'},
    'Tb':      {'cmap': FIELD_CMAP, 'title': 'Tb (K)',          'fmt': '%.1f',
                'label': 'Temperature B'},
    'Ts':      {'cmap': FIELD_CMAP, 'title': 'Ts (K)',          'fmt': '%.1f',
                'label': 'Temperature Solid'},
    'vmag':    {'cmap': FIELD_CMAP, 'title': 'speed A (m/s)',   'fmt': '%.2f',
                'label': 'Velocity A'},
    'vmag_B':  {'cmap': FIELD_CMAP, 'title': 'speed B (m/s)',   'fmt': '%.2f',
                'label': 'Velocity B'},
    'P_kPa':   {'cmap': FIELD_CMAP, 'title': 'PA abs (kPa)',    'fmt': '%.1f',
                'label': 'Pressure A'},
    'P_B_kPa': {'cmap': FIELD_CMAP, 'title': 'PB abs (kPa)',    'fmt': '%.1f',
                'label': 'Pressure B'},
    'L_mm':    {'cmap': FIELD_CMAP, 'title': 'L (mm)',          'fmt': '%.2f',
                'label': 'Design L'},
    't_mm':    {'cmap': FIELD_CMAP, 'title': 't (mm)',          'fmt': '%.3f',
                'label': 'Wall thickness t'},
}


def tone_down_plane_widget(plotter, *,
                           slate=(0.30, 0.35, 0.40),
                           line_width=1.0, outline_opacity=0.45,
                           arrow_opacity=0.55):
    """Mute the `vtkImplicitPlaneWidget` cosmetics per Gemini review.

    - Hide the translucent plane handle (slice already renders the data).
    - Slate-grey outline + edges, half-opaque (not pitch-black, not bold).
    - Normal arrow half-opacity so data stays visually dominant.
    Robust against VTK API differences: every call is wrapped try/except.
    """
    try:
        widgets = list(getattr(plotter, 'plane_widgets', []))
    except Exception:
        return
    for w in widgets:
        try:
            rep = w.GetRepresentation()
        except Exception:
            continue
        _safe_setattr(rep, 'GetPlaneProperty', 'SetOpacity', 0.0)
        for g in ('GetOutlineProperty', 'GetEdgesProperty',
                  'GetSelectedOutlineProperty'):
            p = _safe_get(rep, g)
            if p is None:
                continue
            try:
                p.SetColor(*slate)
                p.SetLineWidth(line_width)
                p.SetOpacity(outline_opacity)
            except Exception:
                pass
        narrow = _safe_get(rep, 'GetNormalProperty')
        if narrow is not None:
            try:
                narrow.SetOpacity(arrow_opacity)
                narrow.SetColor(*slate)
            except Exception:
                pass


def _safe_get(rep, getter_name):
    getter = getattr(rep, getter_name, None)
    if getter is None:
        return None
    try:
        return getter()
    except Exception:
        return None


def _safe_setattr(rep, getter_name, setter_name, *args):
    prop = _safe_get(rep, getter_name)
    if prop is None:
        return
    setter = getattr(prop, setter_name, None)
    if setter is None:
        return
    try:
        setter(*args)
    except Exception:
        pass
