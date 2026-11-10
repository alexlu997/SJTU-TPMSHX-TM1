"""3D engineering reductions over portable fields and boundary evidence."""
import numpy as np

from sjtu_tpmshx.shared import _native_result_metrics as native

from sjtu_tpmshx.shared.result_math import (
    _boundary_enthalpy_duty, _boundary_face_shape,
    _conservative_boundary_power_duty, _temperature_boundary_power_duty, pressure_face_values,
)


def _outlet(field, direction):
    return np.take(field, -1 if direction % 2 == 0 else 0, axis=direction // 2)


def _weighted(values, weights):
    return native.weighted_mean(np.asarray(values), weights)


def _port_pressures(pressure):
    p = np.asarray(pressure['P'])
    if p.ndim != 3 or any(size == 0 for size in p.shape):
        raise ValueError('pressure evidence requires nonempty three-dimensional cells')
    widths = [np.asarray(pressure['d' + axis]) for axis in 'xyz']
    for axis, values, size in zip('xyz', widths, p.shape):
        if values.shape != (size,) or not native.port_width_valid(values):
            raise ValueError(f'pressure {axis} widths must be positive, finite and match cells')
    openings = [np.asarray(pressure[name + '_frac']) for name in ('inlet', 'outlet')]
    for name, values in zip(('inlet', 'outlet'), openings):
        if values.shape != (p.shape[0], p.shape[2]) or not native.port_opening_valid(values):
            raise ValueError(f'pressure {name} fractions must be nonnegative, finite and match faces')
    dx, dy, dz = widths
    inlet, outlet = native.port_weights(dx, dz, *openings)
    pin, pout = pressure_face_values(p, dy)
    return _weighted(pin, inlet), _weighted(pout, outlet)


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
        return native.plane_duty(faces)
    if result.metadata['thermal_mode'] == 'true_h':
        evidence = flux['true_h']
        mass = evidence['mass_flux_' + side]
        enthalpy = evidence['h_' + side]
        if _boundary_face_shape(mass, 3, result.grid) != np.shape(enthalpy):
            raise ValueError('native enthalpy cells disagree with mass faces')
        return _boundary_enthalpy_duty(enthalpy, evidence['h_in_' + side], mass)
    raise NotImplementedError('legacy temperature route has no captured complete enthalpy transport')


def _mass_flow(result, side):
    faces = result.boundary_fluxes['mass_' + side]
    _boundary_face_shape(faces, 3, result.grid)
    planes = [np.take(face, end, axis=axis) for axis, face in enumerate(faces)
              for end in (0, -1)]
    return native.boundary_mass(planes, 3)


def evaluate_metric(result, name, *, duty, mass_flow):
    if (name.endswith('_B') or name == 'energy_imbalance_rel') and 'B' not in result.metadata.get('active_fluids', ('A', 'B')):
        raise NotImplementedError('fluid B is inactive in this prepared research case')
    if name == 'Q':
        return native.duty_magnitude(duty('A'))
    if name in ('Q_A', 'Q_B'):
        return duty(name[-1])
    if name.startswith(('dP_', 'P_out_')):
        pressure = result.pressure_evidence[name[-1]]
        pin, pout = _port_pressures(pressure)
        return (native.pressure_difference(pin, pout) if name.startswith('dP_')
                else native.absolute_outlet_pressure(pout, pressure['P_ref_abs']))
    if name.startswith('T_out_'):
        side = name[-1]
        direction = result.boundary_fluxes['report'][side]['direction']
        mass = result.boundary_fluxes['mass_' + side]
        temperature = result.fields['Ta' if side == 'A' else 'Tb']
        if _boundary_face_shape(mass, 3, result.grid) != np.shape(temperature):
            raise ValueError('outlet temperature cells disagree with native mass faces')
        outward = _outlet(mass[direction // 2], direction)
        temperature = _outlet(temperature, direction)
        return native.outlet_temperature_3d(temperature, outward, direction % 2 != 0)
    if name.startswith('mass_flow_'):
        return mass_flow(name[-1])[0]
    if name.startswith('mass_imbalance_rel_'):
        inflow, outflow = mass_flow(name[-1])
        return native.mass_imbalance(inflow, outflow)
    if name == 'energy_imbalance_rel':
        a, b = (duty(side) for side in ('A', 'B'))
        return native.full_energy_imbalance(a, b)
    if name == 'mass':
        density = result.metadata['solid_density_kg_m3']
        widths = tuple(np.asarray(result.grid['d' + axis]) for axis in 'xyz')
        return native.solid_mass(np.asarray(result.metadata['design_fields']['eps_arr']), density, widths)
    raise NotImplementedError(f'unsupported metric: {name}')
