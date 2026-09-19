"""Engineering metrics recomputed from native evidence, never solver callbacks."""
from functools import cache, partial
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.metric_spec import MetricSpec
from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult
from sjtu_tpmshx.domain.persistence_validation import validate_result_declarations
from sjtu_tpmshx.result_math import (
    _boundary_enthalpy_duty, _enthalpy_balance_2d, _outlet_temperature_2d,
)


def _outward_faces(mass):
    fx, fy = (np.asarray(face) for face in mass)
    return (-fx[0], fx[-1], -fy[:, 0], fy[:, -1])


def _model_duty(balance, side):
    if not balance[side]['physical_boundary_complete']:
        raise ValueError('unknown inflow prevents a complete heat duty')
    return -sum(float(face.sum()) for face in _outward_faces(balance[side]['h_faces_W_per_m']))


def _side_duty(result, side, *, fine=False):
    mode = result.metadata['thermal_mode']
    fluxes = result.boundary_fluxes
    if mode == 'true_h':
        if fine:
            raise NotImplementedError('true enthalpy has no Richardson thermal solve')
        native = fluxes['true_h']
        return _boundary_enthalpy_duty(
            np.asarray(native['h_' + side]), native['h_in_' + side],
            tuple(np.asarray(face) for face in native['mass_flux_' + side]))
    if mode == 'model_h':
        balance = fluxes['fine']['model_h_balance'] if fine else fluxes['model_h']
        return _model_duty(balance, side)
    if mode != 'temperature':
        raise NotImplementedError(f'unsupported thermal mode: {mode}')
    return _temperature_duty(result, side, fine=fine)


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


def _richardson_duty(result, side, duty):
    if result.metadata['thermal_mode'] == 'true_h':
        raise NotImplementedError('true enthalpy has no Richardson thermal solve')
    if not result.metadata['diagnostics']['richardson_info']['extrapolated']:
        raise NotImplementedError('Richardson extrapolation was not accepted')
    return (4. * abs(duty(side, fine=True)) - abs(duty(side))) / 3.


def _mass_flow(result, side):
    faces = _outward_faces(result.boundary_fluxes['mass_' + side])
    inflow = sum(float(np.maximum(-face, 0.).sum()) for face in faces)
    outflow = sum(float(np.maximum(face, 0.).sum()) for face in faces)
    return inflow, outflow


def _pressure_drop_2d(result, side):
    """Use the same physical-face reduction as 3D, with unit depth."""
    from .three_d import _dp
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
    return _dp(dict(P=pressure[:, :, None], dx=dx, dy=dy, dz=np.ones(1),
                    inlet_frac=np.asarray(openings['in_geom_frac'])[:, None],
                    outlet_frac=np.asarray(openings['out_geom_frac'])[:, None]))


def _evaluate_metric(result, name, *, duty, mass_flow):
    if result.metadata.get('mode') in ('screening_2d', 'screening_3d'):
        from .screening import evaluate_metric as evaluate_screening_metric
        return evaluate_screening_metric(result, name)
    if result.metadata.get('mode') == 'quick_design':
        from .quick_design import evaluate_metric as evaluate_quick_design_metric
        return evaluate_quick_design_metric(result, name)
    if result.metadata['dimension'] == 3:
        from .three_d import evaluate_metric as evaluate_3d_metric
        return evaluate_3d_metric(result, name, duty=duty, mass_flow=mass_flow)
    if result.metadata['dimension'] != 2:
        raise NotImplementedError('unsupported physical dimension')
    if name == 'Q':
        return abs(duty('A'))
    if name in ('Q_A', 'Q_B'):
        return duty(name[-1])
    if name.startswith('Q_richardson_'):
        return _richardson_duty(result, name[-1], duty)
    if name.startswith('dP_'):
        return _pressure_drop_2d(result, name[-1])
    if name.startswith('T_out_'):
        side = name[-1]
        return _outlet_temperature_2d(
            np.asarray(result.fields['Ta' if side == 'A' else 'Tb']),
            tuple(np.asarray(face) for face in result.boundary_fluxes['mass_' + side]),
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


def evaluate(result: FieldResult, metric_spec: MetricSpec | None = None) -> PerformanceResult:
    """Compute core metrics; missing evidence stays explicitly unavailable."""
    validate_result_declarations(result)
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
    full_compute = result.metadata.get('mode') not in ('quick_design', 'screening_2d', 'screening_3d')
    duty = mass_flow = None
    if full_compute:
        # One evaluation owns these lazy reductions. A/B and coarse/fine stay
        # separate; failed reductions still reach each metric's error handling.
        if result.metadata['dimension'] == 3:
            from .three_d import thermal_duty, _mass_flow as mass_flow_3d
            duty = cache(partial(thermal_duty, result))
            mass_flow = cache(partial(mass_flow_3d, result))
        else:
            duty = cache(partial(_side_duty, result))
            mass_flow = cache(partial(_mass_flow, result))
        unit = definitions['Q'][1]
        definitions.update({name: (name, unit) for name in ('Q_A', 'Q_B')})
        if result.metadata['dimension'] == 2:
            definitions.update({name: (name, unit) for name in ('Q_richardson_A', 'Q_richardson_B')})
    descriptions = {
        'Q': 'Absolute A-side heat loss from the native main thermal boundary state; no side selection or extrapolation.',
        'Q_A': 'Signed A-side heat loss from the native main thermal boundary state; heat loss is positive.',
        'Q_B': 'Signed B-side heat loss from the native main thermal boundary state; heat loss is positive.',
        'Q_richardson_A': 'A-side Richardson extrapolation of absolute coarse/fine duties; separate from main-grid Q.',
        'Q_richardson_B': 'B-side Richardson extrapolation of absolute coarse/fine duties; separate from main-grid Q.',
        'T_out_A': 'Raw main thermal outlet temperature weighted by positive outward native mass flux.',
        'T_out_B': 'Raw main thermal outlet temperature weighted by positive outward native mass flux.',
        'mass_flow_A': 'Total inward signed boundary mass from the main thermal input state.',
        'mass_flow_B': 'Total inward signed boundary mass from the main thermal input state.',
        'energy_imbalance_rel': 'Absolute sum of native signed A/B duties divided by their maximum absolute value.',
        'dP_A': 'Geometric-area-weighted inlet minus outlet pressure, extrapolated to physical port faces from the final SIMPLE field.',
        'dP_B': 'Geometric-area-weighted inlet minus outlet pressure, extrapolated to physical port faces from the final SIMPLE field.',
    }
    metrics = {}
    for name, (kind, unit) in definitions.items():
        if metric_spec is not None and metric_spec.name not in (kind, name):
            continue
        version = ('pressure_face_v1' if full_compute and name in ('dP_A', 'dP_B')
                   else 'native_boundary_v1' if full_compute and name in descriptions
                   else 'three_module_v1')
        spec = metric_spec or MetricSpec(kind, unit, version, descriptions.get(name, '') if full_compute else '')
        try:
            if spec.unit != unit or spec.definition_version != version:
                raise NotImplementedError(f'unsupported requested definition: {spec}')
            value = float(_evaluate_metric(result, name, duty=duty, mass_flow=mass_flow))
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
