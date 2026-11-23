"""Raw result queries and the public conservation certificate."""
import numpy as np

from sjtu_tpmshx.cpp_interface import _native_result_metrics as native
from sjtu_tpmshx.cpp_interface import _native_result_checks as checks


def pressure_face_values(pressure, stream_widths):
    """Extrapolate a +axis-1 pressure field to its physical end faces."""
    p = np.asarray(pressure)
    if p.shape[1] < 2:
        return p[:, 0], p[:, -1]
    dy = np.asarray(stream_widths)
    ri = native.pressure_ratio(dy[0], dy[1])
    ro = native.pressure_ratio(dy[-1], dy[-2])
    return (native.pressure_face(p[:, 0], p[:, 1], ri),
            native.pressure_face(p[:, -1], p[:, -2], ro))


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
    phases, gates, strict_indices = {}, [], []
    ratios = [float('nan')] * 4
    for side in ('A', 'B'):
        if side == 'B' and not active_b:
            phases[side] = None
            gates.append(('B disabled: no certificate and zero coupling',
                          res['eps_B_strict'] is None
                          and res['eps_B_strict_cellmax'] is None
                          and res['Q_sB'] == 0.0
                          and np.bool_(checks.all_zero(np.asarray(res['h_vB_field'])))))
            continue
        phase = {}
        for metric, key in (('global', f'eps_{side}_strict'),
                            ('cellmax', f'eps_{side}_strict_cellmax')):
            value = res.get(key)
            phase[metric] = value = float(value) if value is not None else float('nan')
            index = (0 if side == 'A' else 2) + (metric == 'cellmax')
            ratios[index] = value
            strict_indices.append((len(gates), index))
            gates.append((f'{side} strict {metric} < 1 %', None))
        phase['boundary'] = balance['sides'][side] if balance is not None else None
        phases[side] = phase
    qa, qb = float(res['Q_sA']), float(res['Q_sB'])
    certificate = checks.strict_certificate(active_b, ratios, qa, qb)
    for gate, index in strict_indices:
        gates[gate] = (gates[gate][0], certificate['strict'][index])
    gates.append(('full-volume LTNE source balance < 1 %',
                  certificate['source_pass']))
    if balance is not None:
        gates.append(('physical boundary data complete',
                      balance['physical_boundary_complete'] is True))
    elif active_b:
        gates.append(('two-fluid model-h boundary ledger available', False))
    return dict(sides=phases, eps_LTNE=certificate['epsilon_ltne'],
                source_residual_W=certificate['source_residual'],
                source_normalization_W=certificate['source_normalization'], gates=gates,
                boundary=balance)
