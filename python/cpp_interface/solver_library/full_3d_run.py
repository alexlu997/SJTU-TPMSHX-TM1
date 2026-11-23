"""Owned native 3D runs with the shared typed state binding."""
import ctypes as ct

from sjtu_tpmshx.cpp_interface.solver_library._thermal_abi import _EnergyOptionsV2
from sjtu_tpmshx.cpp_interface.solver_library._thermal_abi import _IterationOptions
from sjtu_tpmshx.cpp_interface.solver_library._full_3d_abi import _Callbacks, _Control, _Input, _Result
from sjtu_tpmshx.cpp_interface.run_state import NativeRun


class NativeFull3DRun(NativeRun):
    api_prefix = 'tpmshx_full_3d_run'
    creation_version = 3
    advance_name = 'advance_step'
    result_type = _Result
    result_release_name = 'tpmshx_full_3d_release_v1'

    def __init__(self, library, data, controls, energy, callbacks, *, cpu_threads, model_h=None, state=None):
        common = [ct.POINTER(_Input), ct.POINTER(_Control), ct.POINTER(_EnergyOptionsV2),
                  ct.POINTER(_IterationOptions), ct.c_size_t, ct.POINTER(_Callbacks)]
        args = [ct.byref(data), ct.byref(controls), ct.byref(energy) if energy is not None else None,
                ct.byref(model_h) if model_h is not None else None, cpu_threads, ct.byref(callbacks)]
        super().__init__(library, common, args, callbacks, state)
