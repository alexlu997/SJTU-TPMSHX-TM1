"""3D engineering reductions over portable fields and boundary evidence."""
import numpy as np

from sjtu_tpmshx.result_math import _boundary_enthalpy_duty, pressure_face_values


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
    pin, pout = pressure_face_values(p, dy)
    return _weighted(pin, inlet) - _weighted(pout, outlet)


def thermal_duty(result, side):
    flux = result.boundary_fluxes
    if result.metadata['thermal_mode'] == 'model_h':
        if not result.metadata['diagnostics']['model_h_balance']['sides'][side]['physical_boundary_complete']:
            raise ValueError('unknown inflow prevents a complete heat duty')
        return -sum(float(np.sum(face)) for face in flux['model_h'][side].values())
    if result.metadata['thermal_mode'] == 'true_h':
        native = flux['true_h']
        return _boundary_enthalpy_duty(native['h_' + side], native['h_in_' + side],
                                      native['mass_flux_' + side])
    raise NotImplementedError('legacy temperature route has no captured complete enthalpy transport')


def _mass_flow(result, side):
    faces = result.boundary_fluxes['mass_' + side]
    if faces is None:
        raise KeyError('last thermal mass faces')
    outward = [sign * np.take(face, end, axis=axis) for axis, face in enumerate(faces)
               for end, sign in ((0, -1), (-1, 1))]
    return tuple(sum(float(np.maximum(sign * face, 0).sum()) for face in outward)
                 for sign in (-1, 1))


def evaluate_metric(result, name, *, duty, mass_flow):
    if name == 'Q':
        return abs(duty('A'))
    if name in ('Q_A', 'Q_B'):
        return duty(name[-1])
    if name.startswith('dP_'):
        return _dp(result.pressure_evidence[name[-1]])
    if name.startswith('T_out_'):
        side = name[-1]
        direction = result.boundary_fluxes['report'][side]['direction']
        mass = result.boundary_fluxes['mass_' + side]
        outward = _outlet(mass[direction // 2], direction) * (1 if direction % 2 == 0 else -1)
        if not np.all(np.isfinite(outward)):
            raise ValueError('outlet temperature requires finite native mass flux')
        weights = np.maximum(outward, 0.)
        flowing = weights > 0.
        temperature = _outlet(result.fields['Ta' if side == 'A' else 'Tb'], direction)
        return _weighted(temperature[flowing], weights[flowing])
    if name.startswith('mass_flow_'):
        return mass_flow(name[-1])[0]
    if name.startswith('mass_imbalance_rel_'):
        inflow, outflow = mass_flow(name[-1])
        return abs(outflow-inflow) / max(inflow, outflow, 1e-30)
    if name == 'energy_imbalance_rel':
        a, b = (duty(side) for side in ('A', 'B'))
        return abs(a+b) / max(abs(a), abs(b), 1e-30)
    if name == 'mass':
        density = result.metadata['solid_density_kg_m3']
        volume = (np.asarray(result.grid['dx'])[:, None, None]
                  * np.asarray(result.grid['dy'])[None, :, None]
                  * np.asarray(result.grid['dz'])[None, None, :])
        return float(np.sum(density * (1-np.asarray(result.metadata['design_fields']['eps_arr'])) * volume))
    raise NotImplementedError(f'unsupported metric: {name}')
