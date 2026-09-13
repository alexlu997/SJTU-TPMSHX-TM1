"""Physical screening metrics from native archived fields, without objective shaping."""
import numpy as np


def pressure_drop(pressure):
    p = np.asarray(pressure['P_gauge_Pa'])
    inlet, outlet = np.asarray(pressure['inlet_fraction']), np.asarray(pressure['outlet_fraction'])
    if p.ndim == 3:
        area = np.asarray(pressure['dx_m'])[:, None] * np.asarray(pressure['dz_m'])[None, :]
        inlet, outlet = inlet * area, outlet * area
        mi, mo = inlet > 0., outlet > 0.
        if not (mi.any() and mo.any()):
            return 0.
        return float(np.average(p[:, 0, :][mi], weights=inlet[mi]) - np.average(p[:, -1, :][mo], weights=outlet[mo]))
    mi, mo = inlet > .01, outlet > .5
    if not (mi.any() and mo.any()):
        return 0.
    inlet, outlet = inlet * np.asarray(pressure['dx_m']), outlet * np.asarray(pressure['dx_m'])
    return float(np.average(p[mi, 0], weights=inlet[mi]) - np.average(p[mo, -1], weights=outlet[mo]))


def evaluate_metric(result, name):
    if name in ('Q', 'mass'):
        volume = np.asarray(result.grid['dx'])[:, None] * np.asarray(result.grid['dy'])[None, :]
        if result.grid['dimension'] == 3:
            volume = volume[:, :, None] * np.asarray(result.grid['dz'])[None, None, :]
        if name == 'mass':
            return float(np.sum((1. - np.asarray(result.fields['eps_arr'])) * result.metadata['solid_density_kg_m3'] * volume))
        if result.run_status['execution'] == 'rejected':
            raise ValueError(result.run_status['reason'])
        return float(np.sum(np.asarray(result.fields['h_vB_arr']) * (np.asarray(result.fields['Ts']) - np.asarray(result.fields['Tb'])) * volume))
    if name in ('dP_A', 'dP_B'):
        if result.run_status['execution'] == 'rejected':
            raise ValueError(result.run_status['reason'])
        return pressure_drop(result.pressure_evidence[name[-1]])
    raise NotImplementedError(f'screening does not define {name}')
