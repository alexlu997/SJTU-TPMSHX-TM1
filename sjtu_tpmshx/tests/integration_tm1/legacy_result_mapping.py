"""Historical mapping oracle from TM1 main d3ba040 (before adapter cleanup).

Only the real integration comparison imports these frozen functions. Production
uses controllers.module_adapter; do not update this oracle to match that code.
"""
from typing import Any
from sjtu_tpmshx.domain.compute_result import ComputeResult
from sjtu_tpmshx.models.nu_correlations import sco2_nu_metadata, sco2_nu_notices
from sjtu_tpmshx.domain.compute_config import ComputeConfig


def safe_float(v: Any) -> float:
    """float(v) with None / non-numeric → nan (headline-scalar guard).

    ``raw.get(key, default)`` only returns ``default`` when ``key`` is
    absent — explicit ``None`` values (e.g. when fluid B is frozen) would
    crash ``float(None)``.
    """
    try:
        return float(v) if v is not None else float('nan')
    except (TypeError, ValueError):
        return float('nan')


def geometry_props(compute_cfg: ComputeConfig) -> tuple[float, float, float]:
    """(epsilon, D_h_m, A_0_m2) triple for the ComputeResult ``props`` slot,
    derived from cfg geometry via the closed-form tpms_calc.geometry."""
    from sjtu_tpmshx.models.tpms_calc import geometry as _tpms_geom
    g = _tpms_geom(compute_cfg.geometry.tpms,
                   compute_cfg.geometry.L_cell_mm,
                   compute_cfg.geometry.t_wall_mm,
                   compute_cfg.geometry.k_s_W_mK)
    return g['epsilon'], g['D_h'], g['A_0']


_safe_float = safe_float


def _finalize_cfg(raw: dict[str, Any],
                  fields: dict[str, Any]) -> ComputeResult:
    """Phase 4 (Qt-free): assemble a :class:`ComputeResult` from the
    raw ``_run_solvers_cfg`` output and the original ``fields`` dict.

    Audit C4 (L-a-2): no window writes; everything moves through the
    returned :class:`domain.compute_result.ComputeResult`.
    Legacy ``_store_results(window, cfg, result)`` becomes a thin
    adapter that copies the result's slots into the UI attributes
    that ``finalize_plots`` already reads from ``window``.

    The ``fields`` dict still holds the parsed-input cfg dict under
    key ``compute_cfg`` (the original :class:`ComputeConfig`) plus
    ``N_x`` / ``N_y`` / ``L`` / ``H`` / ``dir_A`` / ``dir_B`` /
    ``zone_config`` / ``za`` — the same keys ``_store_results`` read
    from the parsed-cfg dict.
    """
    Ta, Tb, Ts = raw['Ta'], raw['Tb'], raw['Ts']
    ucA, vcA = raw['ucA'], raw['vcA']
    ucB, vcB = raw['ucB'], raw['vcB']

    compute_cfg = fields['compute_cfg']

    # Zone slot — None when zones disabled.
    zones_slot = None
    if (raw.get('_shim_zone_axis_dir') is not None
            or raw.get('_shim_zone_stats') is not None):
        zones_slot = {
            'axis_dir': raw.get('_shim_zone_axis_dir'),
            'stats': raw.get('_shim_zone_stats'),
            'boundaries': raw.get('_shim_zone_boundaries'),
            'boundaries_x': raw.get('_shim_zone_boundaries_x'),
            'boundaries_y': raw.get('_shim_zone_boundaries_y'),
        }

    # TPMS geometry derived from cfg (eps + D_h + A_0) for props slot.
    eps_geom, D_h_m, A_0_m2 = geometry_props(compute_cfg)

    return ComputeResult(
        Q_W=safe_float(raw['Q_total']),
        dP_A_Pa=safe_float(raw['dP_A']),
        dP_B_Pa=safe_float(raw['dP_B']),
        # Fail-safe default: a missing/renamed key must read as NOT converged,
        # not silently report success (blind-spot audit W5, 2026-07-07).
        converged=bool(raw.get('solver_converged', False)),
        T_out_A_K=raw['T_out_A_K'],
        T_out_B_K=raw['T_out_B_K'],
        fields={
            'Ta': Ta, 'Tb': Tb, 'Ts': Ts,
            'ucA': ucA, 'vcA': vcA, 'ucB': ucB, 'vcB': vcB,
            # N5: display-smoothed copies (None on full-face runs ⇒ use raw)
            'ucA_disp': raw.get('ucA_disp'), 'vcA_disp': raw.get('vcA_disp'),
            'ucB_disp': raw.get('ucB_disp'), 'vcB_disp': raw.get('vcB_disp'),
            'P_fA': raw['P_fA'], 'P_fB': raw['P_fB'],
            'dx_arr': raw['energy_dx'], 'dy_arr': raw['energy_dy'],
            'N_x': fields['N_x'], 'N_y': fields['N_y'],
            'L': fields['L'], 'H': fields['H'],
            'dir_A': fields['dir_A'], 'dir_B': fields['dir_B'],
            'zone_config': fields['zone_config'],
            'za': fields['za'],
        },
        coeffs={
            'K_ffA': raw.get('_shim_K_ffA'),
            'K_ffB': raw.get('_shim_K_ffB'),
            'K_ss': raw.get('_shim_K_ss'),
            'h_vA': raw.get('_shim_h_vA'),
            'h_vB': raw.get('_shim_h_vB'),
        },
        props={
            'rho_A': raw.get('_shim_rho_A'),
            'rho_B': raw.get('_shim_rho_B'),
            'mu_A': raw.get('_shim_mu_A'),
            'mu_B': raw.get('_shim_mu_B'),
            'eps_A': eps_geom,
            'D_h_m': D_h_m,
            'A_0_m2': A_0_m2,
        },
        residuals={
            'r_dP_A': float('nan'),  # _run_solvers does not surface
            'r_dP_B': float('nan'),
            'r_Q': 1.0 if raw.get('Q_richardson_warn') else 0.0,
            'simple_A': raw.get('residuals_A'),
            'simple_B': raw.get('residuals_B'),
            'mass_imbalance_rel_A': float(
                raw.get('mass_imbalance_rel_A', float('nan'))),
            'mass_imbalance_rel_B': float(
                raw.get('mass_imbalance_rel_B', float('nan'))),
            'Q_A': float(raw.get('Q_A', float('nan'))),
            'Q_B': float(raw.get('Q_B', float('nan'))),
            'Q_net': float(raw.get('Q_net', float('nan'))),
            'energy_imbalance_rel': float(
                raw.get('energy_imbalance_rel', float('nan'))),
            'enthalpy_imbalance_rel': float(
                raw.get('energy_imbalance_rel', float('nan'))),
        },
        zones=zones_slot,
        warnings=list(raw.get('warnings_list', [])) + sco2_nu_notices(fields.get('compute_cfg')),
        extrap_reasons=list(fields.get('extrap_reasons', [])),
        diagnostics={
            # Dimension marker for write_result dispatch (C4).
            'mode': '2d',
            'Q_enthalpy_A': raw.get('Q_enthalpy_A'),
            'Q_enthalpy_B': raw.get('Q_enthalpy_B'),
            'Q_solid_richardson': raw.get('Q_solid_richardson'),
            'Q_richardson_warn': bool(raw.get('Q_richardson_warn', False)),
            'richardson_info': raw.get('richardson_info'),
            'true_h_balance': raw.get('true_h_balance'),
            'model_h_balance': raw.get('model_h_balance'),
            'mass_flow_A_kg_s_per_m': float(
                raw.get('mass_flow_A_kg_s_per_m', float('nan'))),
            'mass_flow_B_kg_s_per_m': float(
                raw.get('mass_flow_B_kg_s_per_m', float('nan'))),
            # 2026-07-12: solve_2d produced all three of these on the raw dict
            # and none of them were forwarded — every ComputeResult consumer
            # was blind to the 2D compressible-envelope verdict and to the
            # P_abs-clip engagement (the 3D side had the same gap for
            # p_clip_hits; both are closed now).
            'envelope_valid': raw.get('envelope_valid', True),
            'envelope_reasons': list(raw.get('envelope_reasons', [])),
            'p_clip_hits': int(raw.get('p_clip_hits', 0)),
            # C8 shooting diagnostics (openspec c8-p-in-shooting): realized
            # inlet absolute pressure vs the specified P_in, per ideal-gas
            # side (NaN otherwise). Forwarded here for the same reason as
            # envelope_valid above — a raw-dict-only key is invisible to
            # every ComputeResult consumer.
            'P_in_realized_A': float(raw.get('P_in_realized_A', float('nan'))),
            'P_in_shoot_resid_A': float(
                raw.get('P_in_shoot_resid_A', float('nan'))),
            'P_in_realized_B': float(raw.get('P_in_realized_B', float('nan'))),
            'P_in_shoot_resid_B': float(
                raw.get('P_in_shoot_resid_B', float('nan'))),
            # Per-gate breakdown behind ComputeResult.converged, so a caller
            # can see WHICH gate failed (convergence truth-table).
            'convergence_detail': raw.get('convergence_detail'),
            'sco2_nu_observations': raw.get('sco2_nu_observations', {}),
        },
        metadata={'darcy_forchheimer': raw.get('df_metadata'),
                  'sco2_nu': sco2_nu_metadata(getattr(fields.get('compute_cfg'), 'sco2_nu', None))},
    )


def _finalize_3d_cfg(raw: dict[str, Any],
                     fields: dict[str, Any]) -> ComputeResult:
    """Phase 4 (Qt-free) 3D: assemble a :class:`ComputeResult` from the
    ``_run_3d_stack`` output.

    Audit C4 (L-a-2). The 3D result dict is much richer than the 2D
    one — most fields land in ``ComputeResult.fields`` /
    ``ComputeResult.diagnostics``. The headline scalars (``Q_total``,
    ``dP_A`` / ``dP_B``, ``T_out_A`` / ``T_out_B``) lift directly.

    B3 C5 (2026-06-13): the ComputeResult is now the SINGLE result carrier.
    ``Main_Menu.write_result`` publishes it directly as
    ``window._result_3d`` and ``ui/plot_3d_results`` reads ``res.fields`` /
    the dataclass attributes — the old raw-dict ``diagnostics['raw_3d']``
    carrier is gone. The render/export contract (every key the renderer +
    CSV/NPZ export consume) is locked by
    ``tests/test_finalize_3d_result_sync.py``.
    """
    compute_cfg = fields.get('compute_cfg')

    # B2 2.1c (2026-06-13): mirror the legacy extrap tagging onto the raw
    # dict (the retired window path stamped these after _run_3d_stack) so
    # the live carrier below is self-contained.
    raw['extrapolated'] = bool(fields.get('extrap_reasons'))
    raw['extrap_reasons'] = list(fields.get('extrap_reasons', []))

    # 3D solver already computed mass-weighted outlet T per side.
    # _safe_float (shared _stage_common.safe_float): None / non-numeric → nan.
    T_out_A = _safe_float(raw.get('T_out_A', raw.get('T_A_out')))
    T_out_B = _safe_float(raw.get('T_out_B', raw.get('T_B_out')))

    # TPMS geometry (eps + D_h + A_0) for props slot.
    eps_geom = D_h_m = A_0_m2 = float('nan')
    if compute_cfg is not None:
        eps_geom, D_h_m, A_0_m2 = geometry_props(compute_cfg)

    return ComputeResult(
        Q_W=_safe_float(raw.get('Q_total', raw.get('Q'))),
        dP_A_Pa=_safe_float(raw.get('dP_A', raw.get('dP'))),
        dP_B_Pa=_safe_float(raw.get('dP_B')),
        # Fail-safe default: a missing/renamed key must read as NOT converged,
        # not silently report success (blind-spot audit W5, 2026-07-07).
        converged=bool(raw.get('solver_converged', False)),
        T_out_A_K=T_out_A,
        T_out_B_K=T_out_B,
        fields={
            'Ta': raw.get('Ta'),
            'Tb': raw.get('Tb'),
            'Ts': raw.get('Ts'),
            'P_fA': raw.get('P_Pa'),
            'P_fB': raw.get('P_Pa_B'),
            'ucA': raw.get('uc_real'),
            'vcA': raw.get('vc_real'),
            'wcA': raw.get('wc_real'),
            'ucB': raw.get('uc_real_B'),
            'vcB': raw.get('vc_real_B'),
            'wcB': raw.get('wc_real_B'),
            'dx': raw.get('dx'),
            'dy': raw.get('dy'),
            'dz': raw.get('dz'),
            'Lx': raw.get('Lx'),
            'Ly': raw.get('Ly'),
            'Lz': raw.get('Lz'),
            # per-cell unit-cell length field (mm) — renderer label axis;
            # carried so the live UI can drop the raw_3d dict (C5).
            'L_mm': raw.get('L_mm'),
            'dir_A': raw.get('dir_A'),
            'dir_B': raw.get('dir_B'),
            'vmag_A': raw.get('vmag'),
            'vmag_B': raw.get('vmag_B'),
            'chi_B': raw.get('chi_B'),
            'h_vA_field': raw.get('h_vA_field'),
            'h_vB_field': raw.get('h_vB_field'),
        },
        coeffs={
            'K_ffA': raw.get('_audit_K_ffA'),
            'K_ffB': raw.get('_audit_K_ffB'),
            'K_ss': raw.get('_audit_K_ss'),
        },
        props={
            'eps_A': eps_geom,
            'D_h_m': D_h_m,
            'A_0_m2': A_0_m2,
            'rho_cp_A': raw.get('_audit_rho_cp_fA'),
            'rho_cp_B': raw.get('_audit_rho_cp_fB'),
            # CSV-export scalars (main._export_results) — carried so the
            # export can read ComputeResult instead of the raw_3d dict (C5).
            'u_A_in_mps': raw.get('u_A'),
            'T_in_A_K': raw.get('T_in'),
        },
        residuals={
            'Q_enthalpy_A': _safe_float(raw.get('Q_enthalpy_A')),
            'Q_enthalpy_B': _safe_float(raw.get('Q_enthalpy_B')),
            'Q_solid_B': _safe_float(raw.get('Q_solid_B')),
            'Q_sA': _safe_float(raw.get('Q_sA')),
            'Q_sB': _safe_float(raw.get('Q_sB')),
            'Q_net': _safe_float(raw.get('Q_net')),
            'Q_interior': _safe_float(raw.get('Q_interior')),
            'energy_imbalance_rel': _safe_float(
                raw.get('energy_imbalance_rel')),
            'enthalpy_imbalance_rel': _safe_float(
                raw.get('Q_AB_imbalance_rel')),
            'mass_imbalance_rel_A': _safe_float(
                raw.get('mass_imbalance_rel_A')),
            'mass_imbalance_rel_B': _safe_float(
                raw.get('mass_imbalance_rel_B')),
        },
        zones=None,  # 3D zones land in fields['chi_B'] / fields['*'] directly
        # U2 (audit 2026-06-28): _run_3d_stack collects the envelope/choke
        # messages AND the explicit SIMPLE non-convergence warning on the raw
        # dict; forward them so the UI sees them (was hard-coded [], silently
        # dropping a 3D under-resolved/off-envelope flag the 2D path surfaces).
        warnings=list(raw.get('envelope_warnings', [])) + sco2_nu_notices(fields.get('compute_cfg')),
        extrap_reasons=list(fields.get('extrap_reasons', [])),
        diagnostics={
            '_ltne_info': raw.get('_ltne_info'),
            'true_h_balance': raw.get('true_h_balance'),
            'model_h_balance': raw.get('model_h_balance'),
            '_max_outer': raw.get('_max_outer'),
            'mass_flow_A_kg_s': _safe_float(raw.get('mass_flow_A_kg_s')),
            'mass_flow_B_kg_s': _safe_float(raw.get('mass_flow_B_kg_s')),
            # Dimension marker for write_result dispatch (C4); '3d' here,
            # '2d' in stages_2d._finalize_cfg.
            'mode': '3d',
            # Compressible-envelope post-solve verdict (U2): carried so the UI
            # can flag a result the warn-mode gate marked non-physical.
            'envelope_valid': raw.get('envelope_valid', True),
            'envelope_reasons': list(raw.get('envelope_reasons', [])),
            # Companion to envelope_valid: the SIMPLE P_abs-clip engagement
            # count (_run_3d_stack sums A+B side `_p_clip_hits`). It was
            # produced on the raw dict but never forwarded, so every
            # ComputeResult consumer had to hard-code a placeholder — see
            # validate_shanghai_3d_real.py --runner pipeline, which reported a
            # constant 0/valid and thereby disabled its own pressure-validity
            # filter. Informational (lifetime counter, not a validity verdict).
            'p_clip_hits': int(raw.get('p_clip_hits', 0)),
            # Per-gate breakdown behind ComputeResult.converged (SIMPLE / LTNE
            # inner / outer coupling / finite fields / envelope), plus the
            # outer ΔT history. Produced by _run_3d_stack but never forwarded,
            # so a caller could see `converged=False` and not know why.
            'convergence_detail': raw.get('convergence_detail'),
            'sco2_nu_observations': raw.get('sco2_nu_observations', {}),
            'AB_interior': raw.get('AB_interior'),
            'Q_sA_interior': raw.get('Q_sA_interior'),
            'Q_sB_interior': raw.get('Q_sB_interior'),
        },
        metadata={'darcy_forchheimer': raw.get('df_metadata'),
                  'sco2_nu': sco2_nu_metadata(getattr(fields.get('compute_cfg'), 'sco2_nu', None))},
    )

