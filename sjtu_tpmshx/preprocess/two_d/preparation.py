"""Prepare existing 2D physical inputs and grids without running SIMPLE."""
from __future__ import annotations
from typing import Any
import numpy as np
from sjtu_tpmshx.domain.compute_config import ComputeConfig, bc_to_dict
from sjtu_tpmshx.models.tpms_props import geometry as tpms_geometry
from sjtu_tpmshx.models.input_validation import validate_domain_dims, surrogate_extrap_reasons
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)

def _check_zoned_fluid_support(compute_cfg: ComputeConfig) -> None:
    """Guard: the 2D zone property builders (ZoneConfig.compute_properties /
    build_grid_arrays and sigmoid_field.build_continuous_arrays) hardcode AIR
    (they call tpms_calc.compute / air_* with no fluid_type), so a water side
    would silently get air Nu/k — h_v ~280x and K_ff ~25x off (audit:
    zoned-water-side-uses-air-properties). Raise until per-fluid zoned props
    are implemented; the error propagates without solving another problem. The 3D
    zoned path threads fluid_type_B and is unaffected.
    """
    if not getattr(compute_cfg.zones, 'enabled', False):
        return
    fA = compute_cfg.fluid_A.type
    fB = compute_cfg.fluid_B.type
    if fA != 'air' or fB != 'air':
        raise NotImplementedError(
            f"Zoned 2D compute supports air only (fluid_A={fA!r}, "
            f"fluid_B={fB!r}); the zone property builders would silently use "
            "air properties for a non-air side. Disable zones or run a uniform "
            "(non-zoned) case for water.")


def _parse_inputs_cfg(compute_cfg: ComputeConfig) -> dict[str, Any]:
    """Phase 1 (Qt-free): assemble the parsed-config dict from a
    :class:`ComputeConfig`.

    Audit C4 (L-a-2): cfg-only mirror of ``_parse_inputs``. The legacy
    function now wraps this and propagates ``extrap_reasons`` back onto
    ``window._extrap_reasons`` so the UI watermark keeps working.

    Returns the same parsed dict as ``_parse_inputs`` plus an
    ``extrap_reasons`` key (the legacy version mutated this onto the
    window directly; the cfg-pure version returns it instead).
    """
    warnings_list = []
    extrap_reasons = []

    # Block unsupported fluids up-front (2D path currently hardcodes air_*
    # 2026-05-09 (option B) — water + air supported in 2D Compute. sCO2
    # still blocks. Per-side fluid type captured into cfg so _run_solvers
    # picks the right property accessors.
    from sjtu_tpmshx.models.tpms_calc import validate_fluid_type
    fluid_A = compute_cfg.fluid_A.type
    fluid_B = compute_cfg.fluid_B.type
    validate_fluid_type(fluid_A, 'A')
    validate_fluid_type(fluid_B, 'B')
    from sjtu_tpmshx.models.fluid_props import check_water_state
    for side, config in (('A', compute_cfg.fluid_A), ('B', compute_cfg.fluid_B)):
        check_water_state(config.type, config.T_in_K, config.P_in_Pa,
                          where=f'pipeline inlet {side}')

    # Surrogate training-domain guard for the UI Compute path (#10) —
    # previously only the optimizer did this; the Compute tab now also
    # guards a single out-of-window (u, T, L, t) from silent RBF extrap.
    # If ``cfg.extrap.allow`` is set (the checkbox is on, or the env
    # var TPMSHX_ALLOW_EXTRAP=1 fed the dataclass), out-of-window
    # values downgrade to warn and we stash the reasons in the parsed
    # dict so the UI can mark the result + watermark the plots.
    _allow_extrap = bool(compute_cfg.extrap.allow)
    extrap_reasons += surrogate_extrap_reasons(compute_cfg, _allow_extrap)

    # Scalar parameters (already cfg-sourced).
    L = compute_cfg.geometry.L_dom_m
    H = compute_cfg.geometry.H_dom_m
    N_x = compute_cfg.solver.Nx
    N_y = compute_cfg.solver.Ny
    u_A = compute_cfg.fluid_A.u_mps
    u_B = compute_cfg.fluid_B.u_mps
    T_inA = compute_cfg.fluid_A.T_in_K
    T_inB = compute_cfg.fluid_B.T_in_K

    # Optional solid initial temperature — None means legacy seed
    # 0.5*(T_inA+T_inB) inside solve_full_domain. Not a prescribed Ts.
    T_s_init = compute_cfg.solver.T_s_init_K

    # Defensive unit firewall — shared with the 3D parse (_stage_common).
    validate_domain_dims([('L', L), ('H', H)])

    dx = L / N_x
    dy = H / N_y
    cfgA = bc_to_dict(compute_cfg.bc_A, L, H, side='A')
    cfgB = bc_to_dict(compute_cfg.bc_B, L, H, side='A')
    dir_A = cfgA['dir']
    dir_B = cfgB['dir']

    # TPMS geometry derives porosity + hydraulic radius purely from cfg.
    # The legacy version cached this in ``window._eps_A``; we re-derive
    # because tpms_geometry is cheap (closed-form per Cheng 2021).
    tpms_type = compute_cfg.geometry.tpms
    Lcell = compute_cfg.geometry.L_cell_mm
    t_wall = compute_cfg.geometry.t_wall_mm
    k_s = compute_cfg.geometry.k_s_W_mK
    g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
    eps = g['epsilon']
    r_h = g['D_h'] / 2.0

    # ── zone config from cfg.zones (pre-resolved at UI boundary) ──
    zone_config = None
    za = None
    z_axis = 'y'
    if compute_cfg.zones.enabled:
        compute_cfg.zones.validate()
        _check_zoned_fluid_support(compute_cfg)
        z_axis = compute_cfg.zones.axis
        P_in_val = compute_cfg.fluid_A.P_in_Pa
        if z_axis == 'grid':
            grid = compute_cfg.zones.grid
            _x_dec = compute_cfg.zones.pareto_x_decision
            if _x_dec is not None:
                from sjtu_tpmshx.models.sigmoid_field import (
                    build_continuous_arrays, get_geometry_lut,
                )
                _lut = get_geometry_lut(tpms_type)
                za = build_continuous_arrays(
                    _x_dec, Lcell, t_wall,
                    compute_cfg.zones.pareto_y_trans_inlet,
                    compute_cfg.zones.pareto_y_trans_outlet,
                    N_x, N_y, L, H,
                    tpms_type, k_s,
                    u_A, u_B, T_inA, T_inB, _lut,
                    P_in=P_in_val,  # FIX (2026-06-24 audit): was defaulting to P_atm
                    allow_extrap=_allow_extrap,
                    fluid_type=fluid_A)  # air-only builder; non-air raises
                _log.info(f"[ZONE] Continuous Sigmoid field ({N_x}x{N_y})")
            else:
                from sjtu_tpmshx.models.zone_config import ZoneConfig
                za = ZoneConfig.build_grid_arrays(
                    N_x, N_y, L, H,
                    grid['cells'],
                    grid['tpms_type'], grid['k_s'],
                    u_A, u_B, T_inA, T_inB, P_in_val)
                _log.info(f"[ZONE] Grid {len(grid['cells'])} cells (discrete)")
            zone_config = 'grid'
        else:
            # The UI supplies an object; canonical JSON retains its data shape.
            if compute_cfg.zones.config is None:
                raise ValueError('Enabled 1D zones require a ZoneConfig')
            zone_config = compute_cfg.zones.config
            if isinstance(zone_config, dict):
                from copy import deepcopy
                from sjtu_tpmshx.models.zone_config import Zone, ZoneConfig

                zone_data = deepcopy(zone_config)
                zone_data['zones'] = [Zone(**zone) for zone in zone_data['zones']]
                zone_config = ZoneConfig(**zone_data)
            zone_config.compute_properties(
                u_A=u_A, u_B=u_B, T_inA=T_inA, T_inB=T_inB,
                P_in=P_in_val)
            z_dim = H if z_axis == 'y' else L
            za = zone_config.build_structured_arrays(
                N_x, N_y, z_dim, axis=z_axis)
            _log.info(f"[ZONE] {len(zone_config.zones)} zones along "
                      f"{z_axis}")

    # Smooth zone property arrays at boundaries (skip continuous mode).
    if za is not None and zone_config is not None and za.get('axis') != 'continuous':
        from scipy.ndimage import gaussian_filter
        _sigma = 2.0
        for _key in ('K_ffA_arr', 'K_ffB_arr', 'K_ss_arr',
                     'h_vA_arr', 'h_vB_arr', 'eps_arr'):
            if _key in za:
                za[_key] = gaussian_filter(za[_key], sigma=_sigma)

    return {
        'L': L, 'H': H,
        'N_x': N_x, 'N_y': N_y,
        'dx': dx, 'dy': dy,
        'u_A': u_A, 'u_B': u_B,
        'T_inA': T_inA, 'T_inB': T_inB,
        'T_s_init': T_s_init,
        'cfgA': cfgA, 'cfgB': cfgB,
        'dir_A': dir_A, 'dir_B': dir_B,
        'envelope_mode': getattr(compute_cfg, 'envelope_mode', 'raise'),
        'tpms_type': tpms_type,
        'Lcell': Lcell, 't_wall': t_wall, 'k_s': k_s,
        'eps': eps, 'r_h': r_h,
        'zone_config': zone_config, 'za': za, 'z_axis': z_axis,
        'fluid_A': fluid_A, 'fluid_B': fluid_B,
        'warnings_list': warnings_list,
        'extrap_reasons': extrap_reasons,
        # Stash the strict ComputeConfig so downstream phases
        # (_build_fields / _run_solvers / _store_results) can reach
        # P_inA / P_inB etc. without re-reading ``le_*`` widget.
        'compute_cfg': compute_cfg,
    }


def _prepare_grid(cfg):
    L, H = cfg['L'], cfg['H']
    N_x, N_y = cfg['N_x'], cfg['N_y']
    cfgA, cfgB = cfg['cfgA'], cfg['cfgB']
    zone_config, za = cfg['zone_config'], cfg['za']
    # Build aligned grid arrays for energy solver
    from sjtu_tpmshx.models.grid import _aligned_grid
    _x_breaks = set()
    _y_breaks = set()
    for port in (cfgA, cfgB):
        breaks, cross_dim = (_y_breaks, H) if port['dir'] in (0, 1) else (_x_breaks, L)
        for end in ('in', 'out'):
            ctr = port.get(f'{end}_ctr', port['in_ctr'])
            width = port.get(f'{end}_w', port['in_w'])
            lo, hi = ctr - width / 2, ctr + width / 2
            if lo > cross_dim * 0.001:
                breaks.add(lo)
            if hi < cross_dim * 0.999:
                breaks.add(hi)

    # Use 4-wall Brinkman-BL refined grid when inlet/outlet are full-width (no
    # break points). Otherwise, fall back to aligned uniform grid since
    # refinement would conflict with inlet/outlet boundary alignment.
    _wall_refine_gui = (
        len(_x_breaks) == 0 and len(_y_breaks) == 0
        and zone_config is None and za is None
    )
    if _wall_refine_gui:
        from sjtu_tpmshx.models.grid import build_master_refined_grid
        try:
            energy_dx, energy_dy, N_x, N_y = build_master_refined_grid(
                L, H, N_x, N_y, n_refine=8, first_cell=0.02e-3, growth=1.8)
            _log.info(f"[run_calculation] Wall-refined grid: {N_x}×{N_y} cells (4-wall BL resolved)")
        except ValueError:
            energy_dx = _aligned_grid(N_x, L, list(_x_breaks))
            energy_dy = _aligned_grid(N_y, H, list(_y_breaks))
    else:
        energy_dx = _aligned_grid(N_x, L, list(_x_breaks))
        energy_dy = _aligned_grid(N_y, H, list(_y_breaks))

    # From this point onward the 2D compute path must use the effective grid
    # dimensions implied by energy_dx/energy_dy, not the raw UI values.  The
    # refined-grid path can expand e.g. user Nx=20 to actual Nx=23; keeping the
    # old cfg dimensions made Ta/rho/P fields broadcast as (20, 4) vs (23, 4).
    N_x = int(len(energy_dx))
    N_y = int(len(energy_dy))
    cfg['N_x'] = N_x
    cfg['N_y'] = N_y

    def _resize_zone_arrays_to_effective_grid(za_dict, shape):
        if za_dict is None:
            return

        def _nearest(arr):
            sx, sy = arr.shape
            ix = np.clip(((np.arange(shape[0]) + 0.5) * sx / shape[0]).astype(int),
                         0, sx - 1)
            iy = np.clip(((np.arange(shape[1]) + 0.5) * sy / shape[1]).astype(int),
                         0, sy - 1)
            return arr[np.ix_(ix, iy)]

        def _linear(arr):
            sx, sy = arr.shape
            x_old = (np.arange(sx) + 0.5) / sx
            y_old = (np.arange(sy) + 0.5) / sy
            x_new = (np.arange(shape[0]) + 0.5) / shape[0]
            y_new = (np.arange(shape[1]) + 0.5) / shape[1]
            tmp = np.empty((shape[0], sy), dtype=np.float64)
            for j in range(sy):
                tmp[:, j] = np.interp(x_new, x_old, arr[:, j])
            out = np.empty(shape, dtype=np.float64)
            for i in range(shape[0]):
                out[i, :] = np.interp(y_new, y_old, tmp[i, :])
            return out

        for key, value in list(za_dict.items()):
            arr = np.asarray(value)
            if arr.ndim != 2 or arr.shape == shape:
                continue
            if arr.shape[0] == 0 or arr.shape[1] == 0:
                continue
            if key == 'zone_id' or not np.issubdtype(arr.dtype, np.floating):
                za_dict[key] = _nearest(arr)
            else:
                za_dict[key] = _linear(arr.astype(np.float64, copy=False))

        if 'eps_arr' in za_dict:
            za_dict['eps_f_arr'] = np.asarray(za_dict['eps_arr'],
                                              dtype=np.float64) / 2.0

    _resize_zone_arrays_to_effective_grid(za, (N_x, N_y))

    return {'energy_dx': energy_dx, 'energy_dy': energy_dy,
            '_x_breaks': tuple(sorted(_x_breaks)), '_y_breaks': tuple(sorted(_y_breaks))}


def prepare_case(config: ComputeConfig, *, case_id: str):
    """Freeze the effective 2D grid and physical design for another process."""
    from dataclasses import asdict
    from sjtu_tpmshx.domain.case_data import CaseData
    from sjtu_tpmshx.domain.model_refs import ModelRef
    from sjtu_tpmshx.models.catalog import MODEL_VERSIONS

    config = ComputeConfig.from_dict(asdict(config))
    if config.is_3d:
        raise ValueError('2D preparation requires solver.Nz == 1')
    parsed = _parse_inputs_cfg(config)
    physical_grid = _prepare_grid(parsed)
    dx, dy = physical_grid['energy_dx'], physical_grid['energy_dy']
    za = parsed.pop('za')
    zones = parsed.pop('zone_config')
    parsed.pop('compute_cfg')
    parsed['L_cell_m'] = parsed.pop('Lcell') * 1e-3
    parsed['t_wall_m'] = parsed.pop('t_wall') * 1e-3
    # Runtime controls are input data. The solver never reparses config_snapshot.
    parsed['run_settings'] = _zone_data_si(asdict(config))
    parsed['zone_config'] = _zone_data_si(asdict(zones)) if hasattr(zones, '__dataclass_fields__') else zones
    design = _zone_data_si(za) if za is not None else {
        'eps_arr': np.full((len(dx), len(dy)), parsed['eps']),
        'r_h_arr': np.full((len(dx), len(dy)), parsed['r_h']),
        'L_field_m': np.full((len(dx), len(dy)), parsed['L_cell_m']),
        't_field_m': np.full((len(dx), len(dy)), parsed['t_wall_m']),
    }
    from sjtu_tpmshx.models.grid import _port_fractions_1d
    boundaries = {}
    for side in ('A', 'B'):
        port = parsed['cfg' + side]
        widths = dy if port['dir'] in (0, 1) else dx
        openings = {}
        for end in ('in', 'out'):
            center, width = port[end + '_ctr'], port[end + '_w']
            raw, profile = _port_fractions_1d(widths, center-width/2, center+width/2)
            openings[end + '_geom_frac'] = raw
            openings[end + '_profile_frac'] = profile
        boundaries[side] = openings
    parsed['boundary_openings'] = boundaries
    refs = tuple(ModelRef('fluid', MODEL_VERSIONS['fluid'],
                          {'fluid': fluid.type, 'sco2_nu': asdict(config.sco2_nu)},
                          applicability=f'side {side}')
                 for side, fluid in (('A', config.fluid_A), ('B', config.fluid_B)))
    refs += (ModelRef('geometry', MODEL_VERSIONS['geometry']),
             ModelRef('darcy_forchheimer', MODEL_VERSIONS['darcy_forchheimer'],
                      {'topology': config.geometry.tpms}))
    return CaseData.from_compute_config(
        case_id, config,
        grid={'dimension': 2, 'axis_order': ('x', 'y'), 'length_unit': 'm',
              'dx': dx, 'dy': dy,
              'x_edges': np.r_[0., np.cumsum(dx)],
              'y_edges': np.r_[0., np.cumsum(dy)],
              'x_breaks': physical_grid['_x_breaks'],
              'y_breaks': physical_grid['_y_breaks']},
        design_fields=design, parameters=parsed, model_refs=refs,
        metadata={'preprocessor': 'two_d_v1', 'quantity_basis': 'per_unit_depth',
                  'design_mode': 'uniform' if za is None else za['axis'],
                  'model_roles': {'fluid_A': 0, 'fluid_B': 1, 'geometry': 2, 'darcy_forchheimer': 3}})


def _zone_data_si(value):
    """Convert the existing zone builders' explicit millimetre fields to SI."""
    from collections.abc import Mapping
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if key in ('L_mm', 't_mm', 'L_cell_mm', 't_wall_mm', 'L_field', 't_field'):
                result[key.replace('_mm', '_m').replace('_field', '_field_m')] = item * 1e-3
            elif key in ('grid_cells',):
                result[key] = [dict((('L_m' if k == 'L' else 't_m' if k == 't' else k),
                                    v * 1e-3 if k in ('L', 't') else v)
                                   for k, v in cell.items()) for cell in item]
            else:
                result[key] = _zone_data_si(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_zone_data_si(item) for item in value]
    return value
