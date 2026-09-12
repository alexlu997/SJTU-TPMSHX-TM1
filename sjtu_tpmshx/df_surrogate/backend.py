"""Cached access to the supported fixed water+sCO2 CFD model.

The gamma/RBF research backends are archived in docs/history/legacy-models.md.
A replacement or default change still requires Shanghai 3D and D76 gates;
training-domain error alone does not establish end-to-end applicability.
"""
from functools import lru_cache

METHOD = 'cfd_full_core_3cell_fixed_v2'


def available_methods() -> tuple[str, ...]:
    return (METHOD,)


@lru_cache(maxsize=None)
def get_backend(tpms_type: str, method: str):
    if method != METHOD:
        raise ValueError(f"unknown DF method {method!r}; valid: {available_methods()}")
    from .full_core_3cell_fixed_v2 import FullCore3CellFixedDFV2
    return FullCore3CellFixedDFV2(tpms_type)
