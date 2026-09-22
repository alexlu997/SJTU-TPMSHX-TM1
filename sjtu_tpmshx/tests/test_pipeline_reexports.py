"""Retained solver-kernel and UI-builder import surfaces.

Research/tests still use these kernel exports. Former stages_2d/stages_3d
consumers now import preparation, shared models and numerical entries directly;
their existing behavior tests continue at those owning modules.
"""
from __future__ import annotations

import importlib

import pytest


_SURFACE = {
    'sjtu_tpmshx.solvers.simple_solver': [
        'SIMPLESolver', '_aligned_grid', 'build_wall_refined_1d',
        '_sweep_u_jit_df', '_sweep_v_jit_df', '_porous_src_df', '_umag_u', '_umag_v',
        '_sou_corr_u_x', '_sou_corr_u_y', '_sou_corr_v_x', '_sou_corr_v_y',
        '_solve_pp_sparse_fast', '_build_pp_sparsity_pattern',
        '_correct_jit', '_mass_res_jit',
        '_assemble_pp_data_jit',
    ],
    'sjtu_tpmshx.solvers.simple_solver_3d': [
        'SIMPLESolver3D', '_v_bc_3d', '_correct_jit_3d', '_sou_axis',
        '_mass_res_jit_3d', '_assemble_pp_3d',
        '_sweep_u_jit_df_3d', '_sweep_v_jit_df_3d', '_sweep_w_jit_df_3d',
    ],
    'sjtu_tpmshx.solvers.ltne_energy_3d': [
        'solve_full_domain_3d', 'energy_balance_3d', 'mass_balance_3d',
        '_project_faces_div_free',
        '_gs_full_chunk_3d', '_gs_full_chunk_3d_stag',
        '_gs_full_chunk_3d_stag_rb',
    ],
    'sjtu_tpmshx.ui.builders_canvas': [
        '_build_result_sidebar',
        'update_result_sidebar_visibility', 'build_canvas_area',
    ],
}


@pytest.mark.parametrize('module_name', sorted(_SURFACE))
def test_reexport_surface(module_name):
    mod = importlib.import_module(module_name)
    missing = [n for n in _SURFACE[module_name] if not hasattr(mod, n)]
    assert not missing, (
        f"{module_name} lost re-exported names: {missing} — external "
        f"consumers (tests, runs/, validation/) import these from here.")
