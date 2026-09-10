"""Design metrics from prescribed boundary data and the final thermal fields."""
import numpy as np

from sjtu_tpmshx.result_math import _cold_outlet

DEFINITIONS = {'Q_cold': ('Q', 'W'), 'Re_A': ('Re', '1'), 'Re_B': ('Re', '1')}


def evaluate_metric(result, name):
    if result.metadata['model'] != 'plug_ltne_analytic_dp_v1':
        raise NotImplementedError('unsupported quick-design metric definition')
    if name == 'T_out_A':
        return float(np.asarray(result.fields['Ta'])[-1, :, :].mean())
    if name == 'T_out_B':
        return _cold_outlet(result.fields['Tb'], result.metadata['parameters']['arrangement'])
    if name in ('Q', 'Q_cold'):
        side = 'A' if name == 'Q' else 'B'
        boundary = result.boundary_fluxes[side]
        delta = boundary['inlet_temperature_K'] - evaluate_metric(result, 'T_out_' + side)
        return boundary['mass_flow_kg_s'] * boundary['cp_J_kgK'] * delta * (1 if side == 'A' else -1)
    if name in ('dP_A', 'dP_B'):
        pressure = result.pressure_evidence[name[-1]]
        return pressure['inlet_absolute_Pa'] - pressure['outlet_absolute_Pa']
    if name in ('Re_A', 'Re_B'):
        side = name[-1]
        props = result.metadata['properties'][side]
        velocity = result.boundary_fluxes[side]['velocity_m_s']
        return props['rho'] * abs(velocity) * result.metadata['parameters']['D_h'] / props['mu']
    if name in ('mass_flow_A', 'mass_flow_B'):
        return result.boundary_fluxes[name[-1]]['mass_flow_kg_s']
    if name == 'energy_imbalance_rel':
        a, b = evaluate_metric(result, 'Q'), evaluate_metric(result, 'Q_cold')
        return abs(a - b) / max(abs(a), abs(b), 1e-30)
    raise NotImplementedError(f'quick-design does not supply {name}')
