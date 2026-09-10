"""Engineering metrics recomputed from native evidence, never solver callbacks."""
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult
from sjtu_tpmshx.result_math import (
    _boundary_enthalpy_duty, _enthalpy_balance_2d, _outlet_temperature_2d,
    _pipe_weighted,
)


def _outward_faces(mass):
    fx, fy = (np.asarray(face) for face in mass)
    return (-fx[0], fx[-1], -fy[:, 0], fy[:, -1])


def _model_duty(balance, side):
    return -sum(float(face.sum()) for face in _outward_faces(balance[side]['h_faces_W_per_m']))


def _side_duties(result):
    mode = result.metadata['thermal_mode']
    fluxes = result.boundary_fluxes
    if mode == 'true_h':
        native = fluxes['true_h']
        return tuple(_boundary_enthalpy_duty(
            np.asarray(native['h_' + side]), native['h_in_' + side],
            tuple(np.asarray(face) for face in native['mass_flux_' + side]))
                     for side in ('A', 'B'))
    if mode == 'model_h':
        return tuple(_model_duty(fluxes['model_h'], side) for side in ('A', 'B'))
    if mode != 'temperature':
        raise NotImplementedError(f'unsupported thermal mode: {mode}')
    return tuple(_temperature_duty(result, side) for side in ('A', 'B'))


def _temperature_duty(result, side, *, fine=False):
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


def _heat_duty(result):
    user = _side_duties(result)
    mode = result.metadata['thermal_mode']
    if mode == 'true_h':
        return abs(user[0])
    refined = result.metadata['diagnostics']['richardson_info']
    if refined['extrapolated']:
        fine = result.boundary_fluxes['fine']
        values = (tuple(_model_duty(fine['model_h_balance'], side) for side in ('A', 'B'))
                  if mode == 'model_h' else
                  tuple(_temperature_duty(result, side, fine=True) for side in ('A', 'B')))
        candidates = [(4. * abs(finer) - abs(coarser)) / 3.
                      for coarser, finer in zip(user, values)]
    else:
        candidates = [abs(value) for value in user]
    finite = [value for value in candidates if np.isfinite(value)]
    if not finite:
        raise ValueError('no finite native heat-duty evidence')
    return max(finite)


def _mass_flow(result, side):
    faces = _outward_faces(result.boundary_fluxes['mass_' + side])
    inflow = sum(float(np.maximum(-face, 0.).sum()) for face in faces)
    outflow = sum(float(np.maximum(face, 0.).sum()) for face in faces)
    return inflow, outflow


def _evaluate_metric(result, name):
    if result.metadata.get('mode') == 'quick_design':
        from .quick_design import evaluate_metric
        return evaluate_metric(result, name)
    if result.metadata['dimension'] == 3:
        from .three_d import evaluate_metric
        return evaluate_metric(result, name)
    if result.metadata['dimension'] != 2:
        raise NotImplementedError('unsupported physical dimension')
    if name == 'Q':
        return _heat_duty(result)
    if name.startswith('dP_'):
        pressure = result.pressure_evidence[name[-1]]
        return (_pipe_weighted(np.asarray(pressure['inlet_gauge_Pa']), np.asarray(pressure['inlet_fraction']))
                - _pipe_weighted(np.asarray(pressure['outlet_gauge_Pa']), np.asarray(pressure['outlet_fraction'])))
    if name.startswith('T_out_'):
        side = name[-1]
        return _outlet_temperature_2d(
            np.asarray(result.fields['Ta' if side == 'A' else 'Tb']),
            tuple(np.asarray(face) for face in result.boundary_fluxes['mass_' + side]),
            result.metadata['parameters']['dir_' + side],
            result.pressure_evidence[side]['outlet_geom_frac'])
    if name.startswith('mass_flow_'):
        return _mass_flow(result, name[-1])[0]
    if name.startswith('mass_imbalance_rel_'):
        inflow, outflow = _mass_flow(result, name[-1])
        return abs(outflow - inflow) / max(inflow, outflow, 1e-30)
    if name == 'energy_imbalance_rel':
        a, b = _side_duties(result)
        return abs(a + b) / max(abs(a), abs(b), 1e-30)
    if name == 'mass':
        density = result.metadata['solid_density_kg_m3']
        eps = np.asarray(result.metadata['design_fields']['eps_arr'])
        return float(np.sum((1 - eps) * density * np.asarray(result.grid['dx'])[:, None]
                            * np.asarray(result.grid['dy'])[None, :]))
    raise NotImplementedError(f'unsupported metric: {name}')


def evaluate(result, metric_spec=None):
    """Compute core metrics; missing evidence stays explicitly unavailable."""
    definitions = {
        'Q': ('Q', 'W/m'), 'dP_A': ('dP', 'Pa'), 'dP_B': ('dP', 'Pa'),
        'T_out_A': ('T_out', 'K'), 'T_out_B': ('T_out', 'K'),
        'mass_flow_A': ('mass_flow', 'kg/(s m)'), 'mass_flow_B': ('mass_flow', 'kg/(s m)'),
        'mass_imbalance_rel_A': ('mass_imbalance_rel', '1'),
        'mass_imbalance_rel_B': ('mass_imbalance_rel', '1'),
        'energy_imbalance_rel': ('energy_imbalance_rel', '1'), 'mass': ('mass', 'kg/m'),
    }
    if result.metadata['dimension'] == 3:
        definitions.update(Q=('Q', 'W'), mass=('mass', 'kg'),
                           mass_flow_A=('mass_flow', 'kg/s'), mass_flow_B=('mass_flow', 'kg/s'))
    if result.metadata.get('mode') == 'quick_design':
        from .quick_design import DEFINITIONS
        definitions.update(DEFINITIONS)
    metrics = {}
    for name, (kind, unit) in definitions.items():
        if metric_spec is not None and metric_spec.name not in (kind, name):
            continue
        spec = metric_spec or MetricSpec(kind, unit)
        try:
            if spec.unit != unit or spec.definition_version != 'three_module_v1':
                raise NotImplementedError(f'unsupported requested definition: {spec}')
            value = float(_evaluate_metric(result, name))
            if not np.isfinite(value):
                raise ValueError('native evidence produced a non-finite metric')
            metrics[name] = MetricValue(value, spec)
        except (KeyError, TypeError) as exc:
            metrics[name] = MetricValue(None, spec, 'insufficient_data', f'missing or incomplete evidence: {exc}')
        except NotImplementedError as exc:
            metrics[name] = MetricValue(None, spec, 'unsupported', str(exc))
        except (ValueError, IndexError) as exc:
            metrics[name] = MetricValue(None, spec, 'invalid', str(exc))
    if metric_spec is not None and not metrics:
        metrics[metric_spec.name] = MetricValue(None, metric_spec, 'unsupported', 'unknown metric')
    return PerformanceResult(str(uuid4()), result.result_id, metrics)
