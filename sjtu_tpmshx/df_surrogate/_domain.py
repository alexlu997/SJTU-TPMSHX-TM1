"""Current water+sCO2 CFD geometry grid and allowed optimization bounds.

These geometry bounds do not extend any fluid's Nu applicability window.
"""
from __future__ import annotations

# Continuous convex hull (extrapolation-guard bounds).
TRAIN_L = (4.0, 8.0)          # unit cell size L [mm]
TRAIN_T = (0.3, 0.6)          # wall thickness t [mm]

# Discrete training grid nodes (the geometries actually fitted).
TRAIN_L_NODES = (4.0, 5.0, 6.0, 7.0, 8.0)
TRAIN_T_NODES = (0.3, 0.4, 0.5, 0.6)
