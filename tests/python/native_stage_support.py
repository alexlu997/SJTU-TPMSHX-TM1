"""Shared configurations and checks for the native stage run tests."""
import ctypes as ct
import json

import numpy as np

from tm1.cpp_interface import _native_result
from tests.python import result_stage_fixture as report
from tests.python.native_preparation_abi import (
    _configuration_3d, _configuration_continuous, _configuration_continuous_3d, _configuration_fluids,
    _configuration_spatial_3d,
)
from tests.python.native_adapters.test_native_prepare_adapter import _same


def plane_configuration(pair):
    """Return a uniform 2D configuration with a hotter side A inlet."""
    config = _configuration_fluids('Gyroid', pair)
    config.fluid_A.T_in_K += 10.
    return config


def continuous_plane_configuration(pair):
    """Return a continuous-field 2D configuration with a hotter side A inlet."""
    config = _configuration_continuous(pair=pair)
    config.flags.port_wall_refine = False
    config.fluid_A.T_in_K += 10.
    return config


def bound_plane_controls(config):
    """Limit the 2D iterations so that each stage run stays short."""
    config.solver.max_iter_simple, config.solver.max_outer_ltne = 12, 2
    if any(getattr(config, 'fluid_' + side).type in ('co2', 'sco2') for side in 'AB'):
        config.solver.max_iter_simple = None
        config.solver.ltne_enthalpy_outer = 9
    else:
        config.solver.model_h_max_iterations = 9
        config.solver.model_h_temperature_tol_K = .5
        config.solver.model_h_q_relative_tol = 1e-3


def volume_configuration(pair=('air', 'water'), layout='uniform'):
    """Return a bounded 3D configuration for one prepared design layout."""
    if layout in ('xy', 'xyz'):
        config = _configuration_continuous_3d(pair=pair, nz=3 if layout == 'xyz' else None)
    elif layout in ('grid', 'asymmetric'):
        config = _configuration_spatial_3d(pair=pair, spatial=layout == 'grid',
                                           delta=.12 if layout == 'asymmetric' else 0.)
    else:
        config = _configuration_3d(pair=pair)
    if layout == 'fixed':
        config.fluid_A.mass_flow_kg_s, config.fluid_B.mass_flow_kg_s = .002, .02
    config.flags.port_wall_refine = False
    config.solver.max_iter_simple, config.solver.max_outer_ltne = 12, 2
    if any(name in ('sco2', 'co2') for name in pair):
        config.solver.ltne_enthalpy_outer = 9
    else:
        config.solver.model_h_max_iterations = 9
        config.solver.model_h_temperature_tol_K = .5
        config.solver.model_h_q_relative_tol = 1e-3
    return config


def evaluate_evidence(evidence):
    """Evaluate stage evidence through the independent result library."""
    library = _native_result.result_library.get().library
    function = library.tpmshx_result_stage_evaluate_v1
    function.argtypes = [ct.POINTER(report.Evidence), ct.POINTER(report.Spec),
        ct.POINTER(report.Output), ct.POINTER(ct.c_char), ct.c_size_t]
    function.restype = ct.c_int
    output, error = report.Output(struct_size=ct.sizeof(report.Output)), ct.create_string_buffer(4096)
    status = function(ct.byref(evidence), None, ct.byref(output), error, len(error))
    assert status == 0, error.value.decode()
    try:
        return json.loads(output.json)
    finally:
        release = library.tpmshx_result_stage_release_v1
        release.argtypes = [ct.POINTER(report.Output)]
        release.restype = None
        release(ct.byref(output))


def plane_state_equal(actual, expected):
    """Compare two 2D continuation records bit for bit."""
    assert actual.keys() == expected.keys()
    for key, value in expected.items():
        if isinstance(value, str):
            assert actual[key] == value, key
        else:
            assert actual[key].dtype == value.dtype, key
            np.testing.assert_array_equal(actual[key].view(np.uint8), value.view(np.uint8), err_msg=key)


def volume_state_equal(actual, expected):
    """Compare two 3D continuation records. Timing records only stay nonnegative."""
    assert actual.keys() == expected.keys()
    for key, value in expected.items():
        if key.endswith(('.linear.build_seconds', '.linear.solve_seconds')):
            assert actual[key].dtype == value.dtype and actual[key].shape == value.shape
            assert np.all(actual[key] >= 0) and np.all(value >= 0)
        else:
            _same(actual[key], value, key)
