"""Pure 3D physical input and effective-grid preparation."""
from __future__ import annotations
from typing import Any
import os
import numpy as np
from sjtu_tpmshx.domain.compute_config import ComputeConfig, bc_to_dict
from sjtu_tpmshx.models.tpms_props import geometry as tpms_geometry
from sjtu_tpmshx.models.input_validation import validate_domain_dims, surrogate_extrap_reasons
from sjtu_tpmshx.models.grid_3d import _build_grid_3d, _resolve_axis_map, _build_zone_fields_3d
from sjtu_tpmshx.models.field_coordinates_3d import _build_partial_masks

def _parse_inputs_3d_cfg(compute_cfg: ComputeConfig) -> dict[str, Any]:
    """Phase 1 (Qt-free) 3D mirror of ``_parse_inputs(window, compute_cfg)``.

    Audit C4 (L-a-2): reads only :class:`ComputeConfig`. Returns the
    same parsed dict ``_run_3d_stack`` expects plus an
    ``extrap_reasons`` key (the legacy version mutated this onto
    ``window._extrap_reasons``).
    """
    # ── scalar geometry + grid + fluids ─────────────────────────────
    L = compute_cfg.geometry.L_dom_m
    H = compute_cfg.geometry.H_dom_m
    # Lz contract (2026-07-12): GeometryConfig's docstring says the 3D path
    # *requires* Lz_m, but this line silently substituted the Shanghai depth
    # (0.042 m) whenever it was None — so a config that never specified a depth
    # still produced a 3D result, computed against a magic constant the user
    # never chose, and every extensive 3D scalar (Q, mass, dP_B) scaled with it.
    # Nz >= 2 already routes here (ComputeConfig.is_3d), so arriving with
    # Lz_m=None is a config error, not a default. Fail loud.
    if compute_cfg.geometry.Lz_m is None:
        raise ValueError(
            "GeometryConfig.Lz_m is None but the 3D path was selected "
            f"(solver.Nz={compute_cfg.solver.Nz} >= 2). The 3D solver requires "
            "an explicit domain depth — it used to silently fall back to "
            "0.042 m (the Shanghai HX depth), which every extensive 3D scalar "
            "then scaled with. Set geometry.Lz_m explicitly.")
    Lz = float(compute_cfg.geometry.Lz_m)
    Nx = compute_cfg.solver.Nx
    Ny = compute_cfg.solver.Ny
    Nz = compute_cfg.solver.Nz

    for name, val in [('L', L), ('H', H), ('Lz', Lz)]:
        if val <= 0:
            raise ValueError(
                f"Domain dimension {name!r} must be > 0 (got {val})")
    validate_domain_dims([('L', L), ('H', H), ('Lz', Lz)])
    for name, val in [('Nx', Nx), ('Ny', Ny), ('Nz', Nz)]:
        if val < 1:
            raise ValueError(
                f"Grid count {name!r} must be >= 1 (got {val})")

    u_A = compute_cfg.fluid_A.u_mps
    u_B = compute_cfg.fluid_B.u_mps
    T_inA = compute_cfg.fluid_A.T_in_K
    T_inB = compute_cfg.fluid_B.T_in_K
    T_s_init = compute_cfg.solver.T_s_init_K
    P_inA = compute_cfg.fluid_A.P_in_Pa
    P_inB = compute_cfg.fluid_B.P_in_Pa
    Lcell = compute_cfg.geometry.L_cell_mm
    t_wall = compute_cfg.geometry.t_wall_mm
    k_s = compute_cfg.geometry.k_s_W_mK
    tpms_type = compute_cfg.geometry.tpms

    g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
    eps = g['epsilon']
    D_h = g['D_h']

    # Partial-pipe BC dicts — side A full-face fallback, side B raw partial.
    fluid_A_cfg = bc_to_dict(compute_cfg.bc_A, L, H, side='A', with_z=True)
    fluid_B_cfg = bc_to_dict(compute_cfg.bc_B, L, H, side='B', with_z=True)
    if fluid_B_cfg is None:
        # A degenerate B BC (the PartialBCConfig default in_w=out_w=0) reaching
        # THIS ComputeConfig→3D boundary means "full-face cross-flow B", NOT a
        # single-fluid run: via ComputeConfig fluid_B is always a configured 2nd
        # fluid (validated below). bc_to_dict(side='B') returns None for that
        # degenerate case and DROPS the direction; _run_3d_stack's
        # `if fB is not None` gate then skips the entire B SIMPLE build (the
        # A-alone path), so the 2-fluid solve silently returns nan (air uncooled,
        # T_out_B=nan, E_imbal=1.0). Rebuild a full-face dict via the side='A'
        # fallback, which preserves bc_B.dir. The genuine single-fluid A-alone
        # path reaches _run_3d_stack with an explicit fluid_B_cfg=None and
        # bypasses this boundary (e.g. audit_3d_conservation T5), so it — and
        # bc_to_dict's documented side-B None asymmetry — are unaffected.
        fluid_B_cfg = bc_to_dict(compute_cfg.bc_B, L, H, side='A', with_z=True)

    # Surrogate-domain extrap guard — cfg.extrap.allow drives it
    # (shared both-side check in _stage_common; ImportError → skip,
    # ValueError propagates).
    from sjtu_tpmshx.models.fluid_props import check_water_state
    for side, config in (('A', compute_cfg.fluid_A), ('B', compute_cfg.fluid_B)):
        check_water_state(config.type, config.T_in_K, config.P_in_Pa,
                          where=f'pipeline inlet {side}')
    extrap_reasons = surrogate_extrap_reasons(
        compute_cfg, bool(compute_cfg.extrap.allow))

    from sjtu_tpmshx.models.tpms_calc import validate_fluid_type
    fluid_type_A = compute_cfg.fluid_A.type
    fluid_type_B = compute_cfg.fluid_B.type
    validate_fluid_type(fluid_type_A, 'A')
    validate_fluid_type(fluid_type_B, 'B')

    # Feature flags — sourced from cfg.flags + cfg.zones.
    wall_refine = bool(compute_cfg.flags.wall_refine_3d)
    zone_grid_cells = None
    if compute_cfg.zones.enabled:
        compute_cfg.zones.validate()
        if compute_cfg.zones.axis != 'grid':
            raise NotImplementedError('3D zones support grid mode only')
        zone_grid_cells = compute_cfg.zones.grid['cells']

    return dict(
        L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=u_A, u_B=u_B, T_inA=T_inA, T_inB=T_inB,
        P_inA=P_inA, P_inB=P_inB,
        T_s_init=T_s_init,
        envelope_mode=getattr(compute_cfg, 'envelope_mode', 'raise'),
        Lcell=Lcell, t_wall=t_wall, k_s=k_s, tpms_type=tpms_type,
        eps=eps, D_h=D_h,
        delta_levelset=float(compute_cfg.geometry.delta_levelset),
        fluid_A_cfg=fluid_A_cfg,
        fluid_B_cfg=fluid_B_cfg,
        wall_refine_3d=wall_refine,
        variable_rho_cp=bool(compute_cfg.flags.variable_rho_cp),
        # R3 (2026-07-07): production solver knobs (None = run_stack's
        # dim-specific autos; see SolverConfig docstring).
        tol_simple=compute_cfg.solver.tol_simple,
        max_iter_simple=compute_cfg.solver.max_iter_simple,
        max_outer_ltne=compute_cfg.solver.max_outer_ltne,
        outer_tol_K=compute_cfg.solver.outer_tol_K,
        # F2 convergence gates (ledger C6/C7). None -> _apply_accel_flags'
        # resolution: env TPMSHX_CONV_MODE > cfg > default 'f2'.
        **{k: v for k, v in (
            ('convergence_mode', compute_cfg.solver.convergence_mode),
            ('mom_tol', compute_cfg.solver.mom_tol),
            ('mass_local_tol', compute_cfg.solver.mass_local_tol),
            ('mass_global_tol', compute_cfg.solver.mass_global_tol),
        ) if v is not None},
        zone_grid_cells=zone_grid_cells,
        fluid_type_A=fluid_type_A,
        fluid_type_B=fluid_type_B,
        df_mode=compute_cfg.df_mode,
        sco2_nu=compute_cfg.sco2_nu,
        extrap_reasons=extrap_reasons,
        compute_cfg=compute_cfg,
    )




def _prepare_problem_data(cfg):
    """Resolve physical data for the existing low-level 3D input convention."""
    from sjtu_tpmshx.models import fluid_props
    from sjtu_tpmshx.models.tpms_props import chi_s_eff
    from sjtu_tpmshx.models.asym_split import _eps_sides_for_run
    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec, SCO2_DF_METHOD

    cfg = dict(cfg)
    profile = cfg.get('sweep_profile')
    max_outer = None
    ltne_max_iter, compact = 20000, False
    if profile == 'fast_sweep':
        max_outer, compact = 3, True
        for key in ('Nx', 'Ny', 'Nz'):
            cfg[key] = min(cfg.get(key, 20), 15)
    elif profile == 'full_validate':
        max_outer, ltne_max_iter = 12, 50000
    if cfg.get('max_outer_ltne') is not None:
        max_outer = int(cfg['max_outer_ltne'])
        if max_outer < 1:
            raise ValueError('max_outer_ltne must be >= 1; zero iterations solves nothing')
    L, H, Lz = cfg['L'], cfg['H'], cfg['Lz']
    dx, dy, dz, nx, ny, nz = _build_grid_3d(
        cfg.get('wall_refine_3d', False), L, H, Lz, cfg['Nx'], cfg['Ny'], cfg['Nz'])
    cap = int(cfg.get('max_cells_3d', os.environ.get('TPMSHX_MAX_CELLS_3D', '2000000')))
    if nx * ny * nz > cap:
        raise ValueError(f'3D grid {nx}x{ny}x{nz} exceeds the {cap}-cell cap')
    geometry = tpms_geometry(cfg['tpms_type'], cfg['Lcell'], cfg['t_wall'], cfg['k_s'])
    cells = cfg.get('zone_grid_cells')
    if cfg.get('df_mode', 'cfd_smooth') == 'experimental' and cells:
        raise ValueError('experimental calibration currently requires uniform L/t')
    if cells:
        lfield, tfield, eps = _build_zone_fields_3d(
            cells, nx, ny, nz, L, H, cfg['tpms_type'], cfg['k_s'], cfg['Lcell'], cfg['t_wall'])
    else:
        lfield = np.full((nx, ny, nz), cfg['Lcell'])
        tfield = np.full((nx, ny, nz), cfg['t_wall'])
        eps = np.full((nx, ny, nz), cfg['eps'])
    permeability, forchheimer = predict_K_cF_vec(
        cfg['tpms_type'], lfield, tfield, eps / 2., method=SCO2_DF_METHOD)
    eps_A, eps_B = _eps_sides_for_run(cfg, cfg['tpms_type'], cfg['Lcell'], cfg['t_wall'], eps, eps / 2.)
    axes, openings, properties = {}, {}, {}
    for side in ('A', 'B'):
        port = cfg.get('fluid_' + side + '_cfg')
        if port is not None:
            axis = _resolve_axis_map(port, nx, ny, nz, L, H, Lz, dx, dy, dz)
            axes[side] = axis
            inlet, outlet = _build_partial_masks(port, axis['dcross1'], axis['dcross2'],
                                                 axis['N_cross1'], axis['N_cross2'], axis['is_reverse'])
            openings[side] = {'inlet': inlet, 'outlet': outlet}
        fluid = cfg.get('fluid_type_' + side, 'air')
        model = fluid_props.get(fluid)
        temperature, pressure = cfg['T_in' + side], cfg.get('P_in' + side, cfg['P_inA'])
        fluid_props.check_water_state(fluid, temperature, pressure, where=f'3D prepared inlet {side}')
        properties[side] = {key: float(getattr(model, key)(temperature, pressure)) for key in ('rho', 'mu', 'cp', 'k')}
    return dict(cfg=cfg, dx=dx, dy=dy, dz=dz, Nx=nx, Ny=ny, Nz=nz,
                max_outer=max_outer, ltne_max_iter=ltne_max_iter, compact=compact,
                geometry=geometry, axes=axes, openings=openings, properties=properties,
                design=dict(L_field_m=lfield * 1e-3, t_field_m=tfield * 1e-3,
                            eps_arr=eps, eps_A=eps_A, eps_B=eps_B,
                            K_m2=permeability, cF_per_m=forchheimer,
                            K_ss=chi_s_eff(cfg['tpms_type'], eps) * (1-eps) * cfg['k_s']))


def prepare_case(config: ComputeConfig, *, case_id: str):
    from dataclasses import asdict
    from sjtu_tpmshx.domain.case_data import CaseData
    from sjtu_tpmshx.domain.model_refs import ModelRef
    from sjtu_tpmshx.models.catalog import MODEL_VERSIONS
    config = ComputeConfig.from_dict(asdict(config))
    if not config.is_3d:
        raise ValueError('3D preparation requires solver.Nz >= 2')
    from sjtu_tpmshx.domain.run_environment import capture_environment
    cfg = _parse_inputs_3d_cfg(config)
    cfg['_environment'] = capture_environment()
    cfg.setdefault('use_adaptive_amg_tol', (cfg['_environment']['TPMSHX_PHASE_A'] or '1') != '0')
    cfg.setdefault('use_anderson', (cfg['_environment']['TPMSHX_PHASE_B'] or '0') == '1')
    cfg.setdefault('use_coarse_bootstrap', (cfg['_environment']['TPMSHX_PHASE_C'] or '0') == '1')
    prepared = _prepare_problem_data(cfg)
    parameters = dict(prepared['cfg'])
    parameters.pop('compute_cfg')
    parameters['sco2_nu'] = asdict(parameters['sco2_nu'])
    parameters['L_cell_m'] = parameters.pop('Lcell') * 1e-3
    parameters['t_wall_m'] = parameters.pop('t_wall') * 1e-3
    cells = parameters.get('zone_grid_cells')
    if cells:
        parameters['zone_grid_cells'] = [dict((('L_m' if key == 'L' else 't_m' if key == 't' else key),
                                               value*1e-3 if key in ('L', 't') else value)
                                              for key, value in cell.items()) for cell in cells]
    parameters['prepared'] = {key: value for key, value in prepared.items()
                              if key not in ('cfg', 'dx', 'dy', 'dz', 'design')}
    grid = {'dimension': 3, 'axis_order': ('x', 'y', 'z'), 'length_unit': 'm'}
    for axis in ('x', 'y', 'z'):
        widths = prepared['d' + axis]
        grid['d' + axis] = widths
        grid[axis + '_edges'] = np.r_[0., np.cumsum(widths)]
    refs = tuple(ModelRef('fluid', MODEL_VERSIONS['fluid'],
                          {'fluid': fluid.type, 'sco2_nu': asdict(config.sco2_nu)}, f'side {side}')
                 for side, fluid in (('A', config.fluid_A), ('B', config.fluid_B)))
    refs += (ModelRef('geometry', MODEL_VERSIONS['geometry']),
             ModelRef('darcy_forchheimer', MODEL_VERSIONS['darcy_forchheimer'], {'topology': config.geometry.tpms}))
    return CaseData.from_compute_config(case_id, config, grid=grid,
        design_fields=prepared['design'], parameters=parameters, model_refs=refs,
        metadata={'preprocessor': 'three_d_v1', 'quantity_basis': 'total',
                  'design_mode': 'xy_extruded' if cells else 'uniform',
                  'model_roles': {'fluid_A': 0, 'fluid_B': 1, 'geometry': 2, 'darcy_forchheimer': 3}})
