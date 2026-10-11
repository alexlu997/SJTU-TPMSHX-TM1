"""Prepare explicit synthetic 3D studies for the public CaseData solver.

Research inputs use metres, kelvin, pascals and m/s, except Lcell/t_wall in
millimetres. Their prescribed porosity and inactive B phase are intentional;
ordinary ComputeConfig preparation retains its geometry and dual-fluid rules.
"""
from copy import deepcopy
from dataclasses import asdict, replace

import numpy as np

from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, Sco2NuConfig,
    ZoneInputConfig, reject_retired_boundary_options,
)
from sjtu_tpmshx.domain.run_environment import capture_environment, require_f2_mode
from sjtu_tpmshx.domain.validator import validate_pipe_config
from sjtu_tpmshx.models.input_validation import validate_domain_dims
from .preparation import _prepare_problem_data, _case_from_prepared


_INPUTS = frozenset('''
    L H Lz Nx Ny Nz Lcell t_wall k_s tpms_type eps D_h
    u_A u_B T_inA T_inB P_inA P_inB T_s_init fluid_type_A fluid_type_B
    fluid_A_cfg fluid_B_cfg wall_refine_3d port_wall_refine zone_grid_cells
    continuous_field delta_levelset df_mode sco2_nu envelope_mode extrap_reasons
    sweep_profile max_outer_ltne max_iter_simple max_cells_3d outer_tol_K
    convergence_mode mom_tol mass_local_tol mass_global_tol
    use_adaptive_amg_tol use_anderson use_coarse_bootstrap coarse_bootstrap_max_iter
    track_momentum_residual p_in_shooting variable_rho_cp conservative_ltne
    strict_mass_balance force_cc_ltne outer_anderson outer_anderson_m
    outer_anderson_trust outer_anderson_patience ltne_alpha_T
    ltne_enthalpy_nsweep ltne_enthalpy_omega ltne_enthalpy_outer ltne_enthalpy_tol
    disp_C_A disp_C_B mms_S_A_field mms_S_B_field mms_S_s_field
    _case_label _emit_audit _verbose_diag
'''.split())


def prepare_research_case(inputs, *, case_id):
    """Validate a research specification and freeze its effective physical data.

    Unknown settings and runtime callbacks are rejected. ``fluid_B_cfg=None``
    disables B; a one-pass budget remains an unconverged numerical experiment.
    The existing Python research modes are retained without implying native
    backend support. Execution and callbacks use solvers.api.run_case/RunControl.
    """
    cfg = deepcopy(dict(inputs))
    reject_retired_boundary_options(cfg)
    for key, port in (('_cancel_check', 'cancel_check'),
                      ('_progress_cb', 'progress'), ('_iter_cb', 'outer_iteration')):
        if key in cfg:
            raise ValueError(f'{key} is no longer supported in cfg; '
                             f'pass control=RunControl({port}=...) to run_case instead')
    unknown = cfg.keys() - _INPUTS
    if unknown:
        raise ValueError(f'unknown research inputs: {sorted(unknown)}')
    required = set('L H Lz Nx Ny Nz Lcell t_wall k_s tpms_type eps u_A T_inA T_inB P_inA fluid_A_cfg fluid_B_cfg'.split())
    if required - cfg.keys():
        raise ValueError(f'missing research inputs: {sorted(required - cfg.keys())}')
    for key in ('L', 'H', 'Lz', 'Lcell', 't_wall', 'k_s', 'T_inA', 'T_inB', 'P_inA', 'P_inB'):
        value = cfg.get(key, cfg['P_inA'])
        if not np.isscalar(value) or isinstance(value, (bool, str)) or not np.isfinite(value) or value <= 0:
            raise ValueError(f'research {key} must be finite and positive')
    validate_domain_dims([(key, cfg[key]) for key in ('L', 'H', 'Lz')])
    for key in ('Nx', 'Ny', 'Nz', 'max_outer_ltne', 'max_iter_simple', 'max_cells_3d',
                'coarse_bootstrap_max_iter', 'outer_anderson_m', 'outer_anderson_patience'):
        value = cfg.get(key)
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError(f'research {key} must be an integer >= 1')
    eps = cfg['eps']
    if not np.isscalar(eps) or not np.isfinite(eps) or not 0 < eps < 1:
        raise ValueError('research porosity must be finite and between zero and one')
    if cfg.get('sweep_profile') not in (None, 'fast_sweep', 'full_validate'):
        raise ValueError('unsupported research sweep_profile')
    require_f2_mode(cfg.get('convergence_mode'))
    for side in ('A', 'B'):
        port = cfg['fluid_' + side + '_cfg']
        if side == 'A' and port is None:
            raise ValueError('research fluid A must be active')
        if port is not None:
            speed = cfg.get('u_' + side, cfg['u_A'])
            if not np.isscalar(speed) or not np.isfinite(speed) or speed < 0:
                raise ValueError(f'research u_{side} must be finite and nonnegative')
            errors = [str(issue) for issue in validate_pipe_config(
                port, cfg['L'], cfg['H'], Lz_dom=cfg['Lz'], is_3d=True)
                if issue.severity == 'error']
            if errors:
                raise ValueError(f'research fluid {side} boundary is invalid: ' + '; '.join(errors))
        cfg.setdefault('fluid_type_' + side, 'air')
    settings = cfg.get('sco2_nu', Sco2NuConfig())
    if isinstance(settings, dict):
        settings = Sco2NuConfig(**settings)
    settings.validate()
    snapshot = dict(cfg, sco2_nu=asdict(settings))
    cfg.update(sco2_nu=settings, _environment=capture_environment())
    prepared = _prepare_problem_data(cfg)
    shape = tuple(prepared['N' + axis] for axis in 'xyz')
    for key in ('mms_S_A_field', 'mms_S_B_field', 'mms_S_s_field'):
        value = cfg.get(key)
        if value is not None and (np.shape(value) != shape or not np.isfinite(value).all()):
            raise ValueError(f'research {key} must be a finite source field on the effective grid')
    # Reuse the model-resource/notices authority; the research snapshot below
    # retains the actual porosity, inactive phase, grid profile and solver knobs.
    model_config = ComputeConfig(
        **{'fluid_' + side: FluidConfig(type=cfg['fluid_type_' + side],
             u_mps=cfg.get('u_' + side, cfg['u_A']), T_in_K=cfg['T_in' + side],
             P_in_Pa=cfg.get('P_in' + side, cfg['P_inA'])) for side in ('A', 'B')},
        geometry=GeometryConfig(tpms=cfg['tpms_type'], L_cell_mm=cfg['Lcell'],
            t_wall_mm=cfg['t_wall'], k_s_W_mK=cfg['k_s'], L_dom_m=cfg['L'],
            H_dom_m=cfg['H'], Lz_m=cfg['Lz'], delta_levelset=cfg.get('delta_levelset', 0.)),
        zones=ZoneInputConfig(enabled=bool(cfg.get('zone_grid_cells')) or cfg.get('continuous_field') is not None),
        sco2_nu=settings)
    case = _case_from_prepared(model_config, prepared, case_id=case_id,
        config_snapshot={'kind': 'research_3d_v1', 'inputs': snapshot})
    return replace(case, metadata={**case.metadata, 'preprocessor': 'research_three_d_v1',
        'active_fluids': tuple(prepared['axes']), 'supported_backends': ('python',)})
