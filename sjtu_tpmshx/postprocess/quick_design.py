"""Design metrics from prescribed boundary data and the final thermal fields."""
import numpy as np

from sjtu_tpmshx.shared.result_math import _cold_outlet
from sjtu_tpmshx.shared import _native_result as wire
from sjtu_tpmshx.shared import _native_result_metrics as native

DEFINITIONS = {'Q_cold': ('Q', 'W'), 'Re_A': ('Re', '1'), 'Re_B': ('Re', '1')}


def _object_protocol(*values):
    return (any(not isinstance(value, (int, float, complex, np.number))
                and not (isinstance(value, np.ndarray) and value.dtype.kind in 'biufc')
                for value in values)
            or wire.integer_product_requires_python(values))


def evaluate_metric(result, name):
    if result.metadata['model'] != 'plug_ltne_analytic_dp_v1':
        raise NotImplementedError('unsupported quick-design metric definition')
    if name == 'T_out_A':
        return native.outlet_mean(np.asarray(result.fields['Ta'])[-1, :, :])
    if name == 'T_out_B':
        return _cold_outlet(result.fields['Tb'], result.metadata['parameters']['arrangement'])
    if name in ('Q', 'Q_cold'):
        side = 'A' if name == 'Q' else 'B'
        boundary = result.boundary_fluxes[side]
        inlet = boundary['inlet_temperature_K']
        outlet = evaluate_metric(result, 'T_out_' + side)
        delta = (inlet - outlet if _object_protocol(inlet)
                 else native.quick_temperature_difference(inlet, outlet))
        mass, cp = boundary['mass_flow_kg_s'], boundary['cp_J_kgK']
        if _object_protocol(mass, cp):
            # Preserve the exact Python integer/object product before float use.
            return mass * cp * delta * (1 if side == 'A' else -1)
        capacity = native.quick_capacity_product(mass, cp)
        return native.quick_duty_from_capacity(capacity, delta, side != 'A')
    if name in ('dP_A', 'dP_B'):
        pressure = result.pressure_evidence[name[-1]]
        inlet, outlet = pressure['inlet_absolute_Pa'], pressure['outlet_absolute_Pa']
        wide_difference = (type(inlet) in (int, bool) and type(outlet) in (int, bool)
                           and max(abs(inlet).bit_length(), abs(outlet).bit_length()) > 62)
        if _object_protocol(inlet) or _object_protocol(outlet) or wide_difference:
            return inlet - outlet
        return native.pressure_difference(inlet, outlet)
    if name in ('Re_A', 'Re_B'):
        side = name[-1]
        props = result.metadata['properties'][side]
        velocity = result.boundary_fluxes[side]['velocity_m_s']
        rho = props['rho']
        protocol = (_object_protocol(rho, velocity)
                    or (type(velocity) is int and velocity == -(1 << 63)))
        flow = rho * abs(velocity) if protocol else native.quick_reynolds_flow(rho, velocity)
        diameter = result.metadata['parameters']['D_h']
        protocol = protocol or _object_protocol(flow, diameter)
        numerator = flow * diameter if protocol else native.quick_reynolds_length(flow, diameter)
        mu = props['mu']
        integer_division = (type(numerator) in (int, bool) and type(mu) in (int, bool)
                            and max(abs(numerator).bit_length(), abs(mu).bit_length()) > 53)
        if protocol or _object_protocol(mu) or integer_division:
            return numerator / mu
        return native.quick_reynolds_quotient(numerator, mu)
    if name in ('mass_flow_A', 'mass_flow_B'):
        return result.boundary_fluxes[name[-1]]['mass_flow_kg_s']
    if name == 'energy_imbalance_rel':
        a, b = evaluate_metric(result, 'Q'), evaluate_metric(result, 'Q_cold')
        return native.quick_energy_imbalance(a, b)
    raise NotImplementedError(f'quick-design does not supply {name}')


def evaluate(result, metric_spec=None):
    """Keep the Quick Design numeric protocol until its stage is integrated."""
    from uuid import uuid4
    from sjtu_tpmshx.shared.domain.metric_spec import MetricSpec
    from sjtu_tpmshx.shared.domain.performance_result import MetricValue, PerformanceResult
    from sjtu_tpmshx.shared.domain.persistence_validation import validate_result_declarations
    from sjtu_tpmshx.shared._native_result_stage import evaluate_qualification

    dimension = validate_result_declarations(result)
    if dimension not in (2, 3):
        raise ValueError('postprocessing requires physical dimension 2 or 3')
    definitions = {
        'Q': ('Q', 'W'), 'dP_A': ('dP', 'Pa'), 'dP_B': ('dP', 'Pa'),
        'T_out_A': ('T_out', 'K'), 'T_out_B': ('T_out', 'K'),
        'mass_flow_A': ('mass_flow', 'kg/s'), 'mass_flow_B': ('mass_flow', 'kg/s'),
        'mass_imbalance_rel_A': ('mass_imbalance_rel', '1'),
        'mass_imbalance_rel_B': ('mass_imbalance_rel', '1'),
        'energy_imbalance_rel': ('energy_imbalance_rel', '1'), 'mass': ('mass', 'kg'),
        **DEFINITIONS,
    }
    metrics = {}
    for name, (kind, unit) in definitions.items():
        if metric_spec is not None and metric_spec.name not in (kind, name):
            continue
        spec = metric_spec or MetricSpec(kind, unit, 'three_module_v1', '')
        try:
            if spec.unit != unit or spec.definition_version != 'three_module_v1':
                raise NotImplementedError(f'unsupported requested definition: {spec}')
            value = float(evaluate_metric(result, name))
            if not np.isfinite(value):
                raise ValueError('native evidence produced a non-finite metric')
            metrics[name] = MetricValue(value, spec)
        except (KeyError, TypeError) as error:
            metrics[name] = MetricValue(None, spec, 'insufficient_data', f'missing or incomplete evidence: {error}')
        except NotImplementedError as error:
            metrics[name] = MetricValue(None, spec, 'unsupported', str(error))
        except (ValueError, IndexError) as error:
            metrics[name] = MetricValue(None, spec, 'invalid', str(error))
    if metric_spec is not None and not metrics:
        metrics[metric_spec.name] = MetricValue(None, metric_spec, 'unsupported', 'unknown metric')
    return PerformanceResult(str(uuid4()), result.result_id, metrics, evaluate_qualification(result, metrics))
