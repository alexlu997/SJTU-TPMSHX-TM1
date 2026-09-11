"""Re-export surface locks (openspec maintainability-closeout, 2026-07-03).

The 2026-07-03 splits moved engine code out of stages_2d/stages_3d and the
solver kernels out of simple_solver/simple_solver_3d/ltne_energy_3d, with
the originals re-exporting every moved name so the external import surface
stayed put. Those re-export blocks were locked only incidentally (tests
importing a subset). This file locks the FULL surface — deleting any
re-exported name is now a test failure, not a runtime surprise in some
runs/ script.
"""
from __future__ import annotations

import importlib

import pytest


_SURFACE = {
    'sjtu_tpmshx.pipelines.stages_2d': [
        # cfg boundary (kept)
        '_check_zoned_fluid_support', '_parse_inputs_cfg',
        '_build_fields_cfg',
        # re-exported from solve_2d
        '_enthalpy_balance_2d', '_compute_pressure_2d',
        '_compute_Q_richardson', '_run_solvers',
    ],
    'sjtu_tpmshx.pipelines.stages_3d': [
        # cfg boundary (kept)
        '_parse_inputs_3d_cfg', '_build_fields_3d_cfg',
        '_run_solvers_3d_cfg',
        # flux_3d
        '_resolve_ui_roughness', '_face_flux_weights',
        '_mass_weighted_T_out', '_mass_weighted_h_out',
        '_sco2_hv_local_field', '_simple_mass_flow',
        '_apply_roughness_KcF', '_apply_roughness_h_v',
        # grid_3d
        '_resolve_axis_map', '_build_zone_fields_3d', '_build_grid_3d',
        '_solver_spacings',
        # run_stack_3d
        '_seed_p_ref', '_simple_tol_default', '_apply_phase_flags',
        '_apply_accel_flags', '_prof_3d_enabled', '_prof_res_trace',
        '_run_two_simple_parallel', '_conservation_diagnostics_3d',
        '_run_3d_stack',
        # asym + helpers passthrough
        '_asym_split_A', '_eps_sides_for_run', '_per_side_eps_override',
        '_build_chi_B_mass_flux_threshold',
    ],
    'sjtu_tpmshx.solvers.simple_solver': [
        'SIMPLESolver', '_aligned_grid', 'build_wall_refined_1d',
        'build_inlet_stretched_1d',
        '_sweep_u_jit_df', '_sweep_v_jit_df', '_pseudo_u_jit_df',
        '_pseudo_v_jit_df', '_porous_src_df', '_umag_u', '_umag_v',
        '_sou_corr_u_x', '_sou_corr_u_y', '_sou_corr_v_x', '_sou_corr_v_y',
        '_solve_pp_sparse_fast', '_build_pp_sparsity_pattern',
        '_correct_jit', '_mass_res_jit', '_solve_temp_jit',
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
        '_build_result_sidebar', 'refresh_result_sidebar',
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
