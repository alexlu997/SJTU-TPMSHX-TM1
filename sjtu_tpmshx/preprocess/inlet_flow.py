"""Total inlet mass per unit interstitial speed on prepared physical faces."""
from math import isfinite

import numpy as np


def _inlet_mass_capacity(design_fields, prepared, side):
    axis = prepared['axes'][side]
    eps_in = np.take(design_fields['eps_' + side],
                     -1 if axis['is_reverse'] else 0, axis=axis['stream_real_axis'])
    area = np.asarray(axis['dcross1'])[:, None] * np.asarray(axis['dcross2'])[None, :]
    pore_area = float(np.sum(eps_in * prepared['openings'][side]['inlet'] * area))
    capacity = prepared['properties'][side]['rho'] * pore_area
    if not isfinite(capacity) or capacity <= 0:
        raise ValueError(f'side {side}: inlet density times open pore area must be finite and positive')
    return capacity


def total_inlet_mass_capacity(design, parameters, grid, side):
    if grid['dimension'] == 3:
        return _inlet_mass_capacity(design, parameters['prepared'], side)
    geometry = parameters['run_settings']['geometry']
    depth = geometry['Lz_m']
    if depth is None or not isfinite(depth) or depth <= 0:
        raise ValueError('2D total mass flow requires a positive physical Lz_m')
    if geometry['delta_levelset'] != 0:
        raise ValueError('2D fixed-flow optimization currently requires delta_levelset=0')
    direction = parameters['cfg' + side]['dir']
    axis = direction // 2
    eps_in = np.take(design['eps_arr'], -1 if direction % 2 else 0, axis=axis) / 2.
    widths = grid['dy' if axis == 0 else 'dx']
    openings = parameters['boundary_openings'][side]
    opening = openings['in_profile_frac']
    geometric = openings['in_geom_frac']
    # SIMPLE normalizes the tapered speed profile to the geometric open area.
    # Keep epsilon inside the profile integral: it can vary across the inlet.
    scale = 1.0
    if np.any(opening != geometric):
        geometric_area = float(np.sum(geometric * widths))
        profile_area = float(np.sum(opening * widths))
        if profile_area > 1e-30 and geometric_area > 0.0:
            scale = geometric_area / profile_area
    capacity = (parameters['static_properties'][side]['rho']
                * float(np.sum(eps_in * opening * widths)) * depth * scale)
    if not isfinite(capacity) or capacity <= 0:
        raise ValueError(f'side {side}: inlet density times open pore area must be finite and positive')
    return capacity
