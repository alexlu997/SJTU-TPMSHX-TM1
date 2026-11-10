"""Total inlet mass per unit interstitial speed on prepared physical faces."""
from math import isfinite

import numpy as np

from sjtu_tpmshx.shared.models import _native_flow


def _inlet_mass_capacity(design_fields, prepared, side):
    axis = prepared['axes'][side]
    direction = axis['stream_real_axis'] * 2 + int(axis['is_reverse'])
    capacity = _native_flow.capacity_3d(
        design_fields['eps_' + side], direction, axis['dcross1'], axis['dcross2'],
        prepared['openings'][side]['inlet'], prepared['properties'][side]['rho'])
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
    eps_in = np.take(design['eps_arr'], -1 if direction % 2 else 0, axis=axis)
    widths = grid['dy' if axis == 0 else 'dx']
    openings = parameters['boundary_openings'][side]
    opening = openings['in_profile_frac']
    geometric = openings['in_geom_frac']
    capacity = _native_flow.capacity_2d(
        eps_in, opening, geometric, widths, parameters['static_properties'][side]['rho'], depth)
    if not isfinite(capacity) or capacity <= 0:
        raise ValueError(f'side {side}: inlet density times open pore area must be finite and positive')
    return capacity
