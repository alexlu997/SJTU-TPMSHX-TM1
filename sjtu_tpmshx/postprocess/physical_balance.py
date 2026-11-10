"""Read physical balances from saved solver evidence without solver calls."""
import numpy as np

from sjtu_tpmshx.shared.domain.persistence_validation import validate_result_declarations
from sjtu_tpmshx.shared.result_math import _boundary_face_shape
from sjtu_tpmshx.shared import _native_result_balance as native


_PHASES = ('A', 'B', 'solid')
_FACES = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')


def _finite(value, name):
    from sjtu_tpmshx.shared._native_result_checks import array_checks
    array = np.asarray(value)
    if array.dtype.kind not in 'fiu' or (array.size and not array_checks(array)[0]):
        raise ValueError(f'physical balance requires finite {name}')
    return array


def _norms(residual):
    return native.norms(residual)


def _mass_summary(faces, grid, dimension, units, source):
    if faces is None:
        return dict(status='unavailable', reason='mass faces were not recorded', source=source)
    _boundary_face_shape(faces, dimension, grid)
    faces = [_finite(face, 'mass faces') for face in faces]
    values = native.mass(faces)
    return dict(status='available', source=source, units=units, inflow=values.inflow, outflow=values.outflow,
        residual=native.norm_record(values.residual), scale=values.scale,
        scale_definition='max(total inward mass, total outward mass)',
        relative_net=values.relative_net if values.has_scale else None,
        relative_l1=values.relative_l1 if values.has_scale else None,
        boundary_out=dict(zip(_FACES, values.boundary_out[:dimension * 2])),
        telescoping_error=values.telescoping_error)


def _energy_summary(evidence, grid, dimension, source):
    if evidence is None:
        return dict(status='unavailable', reason='physical energy audit was not recorded', source=source)
    if evidence['definition'] not in ('physical_heat_ledger_v1', 'model_enthalpy_temperature_v1'):
        raise ValueError('unsupported physical heat ledger definition')
    units = 'W/m' if dimension == 2 else 'W'
    if evidence['physical_dimension'] != dimension or evidence['power_units'] != units:
        raise ValueError('heat ledger units or dimension disagree with result')
    complete = evidence['physical_boundary_complete']
    if complete is not None and type(complete) is not bool:
        raise ValueError('heat ledger requires an explicit boundary completeness state')
    if set(evidence['solved']) != set(_PHASES) or any(
            type(value) is not bool for value in evidence['solved'].values()):
        raise ValueError('heat ledger requires solved flags for each phase')
    shape = tuple(len(grid['d' + axis]) for axis in 'xyz'[:dimension])
    if not all(shape):
        raise ValueError('heat ledger requires nonempty physical cells')
    shape3 = shape + ((1,) if dimension == 2 else ())
    phases = {}
    for phase in _PHASES:
        if not evidence['solved'][phase]:
            if any(evidence[key][phase] is not None for key in (
                    'residual', 'advective_out', 'diffusive_out', 'source_integral')):
                raise ValueError('unsolved phase cannot carry a solved energy ledger')
            phases[phase] = dict(status='not_solved')
            continue
        residual = _finite(evidence['residual'][phase], 'energy residual')
        if residual.shape != shape:
            raise ValueError('heat ledger residual shape disagrees with grid')
        row = dict(status='available', residual=_norms(residual))
        source_power = _finite(evidence['source_integral'][phase], 'source integral')
        if source_power.ndim:
            raise ValueError('heat ledger requires scalar source integrals')
        row['source_integral'] = float(source_power)
        for key in ('advective_out', 'diffusive_out'):
            values = evidence[key][phase]
            if set(values) != set(_FACES):
                raise ValueError('heat ledger requires all six boundary planes')
            planes = [_finite(values[name], 'boundary power') for name in _FACES]
            if _boundary_face_shape(planes, 3, planes=True) != shape3:
                raise ValueError('heat ledger boundary shape disagrees with grid')
            values = native.plane_sums(planes)
            row[key] = dict(zip(_FACES, values.values))
            row[key + '_sum'] = values.total
        phases[phase] = row
    reservoir = _finite(evidence['prescribed_b_power'], 'prescribed B power')
    if reservoir.ndim:
        raise ValueError('heat ledger requires scalar prescribed B power')
    reservoir = float(reservoir)
    solved = [row for row in phases.values() if row['status'] == 'available']
    values = native.energy_totals(solved, reservoir)
    boundary = values.boundary_out if solved else 0
    sources = values.source_integral if solved else 0
    residual_sum = values.residual_sum if solved else 0
    for index, row in enumerate(solved):
        norms = row['residual']
        norms.update(l1_relative=values.l1_relative[index],
                     cell_max_relative=values.cell_max_relative[index])
    return dict(status='available', source=source, units=units,
        evidence_definition=evidence['definition'], physical_boundary_complete=complete, phases=phases, boundary_out=boundary,
        source_integral=sources, prescribed_b_power=reservoir,
        net_external_in=values.net_external_in, residual_sum=residual_sum,
        telescoping_error=values.telescoping_error, scale=values.scale,
        scale_definition='max(1 native power unit, abs phase net boundary power, abs phase source, abs reservoir power)',
        relative_external_imbalance=values.relative_external_imbalance)


def evaluate_physical_balance(result):
    """Return signed balances and scales; this function does not grant acceptance."""
    dimension = validate_result_declarations(result)
    if dimension not in (2, 3):
        raise ValueError('physical balances require dimension 2 or 3')
    flux = result.boundary_fluxes
    energy_key = 'energy' if flux.get('energy') is not None else 'temperature'
    mass = {side: _mass_summary(flux.get('mass_' + side), result.grid, dimension,
                               'kg/(s m)' if dimension == 2 else 'kg/s',
                               'boundary_fluxes.mass_' + side)
            for side in ('A', 'B')}
    summary = dict(definition='physical_balance_v1', physical_dimension=dimension,
        state=flux.get('state', 'not_recorded'), outer_index=result.run_status.get('outer_index'),
        mass=mass, energy=_energy_summary(flux.get(energy_key), result.grid, dimension,
                                         'boundary_fluxes.' + energy_key),
        signs=dict(mass='positive divergence is net outward mass',
                   power='positive boundary power is outward; sources and reservoir power are inward',
                   residual='physical RHS minus diagonal times state'))
    fine = flux.get('fine')
    if fine is not None:
        key = 'energy' if fine.get('energy') is not None else 'temperature'
        summary['fine_energy'] = _energy_summary(fine.get(key), fine, dimension,
                                                'boundary_fluxes.fine.' + key)
    return summary
