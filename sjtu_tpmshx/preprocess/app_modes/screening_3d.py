"""Prepare the inherited 3D air/air frozen-B screening model."""
import numpy as np
from sjtu_tpmshx.domain.run_environment import require_f2_mode
from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.model_refs import ModelRef
from sjtu_tpmshx.models.catalog import MODEL_VERSIONS
from sjtu_tpmshx.models.screening import DEFAULT_CONFIG, SCREENING_FIELDS, _build_3d_arrays, build_field, validate_screening_config
from sjtu_tpmshx.models.tpms_calc import air_density, air_viscosity
from sjtu_tpmshx.models.envelope import predict_outlet_p_sq
from sjtu_tpmshx.models.df_projection import project_fields_to_streamwise_K_cF_3d
from sjtu_tpmshx.df_surrogate.predict import _resolve_method
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


def prepare_screening_3d(x_decision, cfg, *, case_id,
                         Nx=40, Ny=16, Nz=16, Lz=.042, max_outer=3,
                         outer_tol_K=.5, alpha_outer=.6, max_iter_simple=800,
                         tol_simple=1e-2, max_iter_energy=2000, tol_energy=.5,
                         roughness_mode=None, roughness_eps_um=None,
                         convergence_mode='f2', verbose=True):
    cfg = {**DEFAULT_CONFIG, **cfg}
    validate_screening_config(cfg, dimension=3)
    if max_outer < 1:
        raise ValueError(f'max_outer must be >= 1 (got {max_outer})')
    if min(Nx, Ny, Nz) < 2 or not np.isfinite(Lz) or Lz <= 0.:
        raise ValueError('3D screening requires a positive depth and at least two cells per axis')
    convergence_mode = require_f2_mode(convergence_mode)
    L_dom = float(cfg['L_domain']); H_dom = float(cfg['H_domain'])
    u_A   = float(cfg['u_A']);     u_B   = float(cfg['u_B'])
    T_inA = float(cfg['T_inA']);   T_inB = float(cfg['T_inB'])
    P_inA = float(cfg.get('P_inA', 101325.0))
    P_inB = float(cfg.get('P_inB', P_inA))
    tpms_type = cfg.get('tpms_type', 'Diamond')
    k_s   = float(cfg.get('k_s', 17.0))
    rho_s = float(cfg.get('rho_s', 2700.0))

    # 1. Build 2D field, extrude to 3D arrays
    fc = build_field(x_decision, cfg)
    arrays = _build_3d_arrays(fc, Nx, Ny, Nz,
                               u_A, u_B, T_inA, T_inB, P_inA, k_s, tpms_type, P_inB=P_inB)

    dx_arr = np.full(Nx, L_dom / Nx, dtype=np.float64)
    dy_arr = np.full(Ny, H_dom / Ny, dtype=np.float64)
    dz_arr = np.full(Nz, Lz    / Nz, dtype=np.float64)

    # 2. Project to SIMPLE 3D K/cF arrays (per-row mean over cross-stream)
    K_A, cF_A = project_fields_to_streamwise_K_cF_3d(
        arrays['L_field'], arrays['t_field'], arrays['eps_f_arr'],
        tpms_type, Ny_sim=Nx, Nz_sim=Nz, fluid='A',
        streamwise_dx=dx_arr, z_dx=dz_arr)
    K_B, cF_B = project_fields_to_streamwise_K_cF_3d(
        arrays['L_field'], arrays['t_field'], arrays['eps_f_arr'],
        tpms_type, Ny_sim=Ny, Nz_sim=Nz, fluid='B',
        streamwise_dx=dy_arr, z_dx=dz_arr)

    # 2026-05-13 — air-side wall-roughness correction (Norris 1971 or
    # Bhatti-Shah-Haaland). Resolve mode + ε from env if not passed in.
    # Water side untouched (the per-topology water fit (`nu_water_topo`)
    # embeds AM roughness already).
    if roughness_mode is None or roughness_eps_um is None:
        from sjtu_tpmshx.models.roughness import resolve_mode_from_env as _resolve
        _env_mode, _env_eps = _resolve(default='baseline')
        roughness_mode = roughness_mode or _env_mode
        roughness_eps_um = roughness_eps_um if roughness_eps_um is not None else _env_eps
    if roughness_mode != 'baseline':
        from sjtu_tpmshx.models.roughness import f_enhancement, nu_extra_factor
        from sjtu_tpmshx.models.tpms_calc import geometry as _tpms_geom
        _g_case = _tpms_geom(tpms_type, float(fc.L_ctrl.mean()),
                              float(fc.t_ctrl.mean()), k_s)
        _D_h_m = _g_case['D_h']
        _D_h_mm = _D_h_m * 1000.0
        # Standalone case-Re using freestream A inlet props (mirror validate
        # script). Independent of later SIMPLE init.
        _rho_A_in = air_density(T_inA, P_inA)
        _mu_A_in  = air_viscosity(T_inA)
        Re_A_case = float(_rho_A_in * abs(u_A) * _D_h_m / _mu_A_in)
        f_gain_A = float(f_enhancement(Re_A_case, roughness_mode,
                                        eps_um=roughness_eps_um,
                                        D_h_mm=_D_h_mm))
        K_A = (K_A / f_gain_A).astype(np.float64, copy=False)
        cF_A = (cF_A * f_gain_A).astype(np.float64, copy=False)
        # bhatti_shah_1b overrides Nu × 1.28 baked into compute(); norris_1a
        # leaves Nu unchanged (nu_extra_factor returns 1.0).
        nu_extra_A = float(nu_extra_factor(Re_A_case, roughness_mode,
                                            eps_um=roughness_eps_um,
                                            D_h_mm=_D_h_mm))
        if nu_extra_A != 1.0:
            arrays['h_vA_arr'] = (arrays['h_vA_arr'] * nu_extra_A).astype(
                np.float64, copy=False)
        if verbose:
            _log.info(f"[3D rough] mode={roughness_mode} eps={roughness_eps_um} μm  "
                      f"Re_A={Re_A_case:.0f}  f_gain_A={f_gain_A:.3f}  "
                      f"nu_extra_A={nu_extra_A:.3f}")

    # 3. Build SIMPLE 3D for both fluids. Fluid A: +x streamwise → axis swap
    # so SIMPLE-y = real-x; Fluid B: -y streamwise → SIMPLE-y = real-y reversed.
    rho_A0 = air_density(T_inA, P_inA); mu_A0 = air_viscosity(T_inA)
    rho_B0 = air_density(T_inB, P_inB); mu_B0 = air_viscosity(T_inB)
    eps_mean = float(arrays['eps_arr'].mean())
    # M2b (2026-07-09): the deferred xmod-eps-field-3d-evaluator finding is
    # CLOSED — the per-cell eps_field is installed on both solvers below
    # (fluid A with the SIMPLE-A axis swap), so graded designs run the exact
    # ε in continuity, μ_eff and the M2b VANS momentum ratios. eps_mean
    # remains only as the constructor scalar (the field overrides it).

    # 1D D-F closed-form seed for P_ref_abs (matches retired evaluate_3d)
    K_mean_A = float(np.mean(K_A))
    cF_mean_A = float(np.mean(cF_A))
    G_A = rho_A0 * u_A
    C_A = mu_A0 * G_A / max(K_mean_A, 1e-16) + cF_mean_A * G_A * G_A
    P_out_sq_A = predict_outlet_p_sq(P_inA, T_inA, C_A, L_dom)

    K_mean_B = float(np.mean(K_B))
    cF_mean_B = float(np.mean(cF_B))
    G_B = rho_B0 * u_B
    C_B = mu_B0 * G_B / max(K_mean_B, 1e-16) + cF_mean_B * G_B * G_B
    P_out_sq_B = predict_outlet_p_sq(P_inB, T_inB, C_B, H_dom)

    rejection = None
    if P_out_sq_A <= 0. or P_out_sq_B <= 0.:
        rejection = ('P_out² ≤ 0 on the 1D D-F seed — operating point is choked '
                     f'(A={P_out_sq_A:.3e}, B={P_out_sq_B:.3e}).')
    flows = {}
    if rejection is None:
        flows['A'] = dict(initial=dict(Lx=H_dom, Ly=L_dom, Lz=Lz, Nx=Ny, Ny=Nx, Nz=Nz,
                                      rho=rho_A0, mu=mu_A0, T_in=T_inA, v_inlet=u_A,
                                      eps=eps_mean, K_arr=K_A, cF_arr=cF_A,
                                      P_ref_abs=float(np.sqrt(P_out_sq_A)),
                                      dx_arr=dy_arr, dy_arr=dx_arr, dz_arr=dz_arr),
                           eps_field=arrays['eps_arr'].transpose(1, 0, 2))
        flows['B'] = dict(initial=dict(Lx=L_dom, Ly=H_dom, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
                                      rho=rho_B0, mu=mu_B0, T_in=T_inB, v_inlet=u_B,
                                      eps=eps_mean, K_arr=K_B, cF_arr=cF_B,
                                      P_ref_abs=float(np.sqrt(P_out_sq_B)),
                                      dx_arr=dx_arr, dy_arr=dy_arr, dz_arr=dz_arr),
                           eps_field=arrays['eps_arr'][:, ::-1, :])
    grid = dict(dimension=3, length_unit='m', axis_order=('x', 'y', 'z'))
    for axis, widths in zip('xyz', (dx_arr, dy_arr, dz_arr)):
        grid['d' + axis] = widths
        grid[axis + '_edges'] = np.r_[0., np.cumsum(widths)]
    fields = {key: arrays[key] for key in SCREENING_FIELDS}
    geometry_fields = dict(L_cell_m=arrays['L_field'] / 1000., t_wall_m=arrays['t_field'] / 1000.)
    compute = dict(L_domain=L_dom, H_domain=H_dom, Lz=Lz, rho_s=rho_s,
                   T_inA=T_inA, T_inB=T_inB, P_inA=P_inA, P_inB=P_inB,
                   rho_A0=rho_A0, rho_B0=rho_B0, G_A=G_A,
                   K_mean_A=K_mean_A, cF_mean_A=cF_mean_A, dir_A=0, dir_B=3,
                   max_outer=max_outer, outer_tol_K=outer_tol_K, alpha_outer=alpha_outer,
                   max_iter_simple=max_iter_simple, tol_simple=tol_simple,
                   max_iter_energy=max_iter_energy, tol_energy=tol_energy,
                   convergence_mode=convergence_mode, verbose=verbose)
    return CaseData(case_id=case_id, config_snapshot=cfg, grid=grid, design_fields=fields,
                    parameters=dict(compute=compute, flow=flows, rejection=rejection),
                    model_refs=(ModelRef('screening', MODEL_VERSIONS['screening']),
                                ModelRef('fluid', MODEL_VERSIONS['fluid'], {'fluid': 'air'})),
                    metadata=dict(mode='screening_3d', model='air_air_frozen_b_volume_ltne_v1',
                                  energy_formulation='conservative_air_model_h',
                                  roughness_mode=roughness_mode, roughness_m=roughness_eps_um * 1e-6,
                                  geometry_fields=geometry_fields,
                                  df_options=dict(method=_resolve_method()),
                                  applicability='Optimization screening; frozen cold B flow, native-mass air integral enthalpy and envelope gates; physical validation unestablished.'))
