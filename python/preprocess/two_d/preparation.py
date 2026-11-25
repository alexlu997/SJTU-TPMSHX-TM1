"""Direct 2D preparation entries and their nominal-grid warning source."""
from functools import partial
import warnings

from sjtu_tpmshx.cpp_interface import native_preparation
from .._metadata import prepare_fixed_flow_with_metadata

__all__ = ["prepare_case", "prepare_mass_flow_case", "capacities", "resolve"]


def _nominal_grid_warning(axis, message):
    # The default warning filter uses the line number to distinguish the two axes.
    if axis == 'x':
        warnings.warn(message, RuntimeWarning)
    else:
        warnings.warn(message, RuntimeWarning)


def prepare_case(config, *, case_id):
    return native_preparation.prepare_case(config, case_id=case_id, nominal_grid_warning=_nominal_grid_warning)


def prepare_mass_flow_case(config, targets, *, case_id):
    prepare = partial(native_preparation.prepare_mass_flow_case, nominal_grid_warning=_nominal_grid_warning)
    return prepare_fixed_flow_with_metadata(prepare, config, targets, case_id=case_id)


def capacities(config):
    return native_preparation.capacities(config, nominal_grid_warning=_nominal_grid_warning)


def resolve(config, *, targets=None):
    return native_preparation.resolve(config, targets=targets, nominal_grid_warning=_nominal_grid_warning)
