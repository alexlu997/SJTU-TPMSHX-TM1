"""Core-mass objective and absolute limits for each operating condition."""
from copy import deepcopy
from dataclasses import replace

import numpy as np

from sjtu_tpmshx.domain.metric_spec import MetricSpec, full_metric_version
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.postprocess.api import evaluate


LIMIT_KEYS = ('Q_min_W', 'dP_A_max_Pa', 'dP_B_max_Pa')
CONSTRAINT_KEYS = ('heat_shortfall', 'pressure_excess_A', 'pressure_excess_B')


def validate_mass_requirements(requirements, condition_ids):
    """Require a density and three positive absolute limits for every condition."""
    required = {'solid_density_kg_m3', 'conditions'}
    if (not isinstance(requirements, dict) or not required <= set(requirements)
            or set(requirements) - required - {'allow_nu_re_extrapolation'}):
        raise ValueError('Mass requirements need solid_density_kg_m3 and conditions')
    if type(requirements.get('allow_nu_re_extrapolation', False)) is not bool:
        raise ValueError('allow_nu_re_extrapolation must be a boolean')
    density = requirements['solid_density_kg_m3']
    limits = requirements['conditions']
    if (type(density) not in (int, float) or not np.isfinite(density) or density <= 0):
        raise ValueError('solid_density_kg_m3 must be finite and positive')
    if not isinstance(limits, dict) or set(limits) != set(condition_ids):
        raise ValueError('Mass requirements must match all condition IDs')
    for name, row in limits.items():
        if not isinstance(row, dict) or set(row) != set(LIMIT_KEYS):
            raise ValueError(f'{name}: require Q_min_W, dP_A_max_Pa and dP_B_max_Pa')
        if any(type(value) not in (int, float) or not np.isfinite(value) or value <= 0
               for value in row.values()):
            raise ValueError(f'{name}: all performance limits must be finite and positive')
    return deepcopy(requirements)


def mass_observation(summaries, requirements):
    """Use qualified native metrics and retain each condition's constraint margin."""
    checks = {}
    mass = None
    for name, limits in requirements['conditions'].items():
        summary = summaries[name]
        config = summary['config_snapshot']
        dimension = 3 if config['solver']['Nz'] > 1 else 2
        depth = 1. if dimension == 3 else config['geometry']['Lz_m']
        if depth is None or not np.isfinite(depth) or depth <= 0:
            raise ValueError('2D core mass and total heat require positive Lz_m')
        actual = []
        for metric_name, unit, scale in (('Q_B', 'W' if dimension == 3 else 'W/m', -depth),
                                         ('dP_A', 'Pa', 1.), ('dP_B', 'Pa', 1.)):
            metric = summary['performance'].metrics[metric_name]
            if (metric.status != 'available' or metric.value is None
                    or not np.isfinite(metric.value) or metric.spec.unit != unit
                    or metric.spec.definition_version != full_metric_version(metric_name)):
                raise ValueError(f'{name}: {metric_name} needs a current available native metric')
            actual.append(metric.value * scale)
        bounds = [limits[key] for key in LIMIT_KEYS]
        residuals = [1.-actual[0]/bounds[0], actual[1]/bounds[1]-1., actual[2]/bounds[2]-1.]
        checks[name] = dict(Q_W=actual[0], dP_A_Pa=actual[1], dP_B_Pa=actual[2],
                            residuals=residuals, feasible=all(value <= 0 for value in residuals))
        if 'acceptance' in summary:
            checks[name]['acceptance'] = summary['acceptance']
        if mass is None:
            field = load_result(summary['result_file'])
            metadata = mutable_data(field.metadata)
            metadata['solid_density_kg_m3'] = requirements['solid_density_kg_m3']
            metric = evaluate(replace(field, metadata=metadata),
                              MetricSpec('mass', 'kg' if dimension == 3 else 'kg/m')).metrics['mass']
            if metric.status != 'available' or metric.value is None:
                raise ValueError(f'Core mass unavailable: {metric.reason}')
            mass = float(metric.value * depth)
    residuals = np.max([row['residuals'] for row in checks.values()], axis=0).tolist()
    if mass is None or mass <= 0 or not np.isfinite([mass, *residuals]).all():
        raise ValueError('Core mass and constraint residuals must be finite; mass must be positive')
    objectives = dict(core_mass_kg=mass, **dict(zip(CONSTRAINT_KEYS, residuals)))
    return objectives, checks


def model_observation(objectives, *, constrained):
    """Return maximized objectives and nonpositive feasible constraint outputs."""
    if constrained:
        return [-float(objectives['core_mass_kg']),
                *(float(objectives[key]) for key in CONSTRAINT_KEYS)]
    return [float(objectives['heat_gain_percent']), -float(objectives['pressure_ratio'])]
