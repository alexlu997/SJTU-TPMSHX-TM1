"""Prepare the existing air/air optimizer mesh, coefficients and flow seeds."""
import warnings
import os
import numpy as np

from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.model_refs import ModelRef
from sjtu_tpmshx.models.catalog import MODEL_VERSIONS
from sjtu_tpmshx.models.continuous_field import ContinuousFieldConfig
from sjtu_tpmshx.models.screening import DEFAULT_CONFIG, SCREENING_FIELDS, build_field
from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry, adaptive_grid, air_density, air_viscosity
from sjtu_tpmshx.models.df_projection import project_fields_to_streamwise_K_cF
from sjtu_tpmshx.models.envelope import predict_outlet_p_sq, ChokedFlowError
from sjtu_tpmshx.models.grid import _aligned_grid, _port_fractions_1d
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF, _resolve_method


def _resolve_grid(cfg: dict, fc: ContinuousFieldConfig) -> tuple:
    """Return (Nx, Ny) from cfg or from adaptive_grid using the field's mean
    cell size as the characteristic length scale."""
    if cfg.get('Nx') is not None and cfg.get('Ny') is not None:
        return int(cfg['Nx']), int(cfg['Ny'])
    L_mean = float(fc.L_ctrl.mean())
    t_mean = float(fc.t_ctrl.mean())
    g = tpms_geometry(cfg['tpms_type'], L_mean, t_mean, cfg['k_s'])
    return adaptive_grid(cfg['L_domain'], cfg['H_domain'], g['D_h'],
                         cfg.get('grid_alpha', 0.8))


def _percell_K_cF(cfg: dict, arrays: dict) -> tuple:
    """Per-cell (K, cF) in REAL coords (Nx, Ny) from the design L/t fields.

    2026-07-10 lateral-K: the per-row `override_simple_K_cF` projection
    averages (L, t) laterally BEFORE predicting — nonlinear predict means the
    lateral resistance contrast is erased, which removes the routing lever a
    port-BC study needs. This builds the per-cell prediction instead.
    """
    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF_vec
    L_f = np.asarray(arrays['L_field'], dtype=np.float64)
    t_f = np.asarray(arrays['t_field'], dtype=np.float64)
    eps_f = np.asarray(arrays['eps_arr'], dtype=np.float64) * 0.5  # per-stream
    K, cF = predict_K_cF_vec(cfg['tpms_type'],
                             L_f.ravel(), t_f.ravel(), eps_f.ravel())
    return (K.reshape(L_f.shape).astype(np.float64),
            cF.reshape(L_f.shape).astype(np.float64))


def prepare_flow(cfg, fc, arrays, Nx, Ny, side):
    """Resolve the former _build_simple_A/B geometry without a solver object."""
    is_a = side == 'A'
    W, H = ((float(cfg['H_domain']), float(cfg['L_domain'])) if is_a
            else (float(cfg['L_domain']), float(cfg['H_domain'])))
    nx, ny = (Ny, Nx) if is_a else (Nx, Ny)
    Tin, Pin, velocity = (float(cfg['T_in' + side]), float(cfg['P_in' + side]),
                         float(cfg['u_' + side]))
    rho, mu = air_density(Tin, Pin), air_viscosity(Tin)
    eps = float(arrays['eps_arr'].mean())
    Lmean, tmean = float(fc.L_ctrl.mean()), float(fc.t_ctrl.mean())
    ports = cfg.get('ports_' + side)
    in_lo, in_hi, out_lo, out_hi = tuple(map(float, ports)) if ports is not None else (0., W, 0., W)
    if not (0. <= in_lo < in_hi <= W and 0. <= out_lo < out_hi <= W):
        raise ValueError('screening openings must lie within the physical face')
    breaks = [v for v in (in_lo, in_hi, out_lo, out_hi) if W * .001 < v < W * .999]
    dx, dy = _aligned_grid(nx, W, breaks), _aligned_grid(ny, H, [])
    K0, cF0 = predict_K_cF(cfg['tpms_type'], Lmean, tmean, .5 * eps)
    G = float(rho) * abs(velocity)
    C = float(mu) * G / max(K0, 1e-16) + cF0 * G * G
    psq = predict_outlet_p_sq(Pin, Tin, C, H)
    if psq <= 0.:
        raise ChokedFlowError(f'fluid {side} chokes on the 1D D-F seed: P_out^2 = {psq:.3e} Pa^2 '
                              f'(P_in = {Pin:.0f} Pa, C = {C:.3e}, L = {H} m)')
    pref = float(np.sqrt(max(psq, 1.0e4)))
    K, cF = project_fields_to_streamwise_K_cF(
        arrays['L_field'], arrays['t_field'], cfg['tpms_type'], cfg['k_s'],
        Nx, Ny, ny, side, streamwise_dx=dy)
    Kfield = cFfield = None
    if cfg.get('per_cell_K', False):
        kr, cr = _percell_K_cF(cfg, arrays)
        Kfield, cFfield = (kr.T, cr.T) if is_a else (kr[:, ::-1], cr[:, ::-1])
    ka, ca = (K, cF) if Kfield is None else (Kfield, cFfield)
    if float(np.max(ka)) != float(np.min(ka)) or float(np.max(ca)) != float(np.min(ca)):
        cells = mu * G / np.maximum(ka, 1e-16) + ca * G * G
        psq = predict_outlet_p_sq(Pin, Tin, float(np.mean(cells)), H)
        if psq <= 0.:
            raise ChokedFlowError(f'graded drag chokes on the 1D D-F re-seed: P_out^2 = '
                                  f'{psq:.3e} Pa^2 (P_in = {Pin:.0f} Pa)')
        pref = float(np.sqrt(max(psq, 1.0e4)))
    return dict(initial=dict(W=W, H=H, Nx=nx, Ny=ny, tpms_type=cfg['tpms_type'],
                             L_cell_m=Lmean / 1000., t_wall_m=tmean / 1000.,
                             eps=eps, r_h=float(arrays['r_h_arr'].mean()), rho=rho, mu=mu,
                             T_in=Tin, inlet_lo=in_lo, inlet_hi=in_hi, v_inlet=velocity,
                             outlet_lo=out_lo, outlet_hi=out_hi, wall_refine=False,
                             P_ref_abs=pref, rho_inlet_ref=rho,
                             dx_arr=dx, dy_arr=dy, K_arr=K, cF_arr=cF),
                eps_field=arrays['eps_arr'].T if is_a else arrays['eps_arr'][:, ::-1],
                K_field=Kfield, cF_field=cFfield, cf_aniso=float(cfg.get('cf_aniso', 0.)),
                convergence_mode=os.environ.get('TPMSHX_CONV_MODE', 'legacy'),
                inlet_mask=(_port_fractions_1d(dx, in_lo, in_hi)[0] if ports is not None else None))


def prepare_screening_2d(x, cfg=None, fc=None, *, case_id):
    cfg = {**DEFAULT_CONFIG, **(cfg or {})}
    if (cfg['dir_A'], cfg['dir_B']) != (0, 3):
        raise ValueError('2D screening flow mapping supports only +x A and -y B')
    for key in ('L_domain', 'H_domain', 'T_inA', 'T_inB', 'P_inA', 'P_inB', 'k_s', 'rho_s'):
        if not np.isfinite(cfg[key]) or cfg[key] <= 0.:
            raise ValueError(f'screening {key} must be finite and positive')
    warnings_list = []
    for key in ('fluid_type_A', 'fluid_type_B'):
        fluid = cfg.get(key)
        if fluid is not None and str(fluid).lower() != 'air':
            message = (f'2D optimizer evaluator has no {fluid!r} dispatch yet — '
                       f'{key} runs as AIR. Rankings for water-side cases are not trustworthy.')
            warnings_list.append(message)
            warnings.warn(message, RuntimeWarning, stacklevel=2)
    fc = build_field(x, cfg) if fc is None else fc
    Nx, Ny = _resolve_grid(cfg, fc)
    if min(Nx, Ny) < 2:
        raise ValueError('screening mesh requires at least two cells per axis')
    arrays = fc.build_grid_arrays(Nx, Ny, u_A=cfg['u_A'], u_B=cfg['u_B'],
                                 T_inA=cfg['T_inA'], T_inB=cfg['T_inB'], P_in=cfg['P_inA'])
    grid = dict(dimension=2, length_unit='m', axis_order=('x', 'y'),
                depth_convention='unit_depth', depth_m=1.)
    for axis, count, length in zip('xy', (Nx, Ny), (cfg['L_domain'], cfg['H_domain'])):
        widths = np.full(count, length / count, dtype=np.float64)
        grid['d' + axis] = widths
        grid[axis + '_edges'] = np.r_[0., np.cumsum(widths)]
    flows, rejection = {}, None
    try:
        for side in ('A', 'B'):
            flows[side] = prepare_flow(cfg, fc, arrays, Nx, Ny, side)
    except ChokedFlowError as exc:
        rejection = str(exc)
    fields = {key: arrays[key] for key in SCREENING_FIELDS}
    geometry_fields = dict(L_cell_m=arrays['L_field'] / 1000., t_wall_m=arrays['t_field'] / 1000.)
    computation = {k: v for k, v in cfg.items() if k not in ('penalty_enabled', 'penalty_weight', 'dp_cap_pa')}
    return CaseData(case_id=case_id, config_snapshot=cfg, grid=grid, design_fields=fields,
                    parameters=dict(compute=computation, flow=flows, rejection=rejection),
                    model_refs=(ModelRef('screening', MODEL_VERSIONS['screening']),
                                ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': 'air'})),
                    metadata=dict(mode='screening_2d', model='air_air_volume_ltne_v1',
                                  energy_formulation='conservative_air_model_h', warnings=tuple(warnings_list),
                                  geometry_fields=geometry_fields,
                                  df_options=dict(method=_resolve_method()),
                                  applicability='Optimization screening; inherited flow/thermal coupling and port limitations; physical validation unestablished.'))
