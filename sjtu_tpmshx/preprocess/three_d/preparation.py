"""Pure 3D physical input and effective-grid preparation."""
from __future__ import annotations
from typing import Any
import os
import numpy as np
from sjtu_tpmshx.domain.compute_config import ComputeConfig, bc_to_dict, reject_retired_boundary_options
from sjtu_tpmshx.models.tpms_props import geometry as tpms_geometry
from sjtu_tpmshx.models.input_validation import validate_domain_dims, surrogate_extrap_reasons
from sjtu_tpmshx.models.grid_3d import _build_grid_3d, _resolve_axis_map, _build_zone_fields_3d
from sjtu_tpmshx.models.field_coordinates_3d import _build_partial_masks

def _parse_inputs_3d_cfg(compute_cfg: ComputeConfig) -> dict[str, Any]:
    """Read typed physical input and prepare the numerical parameter mapping.
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

    # Both-side applicability checks are required; import and validation
    # failures propagate rather than becoming an empty warning list.
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
    continuous_field = None
    if compute_cfg.zones.enabled:
        compute_cfg.zones.validate()
        if compute_cfg.zones.axis == 'continuous':
            from copy import deepcopy
            continuous_field = deepcopy(compute_cfg.zones.config)
        elif compute_cfg.zones.axis == 'grid':
            zone_grid_cells = compute_cfg.zones.grid['cells']
        else:
            raise NotImplementedError('3D zones support grid or continuous mode only')

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
        port_wall_refine=compute_cfg.flags.port_wall_refine,
        variable_rho_cp=bool(compute_cfg.flags.variable_rho_cp),
        # R3 (2026-07-07): production solver knobs (None = run_stack's
        # dim-specific autos; see SolverConfig docstring).
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
        continuous_field=continuous_field,
        fluid_type_A=fluid_type_A,
        fluid_type_B=fluid_type_B,
        df_mode=compute_cfg.df_mode,
        sco2_nu=compute_cfg.sco2_nu,
        extrap_reasons=extrap_reasons,
        compute_cfg=compute_cfg,
    )




def _prepare_problem_data(cfg):
    """Resolve physical data for the existing low-level 3D input convention."""
    reject_retired_boundary_options(cfg)
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
    if cfg.get('port_wall_refine', False):
        from sjtu_tpmshx.models.grid import build_port_wall_grid
        dx, dy, dz = build_port_wall_grid(
            (L, H, Lz), (cfg['Nx'], cfg['Ny'], cfg['Nz']),
            (cfg['fluid_A_cfg'], cfg['fluid_B_cfg']))
        nx, ny, nz = map(len, (dx, dy, dz))
    else:
        dx, dy, dz, nx, ny, nz = _build_grid_3d(
            cfg.get('wall_refine_3d', False), L, H, Lz, cfg['Nx'], cfg['Ny'], cfg['Nz'])
    cap = int(cfg.get('max_cells_3d', os.environ.get('TPMSHX_MAX_CELLS_3D', '2000000')))
    if nx * ny * nz > cap:
        raise ValueError(f'3D grid {nx}x{ny}x{nz} exceeds the {cap}-cell cap')
    geometry = tpms_geometry(cfg['tpms_type'], cfg['Lcell'], cfg['t_wall'], cfg['k_s'])
    cells = cfg.get('zone_grid_cells')
    continuous = cfg.get('continuous_field')
    continuous_geometry = None
    spatial = bool(cells) or continuous is not None
    if cfg.get('df_mode', 'cfd_smooth') == 'experimental' and spatial and continuous is None:
        raise ValueError('experimental calibration currently requires uniform L/t')
    if continuous is not None:
        from sjtu_tpmshx.domain.compute_config import ZoneInputConfig
        from sjtu_tpmshx.models.continuous_field import from_decision_vector
        ZoneInputConfig(enabled=True, axis='continuous', config=continuous).validate()
        if cells:
            raise ValueError('Continuous field cannot also supply zone_grid_cells')
        if cfg.get('delta_levelset', 0.) != 0.:
            raise ValueError('Continuous spatial fields require delta_levelset=0')
        if any(cfg.get('fluid_type_' + side) == 'sco2' for side in ('A', 'B')):
            raise ValueError('sCO2 V2 does not support zones')
        spec = dict(continuous)
        volume = 'n_ctrl_z' in spec
        field = from_decision_vector(spec.pop('x_decision'), cfg['tpms_type'], cfg['k_s'],
                                     L, H, **({'Lz_domain': Lz} if volume else {}), **spec)
        local_L, local_t = (field.evaluate_volume(nx, ny, nz, dx, dy, dz) if volume
                            else field.evaluate_grid(nx, ny, dx, dy))
        local_eps = np.empty(local_L.shape)
        continuous_geometry = {key: np.empty(local_L.shape) for key in ('A_0', 'D_h', 'epsilon')}
        # Thermal geometry consumes the recorded SI field converted back to mm.
        # Keep that exact rounding and evaluate any distinct pair immediately,
        # while the original cell geometry is still in the existing leaf cache.
        thermal_L, thermal_t = local_L * 1e-3 * 1e3, local_t * 1e-3 * 1e3
        for index in np.ndindex(local_eps.shape):
            local = tpms_geometry(
                cfg['tpms_type'], float(local_L[index]), float(local_t[index]), cfg['k_s'])
            local_eps[index] = local['epsilon']
            if thermal_L[index] != local_L[index] or thermal_t[index] != local_t[index]:
                local = tpms_geometry(
                    cfg['tpms_type'], float(thermal_L[index]), float(thermal_t[index]), cfg['k_s'])
            for key in continuous_geometry:
                continuous_geometry[key][index] = local[key]
        if volume:
            lfield, tfield, eps = local_L, local_t, local_eps
        else:
            lfield, tfield, eps = (np.repeat(values[:, :, None], nz, axis=2)
                                  for values in (local_L, local_t, local_eps))
            continuous_geometry = {key: np.repeat(values[:, :, None], nz, axis=2)
                                   for key, values in continuous_geometry.items()}
    elif cells:
        lfield, tfield, eps = _build_zone_fields_3d(
            cells, dx, dy, nz, cfg['tpms_type'], cfg['k_s'], cfg['Lcell'], cfg['t_wall'])
    else:
        lfield = np.full((nx, ny, nz), cfg['Lcell'])
        tfield = np.full((nx, ny, nz), cfg['t_wall'])
        eps = np.full((nx, ny, nz), cfg['eps'])
    from sjtu_tpmshx.preprocess.thermal_geometry import prepare_thermal_geometry
    cfg['thermal_geometry'] = prepare_thermal_geometry(
        cfg['tpms_type'], cfg['Lcell'], cfg['t_wall'], cfg['k_s'],
        L_field=lfield * 1e-3 * 1e3 if spatial and continuous_geometry is None else None,
        t_field=tfield * 1e-3 * 1e3 if spatial and continuous_geometry is None else None,
        delta=float(cfg.get('delta_levelset', 0.)))
    if continuous_geometry is not None:
        cfg['thermal_geometry']['fields'] = continuous_geometry
    from sjtu_tpmshx.models.roughness import resolve_mode_from_env
    mode, eps_um = resolve_mode_from_env(default='norris_1a')
    cfg['roughness_resolved'] = {'mode': mode, 'eps_m': eps_um * 1e-6}
    _record_air_bulk_ranges(
        cfg, lfield * 1e-3 * 1e3 if spatial else None,
        tfield * 1e-3 * 1e3 if spatial else None, (nx, ny, nz))
    permeability, forchheimer = predict_K_cF_vec(
        cfg['tpms_type'], lfield, tfield, eps / 2., method=SCO2_DF_METHOD)
    eps_A, eps_B = _eps_sides_for_run(cfg, cfg['tpms_type'], cfg['Lcell'], cfg['t_wall'], eps, eps / 2.)
    axes, openings, properties = {}, {}, {}
    for side in ('A', 'B'):
        port = cfg.get('fluid_' + side + '_cfg')
        if port is not None:
            axis = _resolve_axis_map(port, nx, ny, nz, L, H, Lz, dx, dy, dz)
            axes[side] = axis
            inlet, outlet = _build_partial_masks(port, axis['dcross1'], axis['dcross2'], axis['N_cross2'])
            openings[side] = {'inlet': inlet, 'outlet': outlet}
        fluid = cfg.get('fluid_type_' + side, 'air')
        model = fluid_props.get(fluid)
        temperature, pressure = cfg['T_in' + side], cfg.get('P_in' + side, cfg['P_inA'])
        fluid_props.check_water_state(fluid, temperature, pressure, where=f'3D prepared inlet {side}')
        properties[side] = {key: float(getattr(model, key)(temperature, pressure)) for key in ('rho', 'mu', 'cp', 'k')}
    cfg['df_application'] = _prepare_df_application(cfg, axes, permeability, forchheimer)
    return dict(cfg=cfg, dx=dx, dy=dy, dz=dz, Nx=nx, Ny=ny, Nz=nz,
                max_outer=max_outer, ltne_max_iter=ltne_max_iter, compact=compact,
                geometry=geometry, axes=axes, openings=openings, properties=properties,
                design=dict(L_field_m=lfield * 1e-3, t_field_m=tfield * 1e-3,
                            eps_arr=eps, eps_A=eps_A, eps_B=eps_B,
                            K_m2=permeability, cF_per_m=forchheimer,
                            K_ss=chi_s_eff(cfg['tpms_type'], eps) * (1-eps) * cfg['k_s']))


def _prepare_df_application(cfg, axes, permeability, forchheimer):
    """Resolve experimental calibration once; runtime still consumes K/cF fields."""
    if cfg.get('df_mode', 'cfd_smooth') != 'experimental':
        return None
    from sjtu_tpmshx.df_surrogate.experimental_correction import apply_correction
    from sjtu_tpmshx.domain.run_warnings import range_context
    result = {}
    for side in axes:
        with range_context(side=side, stage='prepared-df', layout='scalar'):
            _, _, result[side] = apply_correction(
                cfg['tpms_type'], cfg['fluid_type_' + side], cfg['Lcell'], cfg['t_wall'],
                float(permeability.flat[0]), float(forchheimer.flat[0]),
                u_mps=abs(float(cfg.get('u_' + side, cfg['u_A']))),
                allow_hx_extrapolation=cfg.get('continuous_field') is not None)
        if cfg.get('continuous_field') is not None:
            # Frozen specimen factors are transferred to each local CFD cell.
            result[side].update(
                geometry_application='continuous-field-extrapolation',
                reference_geometry_mm={'L': cfg['Lcell'], 't': cfg['t_wall']},
                application_scope='Exploratory continuous L/t trend prediction using '
                                  'frozen uniform-HX factors; gradient accuracy unvalidated')
    return result


def _record_air_bulk_ranges(cfg, lfield, tfield, shape):
    """Preserve inlet air observations without storing unused bulk h_v fields."""
    from sjtu_tpmshx.models.tpms_calc import compute
    from sjtu_tpmshx.models.nu_correlations import record_raw_nu_range
    from sjtu_tpmshx.domain.run_warnings import range_context
    for side in ('A', 'B'):
        if cfg.get('fluid_type_' + side, 'air') != 'air':
            continue
        with range_context(side=side, stage='inlet', layout='scalar-hv-bulk'):
            if lfield is None:
                compute(cfg['tpms_type'], cfg['Lcell'], cfg['t_wall'],
                        cfg.get('u_' + side, cfg['u_A']), cfg['T_in' + side],
                        cfg.get('P_in' + side, cfg['P_inA']), cfg['k_s'])
            else:
                from sjtu_tpmshx.models import fluid_props
                model = fluid_props.get('air')
                geometry = cfg['thermal_geometry']['fields']
                temperature = cfg['T_in' + side]
                pressure = cfg.get('P_in' + side, cfg['P_inA'])
                with range_context(layout='scalar-zoned-call'):
                    mu, k, rho, cp = (float(getattr(model, key)(temperature, pressure))
                                      for key in ('mu', 'k', 'rho', 'cp'))
                raw_Re = rho * cfg.get('u_' + side, cfg['u_A']) * geometry['D_h'] / mu
                # Keep scalar correlation observations and the full-cell raw-Re
                # denominator unchanged. The former compute() calls also rebuilt
                # geometry and drag, although only these notices were retained.
                for index in np.ndindex(shape):
                    with range_context(layout='scalar-zoned-call'):
                        model.nu(cfg['tpms_type'], float(raw_Re[index]), .5 * geometry['epsilon'][index],
                                 float(lfield[index]), geometry['D_h'][index] * 1e3, mu * cp / k)
                with range_context(layout='real-cell(x,y,z)-bulk-Re'):
                    record_raw_nu_range('air', cfg['tpms_type'], raw_Re)


def prepare_case(config: ComputeConfig, *, case_id: str):
    from dataclasses import asdict
    from sjtu_tpmshx.domain.case_data import CaseData
    from sjtu_tpmshx.domain.model_refs import ModelRef
    from sjtu_tpmshx.models.catalog import MODEL_VERSIONS
    from sjtu_tpmshx.models.nu_correlations import sco2_nu_metadata, sco2_nu_notices
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
    continuous = parameters.get('continuous_field')
    if continuous is not None:
        design_mode = 'continuous_xyz' if 'n_ctrl_z' in continuous else 'continuous_xy_extruded'
    else:
        design_mode = 'xy_extruded' if cells else 'uniform'
    return CaseData.from_compute_config(case_id, config, grid=grid,
        design_fields=prepared['design'], parameters=parameters, model_refs=refs,
        metadata={'preprocessor': 'three_d_v1', 'quantity_basis': 'total',
                  'model_metadata': {'sco2_nu': sco2_nu_metadata(config.sco2_nu)},
                  'notices': sco2_nu_notices(config),
                  'design_mode': design_mode,
                  'model_roles': {'fluid_A': 0, 'fluid_B': 1, 'geometry': 2, 'darcy_forchheimer': 3}})
