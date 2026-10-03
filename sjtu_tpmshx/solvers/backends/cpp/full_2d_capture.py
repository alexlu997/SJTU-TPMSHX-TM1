"""Map owned native 2D evidence to the existing portable result contract.

Numerical fields, duties and acceptance verdicts come from the native driver.
Only established display smoothing and zone reporting are applied here.
"""
from copy import deepcopy

import numpy as np

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.run_warnings import current_warnings, merge_warnings, warning_messages, warning_scope
from sjtu_tpmshx.domain.validator import compute_volumetric_htc
from sjtu_tpmshx.models.nu_correlations import warn_sco2_nu_evidence
from sjtu_tpmshx.solvers.backends.python.two_d.result_capture import (
    capture_result as _capture_result, _zone_statistics_2d,
)
from .closure_evidence import replay_range_observations


def _model_balance(thermal, result, *, fine=False):
    if thermal['mode'] != 'model_h':
        return None
    balance = deepcopy(thermal['model_h'])
    balance.pop('energy_finishing_checks', None)
    balance.update(
        mass_source=('conservative coarse-face prolongation; no fine SIMPLE' if fine else
                     'last thermal input: actual signed SIMPLE faces'),
        outer_index=int(result['iterations']) - 1,
        outer_converged=bool(result['outer_converged']),
        post_after_last_thermal=bool(result['post_after_last_thermal']))
    if fine:
        balance['state'] = 'raw refined thermal return'
    else:
        balance['raw_state_matches_last_thermal'] = True
    return balance


def _fine_evidence(fine, balance):
    if fine is None:
        return {}
    evidence = dict(zip(('Ta', 'Tb', 'Ts'), fine['temperature']))
    evidence.update(dx=fine['dx'], dy=fine['dy'], eps=fine['epsilon'], model_h_balance=balance)
    for side, label in enumerate('AB'):
        for prefix, key in (('uc', 'uc'), ('vc', 'vc'), ('rho_cp_', 'rho_cp'),
                            ('inlet_', 'inlet_profile'), ('outlet_', 'outlet_profile')):
            evidence[prefix + label] = fine[key][side]
    return evidence


def capture_result(case, cfg, prepared, native):
    """Capture a completed native return without re-entering Python solvers."""
    if native['cancelled']:
        raise CancelledError('compute cancelled by user')
    main, fine = native['main'], native['fine']
    mode = main['mode']
    model_balance = _model_balance(main, native)
    fine_balance = None if fine is None else _model_balance(fine, native, fine=True)
    fine_info = None
    if fine is not None:
        fine_info = dict(converged=fine['stop'] == 0, iterations=fine['iterations'],
                         residual=fine['residual'], extrapolated=bool(native['fine_extrapolated']))
        if fine_balance is not None:
            fine_info.update(model_h_balance=fine_balance,
                             energy_finishing_checks=deepcopy(fine['model_h']['energy_finishing_checks']))
    true_h_info = main['true_h'] if mode == 'true_h' else None
    true_balance = None
    if true_h_info is not None:
        true_balance = dict(
            Q_A=native['duty'][0], Q_B=native['duty'][1], units='W/m',
            outer_index=int(native['iterations']) - 1, converged=bool(native['thermal_ok']),
            iterations=main['iterations'], residual=main['residual'],
            pressure_source=('air: P_ref_abs + SIMPLE gauge; frozen fluids: '
                             'P_in + SIMPLE gauge - open-area physical inlet-face gauge'),
            P_in_A_Pa=cfg['compute_cfg'].fluid_A.P_in_Pa,
            P_in_B_Pa=cfg['compute_cfg'].fluid_B.P_in_Pa,
            outer_converged=bool(native['outer_converged']),
            post_after_last_thermal=bool(native['post_after_last_thermal']),
            state='last true-h solve, before any final post update')
        for side, label in enumerate('AB'):
            pressure = main['pressure'][side]
            true_balance['P_' + label + '_range_Pa'] = [float(pressure.min()), float(pressure.max())]
        true_balance.update({key: deepcopy(true_h_info[key]) for key in (
            'exit_reason', 'enthalpy_clip_counts', 'effective_settings',
            'coupled_energy_balance', 'equation_energy_balance') if key in true_h_info})

    warnings = list(cfg['warnings_list'])
    warnings.extend(replay_range_observations(native['range_observations']))
    notices = {}
    with warning_scope(notices):
        for label, observation in native['sco2_nu_observations'].items():
            if observation:
                warn_sco2_nu_evidence(side=label, stage='2D main-hv', tpms_type=cfg['tpms_type'],
                    L_mm=cfg['Lcell'], t_mm=cfg['t_wall'], P_in=observation['P_abs_Pa'])
    merge_warnings(current_warnings(), [notices])
    warnings.extend(warning_messages(notices))
    if not native['outer_converged']:
        last = native['outer_history'][-1]
        rho, temperature = last['relative_density_change'], last['temperature_change']
        warnings.append(
            f"Velocity-temperature coupling: not converged after {native['iterations']} iters "
            f"(drho_A={rho[0]:.4f}, drho_B={rho[1]:.4f}, "
            f"dT_A={temperature[0]:.2f}K, dT_B={temperature[1]:.2f}K)")
    pressure_states, pressure_evidence = {}, {}
    raw = dict(zip(('Ta', 'Tb', 'Ts'), main['temperature']))
    evidence = dict(raw, fine=_fine_evidence(fine, fine_balance),
        true_h=None if true_h_info is None else true_h_info['_native_state'],
        model_h_balance=model_balance, mode=mode, split_A=cfg['thermal_geometry']['split_A'],
        outer_index=int(native['iterations']) - 1,
        final_after_thermal=bool(native['post_after_last_thermal']), K_ss=main['solid_conductivity'])
    partial = []
    for side, label in enumerate('AB'):
        flow = native['flow'][side]
        openings = cfg['boundary_openings'][label]
        partial.append(bool(np.any(openings['out_profile_frac'] < .99) or
                            np.any(openings['in_profile_frac'] < .99)))
        pressure_states[label] = flow['inlet_pressure']
        pressure_evidence[label] = dict(
            inlet_gauge_Pa=flow['pressure'][:, 0], outlet_gauge_Pa=flow['pressure'][:, -1],
            inlet_fraction=openings['in_profile_frac'], outlet_fraction=openings['out_profile_frac'],
            outlet_geom_frac=openings['out_geom_frac'], reference_abs_Pa=flow['reference_pressure'])
        evidence.update({
            'P_thermal_' + label: main['pressure'][side],
            'P_report_' + label: flow['absolute_pressure'], 'h_v' + label: main['hv'][side],
            'rho_cp_' + label: None if mode == 'true_h' else main['rho_cp'][side],
            'mass_flux_' + label: (flow['mass_x'], flow['mass_y']),
        })
        raw.update({'P_f' + label: flow['absolute_pressure'], 'uc' + label: flow['uc'], 'vc' + label: flow['vc'],
                    'uc' + label + '_disp': None, 'vc' + label + '_disp': None})
        result = flow['result']
        if not result['converged']:
            warnings.append(
                f"SIMPLE (Fluid {label}): not converged after {result['iterations']} iters "
                f"(exit={result['exit_reason']}, mom={result['momentum']['maximum']}, "
                f"mass_local={result['mass']['local_residual']}, "
                f"mass_global={result['mass']['global_residual']})")
    evidence['pressure'] = pressure_evidence
    if fine is not None and not native['fine_extrapolated']:
        source = '主网格值' if np.any(np.isfinite(native['duty'])) else ('不可用值' if mode == 'model_h' else '1D 最后兜底值')
        warnings.append(
            f"Richardson 细解或外推未通过，换热量使用{source}，未外推 "
            f"(converged={fine_info['converged']}, iterations={fine_info['iterations']}, "
            f"residual={fine_info['residual']:.3e})")
    if any(partial):
        from scipy.ndimage import gaussian_filter
        for key in ('Ta', 'Tb', 'Ts'):
            raw[key] = gaussian_filter(raw[key], sigma=1.5)
        for side, label in enumerate('AB'):
            if partial[side]:
                raw['P_f' + label] = gaussian_filter(raw['P_f' + label], sigma=1.5)
                for prefix in ('uc', 'vc'):
                    raw[prefix + label + '_disp'] = gaussian_filter(raw[prefix + label], sigma=2.)

    detail = dict(inlet_pressure=pressure_states, outer_converged=bool(native['outer_converged']),
        outer_iters=int(native['iterations']), outer_hit_cap=not native['outer_converged'],
        simple_ok=bool(native['simple_ok']), ltne_ok=bool(native['thermal_ok']),
        richardson_ok=None if fine is None else bool(fine_info['converged'] and native['fine_extrapolated']),
        ltne_iterations=int(main['iterations']), ltne_residual=float(main['residual']),
        enthalpy_balance_ok=bool(native['pair_balance_ok']),
        model_h_balance_ok=bool(native['model_balance_ok']) if mode == 'model_h' else None,
        envelope_ok=bool(native['envelope_ok']))
    diagnostics = dict(
        sco2_nu_observations=native['sco2_nu_observations'],
        T_out_A_K=native['outlet_temperature'][0], T_out_B_K=native['outlet_temperature'][1],
        dP_A=native['pressure_drop'][0], dP_B=native['pressure_drop'][1], Q_total=native['q_total'],
        mass_flow_A_kg_s_per_m=native['inlet_mass'][0], mass_flow_B_kg_s_per_m=native['inlet_mass'][1],
        warnings_list=warnings, solver_converged=bool(native['converged']), convergence_detail=detail,
        Q_A=native['duty'][0], Q_B=native['duty'][1], Q_net=sum(native['duty']),
        energy_imbalance_rel=native['energy_imbalance'],
        Q_enthalpy_A=abs(native['duty'][0]), Q_enthalpy_B=abs(native['duty'][1]),
        Q_solid_richardson=native['q_solid'], Q_richardson_warn=bool(native['fine_warning']),
        richardson_info=fine_info, model_h_balance=None if model_balance is None else dict(main=model_balance, fine=fine_balance),
        true_h_balance=true_balance, envelope_valid=bool(native['envelope_ok']),
        envelope_reasons=[f'[{label}] {reason}' for label, flow in zip('AB', native['flow']) for reason in flow['envelope_reasons']],
        p_clip_hits=sum(flow['result']['pressure_clip_hits'] for flow in native['flow']),
        df_metadata=dict(mode=cfg['compute_cfg'].df_mode,
                         **{label: cfg['flow_inputs'][label]['metadata'] for label in 'AB'}),
        native_full_2d=dict(numerical_driver='cpp',
                            range_observations=native['range_observations']))
    for side, label in enumerate('AB'):
        state, flow = pressure_states[label], native['flow'][side]
        diagnostics['P_in_realized_' + label] = np.nan if state is None else state['realized_Pa']
        diagnostics['P_in_shoot_resid_' + label] = np.nan if state is None else state['relative_error']
        diagnostics['residuals_' + label] = list(flow['history']['legacy'])
        diagnostics['mass_imbalance_rel_' + label] = flow['result']['mass']['global_residual']
        for prefix in ('uc', 'vc'):
            key = prefix + label + '_disp'
            if raw[key] is None:
                diagnostics[key] = None
    properties = cfg['static_properties']
    r_a, r_b = properties['A'], properties['B']
    raw.update(diagnostics, _native_evidence=evidence,
        application=dict(
            coeffs=dict(K_ffA=r_a['K_ff'], K_ffB=r_b['K_ff'], K_ss=properties['geometry']['K_ss'],
                        h_vA=compute_volumetric_htc(r_a['A_0'], r_a['H_sf']),
                        h_vB=compute_volumetric_htc(r_b['A_0'], r_b['H_sf'])),
            props=dict(rho_A=r_a['rho'], rho_B=r_b['rho'], mu_A=r_a['mu'], mu_B=r_b['mu']),
            zones=_zone_statistics_2d(cfg['z_axis'], cfg['zone_config'], cfg['za'], cfg['L'], cfg['H'],
                prepared['energy_dx'], prepared['energy_dy'], *main['temperature'])))
    return _capture_result(case, raw, diagnostics, backend_id='cpp', backend_version='full_2d_v2')
