"""Owned native 2D runs with the shared typed state binding."""
import ctypes as ct

from sjtu_tpmshx.physical_models.envelope import ChokedFlowError
from sjtu_tpmshx.cpp_interface.solver_library._thermal_abi import _EnergyOptions
from sjtu_tpmshx.cpp_interface.solver_library._thermal_abi import _IterationOptions
from sjtu_tpmshx.cpp_interface.solver_library._full_2d_abi import _Callbacks, _Config, _EnergyControl, _Result
from sjtu_tpmshx.cpp_interface.run_state import NativeRun


class NativeFull2DRun(NativeRun):
    advance_name = 'advance_step'
    api_prefix = 'tpmshx_full_2d_run'
    creation_version = 2
    result_type = _Result
    result_release_name = 'tpmshx_full_2d_release_v2'
    error_types = {**NativeRun.error_types, 4: ChokedFlowError}

    def __init__(self, library, shape, arrays, sizes, config, callbacks, *,
                 cpu_threads, energy=None, energy_control=None, model_h=None, state=None):
        common = [ct.POINTER(ct.c_size_t), ct.POINTER(ct.POINTER(ct.c_double)),
                  ct.POINTER(ct.c_size_t), ct.POINTER(_Config), ct.POINTER(_EnergyOptions),
                  ct.POINTER(_EnergyControl), ct.POINTER(_IterationOptions), ct.c_size_t, ct.POINTER(_Callbacks)]
        args = [shape, arrays, sizes, ct.byref(config), ct.byref(energy) if energy is not None else None,
                ct.byref(energy_control) if energy_control is not None else None,
                ct.byref(model_h) if model_h is not None else None, cpu_threads, ct.byref(callbacks)]
        super().__init__(library, common, args, callbacks, state)
