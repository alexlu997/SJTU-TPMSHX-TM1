"""Single-phase HEOS CO2 properties; independent of the legacy sCO2 range.

No invented constant-property fallback, forced phase or interpolation across
saturation. All actual states must be finite, single phase, above the triple
point; exceptions are propagated with their T/p context. Not a solid-CO2 model.
"""
from __future__ import annotations
from functools import lru_cache
import numpy as np
from . import _native_properties

_KEYS = ('D','V','L','C','H')


def _states(T,P):
    if P is None:
        raise ValueError('CO2 requires absolute pressure P in Pa')
    t,p=np.broadcast_arrays(np.asarray(T,dtype=float),np.asarray(P,dtype=float))
    try:
        _native_properties.paired_state('co2_validate_pt', t, p)
    except _native_properties.StateError as error:
        raise ValueError(str(error)) from None
    return t,p


def _evaluate(keys,t,p):
    try:
        return _native_properties.co2_pt(tuple(_KEYS.index(key) for key in keys), t, p)
    except _native_properties.StateError as error:
        prefix = ('CO2 requires a stable single-phase PT state; '
                  'saturation, two-phase and critical-point states are unsupported. ')
        text = str(error)
        cause = ValueError(text[len(prefix):] if text.startswith(prefix) else text)
        raise ValueError(text) from cause


@lru_cache(maxsize=4096)
def _scalar(T,P):
    try:
        return _native_properties.co2_scalar_bundle(T, P)
    except _native_properties.StateError as error:
        prefix = ('CO2 requires a stable single-phase PT state; '
                  'saturation, two-phase and critical-point states are unsupported. ')
        text = str(error)
        cause = ValueError(text[len(prefix):] if text.startswith(prefix) else text)
        raise ValueError(text) from cause


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
