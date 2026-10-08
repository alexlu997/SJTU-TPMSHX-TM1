"""3D engineering reductions over portable fields and boundary evidence."""
import numpy as np

from sjtu_tpmshx.result_math import (
    _boundary_enthalpy_duty, _boundary_face_shape,
    _conservative_boundary_power_duty, _temperature_boundary_power_duty, pressure_face_values,
)


def _outlet(field, direction):
    return np.take(field, -1 if direction % 2 == 0 else 0, axis=direction // 2)


def _weighted(values, weights):
    total = float(np.sum(weights))
    if total <= 1e-30:
        raise ValueError('no flowing outlet evidence')
    return float(np.sum(np.asarray(values) * weights) / total)


def _dp(pressure):
    p = np.asarray(pressure['P'])
    if p.ndim != 3 or any(size == 0 for size in p.shape):
        raise ValueError('pressure evidence requires nonempty three-dimensional cells')
    widths = [np.asarray(pressure['d' + axis]) for axis in 'xyz']
    for axis, values, size in zip('xyz', widths, p.shape):
        if values.shape != (size,) or not np.all(np.isfinite(values) & (values > 0.)):
            raise ValueError(f'pressure {axis} widths must be positive, finite and match cells')
    openings = [np.asarray(pressure[name + '_frac']) for name in ('inlet', 'outlet')]
    for name, values in zip(('inlet', 'outlet'), openings):
        if values.shape != (p.shape[0], p.shape[2]) or not np.all(np.isfinite(values) & (values >= 0.)):
            raise ValueError(f'pressure {name} fractions must be nonnegative, finite and match faces')
    dx, dy, dz = widths
    area = dx[:, None] * dz[None, :]
    inlet, outlet = (values * area for values in openings)
    pin, pout = pressure_face_values(p, dy)
    return _weighted(pin, inlet) - _weighted(pout, outlet)


def thermal_duty(result, side):
    flux = result.boundary_fluxes
    if result.metadata['thermal_mode'] == 'temperature' and (
            'temperature_transport' in result.metadata or 'temperature' in flux):
        if result.metadata.get('temperature_transport') == 'legacy_frozen_cp_single_a_cc_v1':
            if 'temperature' in flux:
                raise ValueError('legacy single-A sCO2 temperature route cannot carry a model enthalpy ledger')
            raise NotImplementedError('single-A sCO2 frozen-property research route has no captured complete h(P,T) transport')
        if result.metadata.get('temperature_transport') != 'model_enthalpy_temperature_v1':
            raise ValueError('unsupported temperature transport declaration')
        return _temperature_boundary_power_duty(flux['temperature'], side, 3, result.grid)
    if result.metadata['thermal_mode'] == 'conservative_energy':
        return _conservative_boundary_power_duty(flux['true_h'], side, 3, result.grid)
    if result.metadata['thermal_mode'] == 'model_h':
        if not result.metadata['diagnostics']['model_h_balance']['sides'][side]['physical_boundary_complete']:
            raise ValueError('unknown inflow prevents a complete heat duty')
        ledger = flux['model_h'][side]
        keys = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')
        if set(ledger) != set(keys):
            raise ValueError('3D model-h requires all six physical boundary faces')
        faces = tuple(ledger[key] for key in keys)
        _boundary_face_shape(faces, 3, result.grid, planes=True)
        return -sum(float(np.sum(face)) for face in faces)
    if result.metadata['thermal_mode'] == 'true_h':
        native = flux['true_h']
        mass = native['mass_flux_' + side]
        enthalpy = native['h_' + side]
        if _boundary_face_shape(mass, 3, result.grid) != np.shape(enthalpy):
            raise ValueError('native enthalpy cells disagree with mass faces')
        return _boundary_enthalpy_duty(enthalpy, native['h_in_' + side], mass)
    raise NotImplementedError('legacy temperature route has no captured complete enthalpy transport')


def _mass_flow(result, side):
    faces = result.boundary_fluxes['mass_' + side]
    _boundary_face_shape(faces, 3, result.grid)
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
        temperature = result.fields['Ta' if side == 'A' else 'Tb']
        if _boundary_face_shape(mass, 3, result.grid) != np.shape(temperature):
            raise ValueError('outlet temperature cells disagree with native mass faces')
        outward = _outlet(mass[direction // 2], direction) * (1 if direction % 2 == 0 else -1)
        if not np.all(np.isfinite(outward)):
            raise ValueError('outlet temperature requires finite native mass flux')
        weights = np.maximum(outward, 0.)
        flowing = weights > 0.
        temperature = _outlet(temperature, direction)
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
