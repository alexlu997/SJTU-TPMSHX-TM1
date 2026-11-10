"""Current water+sCO2 CFD geometry grid and allowed optimization bounds.

These geometry bounds do not extend any fluid's Nu applicability window.
"""
from __future__ import annotations

from sjtu_tpmshx.shared.configs.model_parameters import load_preparation_df_parameters

_DATA = load_preparation_df_parameters()['domain']
TRAIN_L_NODES = tuple(_DATA['L_nodes_mm'])
TRAIN_T_NODES = tuple(_DATA['t_nodes_mm'])
TRAIN_L = (TRAIN_L_NODES[0], TRAIN_L_NODES[-1])
TRAIN_T = (TRAIN_T_NODES[0], TRAIN_T_NODES[-1])
