"""Adapt physical 3D port data for the native geometry core."""
from sjtu_tpmshx.shared.models import _native_grid


def _port_rectangles(fluid_cfg, cross2_length):
    """Return physical inlet/outlet edges without a reverse-flow swap."""
    return _native_grid.rectangles(fluid_cfg, cross2_length)


def _build_partial_masks(fA, dcross1, dcross2, N_cross2):
    """Return float64 native opening fractions on both cross axes."""
    return _native_grid.partial_masks(fA, dcross1, dcross2, N_cross2)
