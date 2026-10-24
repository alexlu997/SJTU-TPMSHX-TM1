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
_LIMIT_METRICS = {
    'Q_min_W': ('Q_B', 'W', 'heat_shortfall', True),
    'dP_A_max_Pa': ('dP_A', 'Pa', 'pressure_excess_A', False),
    'dP_B_max_Pa': ('dP_B', 'Pa', 'pressure_excess_B', False),
    'T_out_A_min_K': ('T_out_A', 'K', 'outlet_temperature_shortfall_A', True),
    'T_out_A_max_K': ('T_out_A', 'K', 'outlet_temperature_excess_A', False),
    'T_out_B_min_K': ('T_out_B', 'K', 'outlet_temperature_shortfall_B', True),
    'T_out_B_max_K': ('T_out_B', 'K', 'outlet_temperature_excess_B', False),
    'P_out_A_min_Pa': ('P_out_A', 'Pa', 'outlet_pressure_shortfall_A', True),
    'P_out_A_max_Pa': ('P_out_A', 'Pa', 'outlet_pressure_excess_A', False),
    'P_out_B_min_Pa': ('P_out_B', 'Pa', 'outlet_pressure_shortfall_B', True),
    'P_out_B_max_Pa': ('P_out_B', 'Pa', 'outlet_pressure_excess_B', False),
}


def constraint_keys(requirements):
    """Keep the requested model outputs in a fixed order."""
    selected = set().union(*(row for row in requirements['conditions'].values()))
    return tuple(spec[2] for key, spec in _LIMIT_METRICS.items() if key in selected)


def mass_lower_bound(config, field_spec, density, control_count):
    """Use the selected geometry model to bound mass for every clipped field."""
    from sjtu_tpmshx.models import co2_correlations, tpms_geometry

    geometry = config.geometry
    depth = geometry.Lz_m
    if depth is None or not np.isfinite(depth) or depth <= 0:
        raise ValueError('Core mass requires a positive physical depth')
    model = co2_correlations if co2_correlations.uses_co2(config) else tpms_geometry
    point = model.minimum_solid_geometry(geometry.tpms,
        field_spec['L_bounds'], field_spec['t_bounds'])
    mass = density * geometry.L_dom_m * geometry.H_dom_m * depth * (1. - point['epsilon'])
    return dict(mass_kg=float(mass), geometry_model=model.__name__.rsplit('.', 1)[-1],
                x_decision=[point['L_mm']]*control_count + [point['t_mm']]*control_count)


def validate_mass_requirements(requirements, condition_ids):
    """Require positive limits and ordered optional outlet ranges."""
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
        if (not isinstance(row, dict) or not set(LIMIT_KEYS) <= set(row)
                or set(row) - _LIMIT_METRICS.keys()):
            raise ValueError(f'{name}: require Q_min_W, dP_A_max_Pa and dP_B_max_Pa')
        if any(type(value) not in (int, float) or not np.isfinite(value) or value <= 0
               for value in row.values()):
            raise ValueError(f'{name}: all performance limits must be finite and positive')
        for quantity, unit in (('T_out', 'K'), ('P_out', 'Pa')):
            for side in 'AB':
                lower, upper = (f'{quantity}_{side}_{kind}_{unit}' for kind in ('min', 'max'))
                if lower in row and upper in row and row[lower] > row[upper]:
                    raise ValueError(f'{name}: {lower} must not exceed {upper}')
    return deepcopy(requirements)


def mass_observation(summaries, requirements):
    """Use qualified native metrics and retain each condition's constraint margin."""
    checks = {}
    mass = None
    all_residuals = {key: [] for key in constraint_keys(requirements)}
    for name, limits in requirements['conditions'].items():
        summary = summaries[name]
        config = summary['config_snapshot']
        dimension = 3 if config['solver']['Nz'] > 1 else 2
        depth = 1. if dimension == 3 else config['geometry']['Lz_m']
        if depth is None or not np.isfinite(depth) or depth <= 0:
            raise ValueError('2D core mass and total heat require positive Lz_m')
        actual, residuals, names = {}, [], []
        for key, (metric_name, unit, residual_name, minimum) in _LIMIT_METRICS.items():
            if key not in limits:
                continue
            output_name = 'Q_W' if metric_name == 'Q_B' else f'{metric_name}_{unit}'
            scale = -depth if metric_name == 'Q_B' else 1.
            if metric_name == 'Q_B' and dimension == 2:
                unit = 'W/m'
            metric = summary['performance'].metrics[metric_name]
            if (metric.status != 'available' or metric.value is None
                    or not np.isfinite(metric.value) or metric.spec.unit != unit
                    or metric.spec.definition_version != full_metric_version(metric_name)):
                raise ValueError(f'{name}: {metric_name} needs a current available native metric')
            value = metric.value * scale
            actual[output_name] = value
            residual = 1.-value/limits[key] if minimum else value/limits[key]-1.
            residuals.append(residual)
            names.append(residual_name)
            all_residuals[residual_name].append(residual)
        checks[name] = dict(actual, residuals=residuals, feasible=all(value <= 0 for value in residuals))
        if len(names) > len(CONSTRAINT_KEYS):
            checks[name]['constraint_keys'] = names
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
    worst = {key: max(values) for key, values in all_residuals.items()}
    if mass is None or mass <= 0 or not np.isfinite([mass, *worst.values()]).all():
        raise ValueError('Core mass and constraint residuals must be finite; mass must be positive')
    objectives = dict(core_mass_kg=mass, **worst)
    return objectives, checks


def model_observation(objectives, *, constrained, constraint_names=CONSTRAINT_KEYS):
    """Return maximized objectives and nonpositive feasible constraint outputs."""
    if constrained:
        return [-float(objectives['core_mass_kg']),
                *(float(objectives[key]) for key in constraint_names)]
    return [float(objectives['heat_gain_percent']), -float(objectives['pressure_ratio'])]
