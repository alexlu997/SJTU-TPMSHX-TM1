"""Build port masks and map 3D fields to physical coordinates.

Preparation and native result packing use the port helpers. Tests retain the
coordinate transforms as independent native mapping references.
"""
from __future__ import annotations

import numpy as np


def _port_rectangles(fluid_cfg, cross2_length):
    """Keep the original physical edges; reversing flow never swaps ports."""
    result = {}
    for end in ('in', 'out'):
        center, width = fluid_cfg.get(f'{end}_z_ctr'), fluid_cfg.get(f'{end}_z_w')
        if center is None and width is None:
            center, width = cross2_length / 2, cross2_length
        elif center is None or width is None:
            raise ValueError(f'{end} second-cross-axis centre and width must be set together')
        result[f'{end}let_rect'] = (
            fluid_cfg[f'{end}_ctr'] - fluid_cfg[f'{end}_w'] / 2,
            fluid_cfg[f'{end}_ctr'] + fluid_cfg[f'{end}_w'] / 2,
            center - width / 2, center + width / 2)
    return result


def _build_partial_masks(fA, dcross1, dcross2, N_cross2):
    """Build inlet/outlet exact open-area fractions on the 2-axis inlet face.

    Solver's inlet_frac shape is (Nx_sol, Nz_sol) = (N_cross1, N_cross2).
    UI inputs `in_ctr/in_w` → cross1 axis; `in_z_ctr/in_z_w` → cross2 axis.
    For ±x/±y streamwise cross2 is real-z; for ±z streamwise cross2 is real-y.
    (Semantic mismatch noted in UI docs — future UI pass may relabel.)
    """
    from sjtu_tpmshx.development.tests.grid_source_reference import _port_fractions_1d
    in_lo = fA['in_ctr'] - fA['in_w'] / 2
    in_hi = fA['in_ctr'] + fA['in_w'] / 2
    out_lo = fA['out_ctr'] - fA['out_w'] / 2
    out_hi = fA['out_ctr'] + fA['out_w'] / 2
    in_c1, _ = _port_fractions_1d(dcross1, in_lo, in_hi)
    out_c1, _ = _port_fractions_1d(dcross1, out_lo, out_hi)
    if not in_c1.any() or not out_c1.any():
        raise ValueError("Inlet / outlet range (cross1) resolves to zero cells.")

    # cross2 (z-partial keys — treated as second cross-axis regardless of label)
    cross2 = []
    for end in ('in', 'out'):
        center, width = fA.get(f'{end}_z_ctr'), fA.get(f'{end}_z_w')
        if (center is None) != (width is None):
            raise ValueError(f'{end} second-cross-axis centre and width must be set together')
        if center is None or dcross2 is None:
            fractions = np.ones(N_cross2, dtype=bool)
        else:
            fractions, _ = _port_fractions_1d(dcross2, center - width / 2, center + width / 2)
            if not fractions.any():
                raise ValueError("Inlet / outlet range (cross2) resolves to zero cells.")
        cross2.append(fractions)
    in_c2, out_c2 = cross2
    # approach-(a) reverse convention: NO in/out swap. The solver always
    # injects at j=0 with inlet_frac and exhausts at j=-1 with outlet_frac;
    # the reverse-dir spatial flip (in the velocity transforms) maps solver
    # j=0 onto the real inlet end, so in_mask must carry the PHYSICAL inlet
    # patch (in_ctr) regardless of direction. (Was: swap in_c<->out_c for
    # is_reverse — that was approach-(b) and contradicted the LTNE kernel.)
    in_mask = np.outer(in_c1, in_c2).astype(np.float64)   # (N_cross1, N_cross2)
    out_mask = np.outer(out_c1, out_c2).astype(np.float64)
    return in_mask, out_mask


