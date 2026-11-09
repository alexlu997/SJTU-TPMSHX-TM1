"""Engineering metrics recomputed from native evidence, never solver callbacks."""

import numpy as np

from sjtu_tpmshx.shared.result_math import (
    _boundary_enthalpy_duty, _boundary_face_shape,
    _conservative_boundary_power_duty, _temperature_boundary_power_duty,
    _enthalpy_balance_2d, _outlet_temperature_2d,
)


def _outward_faces(mass, grid=None):
    _boundary_face_shape(mass, 2, grid)
    fx, fy = (np.asarray(face) for face in mass)
    return (-fx[0], fx[-1], -fy[:, 0], fy[:, -1])


def _model_duty(balance, side, grid):
    if not balance[side]['physical_boundary_complete']:
        raise ValueError('unknown inflow prevents a complete heat duty')
    return -sum(float(face.sum()) for face in _outward_faces(balance[side]['h_faces_W_per_m'], grid))


def _side_duty(result, side, *, fine=False):
    mode = result.metadata['thermal_mode']
    fluxes = result.boundary_fluxes
    if mode == 'conservative_energy':
        if fine:
            raise NotImplementedError('conservative energy has no Richardson thermal solve')
        return _conservative_boundary_power_duty(fluxes['true_h'], side, 2, result.grid)
    if mode == 'true_h':
        if fine:
            raise NotImplementedError('true enthalpy has no Richardson thermal solve')
        native = fluxes['true_h']
        enthalpy = np.asarray(native['h_' + side])
        mass = tuple(np.asarray(face) for face in native['mass_flux_' + side])
        shape = _boundary_face_shape(mass, 3, result.grid)
        if shape != enthalpy.shape or shape[2] != 1:
            raise ValueError('2D true-h evidence requires matching singleton-z cells and mass faces')
        return _boundary_enthalpy_duty(enthalpy, native['h_in_' + side], mass)
    if mode == 'model_h':
        balance = fluxes['fine']['model_h_balance'] if fine else fluxes['model_h']
        return _model_duty(balance, side, fluxes['fine'] if fine else result.grid)
    if mode != 'temperature':
        raise NotImplementedError(f'unsupported thermal mode: {mode}')
    return _temperature_duty(result, side, fine=fine)


def _temperature_duty(result, side, *, fine=False):
    flux = result.boundary_fluxes
    if ('temperature_transport' in result.metadata or 'temperature' in flux
            or 'temperature' in (flux.get('fine') or {})):
        if result.metadata.get('temperature_transport') != 'model_enthalpy_temperature_v1':
            raise ValueError('unsupported temperature transport declaration')
        evidence = result.boundary_fluxes['fine'] if fine else result.boundary_fluxes
        grid = evidence if fine else result.grid
        return _temperature_boundary_power_duty(evidence['temperature'], side, 2, grid)
    parameters = result.metadata['parameters']
    data = result.boundary_fluxes['fine'] if fine else result.fields
    temperature = np.asarray(data['Ta' if side == 'A' else 'Tb'])
    density_cp = np.asarray(data['rho_cp_' + side] if fine else result.metadata['rho_cp_' + side])
    density_cp = np.broadcast_to(density_cp, temperature.shape)
    eps = np.asarray(data['eps'] if fine else parameters['eps'])
    split = result.metadata['split_A'] if side == 'A' else 1 - result.metadata['split_A']
    pressure = result.pressure_evidence[side]
    return _enthalpy_balance_2d(
        temperature, np.asarray(data['uc' + side]), np.asarray(data['vc' + side]),
        density_cp, parameters['dir_' + side],
        np.asarray(data['dx'] if fine else result.grid['dx']),
        np.asarray(data['dy'] if fine else result.grid['dy']),
        inlet_mask=data['inlet_' + side] if fine else pressure['inlet_fraction'],
        outlet_mask=data['outlet_' + side] if fine else pressure['outlet_fraction'],
        eps_side=eps * split, T_in=parameters['T_in' + side])


def _richardson_duty(result, side, duty):
    if result.metadata['thermal_mode'] == 'conservative_energy':
        raise NotImplementedError('conservative energy has no Richardson thermal solve')
    if result.metadata['thermal_mode'] == 'true_h':
        raise NotImplementedError('true enthalpy has no Richardson thermal solve')
    if not result.metadata['diagnostics']['richardson_info']['extrapolated']:
        raise NotImplementedError('Richardson extrapolation was not accepted')
    return (4. * abs(duty(side, fine=True)) - abs(duty(side))) / 3.


def _mass_flow(result, side):
    faces = _outward_faces(result.boundary_fluxes['mass_' + side], result.grid)
    inflow = sum(float(np.maximum(-face, 0.).sum()) for face in faces)
    outflow = sum(float(np.maximum(face, 0.).sum()) for face in faces)
    return inflow, outflow


def _port_pressures_2d(result, side):
    """Use the same physical-face reduction as 3D, with unit depth."""
    from .three_d import _port_pressures
    parameters = result.metadata['parameters']
    direction = parameters['dir_' + side]
    pressure = np.asarray(result.fields['P_report_' + side])
    dx, dy = np.asarray(result.grid['dx']), np.asarray(result.grid['dy'])
    if direction in (1, 3):
        pressure = np.flip(pressure, axis=direction // 2)
    if direction in (0, 1):
        pressure, dx, dy = pressure.T, dy, dx
    if direction in (1, 3):
        dy = dy[::-1]
    openings = parameters['boundary_openings'][side]
    return _port_pressures(dict(P=pressure[:, :, None], dx=dx, dy=dy, dz=np.ones(1),
                               inlet_frac=np.asarray(openings['in_geom_frac'])[:, None],
                               outlet_frac=np.asarray(openings['out_geom_frac'])[:, None]))


def _evaluate_metric(result, name, *, dimension, duty, mass_flow):
    if result.metadata.get('mode') == 'quick_design':
        from .quick_design import evaluate_metric as evaluate_quick_design_metric
        return evaluate_quick_design_metric(result, name)
    if dimension == 3:
        from .three_d import evaluate_metric as evaluate_3d_metric
        return evaluate_3d_metric(result, name, duty=duty, mass_flow=mass_flow)
    if dimension != 2:
        raise NotImplementedError('unsupported physical dimension')
    if name == 'Q':
        return abs(duty('A'))
    if name in ('Q_A', 'Q_B'):
        return duty(name[-1])
    if name.startswith('Q_richardson_'):
        return _richardson_duty(result, name[-1], duty)
    if name.startswith(('dP_', 'P_out_')):
        pin, pout = _port_pressures_2d(result, name[-1])
        return pin - pout if name.startswith('dP_') else pout
    if name.startswith('T_out_'):
        side = name[-1]
        temperature = np.asarray(result.fields['Ta' if side == 'A' else 'Tb'])
        mass = tuple(np.asarray(face) for face in result.boundary_fluxes['mass_' + side])
        if _boundary_face_shape(mass, 2, result.grid) != temperature.shape:
            raise ValueError('outlet temperature cells disagree with native mass faces')
        return _outlet_temperature_2d(temperature, mass,
            result.metadata['parameters']['dir_' + side],
            result.pressure_evidence[side]['outlet_geom_frac'])
    if name.startswith('mass_flow_'):
        return mass_flow(name[-1])[0]
    if name.startswith('mass_imbalance_rel_'):
        inflow, outflow = mass_flow(name[-1])
        return abs(outflow - inflow) / max(inflow, outflow, 1e-30)
    if name == 'energy_imbalance_rel':
        a, b = (duty(side) for side in ('A', 'B'))
        return abs(a + b) / max(abs(a), abs(b), 1e-30)
    if name == 'mass':
        density = result.metadata['solid_density_kg_m3']
        eps = np.asarray(result.metadata['design_fields']['eps_arr'])
        return float(np.sum((1 - eps) * density * np.asarray(result.grid['dx'])[:, None]
                            * np.asarray(result.grid['dy'])[None, :]))
    raise NotImplementedError(f'unsupported metric: {name}')
