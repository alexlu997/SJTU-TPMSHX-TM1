"""Direct 2D preparation entries and their nominal-grid warning source."""
import warnings

from sjtu_tpmshx.cpp_interface.native_preparation import (
    prepare_case, prepare_mass_flow_case as _prepare_native_mass_flow_case, capacities, resolve,
)


__all__ = ["prepare_case", "prepare_mass_flow_case", "capacities", "resolve"]


def _nominal_grid_warning(axis, message):
    if axis == 'x':
        warnings.warn(message, RuntimeWarning)
    else:
        warnings.warn(message, RuntimeWarning)


def prepare_mass_flow_case(config, targets, *, case_id):
    from sjtu_tpmshx.preprocess.api import _prepare_fixed_flow_with_metadata

    return _prepare_fixed_flow_with_metadata(
        _prepare_native_mass_flow_case, config, targets, case_id=case_id)
