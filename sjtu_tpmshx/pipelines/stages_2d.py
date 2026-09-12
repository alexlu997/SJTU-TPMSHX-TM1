"""Historical 2D input and numerical-stage entry points.

Applications use controllers.compute_pipeline and the three public modules.
"""
from __future__ import annotations

import os

import numpy as np
from sjtu_tpmshx.domain.compute_config import ComputeConfig, bc_to_dict
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.models.tpms_calc import compute as tpms_compute, geometry as tpms_geometry
from sjtu_tpmshx.solvers.df_projection import override_simple_K_cF, extract_dP_from_simple
from sjtu_tpmshx.pipelines._stage_common import (
    validate_domain_dims, surrogate_extrap_reasons,
)
from sjtu_tpmshx.logutil import get_logger

# Scripted numerical-stage entry points.
from sjtu_tpmshx.solvers.backends.python.two_d.coupling import (
    _enthalpy_balance_2d, _compute_pressure_2d,
    _compute_Q_richardson, _run_solvers,
)

_log = get_logger(__name__)


# B2 2.1b (2026-06-13): the legacy window entrypoints
# run_calculation_inner / run_calculation_inner_cfg and the
# _parse_inputs window adapter were DELETED — the GUI 2D path now drives
# controllers.compute_pipeline.Pipeline2D (cfg-only stage functions
# below) and copies the ComputeResult back via Main_Menu.write_result.


from sjtu_tpmshx.preprocess.two_d.preparation import (
    _check_zoned_fluid_support, _parse_inputs_cfg, _prepare_grid,
)
