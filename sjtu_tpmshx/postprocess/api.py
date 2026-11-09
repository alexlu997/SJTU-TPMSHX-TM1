"""Own engineering evaluation from stored field evidence."""
from functools import cache, partial
from uuid import uuid4

import numpy as np

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.metric_spec import MetricSpec, full_metric_version
from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult
from sjtu_tpmshx.domain.persistence_validation import validate_result_declarations
from . import metrics as metric_functions
from .applicability import evaluate_applicability  # noqa: F401
from .physical_balance import evaluate_physical_balance  # noqa: F401
from .qualification import evaluate_qualification  # noqa: F401


def evaluate(result: FieldResult, metric_spec: MetricSpec | None = None) -> PerformanceResult:
    """Compute core metrics; missing evidence stays explicitly unavailable."""
    dimension = validate_result_declarations(result)
    if dimension not in (2, 3):
        raise ValueError('postprocessing requires physical dimension 2 or 3')
    mode = result.metadata.get('mode', 'full')
    if mode not in ('full', 'quick_design'):
        raise ValueError(f'unsupported postprocessing mode: {mode!r}')
    definitions = {
        'Q': ('Q', 'W/m'), 'dP_A': ('dP', 'Pa'), 'dP_B': ('dP', 'Pa'),
        'T_out_A': ('T_out', 'K'), 'T_out_B': ('T_out', 'K'),
        'mass_flow_A': ('mass_flow', 'kg/(s m)'), 'mass_flow_B': ('mass_flow', 'kg/(s m)'),
        'mass_imbalance_rel_A': ('mass_imbalance_rel', '1'),
        'mass_imbalance_rel_B': ('mass_imbalance_rel', '1'),
        'energy_imbalance_rel': ('energy_imbalance_rel', '1'), 'mass': ('mass', 'kg/m'),
    }
    if dimension == 3:
        definitions.update(Q=('Q', 'W'), mass=('mass', 'kg'),
                           mass_flow_A=('mass_flow', 'kg/s'), mass_flow_B=('mass_flow', 'kg/s'))
    if result.metadata.get('mode') == 'quick_design':
        from .quick_design import DEFINITIONS
        definitions.update(DEFINITIONS)
    full_compute = mode == 'full'
    duty = mass_flow = None
    if full_compute:
        # One evaluation owns these lazy reductions. A/B and coarse/fine stay
        # separate; failed reductions still reach each metric's error handling.
        if dimension == 3:
            from .three_d import thermal_duty, _mass_flow as mass_flow_3d
            duty = cache(partial(thermal_duty, result))
            mass_flow = cache(partial(mass_flow_3d, result))
        else:
            duty = cache(partial(metric_functions._side_duty, result))
            mass_flow = cache(partial(metric_functions._mass_flow, result))
        unit = definitions['Q'][1]
        definitions.update({name: (name, unit) for name in ('Q_A', 'Q_B')})
        definitions.update({name: ('P_out', 'Pa') for name in ('P_out_A', 'P_out_B')})
        if dimension == 2:
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
        'P_out_A': 'Absolute pressure at the physical outlet face, weighted by geometric opening area.',
        'P_out_B': 'Absolute pressure at the physical outlet face, weighted by geometric opening area.',
    }
    metrics = {}
    for name, (kind, unit) in definitions.items():
        if metric_spec is not None and metric_spec.name not in (kind, name):
            continue
        version = full_metric_version(name) if full_compute else 'three_module_v1'
        spec = metric_spec or MetricSpec(kind, unit, version, descriptions.get(name, '') if full_compute else '')
        try:
            if spec.unit != unit or spec.definition_version != version:
                raise NotImplementedError(f'unsupported requested definition: {spec}')
            value = float(metric_functions._evaluate_metric(result, name, dimension=dimension, duty=duty, mass_flow=mass_flow))
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
    from .qualification import evaluate_qualification as qualify
    return PerformanceResult(str(uuid4()), result.result_id, metrics,
                             qualify(result, metrics))
