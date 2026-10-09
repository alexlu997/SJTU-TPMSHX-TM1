"""Single-phase CO2 CFD Nu/geometry with the fixed user-specified factors.

Nu is the supplied segment-2 fit. Drag uses the existing common three-cell
CFD base. The factors are application inputs, not a new experimental fit.
"""
from functools import lru_cache
import json
from pathlib import Path
import warnings

import numpy as np

VERSION = 'co2-segment2-20261002-v1'
APPLICATION_VERSION = 'co2-fixed-factors-20261009-v1'
PRESSURE_MULTIPLIER = 2.5
NU_MULTIPLIER = 1.28
RE_RANGE = (3000., 60000.)
DATA_PATH = Path(__file__).resolve().parents[1] / 'configs' / 'co2_segment2_v1.json'


@lru_cache(maxsize=1)
def coefficients():
    data = json.loads(DATA_PATH.read_text(encoding='utf-8'))
    if data['model_version'] != VERSION or data['segment'] != 2:
        raise ValueError('CO2 coefficient resource/version mismatch')
    if set(data['topologies']) != {'Diamond', 'Gyroid'}:
        raise ValueError('CO2 requires both supported topologies')
    for model in data['topologies'].values():
        theta = np.asarray(model['Nu']['parameters']['theta'], dtype=float)
        if theta.shape != (5,) or not np.isfinite(theta).all():
            raise ValueError('CO2 Nu requires five finite coefficients')
    return data


def _topology(tpms):
    if tpms not in ('Diamond', 'Gyroid'):
        raise ValueError('CO2 supports Diamond and Gyroid only')
    return coefficients()['topologies'][tpms]


def _observe(tpms, quantity, values, bounds):
    from sjtu_tpmshx.domain.run_warnings import record_range
    if record_range(('nu' if quantity == 'Re' else 'nu_pr', 'co2', tpms), values, bounds,
                    label=f'[CO2 Nu extrap] {tpms}', quantity=quantity, unit='-'):
        return
    if np.any((values < bounds[0]) | (values > bounds[1])):
        warnings.warn(f'CO2 {quantity} outside CFD calibration {bounds}; '
                      'extrapolation, not validation.', UserWarning, stacklevel=3)


def nusselt(tpms, Re, Pr, L_mm, Dh_mm):
    """Fixed 1.28 times exp(b0+b1*x+b2*y+b3*z+b4*x*x)."""
    re, pr, cell, dh = np.broadcast_arrays(
        *(np.asarray(v, dtype=float) for v in (Re, Pr, L_mm, Dh_mm)))
    if not all(v.size and np.isfinite(v).all() and (v > 0).all()
               for v in (re, pr, cell, dh)):
        raise ValueError('CO2 closure inputs must be finite and positive')
    _observe(tpms, 'Re', re, RE_RANGE)
    _observe(tpms, 'Pr', pr, coefficients()['bounds']['Pr'])
    b = _topology(tpms)['Nu']['parameters']['theta']
    x, y, z = np.log(re / 1e4), np.log(pr / 2.), np.log((dh / cell) / .5)
    result = NU_MULTIPLIER * np.exp(b[0] + b[1]*x + b[2]*y + b[3]*z + b[4]*x*x)
    return float(result) if result.ndim == 0 else result


@lru_cache(maxsize=2)
def _geometry_table(tpms):
    nodes = _topology(tpms)['geometry_nodes']
    ls = sorted({n['L_mm'] for n in nodes})
    ts = sorted({n['t_mm'] for n in nodes})
    lookup = {(n['L_mm'], n['t_mm']): n for n in nodes}
    if (len(nodes) != len(lookup) or len(lookup) != len(ls)*len(ts)
            or ls != [4., 5., 6., 7., 8.] or ts != [.3, .4, .5, .6]):
        raise ValueError('CO2 geometry requires a complete, unique 5 by 4 grid')
    table = np.empty((len(ls), len(ts), 3))
    for i, length in enumerate(ls):
        for j, wall in enumerate(ts):
            node = lookup[length, wall]
            cell = length * 1e-3
            table[i, j] = (node['epsilon_single'], node['Dh_m']/cell,
                           node['A0_single_per_m']*cell)
    if (not np.isfinite(table).all() or (table <= 0).any()
            or (table[:, :, 0] >= .5).any()):
        raise ValueError('CO2 geometry contains invalid porosity, diameter or area')
    table.setflags(write=False)
    return ls, ts, table


def _bracket(value, nodes):
    value = float(value)
    if not np.isfinite(value) or value < nodes[0]-1e-12 or value > nodes[-1]+1e-12:
        raise ValueError('CO2 geometry requires 4 <= L <= 8 mm and 0.3 <= t <= 0.6 mm; no extrapolation')
    value = min(max(value, nodes[0]), nodes[-1])
    upper = int(np.searchsorted(nodes, value))
    if upper == 0 or abs(value-nodes[upper]) < 1e-12:
        return upper, upper, 0.
    return upper-1, upper, (value-nodes[upper-1])/(nodes[upper]-nodes[upper-1])


def geometry(tpms, L_mm, t_mm, k_s=1.):
    """Interpolate dimensionless CFD geometry, then scale at the requested L."""
    from .tpms_props import chi_s_eff
    ls, ts, table = _geometry_table(tpms)
    i0, i1, wl = _bracket(L_mm, ls)
    j0, j1, wt = _bracket(t_mm, ts)
    e, dh, area = ((1-wt)*((1-wl)*table[i0, j0]+wl*table[i1, j0])
                   + wt*((1-wl)*table[i0, j1]+wl*table[i1, j1]))
    cell = float(L_mm)*1e-3
    return dict(epsilon=2*e, epsilon_A=e, epsilon_B=e, D_h=dh*cell,
                A_0=area/cell, K_ss=chi_s_eff(tpms, 2*e)*(1-2*e)*k_s)


def uses_co2(config):
    return 'co2' in (config.fluid_A.type, config.fluid_B.type)


def apply_drag(K, cF):
    """Apply the fixed factor once to the common CFD base, on a CO2 side."""
    from sjtu_tpmshx.df_surrogate.experimental_correction import (
        apply_prepared_correction)
    return apply_prepared_correction(K, cF, dict(
        scale_K=1./PRESSURE_MULTIPLIER, scale_F=PRESSURE_MULTIPLIER,
        campaign=APPLICATION_VERSION, scope='CO2-user-fixed', fluid='co2'))


def model_metadata(config):
    if not uses_co2(config):
        return {}
    from sjtu_tpmshx.df_surrogate.predict import SCO2_DF_METHOD
    return {'co2': dict(
        version=VERSION, application_version=APPLICATION_VERSION,
        sides=[side for side in ('A', 'B') if getattr(config, 'fluid_'+side).type == 'co2'],
        pressure_model=SCO2_DF_METHOD, pressure_multiplier=PRESSURE_MULTIPLIER,
        scale_K=1./PRESSURE_MULTIPLIER, scale_F=PRESSURE_MULTIPLIER,
        nu_multiplier=NU_MULTIPLIER, nu_floor_multiplier=NU_MULTIPLIER,
        correction_source='fixed user-specified factors; not fitted experimental evidence',
        property_model='HEOS::CO2; single-phase; low-Mach momentum adapter',
        common_geometry='single-side CFD geometry assigned symmetrically to both sides',
        Re_range=list(RE_RANGE), Pr_range=coefficients()['bounds']['Pr'])}


def notices(config):
    if not uses_co2(config):
        return []
    return ['CO2: single-phase HEOS; segment-2 constant-property CFD Nu. '
            'Fixed K=K0/2.5, cF=2.5*cF0, Nu=1.28*Nu_base, including its floor, '
            'on CO2 sides only. These user factors do not establish experimental '
            'accuracy for variable-property heat exchangers or geometry gradients.']
