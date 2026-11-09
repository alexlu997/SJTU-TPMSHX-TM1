"""Single-phase HEOS CO2 properties; independent of the legacy sCO2 range.

No invented constant-property fallback, forced phase or interpolation across
saturation. All actual states must be finite, single phase, above the triple
point; exceptions are propagated with their T/p context. Not a solid-CO2 model.
"""
from __future__ import annotations
from functools import lru_cache
import numpy as np

_KEYS = ('D','V','L','C','H')


@lru_cache(maxsize=1)
def _cp():
    import CoolProp.CoolProp as CP
    return CP


def _states(T,P):
    if P is None:
        raise ValueError('CO2 requires absolute pressure P in Pa')
    t,p=np.broadcast_arrays(np.asarray(T,dtype=float),np.asarray(P,dtype=float))
    if not t.size or not (np.isfinite(t).all() and np.isfinite(p).all()
                         and (t>0).all() and (p>0).all()):
        raise ValueError('CO2 requires finite positive temperature [K] and pressure [Pa(abs)]')
    if (t <= float(_cp().PropsSI('Ttriple','CO2'))).any():
        raise ValueError('CO2 at/below its triple-point temperature is outside this fluid model')
    return t,p


def _evaluate(keys,t,p):
    CP=_cp(); shape=t.shape
    try:
        result=np.asarray(CP.PropsSI(list(keys)+['Phase'],'T',t.ravel(),
                                    'P',p.ravel(),'HEOS::CO2'),dtype=float)
        result=result.reshape(-1,len(keys)+1)
        phases=result[:,-1]
        allowed=[CP.iphase_liquid,CP.iphase_gas,CP.iphase_supercritical,
                 CP.iphase_supercritical_gas,CP.iphase_supercritical_liquid]
        valid=np.isfinite(result).all(axis=1)&np.isin(phases,allowed)
        for j,key in enumerate(keys):
            if key in ('D','V','L','C'):
                valid &= result[:,j]>0
        if not valid.all():
            i=int(np.flatnonzero(~valid)[0])
            raise ValueError(f'unsupported/nonfinite state at T={t.flat[i]:g} K, '
                             f'P_abs={p.flat[i]:g} Pa; phase code={phases[i]:g}')
        return tuple(result[:,j].reshape(shape) for j in range(len(keys)))
    except (ValueError,RuntimeError) as exc:
        raise ValueError('CO2 requires a stable single-phase PT state; '
                         'saturation, two-phase and critical-point states are unsupported. '
                         f'{exc}') from exc


@lru_cache(maxsize=4096)
def _scalar(T,P):
    return tuple(float(v) for v in _evaluate(_KEYS,np.asarray(T),np.asarray(P)))


def co2_prop(keys,T,P):
    """One property -> scalar/array; tuple of keys -> tuple with matching shape."""
    one=isinstance(keys,str); requested=(keys,) if one else tuple(keys)
    if any(k not in _KEYS for k in requested):
        raise ValueError(f'CO2 property keys are {_KEYS}')
    t,p=_states(T,P)
    if t.ndim==0:
        bundle=_scalar(float(t),float(p))
        values=tuple(bundle[_KEYS.index(k)] for k in requested)
    else:
        values=_evaluate(requested,t,p)
    return values[0] if one else values


def check_co2_state(fluid,T,P,*,where='CO2 state'):
    if fluid.strip().lower()!='co2':
        return
    try:
        co2_prop((),T,P)
    except (ValueError,RuntimeError) as exc:
        raise ValueError(f'{where}: {exc}') from exc
