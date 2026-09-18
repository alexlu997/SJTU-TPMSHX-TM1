"""2D SIMPLE/LTNE coupling and native heat/pressure evidence."""
import numpy as np
from sjtu_tpmshx.domain.run_warnings import range_context
from sjtu_tpmshx.models.nu_correlations import record_raw_nu_range, warn_sco2_nu_evidence
from sjtu_tpmshx.models.tpms_props import record_temperature_ranges
from sjtu_tpmshx.models.grid import cell_average
from sjtu_tpmshx.models.local_heat_transfer import local_nusselt, local_speed
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.validator import compute_volumetric_htc
from sjtu_tpmshx.solvers.coupling_skeleton import OuterConvergence, run_outer_coupling
from sjtu_tpmshx.solvers._solve_common import inlet_pressure_state
from sjtu_tpmshx.solvers.ltne_energy import solve_full_domain
from sjtu_tpmshx.solvers.simple_solver import _prolong_mass_faces_2d
from sjtu_tpmshx.solvers.envelope import gate_solution, mach_field_max
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


from sjtu_tpmshx.result_math import _enthalpy_balance_2d  # noqa: F401 - existing public name


from sjtu_tpmshx.result_math import _pipe_weighted  # noqa: F401 - existing public name


def _simple_staggered_to_real_2d(simp, direction):
    """Map SIMPLE's +y-stream staggered faces to signed real x/y faces."""
    if direction in (0, 1):
        faces = [simp.v.T.copy(), simp.u.T.copy()]
        stream_axis = 0
    else:
        faces = [simp.u.copy(), simp.v.copy()]
        stream_axis = 1
    if direction in (1, 3):
        faces[stream_axis] *= -1.0
        faces = [np.flip(face, axis=stream_axis) for face in faces]
    return tuple(np.ascontiguousarray(face, dtype=np.float64) for face in faces)


def _simple_scalar_to_real_2d(field, direction):
    out = np.asarray(field, dtype=np.float64).T.copy() \
        if direction in (0, 1) else np.asarray(field, dtype=np.float64).copy()
    if direction in (1, 3):
        out = np.flip(out, axis=0 if direction == 1 else 1)
    return np.ascontiguousarray(out)


def _simple_pressure_abs_2d(simp, direction, P_in):
    """Air uses the SIMPLE absolute state; frozen fluids retain their anchor."""
    gauge = _simple_scalar_to_real_2d(simp.P, direction)
    if simp.fluid_type == 'ideal_gas':
        return np.ascontiguousarray(simp.P_ref_abs + gauge)
    inlet_gauge = _pipe_weighted(simp.P[:, 0], simp.inlet_frac.astype(np.float64))
    return np.ascontiguousarray(P_in + gauge - inlet_gauge)


def _face_mass_fluxes_2d(simp, direction, eps_side, dx, dy):
    """Actual signed SIMPLE face mass flows per metre depth."""
    ux, uy = _simple_staggered_to_real_2d(simp, direction)
    rho = _simple_scalar_to_real_2d(simp.rho_field, direction)
    coef = rho * np.broadcast_to(np.asarray(eps_side, dtype=np.float64), rho.shape)
    cx = np.empty(ux.shape, dtype=np.float64)
    cy = np.empty(uy.shape, dtype=np.float64)
    cx[1:-1] = 0.5 * (coef[:-1] + coef[1:])
    cx[0] = coef[0]; cx[-1] = coef[-1]
    cy[:, 1:-1] = 0.5 * (coef[:, :-1] + coef[:, 1:])
    cy[:, 0] = coef[:, 0]; cy[:, -1] = coef[:, -1]
    return (np.ascontiguousarray(cx * ux * np.asarray(dy)[None, :]),
            np.ascontiguousarray(cy * uy * np.asarray(dx)[:, None]))


def _inlet_transport_2d(simp, direction, eps_side, cp_in, dx, dy):
    """Actual inward SIMPLE face mass times cp(Tin, Pin), W/(m K)."""
    mx, my = _face_mass_fluxes_2d(simp, direction, eps_side, dx, dy)
    if direction == 0:
        flux = mx[0]
    elif direction == 1:
        flux = -mx[-1]
    elif direction == 2:
        flux = my[:, 0]
    else:
        flux = -my[:, -1]
    return np.ascontiguousarray(flux * cp_in)


from sjtu_tpmshx.result_math import _outlet_temperature_2d  # noqa: F401 - existing public name


def _compute_pressure_2d(simpA, simpB, dir_A, dir_B, P_inA, P_inB):
    """Property pressure fields and legacy cell-row dP; public dP uses faces."""
    # Pipe-weighted pressure references (exclude wall cells under partial BC).
    # SIMPLE convention: inlet row = P[:, 0], outlet row = P[:, -1]; inlet_frac
    # / outlet_frac are 1-D (length = SIMPLE's perpendicular dim) indicating the
    # open fraction of each cell at the boundary. A plain row mean mixes wall
    # and pipe cells, severely diluting dP for partial-BC flows (validation
    # showed B's dP under-estimated by >10x in default cross-flow cases).
    _wA_in  = simpA.inlet_frac.astype(np.float64)
    _wA_out = simpA.outlet_frac.astype(np.float64)
    _wB_in  = simpB.inlet_frac.astype(np.float64)
    _wB_out = simpB.outlet_frac.astype(np.float64)

    P_ref_A       = _pipe_weighted(simpA.P[:,  0], _wA_in)   # pipe-inlet gauge
    P_ref_B       = _pipe_weighted(simpB.P[:,  0], _wB_in)
    P_out_gauge_A = _pipe_weighted(simpA.P[:, -1], _wA_out)  # pipe-outlet gauge
    P_out_gauge_B = _pipe_weighted(simpB.P[:, -1], _wB_out)

    P_fA = _simple_pressure_abs_2d(simpA, dir_A, P_inA)
    P_fB = _simple_pressure_abs_2d(simpB, dir_B, P_inB)

    # Pressure drop = pipe-inlet minus pipe-outlet gauge pressure. The
    # P_inA/P_inB shift cancels in this difference, so using gauge directly
    # is equivalent and avoids double-counting the reference.
    dP_A = P_ref_A - P_out_gauge_A
    dP_B = P_ref_B - P_out_gauge_B
    return P_fA, P_fB, dP_A, dP_B


def _zone_statistics_2d(z_axis, zone_config, za, L, H,
                        energy_dx, energy_dy, Ta, Tb, Ts):
    """Return area-weighted zone statistics and physical boundary positions."""
    if zone_config is not None and za is not None:
        zones = dict(axis_dir=z_axis)
        if z_axis == 'grid':
            # Grid mode: boundaries from zone_config
            zones['boundaries'] = []
            zones['boundaries_x'] = [b * L for b in za.get('x_bounds', [])]
            zones['boundaries_y'] = [b * H for b in za.get('y_bounds', [])]
            # Build dummy Zone objects for statistics
            from sjtu_tpmshx.models.zone_config import Zone
            dummy_zones = [Zone(f'g{r}', gc['y0'], gc['y1'], gc['L'], gc['t'])
                           for r, gc in enumerate(za.get('grid_cells', []))]
            from sjtu_tpmshx.models.zone_config import compute_zone_statistics, format_zone_report
            _ca = energy_dx[:, None] * energy_dy[None, :]
            stats = compute_zone_statistics(Ta, Tb, Ts, za['zone_id'], dummy_zones,
                                            cell_area=_ca)
            _log.info("\n[ZONE STATISTICS]")
            _log.info(format_zone_report(stats))
            zones['stats'] = stats
        else:
            # 1D mode
            from sjtu_tpmshx.models.zone_config import compute_zone_statistics, format_zone_report
            _ca = energy_dx[:, None] * energy_dy[None, :]
            stats = compute_zone_statistics(Ta, Tb, Ts, za['zone_id'],
                                            zone_config.zones, cell_area=_ca)
            _log.info("\n[ZONE STATISTICS]")
            _log.info(format_zone_report(stats))
            zones['stats'] = stats
            zones['boundaries_x'] = None
            zones['boundaries_y'] = None
            if z_axis == 'y':
                zones['boundaries'] = [z.y_frac_end * H for z in zone_config.zones[:-1]]
            else:
                zones['boundaries'] = [z.y_frac_end * L for z in zone_config.zones[:-1]]
        return zones
    return None


def _compute_Q_richardson(
        Ta, Tb, Ts, ucA, vcA, ucB, vcB, rho_cp_A, rho_cp_B,
        simpA, simpB, N_x, N_y, L, H, dir_A, dir_B,
        energy_dx, energy_dy, _x_breaks, _y_breaks,
        T_inA, T_inB, P_inA_val, P_inB_val, eps, za, coeffs,
        _pA, _pB, cfgA, cfgB, u_A, u_B, warnings_list,
        h_vA_coarse, h_vB_coarse, split_A=0.5, cancel_check=None,
        model_inputs=None, model_balance=None, evidence=None, port_wall_refine=False):
    """Heat duty Q via Richardson extrapolation on the enthalpy balance.

    Re-solves the coupled energy field on a 2x-refined grid, applies
    per-side Richardson extrapolation to |Q_A|/|Q_B|, and falls back to
    a 1D plate-average when the refined solve is unavailable. Extracted
    verbatim from ``_run_solvers`` (#9-2D god-function split);
    ``warnings_list`` is appended in place on fallback paths.

    ``split_A`` (offset-isosurface δ): fraction of total ε on side A. 0.5 →
    symmetric (bit-identical). δ≠0 → the refined solve uses the per-side
    porosity (eps_A/eps_B + K_ff scaled by 2s / 2(1−s), mirroring the main
    solve) and each side's duty mass flux is weighted by the same per-side
    factor so ṁ_A / ṁ_B reflect ε_A / ε_B (not a shared ε/2).

    Returns ``(Q_total, Q_A_fine, Q_B_fine, Q_solid_richardson,
    richardson_warn, richardson_info)``. Failed refinement keeps user-grid duty.
    """
    # Per-side duty weighting relative to the symmetric ε/2 baseline (= 1.0 at
    # δ=0 ⇒ bit-identical). Matches the K_ff / convective scaling in the main
    # solve so the extracted A / B duties stay balanced on the split geometry.
    from sjtu_tpmshx.models.fluid_props import check_water_state, WaterStateError, check_finite_temperatures
    check_water_state(_pA.name, T_inA, P_inA_val, where='Richardson inlet A')
    check_water_state(_pB.name, T_inB, P_inB_val, where='Richardson inlet B')
    _asymQ = (float(split_A) != 0.5)
    _fAQ = 2.0 * float(split_A)
    _fBQ = 2.0 * (1.0 - float(split_A))
    from sjtu_tpmshx.solvers.simple_solver import _aligned_grid, _port_fractions_1d
    # Compute Q with Richardson extrapolation (N_x×N_y + 2N_x×2N_y)
    _cell_area = energy_dx[:, None] * energy_dy[None, :]  # (Nx, Ny)
    Q_solid_100 = float(np.sum(h_vB_coarse * (Ts - Tb) * _cell_area))

    # Richardson: run energy at 200×100 for Q extrapolation
    Nx2, Ny2 = N_x * 2, N_y * 2
    if port_wall_refine:
        from sjtu_tpmshx.models.grid import split_cells
        energy_dx2, energy_dy2 = split_cells(energy_dx), split_cells(energy_dy)
    else:
        energy_dx2 = _aligned_grid(Nx2, L, list(_x_breaks))
        energy_dy2 = _aligned_grid(Ny2, H, list(_y_breaks))
    # 2026-05-07: `_aligned_grid` silently expands the cell count when
    # `min(2, ...)` per segment forces total > N (case: B partial pipe
    # with 4 break points on x). Read back the actual length so Nx2/Ny2
    # match the returned dx/dy arrays — otherwise solve_full_domain
    # receives mismatched (Nx2, Ny2) vs dx_arr/dy_arr shapes and
    # `h_vB_arr * (Ts - Tb)` broadcasts the wrong way.
    Nx2 = int(len(energy_dx2))
    Ny2 = int(len(energy_dy2))

    # Both thermal BCs and duty use the same physical transverse coordinates.
    # Negative flow reverses the stream axis only, not these port profiles.
    def _profiles(port, direction):
        widths = energy_dy2 if direction in (0, 1) else energy_dx2
        raw_inlet, inlet = _port_fractions_1d(
            widths, port['in_ctr'] - port['in_w'] / 2,
            port['in_ctr'] + port['in_w'] / 2,
            uniform=port.get('uniform_inlet_2d', False))
        outlet = _port_fractions_1d(
            widths, port['out_ctr'] - port['out_w'] / 2,
            port['out_ctr'] + port['out_w'] / 2)[1]
        return raw_inlet, inlet, outlet

    areaA_in2, mA_in2, mA_out2 = _profiles(cfgA, dir_A)
    areaB_in2, mB_in2, mB_out2 = _profiles(cfgB, dir_B)

    # Interpolate fields from coarse to fine grid using actual coordinates
    from scipy.interpolate import RegularGridInterpolator
    x_c1 = np.cumsum(energy_dx) - energy_dx / 2   # coarse centres
    y_c1 = np.cumsum(energy_dy) - energy_dy / 2
    x_c2 = np.cumsum(energy_dx2) - energy_dx2 / 2  # fine centres
    y_c2 = np.cumsum(energy_dy2) - energy_dy2 / 2
    def _interp2(arr):
        if np.ndim(arr) < 2:
            return arr
        f = RegularGridInterpolator((x_c1, y_c1), arr, method='linear',
                                    bounds_error=False, fill_value=None)
        pts = np.stack(np.meshgrid(x_c2, y_c2, indexing='ij'), axis=-1)
        return f(pts)

    ucA2 = _interp2(ucA); vcA2 = _interp2(vcA)
    ucB2 = _interp2(ucB); vcB2 = _interp2(vcB)
    with range_context(side='A', stage='richardson-inlet', layout='scalar'):
        rcp_A2 = _interp2(rho_cp_A if np.ndim(rho_cp_A) > 0 else
                           np.full((N_x, N_y),
                                   _pA.rho(T_inA, P_inA_val) * _pA.cp(T_inA, P_inA_val)))
    with range_context(side='B', stage='richardson-inlet', layout='scalar'):
        rcp_B2 = _interp2(rho_cp_B if np.ndim(rho_cp_B) > 0 else
                           np.full((N_x, N_y),
                                   _pB.rho(T_inB, P_inB_val) * _pB.cp(T_inB, P_inB_val)))
    if za is not None and 'h_vB_arr' in za:
        K_ffA2 = _interp2(za['K_ffA_arr'])
        K_ffB2 = _interp2(za['K_ffB_arr'])
        K_ss2 = _interp2(za['K_ss_arr'])
        eps2 = _interp2(za['eps_arr'])
    else:
        K_ffA2 = coeffs['K_ffA']; K_ffB2 = coeffs['K_ffB']
        K_ss2 = coeffs['K_ss']; eps2 = eps
    # Use the actual last coarse thermal problem, including local Re and split.
    h_vA2, h_vB2 = _interp2(h_vA_coarse), _interp2(h_vB_coarse)
    # Per-side porosity on the refined grid (mirror the main solve) so the
    # Richardson pair is solved with the SAME physics. δ=0 → unchanged.
    if _asymQ:
        K_ffA2_use = K_ffA2 * _fAQ
        K_ffB2_use = K_ffB2 * _fBQ
        epsA2_use = (eps2 * float(split_A) if np.ndim(eps2) > 0
                     else float(eps2) * float(split_A))
        epsB2_use = (eps2 * (1.0 - float(split_A)) if np.ndim(eps2) > 0
                     else float(eps2) * (1.0 - float(split_A)))
    else:
        K_ffA2_use = K_ffA2; K_ffB2_use = K_ffB2
        epsA2_use = None; epsB2_use = None
    Ta_init2, Tb_init2, Ts_init2 = _interp2(Ta), _interp2(Tb), _interp2(Ts)
    for side, props, temperature in (('A', _pA, Ta_init2), ('B', _pB, Tb_init2)):
        with range_context(side=side, stage='richardson-warm', layout='real-cell(x,y)'):
            record_temperature_ranges(props.name, temperature)
    water_pressures = []
    for props, simp, direction, pin, coarse, initial, side in (
            (_pA, simpA, dir_A, P_inA_val, Ta, Ta_init2, 'A'),
            (_pB, simpB, dir_B, P_inB_val, Tb, Tb_init2, 'B')):
        if props.name == 'water':
            if simp is None:
                raise WaterStateError(f'Richardson {side}: actual water pressure unavailable')
            pressure = _simple_pressure_abs_2d(simp, direction, pin)
            check_water_state('water', coarse, pressure, where=f'Richardson coarse {side}')
            refined_pressure = _interp2(pressure)
            check_water_state('water', initial, refined_pressure,
                              where=f'Richardson warm start {side}')
            water_pressures.append((side, refined_pressure))
    # Transfer the SAME integrated inlet transport to the fine face partition.
    # Cumulative interpolation conserves each coarse face's input; it does not
    # interpolate a cell-centre velocity onto a different physical boundary.
    eps_coarse = za['eps_arr'] if za is not None and 'eps_arr' in za else eps
    def _refined_inlet(simp, direction, cp_in, split):
        coarse = energy_dy if direction <= 1 else energy_dx
        fine = energy_dy2 if direction <= 1 else energy_dx2
        flux = _inlet_transport_2d(
            simp, direction, eps_coarse * split, cp_in, energy_dx, energy_dy)
        return np.diff(np.interp(np.r_[0., np.cumsum(fine)],
                                 np.r_[0., np.cumsum(coarse)],
                                 np.r_[0., np.cumsum(flux)]))
    model_kwargs = {}
    if model_inputs is not None:
        model_kwargs = dict(
            model_fluids=model_inputs['model_fluids'],
            accelerate=port_wall_refine,
            mass_flux_A=_prolong_mass_faces_2d(model_inputs['mass_flux_A'], energy_dx, energy_dy, energy_dx2, energy_dy2),
            mass_flux_B=_prolong_mass_faces_2d(model_inputs['mass_flux_B'], energy_dx, energy_dy, energy_dx2, energy_dy2))
        K_ffA2_use = _interp2(model_inputs['K_ffA'])
        K_ffB2_use = _interp2(model_inputs['K_ffB'])
        K_ss2 = _interp2(model_inputs['K_ss'])
    with range_context(side='A', stage='richardson-inlet', layout='scalar'):
        inlet_flux_A2 = (_refined_inlet(
            simpA, dir_A, _pA.cp(T_inA, P_inA_val), split_A)
            if model_inputs is None else None)
    with range_context(side='B', stage='richardson-inlet', layout='scalar'):
        inlet_flux_B2 = (_refined_inlet(
            simpB, dir_B, _pB.cp(T_inB, P_inB_val), 1. - split_A)
            if model_inputs is None else None)
    Ta2, Tb2, Ts2, refined_info = solve_full_domain(
        L, H, Nx2, Ny2, T_inA, T_inB,
        K_ffA2_use, K_ffB2_use, K_ss2, h_vA2, h_vB2,
        rcp_A2, rcp_B2, eps2,
        ucA2, vcA2, ucB2, vcB2,
        # Damped model-h can need more sweeps on the doubled thermal grid.
        # Keep the convergence criteria; stop early at the same accepted state.
        dir_A, dir_B, tol=0.5, max_iter=12000 if model_inputs is not None else 5000,
        dx_arr=energy_dx2, dy_arr=energy_dy2,
        inlet_mask_A=areaA_in2, inlet_mask_B=areaB_in2, return_info=True,
        inlet_flux_A=inlet_flux_A2,
        inlet_flux_B=inlet_flux_B2,
        Ta_init=Ta_init2, Tb_init=Tb_init2, Ts_init=Ts_init2,
        eps_A=epsA2_use, eps_B=epsB2_use, cancel_check=cancel_check, **model_kwargs)
    for side, props, temperature in (('A', _pA, Ta2), ('B', _pB, Tb2)):
        with range_context(side=side, stage='richardson-return', layout='real-cell(x,y)'):
            record_temperature_ranges(props.name, temperature)
    for side, pressure in water_pressures:
        check_water_state('water', Ta2 if side == 'A' else Tb2, pressure,
                          where=f'Richardson return {side}')
    check_finite_temperatures(Ta2, Tb2, Ts2, where='Richardson energy return')
    if evidence is not None:
        evidence.update(Ta=Ta2, Tb=Tb2, Ts=Ts2, dx=energy_dx2, dy=energy_dy2,
                        ucA=ucA2, vcA=vcA2, ucB=ucB2, vcB=vcB2,
                        rho_cp_A=rcp_A2, rho_cp_B=rcp_B2, eps=eps2,
                        inlet_A=mA_in2, outlet_A=mA_out2, inlet_B=mB_in2, outlet_B=mB_out2,
                        model_h_balance=refined_info.get('model_h_balance'))
    richardson_info = dict(refined_info, extrapolated=False)
    refined_ok = bool(refined_info['converged'] and all(
        np.all(np.isfinite(field)) for field in (Ta2, Tb2, Ts2)))
    if model_inputs is not None:
        fine_balance = refined_info['model_h_balance']
        fine_balance.update(
            mass_source='conservative coarse-face prolongation; no fine SIMPLE',
            state='raw refined thermal return', outer_index=model_inputs['outer_index'],
            outer_converged=model_balance['outer_converged'],
            post_after_last_thermal=model_balance['post_after_last_thermal'])
        fine_balance['passed'] = bool(fine_balance['passed'] and model_balance['outer_converged']
                                       and not model_balance['post_after_last_thermal'])
        refined_ok = bool(refined_ok and fine_balance['passed'] and model_balance['passed'])
    _area2 = energy_dx2[:, None] * energy_dy2[None, :]
    if za is not None and 'h_vB_arr' in za:
        Q_solid_200 = float(np.sum(h_vB2 * (Ts2 - Tb2) * _area2))
    else:
        Q_solid_200 = float(np.sum(h_vB2 * (Ts2 - Tb2) * _area2))
    # Diagnostic only — solid-side Richardson retains the old signed
    # convention and lets us track grid convergence on ∑h_vB·(Ts−Tb).
    Q_solid_richardson = ((4.0 * Q_solid_200 - Q_solid_100) / 3.0
                          if refined_ok else Q_solid_100)

    # User-grid duty retains the original SIMPLE port profiles.
    mA_in  = simpA.inlet_frac.astype(np.float64)  if simpA is not None else None
    mA_out = simpA.outlet_frac.astype(np.float64) if simpA is not None else None
    mB_in  = simpB.inlet_frac.astype(np.float64)  if simpB is not None else None
    mB_out = simpB.outlet_frac.astype(np.float64) if simpB is not None else None
    rho_cp_A_fld = (rho_cp_A if np.ndim(rho_cp_A) > 0
                    else np.full((N_x, N_y), rho_cp_A))
    rho_cp_B_fld = (rho_cp_B if np.ndim(rho_cp_B) > 0
                    else np.full((N_x, N_y), rho_cp_B))

    # sCO2 (audit 2026-06-28 D1): true mass-weighted enthalpy duty ṁ·(⟨h_in⟩−
    # ⟨h_out⟩); cp(T_in)·ΔT is −40 %…+224 % wrong across the pseudocritical cp
    # spike. air/water pass None → byte-identical legacy ρcp·ΔT (golden-safe).
    _enth_A = _pA.enthalpy if _pA.name == 'sco2' else None
    _enth_B = _pB.enthalpy if _pB.name == 'sco2' else None

    # Per-side void fraction ε_side = ε·s (N1 fix, 2026-07-07): velocities are
    # interstitial, so the physical face mass flux is ε_side·ρ·|u|·A. The old
    # code integrated with NO ε (duty over-read by 1/ε_side ≈ 2.7× on the
    # golden case, self-inconsistent with Q_solid_richardson by the same
    # factor) and applied only the asym reweight 2s/2(1−s) — i.e. the split
    # RATIO was right but the ε/2 base factor was missing. ε_side inside the
    # balance supersedes that reweight: ε·s = (ε/2)·2s. δ=0 → ε/2 per side;
    # matches the 3D flux extraction convention (flux_3d eps_mode='ltne').
    _sA_Q = float(split_A)
    _sB_Q = 1.0 - float(split_A)
    try:
        if model_inputs is not None:
            Q_A_fine = model_balance['A']['Q_advective_W_per_m']
            Q_B_fine = model_balance['B']['Q_advective_W_per_m']
            Q_A_coarse = fine_balance['A']['Q_advective_W_per_m'] if refined_ok else float('nan')
            Q_B_coarse = fine_balance['B']['Q_advective_W_per_m'] if refined_ok else float('nan')
        else:
            with range_context(side='A', stage='main-duty', layout='duty-source'):
                Q_A_fine = _enthalpy_balance_2d(
                    Ta, ucA, vcA, rho_cp_A_fld, dir_A, energy_dx, energy_dy,
                    inlet_mask=mA_in, outlet_mask=mA_out,
                    enthalpy_fn=_enth_A, rho_fn=_pA.rho, P_ref=P_inA_val,
                    eps_side=eps * _sA_Q, T_in=T_inA)
            with range_context(side='B', stage='main-duty', layout='duty-source'):
                Q_B_fine = _enthalpy_balance_2d(
                    Tb, ucB, vcB, rho_cp_B_fld, dir_B, energy_dx, energy_dy,
                    inlet_mask=mB_in, outlet_mask=mB_out,
                    enthalpy_fn=_enth_B, rho_fn=_pB.rho, P_ref=P_inB_val,
                    eps_side=eps * _sB_Q, T_in=T_inB)
            if refined_ok:
                with range_context(side='A', stage='richardson-duty', layout='duty-source'):
                    Q_A_coarse = _enthalpy_balance_2d(
                        Ta2, ucA2, vcA2, rcp_A2, dir_A, energy_dx2, energy_dy2,
                        inlet_mask=mA_in2, outlet_mask=mA_out2,
                        enthalpy_fn=_enth_A, rho_fn=_pA.rho, P_ref=P_inA_val,
                        eps_side=eps2 * _sA_Q, T_in=T_inA)
                with range_context(side='B', stage='richardson-duty', layout='duty-source'):
                    Q_B_coarse = _enthalpy_balance_2d(
                        Tb2, ucB2, vcB2, rcp_B2, dir_B, energy_dx2, energy_dy2,
                        inlet_mask=mB_in2, outlet_mask=mB_out2,
                        enthalpy_fn=_enth_B, rho_fn=_pB.rho, P_ref=P_inB_val,
                        eps_side=eps2 * _sB_Q, T_in=T_inB)
            else:
                Q_A_coarse = Q_B_coarse = float('nan')
        # A-1 refactor (2026-04-24): apply Richardson to |Q_A| and |Q_B|
        # separately, THEN take max. Each Richardson acts on a smooth
        # (single-sign) function across refinement, so the formal
        # 2nd-order extrapolation stays valid. Prior pipeline applied
        # Richardson after max(), which fails if max-argument flips
        # between the coarse and fine grids.
        # FIX (2026-06-24 audit): Richardson r=2 weights the FINER grid by r^2=4.
        # The historical names here are INVERTED relative to grid resolution:
        # Q_*_fine is built from `Ta`/`energy_dx` (the USER grid = COARSER), while
        # Q_*_coarse is built from `Ta2`/`energy_dx2` (the 2x-REFINED = FINER) solve.
        # So the 4x weight must sit on Q_*_coarse (the finer value). Disambiguate
        # with explicit aliases. Prior code put 4x on Q_*_fine (user/coarse grid),
        # which AMPLIFIES the O(h^2) error ~1.25x instead of cancelling it; the
        # solid-side Richardson in this same function (the _200/_100 site) is correct.
        Q_A_user, Q_A_ref2x = abs(Q_A_fine), abs(Q_A_coarse)
        Q_B_user, Q_B_ref2x = abs(Q_B_fine), abs(Q_B_coarse)
        Q_A_ext = (4.0 * Q_A_ref2x - Q_A_user) / 3.0
        Q_B_ext = (4.0 * Q_B_ref2x - Q_B_user) / 3.0
        richardson_info['extrapolated'] = bool(
            refined_ok and np.isfinite(Q_A_ext) and np.isfinite(Q_B_ext))
        # 2026-05-09 — NaN-fallback: if either side's 2× refined solve
        # NaN-blew up (e.g. ConstDF-v1 K extrapolation at t outside
        # [0.3, 0.5] mm produces unphysical Brinkman coefficients on the
        # finer grid), Richardson extrapolation propagates nan up to
        # Q_total. Fall back to the directly-measured Q_fine value, which
        # only depends on the user-grid Ta (already nan-guarded above).
        # User still sees a finite Q in the UI; we set richardson_warn
        # so the warning banner reflects degraded grid convergence.
        if not richardson_info['extrapolated']:
            Q_A_ext = abs(Q_A_fine) if np.isfinite(Q_A_fine) else float('nan')
            Q_B_ext = abs(Q_B_fine) if np.isfinite(Q_B_fine) else float('nan')
        # Robust max across (possibly nan) candidates: prefer finite values.
        _q_candidates = [v for v in (Q_A_ext, Q_B_ext)
                         if np.isfinite(v)]
        Q_total = max(_q_candidates) if _q_candidates else float('nan')

        Q_fine_max = max(abs(Q_A_fine), abs(Q_B_fine))
        Q_coarse_max = max(abs(Q_A_coarse), abs(Q_B_coarse))
        # Flag when fine vs coarse grid differ a lot (Richardson 2nd-order
        # assumption in doubt). Per-side unified metric: compare the side
        # that dominates Q_total. Also flag when Richardson fell back to
        # the direct Q_fine (means the 2× refined solve was unreliable).
        _denom = max(Q_fine_max, 1e-12)
        richardson_warn = (
            (np.isfinite(Q_coarse_max)
             and abs(Q_fine_max - Q_coarse_max) / _denom > 0.10)
            or (not np.isfinite(Q_A_coarse) or not np.isfinite(Q_B_coarse)))
    except WaterStateError:
        raise
    except Exception as _q_exc:
        if model_inputs is not None:
            raise
        richardson_info['extrapolated'] = False
        import traceback as _tb
        _tb.print_exc()
        _log.warning(f"[Q-calc] Richardson try-block raised {_q_exc!r} — "
                     f"falling through to 1D-mean fallback.")
        Q_A_fine = Q_B_fine = float('nan')
        Q_A_ext = Q_B_ext = float('nan')
        Q_fine_max = float('nan')
        Q_total = float('nan')
        richardson_warn = False

    # 2026-05-09 — UNCONDITIONAL last-resort 1D fallback. Runs OUTSIDE the
    # try/except above so an exception in the Richardson block doesn't
    # short-circuit it. Computes
    #     Q_A ≈ m_dot_A · cp_A · |T_inA − ⟨T_out_A⟩|
    # using the legacy finite-only outlet-face mean. This Q fallback is
    # independent of the result/UI mass-weighted outlet temperature. Finite
    # Richardson / Q_*_fine duty remains unchanged.
    if not np.isfinite(Q_total) and model_inputs is None:
        try:
            # Outlet face per side. dir_code: 0=+x 1=-x 2=+y 3=-y.
            if dir_A == 0:    Tout_A_face = Ta[-1, :]
            elif dir_A == 1:  Tout_A_face = Ta[0, :]
            elif dir_A == 2:  Tout_A_face = Ta[:, -1]
            else:             Tout_A_face = Ta[:, 0]
            if dir_B == 0:    Tout_B_face = Tb[-1, :]
            elif dir_B == 1:  Tout_B_face = Tb[0, :]
            elif dir_B == 2:  Tout_B_face = Tb[:, -1]
            else:             Tout_B_face = Tb[:, 0]
            _Tout_A_finite = Tout_A_face[np.isfinite(Tout_A_face)]
            _Tout_B_finite = Tout_B_face[np.isfinite(Tout_B_face)]
            T_out_A_mean = (float(np.mean(_Tout_A_finite))
                            if _Tout_A_finite.size else float(T_inA))
            T_out_B_mean = (float(np.mean(_Tout_B_finite))
                            if _Tout_B_finite.size else float(T_inB))
            with range_context(side='A', stage='fallback-inlet', layout='scalar'):
                rho_A_in = float(_pA.rho(T_inA, P_inA_val))
            with range_context(side='B', stage='fallback-inlet', layout='scalar'):
                rho_B_in = float(_pB.rho(T_inB, P_inB_val))
            with range_context(side='A', stage='fallback-inlet', layout='scalar'):
                cp_A_in  = float(_pA.cp(T_inA, P_inA_val))
            with range_context(side='B', stage='fallback-inlet', layout='scalar'):
                cp_B_in  = float(_pB.cp(T_inB, P_inB_val))
            A_in_A = float(cfgA.get('in_w', H))
            A_in_B = float(cfgB.get('in_w', L))
            m_dot_A = rho_A_in * abs(u_A) * A_in_A
            m_dot_B = rho_B_in * abs(u_B) * A_in_B
            # Per-side void fraction ε·s (N1 fix, 2026-07-07): interstitial
            # velocity ⇒ ṁ_phys = ε_side·ρ·u·A. Replaces the ε-less 2s/2(1−s)
            # asym reweight (same ratio, adds the missing ε/2 base factor).
            _eps_mean_1d = float(np.mean(eps))
            m_dot_A *= _eps_mean_1d * float(split_A)
            m_dot_B *= _eps_mean_1d * (1.0 - float(split_A))
            # sCO2 (D1): ṁ·Δh even in the last-resort fallback (cp_in·ΔT is
            # badly wrong near the pseudocritical line). air/water keep cp·ΔT.
            if _pA.name == 'sco2':
                Q_A_simple = m_dot_A * abs(float(_pA.enthalpy(T_inA, P_inA_val))
                                           - float(_pA.enthalpy(T_out_A_mean, P_inA_val)))
            else:
                Q_A_simple = m_dot_A * cp_A_in * abs(T_inA - T_out_A_mean)
            if _pB.name == 'sco2':
                Q_B_simple = m_dot_B * abs(float(_pB.enthalpy(T_inB, P_inB_val))
                                           - float(_pB.enthalpy(T_out_B_mean, P_inB_val)))
            else:
                Q_B_simple = m_dot_B * cp_B_in * abs(T_inB - T_out_B_mean)
            Q_total = max(Q_A_simple, Q_B_simple)
            if np.isfinite(Q_total):
                warnings_list.append(
                    f"Q_total computed via 1D plate-average fallback "
                    f"(m_dot · cp · |T_in − ⟨T_out⟩|) because the "
                    f"cross-stream-resolved enthalpy integral was unavailable. "
                    f"Q_A={Q_A_simple:.0f} W/m, Q_B={Q_B_simple:.0f} W/m. "
                    f"Tighten tol or refine grid for production-grade Q.")
                richardson_warn = True
            _log.warning(f"[Q-calc] 1D fallback: Q_A={Q_A_simple:.1f}, "
                         f"Q_B={Q_B_simple:.1f}, Q_total={Q_total:.1f} W/m  "
                         f"(T_out_A_mean={T_out_A_mean:.2f}K, "
                         f"T_out_B_mean={T_out_B_mean:.2f}K)")
        except WaterStateError:
            raise
        except Exception as _fb_exc:
            import traceback as _tb2
            _tb2.print_exc()
            _log.warning(f"[Q-calc] 1D fallback also raised {_fb_exc!r} — "
                         f"Q_total stays nan.")
    if not richardson_info['extrapolated']:
        richardson_warn = True
        Q_solid_richardson = Q_solid_100
        source = ('主网格值' if np.isfinite(Q_A_fine) or np.isfinite(Q_B_fine)
                  else ('不可用值' if model_inputs is not None else '1D 最后兜底值'))
        warnings_list.append(
            f"Richardson 细解或外推未通过，换热量使用{source}，未外推 "
            f"(converged={refined_info['converged']}, "
            f"iterations={refined_info['iterations']}, residual={refined_info['residual']:.3e})")
    return (Q_total, Q_A_fine, Q_B_fine, Q_solid_richardson,
            richardson_warn, richardson_info)


def _run_solvers(cfg, fields, control: RunControl = RunControl()):
    """Phase 3: run SIMPLE + coupling loop + pressure + Richardson Q."""
    properties = cfg['static_properties']
    rA, rB = properties['A'], properties['B']
    coeffs = dict(K_ffA=rA['K_ff'], K_ffB=rB['K_ff'],
                  K_ss=properties['geometry']['K_ss'],
                  h_vA=compute_volumetric_htc(rA['A_0'], rA['H_sf']),
                  h_vB=compute_volumetric_htc(rB['A_0'], rB['H_sf']))
    cancel_check = control.cancel_check
    L = cfg['L']; H = cfg['H']
    N_x = cfg['N_x']; N_y = cfg['N_y']
    u_A = cfg['u_A']; u_B = cfg['u_B']
    T_inA = cfg['T_inA']; T_inB = cfg['T_inB']
    cfgA = cfg['cfgA']; cfgB = cfg['cfgB']
    dir_A = cfg['dir_A']; dir_B = cfg['dir_B']
    tpms_type = cfg['tpms_type']
    eps = cfg['eps']
    zone_config = cfg['zone_config']; za = cfg['za']
    warnings_list = cfg['warnings_list']
    fluid_A = cfg.get('fluid_A', 'air')
    fluid_B = cfg.get('fluid_B', 'air')

    energy_dx = fields['energy_dx']; energy_dy = fields['energy_dy']
    _x_breaks = fields['_x_breaks']; _y_breaks = fields['_y_breaks']
    _run_simple = fields['_run_simple']
    simple_warnings = fields['simple_warnings']

    # ── Outer velocity-temperature coupling loop ──
    from sjtu_tpmshx.domain.run_warnings import (
        current_warnings, merge_warnings, warning_scope,
    )
    from sjtu_tpmshx.models import tpms_calc as _tc
    from sjtu_tpmshx.models import fluid_props

    # Use the same FluidModel objects as 3D, including prepared model resources.
    sco2_nu = getattr(cfg.get('compute_cfg'), 'sco2_nu', None)
    nu_observations = {'A': {}, 'B': {}}
    _pA = cfg['_models']['fluid_A'] if '_models' in cfg else fluid_props.get(fluid_A)
    _pB = cfg['_models']['fluid_B'] if '_models' in cfg else fluid_props.get(fluid_B)
    _enthalpy_mode = ('sco2' in (_pA.name, _pB.name)
                      and zone_config is None)
    mA_rows = mB_rows = None

    # 2026-05-09 — bump _MAX_COUPLING 5→10 default. The loop short-circuits
    # once both drho_X and dT_X drop below their respective tolerances, so
    # already-converged cases (most air-air on fitted-window geometries)
    # still exit at iter 3-5 with no extra work. Cases that previously hit
    # iter 5 with dT_B still bouncing (cross-flow + partial-BC inlet) now
    # have headroom to settle without firing the "not converged" warning.
    _MAX_COUPLING = 10
    _COUPLING_TOL = 0.01  # 1% relative change in rho
    _DT_TOL_K     = 1.0   # max |ΔT| between outer iterations, Kelvin
    _ALPHA_COUP = 0.7     # under-relaxation
    # R3 (2026-07-07): SolverConfig production knobs override the autos
    # above (None keeps them bit-identically). max_outer_ltne caps the
    # SIMPLE↔LTNE coupling rounds; outer_tol_K replaces the ΔT criterion.
    _sol_knobs = getattr(cfg.get('compute_cfg'), 'solver', None)
    if _sol_knobs is not None:
        if _sol_knobs.max_outer_ltne is not None:
            _MAX_COUPLING = int(_sol_knobs.max_outer_ltne)
        if _sol_knobs.outer_tol_K is not None:
            _DT_TOL_K = float(_sol_knobs.outer_tol_K)

    # Local-Re Nu rescale (2D #1 fix 2026-04-25): per-cell h_v using local
    # |u_cc|·D_h·ρ/μ Reynolds. Wall cells with u→0 fall to the laminar
    # Hagen-Poiseuille floor (prevents Nu→0 non-physical extrapolation).
    from sjtu_tpmshx.models.nu_correlations import NU_LAM_FLOOR as _NU_LAM_FLOOR_2D

    def _nu_inputs(side_props, side_T_for_Pr, side_P):
        """Retain the 2D property sampling and unguarded Pr denominator."""
        m = fluid_props.get(side_props.name, sco2_nu=sco2_nu)
        Pr = None
        if side_props.name in ('water', 'sco2'):
            # Pr-substitution (2D convention: no k guard) computed here so the
            # registry stays free of the 2D-vs-3D Prandtl differences.
            mu_w = float(side_props.mu(side_T_for_Pr, side_P))
            k_w  = float(side_props.k(side_T_for_Pr, side_P))
            cp_w = float(side_props.cp(side_T_for_Pr, side_P))
            Pr = mu_w * cp_w / k_w
        return m, Pr

    def _nu_dispatch(side_props, side_T_for_Pr, Re, eps_f, L_mm, D_h_mm,
                     side_P=None):
        m, Pr = _nu_inputs(side_props, side_T_for_Pr, side_P)
        return m.nu(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr)

    def _build_hv_local_2d(rho_scalar, mu_scalar, k_f_scalar,
                            u_mag_field, L_mm_field, t_mm_field,
                            *, side_props, side_T_for_Pr, side_P):
        """Per-cell h_v = A_0 · max(Nu(Re_local), Nu_lam) · k_f / D_h.
        L_mm_field, t_mm_field None → uniform Lcell, t_wall.
        The supplied FluidModel and scalar T/P determine the Nu correlation."""
        Nx_l, Ny_l = u_mag_field.shape
        if L_mm_field is None:
            g_u = cfg['thermal_geometry']['uniform']
            A0 = g_u['A_0']; D_h = g_u['D_h']; eps_g = g_u['epsilon']
            Re_loc = rho_scalar * (np.abs(u_mag_field) + 1e-12) * D_h / mu_scalar
            record_raw_nu_range(side_props.name, tpms_type, Re_loc)
            m, Pr = _nu_inputs(side_props, side_T_for_Pr, side_P)
            Nu_arr = local_nusselt(m, tpms_type, Re_loc,
                                  eps_g / 2.0, Lcell, D_h * 1000.0, Pr)
            return A0 * Nu_arr * k_f_scalar / D_h
        out = np.empty((Nx_l, Ny_l), dtype=np.float64)
        raw_Re = np.empty_like(out)
        for i in range(Nx_l):
            for j in range(Ny_l):
                L_ij = float(L_mm_field[i, j])
                g = {key: value[i, j] for key, value in cfg['thermal_geometry']['fields'].items()}
                D_h_l = g['D_h']
                Re_l = rho_scalar * (abs(float(u_mag_field[i, j])) + 1e-12) * D_h_l / mu_scalar
                raw_Re[i, j] = Re_l
                Re_ij = max(Re_l, 1.0)
                nu_corr = _nu_dispatch(side_props, side_T_for_Pr,
                                        Re_ij, g['epsilon'] / 2.0,
                                        L_ij, D_h_l * 1000.0, side_P)
                Nu_l = max(nu_corr, _NU_LAM_FLOOR_2D)
                out[i, j] = g['A_0'] * Nu_l * k_f_scalar / D_h_l
        record_raw_nu_range(side_props.name, tpms_type, raw_Re)
        return out

    tpms_type = cfg['tpms_type']
    Lcell = cfg['Lcell']; t_wall = cfg['t_wall']

    mu_A, mu_B = rA['mu'], rB['mu']
    P_inA_val = cfg['compute_cfg'].fluid_A.P_in_Pa
    P_inB_val = cfg['compute_cfg'].fluid_B.P_in_Pa
    fluid_props.check_water_state(fluid_A, T_inA, P_inA_val, where='2D direct inlet A')
    fluid_props.check_water_state(fluid_B, T_inB, P_inB_val, where='2D direct inlet B')

    # ── Asymmetric per-side porosity (offset-isosurface δ) — mirror 3D ──
    # δ=0 → symmetric (split=0.5, factors=1, no per-side override) → bit-
    # identical legacy path. δ≠0 → redistribute the total void between channels
    # A / B by the geometry split ratio s = split_A (shared with 3D via
    # solvers.asym_split). 2D's symmetric K_ff uses the FULL ε (tpms_calc:506)
    # while the convective term uses ε/2, so EVERY per-side void-weighted term
    # scales by the SAME factor relative to the symmetric ε/2 baseline —
    # 2s for A, 2(1−s) for B — which is bit-identical at δ=0 (factor=1 at s=0.5)
    # and keeps diffusion / convection / duty per-side consistent. The kernel
    # itself receives the absolute eps_A = ε·s / eps_B = ε·(1−s) (Phase 1 hook).
    # See design add-2d-asym-porosity D2(b).
    _delta_2d = float(cfg['compute_cfg'].geometry.delta_levelset)
    _asym_2d = (_delta_2d != 0.0)
    _model_h_mode = (not _enthalpy_mode and zone_config is None and not _asym_2d
                     and _pA.name in ('air', 'water') and _pB.name in ('air', 'water'))
    _split_A_2d = cfg['thermal_geometry']['split_A']
    _epsfac_A = 2.0 * _split_A_2d            # ε_A / (ε/2)
    _epsfac_B = 2.0 * (1.0 - _split_A_2d)    # ε_B / (ε/2)

    # Per-side interfacial coupling h_v geometry ratio under δ (mirror 3D
    # three_d.runtime._hv_side_geom_ratio). Each side's (A_0, D_h) shift with the
    # offset; the ratio vs the δ=0 reference is EXACTLY 1.0 at δ=0 (bit-
    # identical ×1.0). The inlet-reference scalar is also applied to local h_v;
    # Re/Nu floors can put the side and reference on different branches, so
    # their diameter ratio alone does not prove speed independence. k_f cancels. Captures
    # the geometric Nu/area effect; the residual κ_Nu is CFD calibration (P1-CFD,
    # out of scope). Per-side dP (Darcy-Forchheimer κ) is likewise the opt-in
    # CFD κ layer — 3D's default kappa_KcF returns (1,1) with no table, so the
    # symmetric K_df/cF here matches the 3D default. See design D2(b) / Risks.
    def _hv_side_geom_ratio_2d(side_props, u_side, T_side, P_side, side):
        if not _asym_2d:
            return 1.0
        A0_s, Dh_s, A0_r, Dh_r = cfg['thermal_geometry']['side_geometry'][side]
        _rho = float(side_props.rho(T_side, P_side))
        _mu = float(side_props.mu(T_side, P_side))

        def _hv(A0, Dh):
            Dh_m = max(float(Dh), 1e-12)
            Re_raw = _rho * abs(float(u_side)) * Dh_m / max(_mu, 1e-30)
            record_raw_nu_range(side_props.name, tpms_type, Re_raw)
            Re = max(Re_raw, 1.0)
            if side_props.name in ('water', 'sco2'):
                nu = _nu_dispatch(side_props, T_side, Re, 0.5 * float(eps),
                                  Lcell, Dh_m * 1000.0, P_side)
            else:
                nu = _tc.nu_from_Re(tpms_type, Re, 0.5 * float(eps),
                                    Lcell, Dh_m * 1000.0)
            nu = max(nu, _NU_LAM_FLOOR_2D)
            return A0 * nu / Dh_m
        with range_context(layout='asym-reference-scalar'):
            _ref = _hv(A0_r, Dh_r)
        with range_context(layout='asym-side-scalar'):
            return (_hv(A0_s, Dh_s) / _ref) if _ref > 0 else 1.0

    with range_context(side='A', stage='asym-ratio', layout='scalar'):
        _hv_ratio_A_2d = _hv_side_geom_ratio_2d(_pA, u_A, T_inA, P_inA_val, 'A')
    with range_context(side='B', stage='asym-ratio', layout='scalar'):
        _hv_ratio_B_2d = _hv_side_geom_ratio_2d(_pB, u_B, T_inB, P_inB_val, 'B')

    def _on_progress(step, total):
        pass  # progress handled by main thread timer

    coupling_converged = False
    drho_A = drho_B = float('inf')
    dT_A = dT_B = float('inf')
    # Warm-start delta tracker (shared with the 3D driver) — ΔTa/ΔTb/ΔTs < tol
    # AND mass-flux-weighted Δρ < tol; owns the prev-copy bookkeeping.
    # A2 (2026-07-06): Ts added — the solid field settles slowest and the old
    # (Ta,Tb)-only gate could break while Ts was still moving.
    _outer_conv = OuterConvergence(tol_T=_DT_TOL_K, track=('Ta', 'Tb', 'Ts'))
    e_info = {'converged': False, 'iterations': 0, 'residual': float('inf')}
    # Sticky: set the moment the energy solve produces a NaN cell. The NaN is
    # patched over (below) so the UI can still render velocity/pressure, but a
    # patched-over blow-up must never be reported as a converged solve. Sticky
    # because a later outer iteration starting from the PATCHED field can
    # converge on the patch — the deltas between two identically-patched fields
    # are small. (Audit 2026-07-12.)
    _energy_nan_hit = False
    Ta = Tb = Ts = None
    # User-provided solid warm-start seed. Empty → solver fallback
    # (per-fluid inlet T for Ta/Tb, 0.5*(T_inA+T_inB) for Ts).
    # Filled → only Ts is overridden with the user value; Ta/Tb stay at
    # the per-fluid inlet T to avoid the 0.5-mean energy-balance leak
    # (2026-04-24 FV fix in solvers/ltne_energy_3d.py: mid-T value at
    # non-pipe inlet cells diffuses back as a virtual heat source,
    # ~20–25% on partial-inlet geometries). Ts is *not* prescribed; the
    # solid energy equation still updates it every sweep.
    _Ts_init_user = cfg.get('T_s_init')
    if _Ts_init_user is not None:
        Ta = np.full((N_x, N_y), float(T_inA), dtype=np.float64)
        Tb = np.full((N_x, N_y), float(T_inB), dtype=np.float64)
        Ts = np.full((N_x, N_y), float(_Ts_init_user), dtype=np.float64)
    _has_partial_A = False
    _has_partial_B = False
    ucA = vcA = ucB = vcB = None
    ucA_disp = vcA_disp = ucB_disp = vcB_disp = None   # N5 display copies
    simpA = simpB = None

    with range_context(side='A', stage='inlet', layout='scalar'):
        rho_cp_A = _pA.rho(T_inA, P_inA_val) * _pA.cp(T_inA, P_inA_val)
    with range_context(side='B', stage='inlet', layout='scalar'):
        rho_cp_B = _pB.rho(T_inB, P_inB_val) * _pB.cp(T_inB, P_inB_val)
    last_temperature_inputs = None
    native_evidence = {}
    fine_evidence = {}
    last_model_inputs = None
    mass_flux_A = mass_flux_B = None

    # Variable density: 2D rho fields for SIMPLE (initialized uniform)
    with range_context(side='A', stage='inlet', layout='scalar'):
        rho_A_field = np.full((N_x, N_y), _pA.rho(T_inA, P_inA_val))
    with range_context(side='B', stage='inlet', layout='scalar'):
        rho_B_field = np.full((N_x, N_y), _pB.rho(T_inB, P_inB_val))

    # Outer SIMPLE↔LTNE loop, driven by the shared run_outer_coupling skeleton
    # (2D = SIMPLE-first: `step` solves SIMPLE A/B + the coupled energy + the
    # dual ΔT/Δρ check; `post` under-relaxes the rho/rho·cp fields for the next
    # iter via the carry). Body below is the verbatim former loop body; the
    # `nonlocal`s are the vars that persist across iters or are read afterwards.
    def _step_2d(_coup_it):
        nonlocal ucA, vcA, ucB, vcB, simpA, simpB, Ta, Tb, Ts, e_info
        nonlocal mA_rows, mB_rows
        nonlocal _energy_nan_hit
        nonlocal ucA_disp, vcA_disp, ucB_disp, vcB_disp
        nonlocal mu_A, mu_B, _has_partial_A, _has_partial_B
        nonlocal drho_A, drho_B, dT_A, dT_B
        nonlocal last_temperature_inputs
        nonlocal last_model_inputs
        nonlocal mass_flux_A, mass_flux_B
        if cancel_check is not None and cancel_check():
            raise CancelledError("compute cancelled by user")
        control.report_progress(10 + int(80 * _coup_it / _MAX_COUPLING))
        # Live iteration label for the UI button ticker (replaces the
        # dropped ETA text). 2026-05-14.
        if control.iteration is not None:
            control.iteration(f"iter {_coup_it + 1}/{_MAX_COUPLING}")

        # Step 1: SIMPLE velocity with current rho field. Pass Ta/Tb after
        # first outer iter so SIMPLE _update_density uses local T (not stale T_in).
        _Ta_for_simpA = Ta if _coup_it > 0 else None
        _Tb_for_simpB = Tb if _coup_it > 0 else None
        # 2026-05-09 (option B) — incompressible fluids run SIMPLE with
        # _update_density (ideal-gas P/RT update) as a no-op; ρ stays
        # at the inlet value over the whole field. B1 1.1: mapping via
        # the registry's flow_model() instead of a per-site string check.
        _ftA = fluid_props.flow_model(_pA.name)
        _ftB = fluid_props.flow_model(_pB.name)
        from sjtu_tpmshx.df_surrogate.predict import SCO2_DF_METHOD
        # V2 uses one water+sCO2 CFD-only closure for every fluid. K and
        # cF depend on TPMS/L/t only and stay fixed through the solve.
        _dfA = _dfB = SCO2_DF_METHOD
        # perf-wave1 (2026-07-03): run the two independent SIMPLE solves
        # on two OS threads. The solvers share no mutable state (separate instances,
        # per-side live-residual lists, per-label simple_warnings keys),
        # and the outputs are the same objects the sequential calls
        # produced — golden 2D stays bit-identical, only wall-clock
        # changes. Errors are re-raised after BOTH threads join so a
        # cancel/exception on one side can't orphan the other.
        import threading as _threading
        from sjtu_tpmshx.logutil import current_output, output_scope
        _parent_output = current_output()
        _res: list = [None, None]
        _err: list = [None, None]
        _parent_warnings = current_warnings()
        _side_warnings = [{} if _parent_warnings is not None else None for _ in range(2)]

        def _solve_side(idx, args, kwargs):
            try:
                with output_scope(_parent_output), warning_scope(_side_warnings[idx]), range_context(
                        side=('A', 'B')[idx], stage='main', layout='solver-cell(perp,stream)'):
                    _res[idx] = _run_simple(*args, **kwargs, cancel_check=cancel_check)
            except BaseException as e:   # incl. InterruptedError
                _err[idx] = e

        # The rebuilt solver uses the previous physical port pressures.
        # The first iteration has no previous solve and uses the 1D seed.
        _psA = inlet_pressure_state(simpA, P_inA_val)
        _psB = inlet_pressure_state(simpB, P_inB_val)
        # All fluids use their inlet-state model density. Air must not use
        # a separately rounded gas constant here; water's rho(T) updates
        # must not redefine the prescribed inlet throughput on each rebuild.
        with range_context(side='A', stage='inlet', layout='scalar'):
            _tA = _threading.Thread(
                target=_solve_side,
                args=(0, (cfgA, rho_A_field, mu_A, T_inA, u_A,
                          'Fluid A', P_inA_val),
                      dict(T_field_real=_Ta_for_simpA,
                           fluid_type=_ftA, df_method=_dfA,
                           fluid_name=_pA.name,
                           rho_inlet_ref=float(_pA.rho(T_inA, P_inA_val)),
                           p_shoot_prev=_psA)),
                daemon=True)
        with range_context(side='B', stage='inlet', layout='scalar'):
            _tB = _threading.Thread(
                target=_solve_side,
                args=(1, (cfgB, rho_B_field, mu_B, T_inB, u_B,
                          'Fluid B', P_inB_val),
                      dict(T_field_real=_Tb_for_simpB,
                           fluid_type=_ftB, df_method=_dfB,
                           fluid_name=_pB.name,
                           rho_inlet_ref=float(_pB.rho(T_inB, P_inB_val)),
                           p_shoot_prev=_psB)),
                daemon=True)
        _tA.start(); _tB.start()
        _tA.join(); _tB.join()
        merge_warnings(_parent_warnings, _side_warnings)
        # Both workers have exited. A real failure takes precedence over
        # a concurrent user cancellation on the other side.
        for _e in _err:
            if _e is not None and not isinstance(_e, CancelledError):
                raise _e
        for _e in _err:
            if _e is not None:
                raise _e
        if cancel_check is not None and cancel_check():
            raise CancelledError("compute cancelled by user")
        ucA, vcA, simpA = _res[0]
        ucB, vcB, simpB = _res[1]
        P_abs_A = _simple_pressure_abs_2d(simpA, dir_A, P_inA_val)
        P_abs_B = _simple_pressure_abs_2d(simpB, dir_B, P_inB_val)
        fluid_props.check_water_state(fluid_A, T_inA if Ta is None else Ta,
                                      P_abs_A, where='2D SIMPLE return A')
        fluid_props.check_water_state(fluid_B, T_inB if Tb is None else Tb,
                                      P_abs_B, where='2D SIMPLE return B')

        def _classify_nonfinite_flow_failure():
            # Only called on already-fatal inputs/returns; finite outer states
            # can still recover. Use this SIMPLE iteration's temperature input.
            for side, solver, u, v, temperature, inlet in (
                    ('A', simpA, ucA, vcA, _Ta_for_simpA, T_inA),
                    ('B', simpB, ucB, vcB, _Tb_for_simpB, T_inB)):
                if solver.fluid_type != 'ideal_gas':
                    continue
                temperature = inlet if temperature is None else temperature
                if not np.all(np.isfinite(temperature)):
                    continue
                speed = np.sqrt(np.asarray(u)**2 + np.asarray(v)**2)
                gate_solution(
                    float((solver.P_ref_abs + solver.P).min()), float(speed.max()),
                    float(inlet), mode=cfg.get('envelope_mode', 'raise'),
                    dims=f'2D-{side}', ma_max=mach_field_max(speed, temperature))

        control.report_progress(10 + int(80 * (_coup_it + 0.3) / _MAX_COUPLING))

        # Smooth velocity near partial-width wall boundaries — DISPLAY ONLY.
        # N5 (2026-07-07): the smoothed fields used to OVERWRITE ucA/vcA and
        # feed the LTNE energy solve, the local-Re h_v build and the duty
        # extraction. Gaussian filtering breaks the discrete mass balance of
        # the advecting field (spurious grid-dependent ∇·(ερcp·u) sources on
        # the temperature-form kernel) — the same defect class as the
        # 2026-06-24 temperature-smoothing fix, which kept Ta_raw for
        # physics. Physics now consumes the raw mass-conserving fields;
        # only the rendered copies are smoothed.
        _has_partial_A = np.any(simpA.outlet_frac < 0.99) or np.any(simpA.inlet_frac < 0.99)
        _has_partial_B = np.any(simpB.outlet_frac < 0.99) or np.any(simpB.inlet_frac < 0.99)
        ucA_disp = vcA_disp = ucB_disp = vcB_disp = None
        if _has_partial_A or _has_partial_B:
            from scipy.ndimage import gaussian_filter
            _sv = 2.0
            if _has_partial_A:
                ucA_disp = gaussian_filter(ucA, sigma=_sv)
                vcA_disp = gaussian_filter(vcA, sigma=_sv)
            if _has_partial_B:
                ucB_disp = gaussian_filter(ucB, sigma=_sv)
                vcB_disp = gaussian_filter(vcB, sigma=_sv)

        # Heat diffusion uses physical open area; SIMPLE's taper is velocity data.
        _imA, _imB = (cfg['boundary_openings'][side]['in_geom_frac'] for side in ('A', 'B'))

        # Build local-Re per-cell h_v fields (#1 fix). Use cell-center magnitude.
        u_mag_A = local_speed(ucA, vcA)
        u_mag_B = local_speed(ucB, vcB)
        # Zoned L/t fields (only if zone_config and grid mode); otherwise None
        L_field_2d = None; t_field_2d = None
        if zone_config is not None and za is not None:
            L_field_2d = za.get('L_mm_arr')
            t_field_2d = za.get('t_arr')
        if _enthalpy_mode:
            from sjtu_tpmshx.models.local_heat_transfer import _sco2_hv_local_field
            _g_hv = cfg['thermal_geometry']['uniform']
            _Ta_hv = (Ta if Ta is not None
                      else np.full_like(u_mag_A, T_inA))
            _Tb_hv = (Tb if Tb is not None
                      else np.full_like(u_mag_B, T_inB))

            def _enthalpy_side_hv(props, T_field, P_in, u_mag, observation):
                fluid_props.check_water_state(props.name, T_field, P_in,
                                              where='2D h_v property refresh')
                if props.name == 'sco2':
                    return _sco2_hv_local_field(
                        T_field, P_in, u_mag, _g_hv['A_0'], _g_hv['D_h'],
                        tpms_type, Lcell, sco2_nu=sco2_nu, observation=observation)
                rho = cell_average(props.rho(T_field, P_in), energy_dx, energy_dy)
                mu = cell_average(props.mu(T_field, P_in), energy_dx, energy_dy)
                mean_T = cell_average(T_field, energy_dx, energy_dy)
                return _build_hv_local_2d(
                    rho, mu, float(props.k(mean_T, P_in)),
                    u_mag, None, None, side_props=props,
                    side_T_for_Pr=mean_T, side_P=P_in)

            with range_context(side='A', stage='main-hv', layout='real-cell(x,y)'):
                h_vA_local = _enthalpy_side_hv(_pA, _Ta_hv, P_inA_val, u_mag_A, nu_observations['A'])
                if _coup_it == 0 and _pA.name == 'sco2':
                    warn_sco2_nu_evidence(
                        side='A', stage='2D main-hv', tpms_type=tpms_type,
                        L_mm=Lcell, t_mm=t_wall, P_in=P_inA_val)
            with range_context(side='B', stage='main-hv', layout='real-cell(x,y)'):
                h_vB_local = _enthalpy_side_hv(_pB, _Tb_hv, P_inB_val, u_mag_B, nu_observations['B'])
                if _coup_it == 0 and _pB.name == 'sco2':
                    warn_sco2_nu_evidence(
                        side='B', stage='2D main-hv', tpms_type=tpms_type,
                        L_mm=Lcell, t_mm=t_wall, P_in=P_inB_val)
        else:
            rho_A_scalar = cell_average(rho_A_field, energy_dx, energy_dy)
            rho_B_scalar = cell_average(rho_B_field, energy_dx, energy_dy)
            mu_A_scalar = cell_average(mu_A, energy_dx, energy_dy)
            mu_B_scalar = cell_average(mu_B, energy_dx, energy_dy)
            with range_context(side='A', stage='main-hv', layout='scalar'):
                k_fA = float(_pA.k(T_inA, P_inA_val))
            with range_context(side='B', stage='main-hv', layout='scalar'):
                k_fB = float(_pB.k(T_inB, P_inB_val))
            with range_context(side='A', stage='main-hv', layout='real-cell(x,y)'):
                h_vA_local = _build_hv_local_2d(
                    rho_A_scalar, mu_A_scalar, k_fA,
                    u_mag_A, L_field_2d, t_field_2d,
                    side_props=_pA, side_T_for_Pr=T_inA, side_P=P_inA_val)
            with range_context(side='B', stage='main-hv', layout='real-cell(x,y)'):
                h_vB_local = _build_hv_local_2d(
                    rho_B_scalar, mu_B_scalar, k_fB,
                    u_mag_B, L_field_2d, t_field_2d,
                    side_props=_pB, side_T_for_Pr=T_inB, side_P=P_inB_val)
        # Per-side interfacial geometry under δ (1.0 at δ=0 → bit-identical).
        if _asym_2d:
            h_vA_local = h_vA_local * _hv_ratio_A_2d
            h_vB_local = h_vB_local * _hv_ratio_B_2d

        # 2026-05-09 (option B) — water-side stiffness: ρ·cp_water ~ 4100×
        # ρ·cp_air, h_v_water ~ 2-3× h_v_air (Pr-substitution). solve_full_domain
        # GS-smoother is air-fit and can NaN-blow up on raw water settings.
        # Loosen tol + raise max_iter when ANY side is water; air-air case
        # keeps the original tight settings.
        _has_water = (_pA.name == 'water') or (_pB.name == 'water')
        _e_max_iter = 12000 if _has_water else 5000
        _e_tol      = 1.0   if _has_water else 0.5
        if _enthalpy_mode:
            _e_tol = 0.1

        # Step 2: Full-domain coupled energy solve (warm-start from previous iteration)
        # Per-side porosity for the offset-isosurface δ. δ=0 → eps_A/eps_B None
        # and the K_ff sources are passed through unscaled → bit-identical to the
        # legacy symmetric path (zoned and non-zoned branches only ever differed
        # in the K_ff / ε *source* and the kwarg order, both equivalent here).
        if zone_config is not None:
            _Kffa_src = za['K_ffA_arr']; _Kffb_src = za['K_ffB_arr']
            _Kss_src = za['K_ss_arr']; _eps_src = za['eps_arr']
        else:
            _Kffa_src = coeffs['K_ffA']; _Kffb_src = coeffs['K_ffB']
            _Kss_src = coeffs['K_ss']; _eps_src = eps
        if _asym_2d:
            _Kffa_use = _Kffa_src * _epsfac_A
            _Kffb_use = _Kffb_src * _epsfac_B
            _epsA_use = _eps_src * _split_A_2d
            _epsB_use = _eps_src * (1.0 - _split_A_2d)
        else:
            _Kffa_use = _Kffa_src; _Kffb_use = _Kffb_src
            _epsA_use = None; _epsB_use = None
        # Retain the last main thermal input for the raw outlet temperature,
        # including the legacy temperature-form zones/offset paths.
        mass_flux_A = _face_mass_fluxes_2d(
            simpA, dir_A, _epsA_use if _epsA_use is not None else .5*_eps_src,
            energy_dx, energy_dy)
        mass_flux_B = _face_mass_fluxes_2d(
            simpB, dir_B, _epsB_use if _epsB_use is not None else .5*_eps_src,
            energy_dx, energy_dy)
        if cfg.get('_capture_native'):
            native_evidence.update(
                P_thermal_A=np.array(P_abs_A, copy=True), P_thermal_B=np.array(P_abs_B, copy=True),
                mass_flux_A=mass_flux_A, mass_flux_B=mass_flux_B,
                outer_index=int(_coup_it), h_vA=np.array(h_vA_local, copy=True),
                h_vB=np.array(h_vB_local, copy=True), K_ss=np.array(_Kss_src, copy=True))
        if _enthalpy_mode:
            from sjtu_tpmshx.solvers.ltne_enthalpy_2d import solve_enthalpy_2d
            eps_total = np.broadcast_to(
                np.asarray(_eps_src, dtype=np.float64), (N_x, N_y))
            eps_A_ent = (_epsA_use if _epsA_use is not None
                         else 0.5 * eps_total)
            eps_B_ent = (_epsB_use if _epsB_use is not None
                         else 0.5 * eps_total)
            def _inflow_total(face_flux):
                fx, fy = face_flux
                return float(
                    np.maximum(fx[0], 0.0).sum()
                    + np.maximum(-fx[-1], 0.0).sum()
                    + np.maximum(fy[:, 0], 0.0).sum()
                    + np.maximum(-fy[:, -1], 0.0).sum())
            mA_rows = np.array([_inflow_total(mass_flux_A)])
            mB_rows = np.array([_inflow_total(mass_flux_B)])
            Ta, Tb, Ts, e_info = solve_enthalpy_2d(
                T_inA, T_inB, P_abs_A, P_abs_B, mass_flux_A, mass_flux_B,
                h_vA_local, h_vB_local, _Kss_src, eps_A_ent, eps_B_ent,
                energy_dx, energy_dy, fluid_A=_pA.name, fluid_B=_pB.name,
                P_inA=P_inA_val, P_inB=P_inB_val,
                Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
                max_iter=_e_max_iter, tol=_e_tol, cancel_check=cancel_check)
            e_info['true_h_balance'] = dict(
                Q_A=float(e_info['Q_A']), Q_B=float(e_info['Q_B']), units='W/m',
                outer_index=int(_coup_it), converged=bool(e_info['converged']),
                iterations=int(e_info['iterations']), residual=float(e_info['residual']),
                pressure_source=('air: P_ref_abs + SIMPLE gauge; frozen fluids: '
                                 'P_in + SIMPLE gauge - weighted inlet gauge'),
                P_in_A_Pa=float(P_inA_val), P_in_B_Pa=float(P_inB_val),
                P_A_range_Pa=[float(P_abs_A.min()), float(P_abs_A.max())],
                P_B_range_Pa=[float(P_abs_B.min()), float(P_abs_B.max())])
            e_info['true_h_balance'].update({key: e_info[key] for key in (
                'exit_reason', 'enthalpy_clip_counts', 'effective_settings',
                'coupled_energy_balance', 'equation_energy_balance') if key in e_info})
        else:
            last_temperature_inputs = (rho_cp_A, rho_cp_B, h_vA_local, h_vB_local)
            model_kwargs = {}
            if _model_h_mode:
                model_kwargs = dict(
                    model_fluids=(_pA.name, _pB.name),
                    accelerate=cfg['compute_cfg'].flags.port_wall_refine,
                    mass_flux_A=mass_flux_A, mass_flux_B=mass_flux_B)
                last_model_inputs = dict(model_kwargs, K_ffA=_Kffa_use, K_ffB=_Kffb_use,
                                         K_ss=_Kss_src, outer_index=int(_coup_it))
                masses = (model_kwargs['mass_flux_A'], model_kwargs['mass_flux_B'])
                if (all(m is not None and len(m) == 2
                        and m[0].shape == (N_x+1, N_y)
                        and m[1].shape == (N_x, N_y+1) for m in masses)
                        and any(not np.all(np.isfinite(f)) for m in masses for f in m)):
                    _classify_nonfinite_flow_failure()
            with range_context(side='A', stage='main-inlet', layout='scalar'):
                inlet_flux_A = (_inlet_transport_2d(
                    simpA, dir_A, _epsA_use if _epsA_use is not None else .5*_eps_src,
                    _pA.cp(T_inA, P_inA_val), energy_dx, energy_dy)
                    if not _model_h_mode else None)
            with range_context(side='B', stage='main-inlet', layout='scalar'):
                inlet_flux_B = (_inlet_transport_2d(
                    simpB, dir_B, _epsB_use if _epsB_use is not None else .5*_eps_src,
                    _pB.cp(T_inB, P_inB_val), energy_dx, energy_dy)
                    if not _model_h_mode else None)
            for side, fluid, temperature in (('A', fluid_A, Ta), ('B', fluid_B, Tb)):
                with range_context(side=side, stage='main-warm', layout='real-cell(x,y)'):
                    record_temperature_ranges(fluid, temperature)
            Ta, Tb, Ts, e_info = solve_full_domain(
                L, H, N_x, N_y, T_inA, T_inB,
                _Kffa_use, _Kffb_use, _Kss_src,
                h_vA_local, h_vB_local,
                rho_cp_A, rho_cp_B,
                _eps_src, ucA, vcA, ucB, vcB,
                dir_A, dir_B,
                max_iter=_e_max_iter, tol=_e_tol,
                progress_cb=_on_progress, return_info=True,
                Ta_init=Ta, Tb_init=Tb, Ts_init=Ts,
                dx_arr=energy_dx, dy_arr=energy_dy,
                inlet_mask_A=_imA, inlet_mask_B=_imB,
                inlet_flux_A=inlet_flux_A,
                inlet_flux_B=inlet_flux_B,
                eps_A=_epsA_use, eps_B=_epsB_use, cancel_check=cancel_check, **model_kwargs)

        if not _enthalpy_mode:
            for side, fluid, temperature in (('A', fluid_A, Ta), ('B', fluid_B, Tb)):
                with range_context(side=side, stage='main-return', layout='real-cell(x,y)'):
                    record_temperature_ranges(fluid, temperature)

        fluid_props.check_water_state(fluid_A, Ta, P_abs_A, where='2D energy return A')
        fluid_props.check_water_state(fluid_B, Tb, P_abs_B, where='2D energy return B')
        if not _enthalpy_mode:
            if any(not np.all(np.isfinite(t)) for t in (Ta, Tb, Ts)):
                _classify_nonfinite_flow_failure()
            fluid_props.check_finite_temperatures(Ta, Tb, Ts, where='2D energy return')

        # 2026-05-09 NaN guard — energy solver may NaN-blow up on water-side
        # stiffness (rho·cp 4100× + h_v 2-3× vs air). Replace nan with the
        # per-side inlet T so finalize_plots can render velocity / pressure
        # canvases (the user still wants those visible) instead of crashing
        # on contourf(nan). Surface a warning so the user knows Q is unreliable.
        _has_nan = (np.any(np.isnan(Ta)) or np.any(np.isnan(Tb))
                    or np.any(np.isnan(Ts)))
        if _has_nan:
            # Validity, not just a warning string: the patched field is NOT a
            # solution. Sticky flag → forced into solver_converged below.
            _energy_nan_hit = True
            n_nan_a = int(np.sum(np.isnan(Ta)))
            n_nan_b = int(np.sum(np.isnan(Tb)))
            n_nan_s = int(np.sum(np.isnan(Ts)))
            n_total = Ta.size
            _cause = ("water-side LTNE stiffness (ρ·cp 4100× air)"
                      if _has_water
                      else "energy solver divergence (likely Nu/h_v "
                           "extrapolation, partial-BC layer, or non-monotonic "
                           "convection — check log)")
            warnings_list.append(
                f"Energy solver produced NaN cells "
                f"(Ta {n_nan_a}/{n_total}, Tb {n_nan_b}/{n_total}, "
                f"Ts {n_nan_s}/{n_total}) — replacing with inlet T so "
                f"the 2D result view can render velocity/pressure. "
                f"Q value is unreliable. Cause: {_cause}.")
            Ta = np.where(np.isnan(Ta), T_inA, Ta)
            Tb = np.where(np.isnan(Tb), T_inB, Tb)
            Ts = np.where(np.isnan(Ts), 0.5 * (T_inA + T_inB), Ts)

        # Step 3: Update rho*cp and rho field from per-cell temperature AND
        # per-cell absolute pressure. Using the scalar inlet P here under-
        # predicts density drop across the domain at high dP and diverges
        # from the 3D path (which already uses P_ref_abs + P). Transpose /
        # flip SIMPLE coords → real (Nx, Ny) to match Ta shape.
        with range_context(side='A', stage='property-refresh', layout='real-cell(x,y)'):
            rho_cp_A_new = _pA.rho(Ta, P_abs_A) * _pA.cp(Ta, P_abs_A)
        with range_context(side='B', stage='property-refresh', layout='real-cell(x,y)'):
            rho_cp_B_new = _pB.rho(Tb, P_abs_B) * _pB.cp(Tb, P_abs_B)
        with range_context(side='A', stage='property-refresh', layout='real-cell(x,y)'):
            rho_A_field_new = _pA.rho(Ta, P_abs_A)
        with range_context(side='B', stage='property-refresh', layout='real-cell(x,y)'):
            rho_B_field_new = _pB.rho(Tb, P_abs_B)

        # Variable mu: build 2D viscosity field from per-cell Ta/Tb via
        # Sutherland (air) or Vogel (water). With local-P density now using
        # the full field, local mu keeps the momentum balance consistent
        # cell-by-cell.
        with range_context(side='A', stage='property-refresh', layout='real-cell(x,y)'):
            mu_A = _pA.mu(Ta, P_abs_A)
        with range_context(side='B', stage='property-refresh', layout='real-cell(x,y)'):
            mu_B = _pB.mu(Tb, P_abs_B)
        T_avg_A = cell_average(Ta, energy_dx, energy_dy)
        T_avg_B = cell_average(Tb, energy_dx, energy_dy)

        # Convergence: mass-flux-weighted relative rho change.
        # Physical reasoning — the coupling is driven by ∇·(ρu) = 0, so only
        # cells with nonzero mass flux are physically relevant. Wall cells
        # (v≈0 under partial BC) have T that drifts slowly from neighbor
        # diffusion but does not affect the coupled solution. Weighting by
        # |u| filters that tail-end noise cleanly so the metric reflects
        # convergence where it matters.
        dA = rho_A_field_new - rho_A_field
        dB = rho_B_field_new - rho_B_field
        wA = np.sqrt(ucA * ucA + vcA * vcA) + 1e-12
        wB = np.sqrt(ucB * ucB + vcB * vcB) + 1e-12
        drho_A = float(np.sum(np.abs(dA / rho_A_field) * wA) / np.sum(wA))
        drho_B = float(np.sum(np.abs(dB / rho_B_field) * wB) / np.sum(wB))

        # Temperature-field convergence: max|ΔT| across outer iterations.
        # rho-only criterion can flag converged while the T field is still
        # drifting (rho = P / (R·T) damps temperature swings); requiring
        # both is a tighter guarantee the coupled state is stationary.
        # ΔTa/ΔTb/ΔTs (tol _DT_TOL_K) AND mass-flux-weighted Δρ (tol
        # _COUPLING_TOL) — the shared tracker owns the ΔT deltas + warm-start
        # prev-copy; Δρ is the 2D-specific extra criterion.
        _converged, _deltas = _outer_conv.check(
            {'Ta': Ta, 'Tb': Tb, 'Ts': Ts},
            extra=(drho_A, drho_B), extra_tol=_COUPLING_TOL)
        pressure_states = (inlet_pressure_state(simpA, P_inA_val),
                           inlet_pressure_state(simpB, P_inB_val))
        _converged = _converged and all(s is None or s['passed'] for s in pressure_states)
        dT_A = _deltas['Ta']; dT_B = _deltas['Tb']
        _log.info(f"  [Coupling {_coup_it+1}] drho_A={drho_A:.4f} drho_B={drho_B:.4f} "
                  f"dT_A={dT_A:.2f}K dT_B={dT_B:.2f}K dT_S={_deltas['Ts']:.2f}K "
                  f"T_avg_A={T_avg_A:.1f}K T_avg_B={T_avg_B:.1f}K")

        # Carry the under-relaxation inputs to `post` (avoids 4 more nonlocals).
        return _converged, (rho_A_field_new, rho_B_field_new,
                            rho_cp_A_new, rho_cp_B_new)

    def _post_2d(_coup_it, _carry):
        nonlocal rho_A_field, rho_B_field, rho_cp_A, rho_cp_B
        (rho_A_field_new, rho_B_field_new,
         rho_cp_A_new, rho_cp_B_new) = _carry
        # Under-relax (field-wise)
        rho_A_field = _ALPHA_COUP * rho_A_field_new + (1 - _ALPHA_COUP) * rho_A_field
        rho_B_field = _ALPHA_COUP * rho_B_field_new + (1 - _ALPHA_COUP) * rho_B_field
        rho_cp_A = _ALPHA_COUP * rho_cp_A_new + (1 - _ALPHA_COUP) * rho_cp_A
        rho_cp_B = _ALPHA_COUP * rho_cp_B_new + (1 - _ALPHA_COUP) * rho_cp_B

    _last_coup, coupling_converged = run_outer_coupling(
        max_iter=_MAX_COUPLING, step=_step_2d, post=_post_2d)
    pressure_states = {'A': inlet_pressure_state(simpA, P_inA_val),
                       'B': inlet_pressure_state(simpB, P_inB_val)}
    model_balance = None
    if _model_h_mode:
        model_balance = e_info['model_h_balance']
        model_balance.update(
            mass_source='last thermal input: actual signed SIMPLE faces',
            outer_index=int(_last_coup), outer_converged=bool(coupling_converged),
            post_after_last_thermal=bool(not coupling_converged),
            raw_state_matches_last_thermal=bool(not _energy_nan_hit))
        model_balance['passed'] = bool(model_balance['passed'] and coupling_converged
                                       and not _energy_nan_hit)
        mA_rows = np.array([model_balance['A']['mass_in_kg_s_per_m']])
        mB_rows = np.array([model_balance['B']['mass_in_kg_s_per_m']])
    if cancel_check is not None and cancel_check():
        raise CancelledError("compute cancelled by user")

    if not coupling_converged:
        warnings_list.append(
            f"Velocity-temperature coupling: not converged after {_MAX_COUPLING} iters "
            f"(drho_A={drho_A:.4f}, drho_B={drho_B:.4f}, "
            f"dT_A={dT_A:.2f}K, dT_B={dT_B:.2f}K)")
    warnings_list.extend(simple_warnings.values())

    # Zone statistics and boundary lines
    z_axis = cfg['z_axis']
    zones = _zone_statistics_2d(z_axis, zone_config, za, L, H,
                               energy_dx, energy_dy, Ta, Tb, Ts)

    # FIX (2026-06-24): keep RAW (unsmoothed) fields for Q extraction. The
    # display smoothing below blurs the sharp inlet/outlet thermal gradients;
    # because gaussian_filter `sigma` is in CELLS, that blur is GRID-DEPENDENT
    # and corrupts the enthalpy-balance Q — it drags the pinned 422 K air inlet
    # down to ~403 K on a 20-grid (and warms the outlet), halving the apparent
    # ΔT. This was the root cause of the 2D heat-duty grid non-convergence
    # (Q_A_fine used the smoothed field, while the Richardson 2× grid is solved
    # fresh = unsmoothed, so the two disagreed wildly). The old comment "Q/dP
    # already computed from raw fields" was STALE — Q is computed below, AFTER
    # this block, so it must be fed the raw fields explicitly.
    Ta_raw, Tb_raw, Ts_raw = Ta, Tb, Ts

    # Smooth temperature fields FOR DISPLAY ONLY if partial-width inlets exist
    # (removes Brinkman-induced stripes). Rebinds Ta/Tb/Ts to display copies;
    # the Q call below uses Ta_raw/Tb_raw/Ts_raw.
    if _has_partial_A or _has_partial_B:
        from scipy.ndimage import gaussian_filter
        _st = 1.5  # temperature smoothing width in cells
        Ta = gaussian_filter(Ta, sigma=_st)
        Tb = gaussian_filter(Tb, sigma=_st)
        Ts = gaussian_filter(Ts, sigma=_st)

    # ── Step 3: Pressure from SIMPLE ──
    P_inA = cfg['compute_cfg'].fluid_A.P_in_Pa
    P_inB = cfg['compute_cfg'].fluid_B.P_in_Pa
    P_fA, P_fB, dP_A, dP_B = _compute_pressure_2d(
        simpA, simpB, dir_A, dir_B, P_inA, P_inB)
    if not _enthalpy_mode:
        for side, fluid, temperature in (('A', fluid_A, Ta_raw), ('B', fluid_B, Tb_raw)):
            with range_context(side=side, stage='final', layout='real-cell(x,y)'):
                record_temperature_ranges(fluid, temperature)
    fluid_props.check_water_state(fluid_A, Ta_raw, P_fA, where='2D final state A')
    fluid_props.check_water_state(fluid_B, Tb_raw, P_fB, where='2D final state B')

    # ── Post-solve compressible validity gate (robustness, 2026-06-25) ──
    # Same fail-loud guard as the 3D pipeline: a choked air case (dP -> P_in,
    # outlet vacuum) drives v=G/rho supersonic; flag it instead of returning
    # garbage. Both ideal-gas sides checked (air-air B can choke too); water is
    # incompressible. Mach is per-cell against the local temperature.
    _env_mode = cfg.get('envelope_mode', 'raise')
    _env_valid = True
    _env_reasons = []
    _clip_hits_2d = 0
    if simpA is not None and getattr(simpA, 'fluid_type', None) == 'ideal_gas':
        _clip_hits_2d += int(getattr(simpA, '_p_clip_hits', 0))
        _vmagA = np.sqrt(np.asarray(ucA) ** 2 + np.asarray(vcA) ** 2)
        _vA, _rA = gate_solution(
            float((simpA.P_ref_abs + simpA.P).min()), float(_vmagA.max()),
            float(T_inA), mode=_env_mode, dims='2D-A',
            # RAW T (2026-07-13 audit): Ta/Tb are display-smoothed rebinds by
            # this point on partial-BC runs — a physics gate must not read a
            # cosmetic filter. Q below already uses the raw fields.
            ma_max=mach_field_max(_vmagA, Ta_raw))
        _env_valid = _env_valid and _vA
        _env_reasons += [f"[A] {r}" for r in _rA]
    if simpB is not None and getattr(simpB, 'fluid_type', None) == 'ideal_gas':
        _clip_hits_2d += int(getattr(simpB, '_p_clip_hits', 0))
        _vmagB = np.sqrt(np.asarray(ucB) ** 2 + np.asarray(vcB) ** 2)
        _vB, _rB = gate_solution(
            float((simpB.P_ref_abs + simpB.P).min()), float(_vmagB.max()),
            float(T_inB), mode=_env_mode, dims='2D-B',
            ma_max=mach_field_max(_vmagB, Tb_raw))
        _env_valid = _env_valid and _vB
        _env_reasons += [f"[B] {r}" for r in _rB]

    richardson_info = None
    if _enthalpy_mode:
        Q_A_fine = float(e_info['Q_A'])
        Q_B_fine = float(e_info['Q_B'])
        # Match the established 3D/Shanghai headline convention: Fluid-A
        # advective enthalpy duty. Fluid B remains the conservation diagnostic.
        Q_total = abs(Q_A_fine)
        Q_solid_richardson = abs(Q_B_fine)
        richardson_warn = False
    else:
        # Compute Q with Richardson extrapolation (N_x×N_y + 2N_x×2N_y)
        rcp_A_energy, rcp_B_energy, hv_A_energy, hv_B_energy = last_temperature_inputs
        (Q_total, Q_A_fine, Q_B_fine, Q_solid_richardson,
         richardson_warn, richardson_info) = _compute_Q_richardson(
            Ta_raw, Tb_raw, Ts_raw, ucA, vcA, ucB, vcB, rcp_A_energy, rcp_B_energy,
            simpA, simpB, N_x, N_y, L, H, dir_A, dir_B,
            energy_dx, energy_dy, _x_breaks, _y_breaks,
            T_inA, T_inB, P_inA_val, P_inB_val, eps, za, coeffs,
            _pA, _pB, cfgA, cfgB, u_A, u_B, warnings_list,
            h_vA_coarse=hv_A_energy, h_vB_coarse=hv_B_energy,
            split_A=_split_A_2d,
            port_wall_refine=cfg['compute_cfg'].flags.port_wall_refine,
            cancel_check=cancel_check, model_inputs=last_model_inputs, model_balance=model_balance,
            **({'evidence': fine_evidence} if cfg.get('_capture_native') else {}))

    # ΔP: always from SIMPLE converged P fields (dP_A, dP_B set above at line 580-581
    # via inlet/outlet-weighted SIMPLE pressure averages). Previously this block
    # overrode dP with compute_dP_continuous (legacy f-Re) when sigmoid fields
    # were present — that bypassed SIMPLE's D-F closure and is now removed.
    # Production dP path is strictly SIMPLE (2026-04-17).

    if cfg.get('_capture_native'):
        native_evidence.update(
            Ta=Ta_raw, Tb=Tb_raw, Ts=Ts_raw,
            P_report_A=np.array(P_fA, copy=True), P_report_B=np.array(P_fB, copy=True),
            fine=fine_evidence, true_h=e_info.get('_native_state'),
            model_h_balance=model_balance, mode=('true_h' if _enthalpy_mode else
                                                'model_h' if _model_h_mode else 'temperature'),
            split_A=float(_split_A_2d), rho_cp_A=None if _enthalpy_mode else rcp_A_energy,
            rho_cp_B=None if _enthalpy_mode else rcp_B_energy,
            final_after_thermal=bool(not coupling_converged),
            pressure={side: dict(inlet_gauge_Pa=np.array(simp.P[:, 0], copy=True),
                                 outlet_gauge_Pa=np.array(simp.P[:, -1], copy=True),
                                 inlet_fraction=np.array(simp.inlet_frac, copy=True),
                                 outlet_fraction=np.array(simp.outlet_frac, copy=True),
                                 outlet_geom_frac=np.array(simp.outlet_geom_frac, copy=True),
                                 reference_abs_Pa=float(simp.P_ref_abs))
                      for side, simp in (('A', simpA), ('B', simpB))})

    # Smooth pressure and velocity fields for display if partial-width
    if _has_partial_A or _has_partial_B:
        from scipy.ndimage import gaussian_filter
        _sp = 1.5
        if _has_partial_A:
            P_fA = gaussian_filter(P_fA, sigma=_sp)
        if _has_partial_B:
            P_fB = gaussian_filter(P_fB, sigma=_sp)

    # Capture SIMPLE residual histories so the Pressure tab can render a
    # convergence mini-plot alongside the pressure fields. A copy avoids
    # holding a reference to the live solver past this function.
    # except-audit 2026-07-03: narrowed from bare Exception — only a missing
    # / non-iterable `residuals` attr is expected here (cosmetic mini-plot
    # data); anything else should surface.
    try:
        resid_A = list(simpA.residuals) if simpA is not None else None
    except (AttributeError, TypeError):
        resid_A = None
    try:
        resid_B = list(simpB.residuals) if simpB is not None else None
    except (AttributeError, TypeError):
        resid_B = None

    # Conservation diagnostics — STRICT enthalpy flux at inlet / outlet.
    # The previous implementation averaged T with a normalised mass-flux
    # weight that divided by a plane-mean ρ·cp (#5 reviewer concern —
    # not equal to ∑ρ·cp·u·A·T when ρ·cp varied along the face). Now we
    # compute the integral directly:
    #   H_in  = ∑_face ρ·cp·|u·n̂|·A · T
    #   H_out = same on the outlet face
    #   Q_fluid = H_in − H_out   (positive = heat given up by the fluid)
    # Enthalpy balance uses module-level _enthalpy_balance_2d; see top of file.

    # Reuse fine-grid enthalpy already computed above in the Richardson block.
    Q_A = Q_A_fine
    Q_B = Q_B_fine
    # except-audit 2026-07-03: narrowed — only a None operand (side not
    # solved) is expected; arithmetic on floats cannot otherwise raise.
    try:
        Q_net = Q_A + Q_B
        energy_rel = abs(Q_net) / (abs(Q_A) + abs(Q_B) + 1e-30)
    except TypeError:
        Q_net = energy_rel = float('nan')

    result = {
        'sco2_nu_observations': nu_observations,
        'Ta': Ta, 'Tb': Tb, 'Ts': Ts,
        'T_out_A_K': _outlet_temperature_2d(
            Ta_raw, mass_flux_A, dir_A, simpA.outlet_geom_frac),
        'T_out_B_K': _outlet_temperature_2d(
            Tb_raw, mass_flux_B, dir_B, simpB.outlet_geom_frac),
        'ucA': ucA, 'vcA': vcA, 'ucB': ucB, 'vcB': vcB,
        # N5: display-smoothed copies (partial-BC runs only; None ⇒ use raw).
        # Physics consumers ('ucA' etc.) stay raw / mass-conserving.
        'ucA_disp': ucA_disp, 'vcA_disp': vcA_disp,
        'ucB_disp': ucB_disp, 'vcB_disp': vcB_disp,
        'P_fA': P_fA, 'P_fB': P_fB,
        'dP_A': dP_A, 'dP_B': dP_B,
        # Actual ideal-gas face pressures, also used by the convergence gate.
        'P_in_realized_A': (
            pressure_states['A']['realized_Pa']
            if pressure_states['A'] is not None
            else float('nan')),
        'P_in_shoot_resid_A': (
            pressure_states['A']['relative_error']
            if pressure_states['A'] is not None
            else float('nan')),
        'P_in_realized_B': (
            pressure_states['B']['realized_Pa']
            if pressure_states['B'] is not None
            else float('nan')),
        'P_in_shoot_resid_B': (
            pressure_states['B']['relative_error']
            if pressure_states['B'] is not None
            else float('nan')),
        'Q_total': Q_total,
        'mass_flow_A_kg_s_per_m': (
            float(np.sum(mA_rows)) if mA_rows is not None else float('nan')),
        'mass_flow_B_kg_s_per_m': (
            float(np.sum(mB_rows)) if mB_rows is not None else float('nan')),
        'energy_dx': energy_dx, 'energy_dy': energy_dy,
        'warnings_list': warnings_list,
        # ── Convergence verdict — explicit AND over every gate (2026-07-12) ──
        # robustness-hardening (2026-07-03) ANDed SIMPLE with the outer
        # coupling only. Three gaps closed here (mirrors the 3D fix):
        #   (a) the LTNE inner verdict `e_info['converged']` was captured at
        #       the solve_full_domain call and then NEVER READ — a write-only
        #       variable;
        #   (b) a NaN blow-up patched over with inlet T (see _energy_nan_hit)
        #       left `converged` untouched, so a patched non-solution could
        #       report success;
        #   (c) the post-solve compressible envelope verdict was reported on a
        #       separate key but not ANDed into the headline flag.
        # Verdict only — no numeric field is touched.
        'solver_converged': bool(
            coupling_converged                       # outer ΔT+Δρ+inlet-P
            and not simple_warnings                  # every SIMPLE side ok
            and bool(e_info.get('converged', False))  # LTNE inner pass
            and (_enthalpy_mode or (richardson_info['converged']
                                    and richardson_info['extrapolated']))
            and (not _enthalpy_mode or energy_rel < 0.05)  # true-h pair balance
            and (not _model_h_mode or (model_balance['passed']
                 and richardson_info['model_h_balance']['passed']))
            and not _energy_nan_hit                  # no patched-over NaN
            and bool(_env_valid)),                   # envelope gate
        'convergence_detail': {
            'inlet_pressure': pressure_states,
            'outer_converged': bool(coupling_converged),
            # The ACTUAL outer-iteration count (3D parity). `_last_coup` is the
            # 0-based index the skeleton stopped at, so +1 is the count of passes
            # actually run — NOT the cap. Absent before 2026-07-12, so callers
            # reading `outer_iters` (e.g. the Shanghai 2D gate) silently got -1.
            'outer_iters': int(_last_coup) + 1,
            'outer_hit_cap': bool(not coupling_converged),
            'simple_ok': bool(not simple_warnings),
            'ltne_ok': bool(e_info.get('converged', False)),
            'richardson_ok': (None if _enthalpy_mode else bool(
                richardson_info['converged'] and richardson_info['extrapolated'])),
            'ltne_iterations': int(e_info.get('iterations', 0)),
            'ltne_residual': float(e_info.get('residual', float('inf'))),
            'enthalpy_balance_ok': bool(not _enthalpy_mode or energy_rel < 0.05),
            'model_h_balance_ok': (bool(model_balance['passed'] and richardson_info['model_h_balance']['passed'])
                                   if _model_h_mode else None),
            'energy_nan_hit': bool(_energy_nan_hit),
            'envelope_ok': bool(_env_valid),
        },
        'residuals_A': resid_A, 'residuals_B': resid_B,
        'mass_imbalance_rel_A': float(getattr(
            simpA, 'final_res_mass_global', float('nan'))),
        'mass_imbalance_rel_B': float(getattr(
            simpB, 'final_res_mass_global', float('nan'))),
        # Conservation diagnostics
        'Q_A': Q_A, 'Q_B': Q_B, 'Q_net': Q_net,
        'energy_imbalance_rel': energy_rel,
        # Q-reconciliation diagnostics (Option C, 2026-04-24)
        'Q_enthalpy_A': abs(Q_A_fine) if Q_A_fine == Q_A_fine else float('nan'),
        'Q_enthalpy_B': abs(Q_B_fine) if Q_B_fine == Q_B_fine else float('nan'),
        'Q_solid_richardson': Q_solid_richardson,
        'Q_richardson_warn': bool(richardson_warn),
        'richardson_info': richardson_info,
        'model_h_balance': (dict(main=model_balance, fine=richardson_info['model_h_balance'])
                            if _model_h_mode else None),
        'true_h_balance': (dict(
            e_info['true_h_balance'], outer_converged=bool(coupling_converged),
            post_after_last_thermal=bool(not coupling_converged),
            state='last true-h solve, before any final post update')
            if _enthalpy_mode else None),
        # Compressible validity gate (robustness, 2026-06-25)
        'envelope_valid': _env_valid,
        'envelope_reasons': _env_reasons,
        'p_clip_hits': _clip_hits_2d,
        'df_metadata': {
            'mode': getattr(cfg.get('compute_cfg'), 'df_mode', 'cfd_smooth'),
            'A': getattr(simpA, '_df_metadata', None),
            'B': getattr(simpB, '_df_metadata', None),
        },
    }
    if cfg.get('_capture_native'):
        result['_native_evidence'] = native_evidence
    result['application'] = dict(
        coeffs=coeffs,
        props=dict(rho_A=rA['rho'], rho_B=rB['rho'], mu_A=rA['mu'], mu_B=rB['mu']),
        zones=zones)
    return result
