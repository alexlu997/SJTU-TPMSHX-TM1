"""3D engineering reductions over portable fields and boundary evidence."""
import numpy as np

from sjtu_tpmshx.result_math import _boundary_enthalpy_duty


def _outlet(field, direction):
    return np.take(field, -1 if direction % 2 == 0 else 0, axis=direction // 2)


def _weighted(values, weights):
    total = float(np.sum(weights))
    if total <= 1e-30:
        raise ValueError('no flowing outlet evidence')
    return float(np.sum(np.asarray(values) * weights) / total)


def _dp(pressure):
    p = np.asarray(pressure['P'])
    dy = np.asarray(pressure['dy'])
    area = np.asarray(pressure['dx'])[:, None] * np.asarray(pressure['dz'])[None, :]
    inlet = np.asarray(pressure['inlet_frac']) * area
    outlet = np.asarray(pressure['outlet_frac']) * area
    if p.shape[1] < 2:
        return _weighted(p[:, 0], inlet) - _weighted(p[:, -1], outlet)
    ri, ro = dy[0] / (dy[0] + dy[1]), dy[-1] / (dy[-2] + dy[-1])
    return (_weighted((1 + ri) * p[:, 0] - ri * p[:, 1], inlet)
            - _weighted((1 + ro) * p[:, -1] - ro * p[:, -2], outlet))


def thermal_duties(result):
    flux = result.boundary_fluxes
    if result.metadata['thermal_mode'] == 'model_h':
        return tuple(-sum(float(np.sum(face)) for face in flux['model_h'][side].values())
                     for side in ('A', 'B'))
    if result.metadata['thermal_mode'] == 'true_h':
        native = flux['true_h']
        return tuple(_boundary_enthalpy_duty(native['h_' + side], native['h_in_' + side],
                                             native['mass_flux_' + side]) for side in ('A', 'B'))
    raise NotImplementedError('legacy temperature route has no captured complete enthalpy transport')


def _reported_duty(result, side):
    report = result.boundary_fluxes['report'][side]
    temperature = _outlet(result.fields['Ta' if side == 'A' else 'Tb'], report['direction'])
    weights = np.asarray(report['outlet_weights'])
    inlet_mass = float(np.sum(report['inlet_weights']))
    parameters = result.metadata['parameters']
    if 'sco2' in (parameters['fluid_type_A'], parameters['fluid_type_B']):
        h_out = _weighted(report['h_out_J_kg'], weights)
        h_in = report['h_in_J_kg']
        return abs(inlet_mass * (h_in - h_out))
    return abs(inlet_mass * report['cp'] * (report['inlet_temperature'] - _weighted(temperature, weights)))


def evaluate_metric(result, name):
    if name == 'Q':
        if result.metadata['thermal_mode'] == 'model_h':
            if not result.metadata['diagnostics']['model_h_balance']['sides']['A']['physical_boundary_complete']:
                raise ValueError('unknown inflow prevents a complete heat duty')
            return abs(thermal_duties(result)[0])
        return _reported_duty(result, 'A')
    if name.startswith('dP_'):
        return _dp(result.pressure_evidence[name[-1]])
    if name.startswith('T_out_'):
        side = name[-1]
        report = result.boundary_fluxes['report'][side]
        return _weighted(_outlet(result.fields['Ta' if side == 'A' else 'Tb'], report['direction']),
                         np.asarray(report['outlet_weights']))
    if name.startswith('mass_flow_'):
        return float(np.sum(result.boundary_fluxes['report'][name[-1]]['inlet_weights']))
    if name.startswith('mass_imbalance_rel_'):
        faces = result.boundary_fluxes['mass_' + name[-1]]
        if faces is None:
            raise KeyError('last thermal mass faces')
        outward = [sign * np.take(face, end, axis=axis) for axis, face in enumerate(faces)
                   for end, sign in ((0, -1), (-1, 1))]
        inflow = sum(float(np.maximum(-face, 0).sum()) for face in outward)
        outflow = sum(float(np.maximum(face, 0).sum()) for face in outward)
        return abs(outflow-inflow) / max(inflow, outflow, 1e-30)
    if name == 'energy_imbalance_rel':
        a, b = thermal_duties(result)
        return abs(a+b) / max(abs(a), abs(b), 1e-30)
    if name == 'mass':
        density = result.metadata['solid_density_kg_m3']
        volume = (np.asarray(result.grid['dx'])[:, None, None]
                  * np.asarray(result.grid['dy'])[None, :, None]
                  * np.asarray(result.grid['dz'])[None, None, :])
        return float(np.sum(density * (1-np.asarray(result.metadata['design_fields']['eps_arr'])) * volume))
    raise NotImplementedError(f'unsupported metric: {name}')
