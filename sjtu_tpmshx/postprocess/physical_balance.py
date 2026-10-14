"""Read physical balances from saved solver evidence without solver calls."""
import numpy as np

from sjtu_tpmshx.domain.persistence_validation import validate_result_declarations
from sjtu_tpmshx.result_math import _boundary_face_shape


_PHASES = ('A', 'B', 'solid')
_FACES = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')


def _finite(value, name):
    array = np.asarray(value)
    if array.dtype.kind not in 'fiu' or not np.all(np.isfinite(array)):
        raise ValueError(f'physical balance requires finite {name}')
    return array


def _norms(residual):
    return dict(signed_sum=float(residual.sum()), l1=float(np.abs(residual).sum()),
                cell_max=float(np.abs(residual).max()), cell_count=int(residual.size))


def _mass_summary(faces, grid, dimension, units, source):
    if faces is None:
        return dict(status='unavailable', reason='mass faces were not recorded', source=source)
    _boundary_face_shape(faces, dimension, grid)
    faces = [_finite(face, 'mass faces') for face in faces]
    outward = [sign * np.take(face, end, axis=axis) for axis, face in enumerate(faces)
               for end, sign in ((0, -1), (-1, 1))]
    inflow, outflow = (sum(float(np.maximum(sign * face, 0.).sum()) for face in outward)
                       for sign in (-1, 1))
    residual = sum(np.diff(face, axis=axis) for axis, face in enumerate(faces))
    norms = _norms(residual)
    scale = max(inflow, outflow)
    return dict(status='available', source=source, units=units, inflow=inflow, outflow=outflow,
        residual=norms, scale=scale, scale_definition='max(total inward mass, total outward mass)',
        relative_net=abs(norms['signed_sum']) / scale if scale else None,
        relative_l1=norms['l1'] / scale if scale else None,
        boundary_out=dict(zip(_FACES, (float(face.sum()) for face in outward))),
        telescoping_error=norms['signed_sum'] - (outflow - inflow))


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
            row[key] = dict(zip(_FACES, (float(face.sum()) for face in planes)))
            row[key + '_sum'] = sum(row[key].values())
        phases[phase] = row
    reservoir = _finite(evidence['prescribed_b_power'], 'prescribed B power')
    if reservoir.ndim:
        raise ValueError('heat ledger requires scalar prescribed B power')
    reservoir = float(reservoir)
    solved = [row for row in phases.values() if row['status'] == 'available']
    boundary = sum(row['advective_out_sum'] + row['diffusive_out_sum'] for row in solved)
    sources = sum(row['source_integral'] for row in solved)
    residual_sum = sum(row['residual']['signed_sum'] for row in solved)
    scale = max(1., abs(reservoir), *(abs(row['advective_out_sum'] + row['diffusive_out_sum'])
                                     for row in solved), *(abs(row['source_integral']) for row in solved))
    for row in solved:
        norms = row['residual']
        norms.update(l1_relative=norms['l1'] / scale,
                     cell_max_relative=norms['cell_max'] * norms['cell_count'] / scale)
    return dict(status='available', source=source, units=units,
        evidence_definition=evidence['definition'], physical_boundary_complete=complete, phases=phases, boundary_out=boundary,
        source_integral=sources, prescribed_b_power=reservoir,
        net_external_in=sources + reservoir - boundary, residual_sum=residual_sum,
        telescoping_error=residual_sum - (sources + reservoir - boundary), scale=scale,
        scale_definition='max(1 native power unit, abs phase net boundary power, abs phase source, abs reservoir power)',
        relative_external_imbalance=abs(sources + reservoir - boundary) / scale)


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
