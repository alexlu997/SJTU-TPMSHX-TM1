"""Shared 3D display order, color-range helpers, and plane-widget styling."""
from __future__ import annotations

from math import isfinite

import numpy as np

from tm1.postprocess.result_display import PANEL_FIELD_SPECS

# Display order for 3D panel field selectors (persisted 3D keys).
FIELD_ORDER = tuple(PANEL_FIELD_SPECS)


def field_color_limits(fields, shared=False):
    """Use complete field ranges; keep constant fields readable."""
    limits = [(float(np.min(a)), float(np.max(a))) for a in fields]
    if shared:
        limits = [(min(lo for lo, hi in limits), max(hi for lo, hi in limits))] * len(limits)
    # Leave room for distinct contour levels in fields at rounding precision.
    return [(lo, hi if hi - lo > max(abs(lo), abs(hi), 1.) * np.finfo(float).eps * 256
             else lo + max(abs(lo) * 1e-6, 1e-9))
            for lo, hi in limits]


def field_tick_format(limits):
    """Keep adjacent labels distinct on narrow physical ranges."""
    step = (limits[1] - limits[0]) / 4
    digits = max(0, int(np.ceil(-np.log10(step))) + 1)
    return f'%.{digits}f'


def validate_color_range_state(state):
    """Validate saved display ranges before changing a window or a panel."""
    if not isinstance(state, dict) or set(state) - {'mode', 'ranges'}:
        raise ValueError('Invalid 3D color-range state')
    mode, ranges = state.get('mode', 'global'), state.get('ranges', {})
    if mode not in ('global', 'local', 'custom') or not isinstance(ranges, dict):
        raise ValueError('Invalid 3D color-range mode or ranges')
    checked = {}
    for key, limits in ranges.items():
        if key not in PANEL_FIELD_SPECS or not isinstance(limits, (list, tuple)) or len(limits) != 2:
            raise ValueError('3D color ranges require a known field and two limits')
        lo, hi = map(float, limits)
        if not (isfinite(lo) and isfinite(hi) and hi > lo):
            raise ValueError('3D color ranges require finite Max > Min')
        checked[key] = [lo, hi]
    return {'mode': mode, 'ranges': checked}


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
