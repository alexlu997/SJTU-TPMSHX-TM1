"""Vertices for viewing and saving retired polygon-domain presets.

Polygon computation is retired; see docs/history/retired-tools.md.
"""
import numpy as np


def hexagon(W, H):
    """Elongated hexagon fitting inside W × H bounding box."""
    dx = W * 0.15
    return np.array([
        [dx, 0], [W - dx, 0], [W, H / 2], [W - dx, H], [dx, H], [0, H / 2]
    ], dtype=np.float64)


def octagon(W, H):
    """Octagon fitting inside W × H bounding box."""
    dx = W * 0.2
    dy = H * 0.2
    return np.array([
        [dx, 0], [W - dx, 0], [W, dy], [W, H - dy],
        [W - dx, H], [dx, H], [0, H - dy], [0, dy]
    ], dtype=np.float64)
