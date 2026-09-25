"""Existing full-control-volume conservation certificate from native evidence."""
import numpy as np


def compute_phase2a(res):
    """Consume the existing strict certificate and actual model-h face ledger.

    The thermal operator owns its final-state face masks, advective fluxes and
    half-cell inlet diffusion. T5 uses the capacity-temperature operator and
    has no model-h ledger; its active-fluid strict certificate still applies.
    Rebuilding a budget from cell-centred velocities or guessed masks is not
    equivalent to either discrete operator.
    """
    balance = res['model_h_balance']
    active_b = res['_audit_fB'] is not None
    phases, gates = {}, []
    for side in ('A', 'B'):
        if side == 'B' and not active_b:
            phases[side] = None
            gates.append(('B disabled: no certificate and zero coupling',
                          res['eps_B_strict'] is None
                          and res['eps_B_strict_cellmax'] is None
                          and res['Q_sB'] == 0.0
                          and np.all(np.asarray(res['h_vB_field']) == 0.0)))
            continue
        phase = {}
        for metric, key in (('global', f'eps_{side}_strict'),
                            ('cellmax', f'eps_{side}_strict_cellmax')):
            value = res.get(key)
            phase[metric] = value = float(value) if value is not None else float('nan')
            gates.append((f'{side} strict {metric} < 1 %',
                          bool(np.isfinite(value) and 0.0 <= value < 0.01)))
        phase['boundary'] = balance['sides'][side] if balance is not None else None
        phases[side] = phase
    qa, qb = float(res['Q_sA']), float(res['Q_sB'])
    eps_ltne = abs(qa + qb) / max(abs(qa), abs(qb), 1e-30)
    gates.append(('full-volume LTNE source balance < 1 %',
                  bool(np.isfinite(eps_ltne) and eps_ltne < 0.01)))
    if balance is not None:
        gates.append(('physical boundary data complete',
                      balance['physical_boundary_complete'] is True))
    elif active_b:
        gates.append(('two-fluid model-h boundary ledger available', False))
    return dict(sides=phases, eps_LTNE=eps_ltne, gates=gates,
                boundary=balance)
