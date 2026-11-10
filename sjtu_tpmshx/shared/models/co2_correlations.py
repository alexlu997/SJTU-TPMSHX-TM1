"""Single-phase CO2 CFD Nu/geometry with the fixed user-specified factors.

Nu is the supplied segment-2 fit. Drag uses the existing common three-cell
CFD base. The factors are application inputs, not a new experimental fit.
"""
from functools import lru_cache
from pathlib import Path
import warnings

import numpy as np

from . import _native_geometry

from sjtu_tpmshx.shared.configs.model_parameters import (
    load_co2_coefficients, load_model_parameters)

_APPLICATION = load_model_parameters()['co2_application']
_CO2_DATA = load_co2_coefficients()
VERSION = _CO2_DATA['model_version']
APPLICATION_VERSION = _APPLICATION['version']
PRESSURE_MULTIPLIER = _APPLICATION['pressure_multiplier']
NU_MULTIPLIER = _APPLICATION['nu_multiplier']
RE_RANGE = tuple(_CO2_DATA['bounds']['Re'])
del _CO2_DATA, _APPLICATION
DATA_PATH = Path(__file__).resolve().parents[1] / 'configs' / 'co2_segment2_v1.json'


@lru_cache(maxsize=1)
def coefficients():
    return load_co2_coefficients(DATA_PATH)


def _topology(tpms):
    if tpms not in ('Diamond', 'Gyroid'):
        raise ValueError('CO2 supports Diamond and Gyroid only')
    return coefficients()['topologies'][tpms]


def _observe(tpms, quantity, values, bounds):
    from sjtu_tpmshx.shared.domain.run_warnings import record_range
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


def geometry(tpms, L_mm, t_mm, k_s=1.):
    """Return the native dimensionless-table geometry at the requested L."""
    from .tpms_props import _resolve_chi_s
    fields = _native_geometry.co2_fields(tpms, L_mm, t_mm, k_s, chi_s=_resolve_chi_s())
    return {key: fields[key][()]
            for key in ('epsilon', 'epsilon_A', 'epsilon_B', 'D_h', 'A_0', 'K_ss')}


def minimum_solid_geometry(tpms, L_bounds, t_bounds):
    """Find the native bounded minimum with the current material override."""
    from .tpms_props import _resolve_chi_s
    result = _native_geometry.co2_minimum(tpms, L_bounds, t_bounds, chi_s=_resolve_chi_s())
    return dict(L_mm=float(result['L_mm']), t_mm=float(result['t_mm']), epsilon=result['epsilon'])


def uses_co2(config):
    return 'co2' in (config.fluid_A.type, config.fluid_B.type)


def apply_drag(K, cF):
    """Apply the fixed factor once to the common CFD base, on a CO2 side."""
    from sjtu_tpmshx.shared.df_surrogate.experimental_correction import (
        apply_prepared_correction)
    return apply_prepared_correction(K, cF, dict(
        scale_K=1./PRESSURE_MULTIPLIER, scale_F=PRESSURE_MULTIPLIER,
        campaign=APPLICATION_VERSION, scope='CO2-user-fixed', fluid='co2'))


def model_metadata(config):
    if not uses_co2(config):
        return {}
    from sjtu_tpmshx.shared.df_surrogate.predict import SCO2_DF_METHOD
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
