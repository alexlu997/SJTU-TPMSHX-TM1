"""Owned native 2D runs with the shared typed state binding."""
import ctypes as ct

from sjtu_tpmshx.models.envelope import ChokedFlowError
from .enthalpy import _EnergyOptions
from .model_h import _IterationOptions
from ._full_2d_abi import _Callbacks, _Config, _EnergyControl, _Result
from .run_state import NativeRun


class NativeFull2DRun(NativeRun):
    advance_name = 'advance_step'
    api_prefix = 'tpmshx_full_2d_run'
    creation_version = 2
    result_type = _Result
    error_types = {**NativeRun.error_types, 4: ChokedFlowError}

    def __init__(self, library, shape, arrays, sizes, config, callbacks, *,
                 energy=None, energy_control=None, model_h=None, state=None, cpu_threads=None):
        common = [ct.POINTER(ct.c_size_t), ct.POINTER(ct.POINTER(ct.c_double)),
                  ct.POINTER(ct.c_size_t), ct.POINTER(_Config), ct.POINTER(_EnergyOptions),
                  ct.POINTER(_EnergyControl), ct.POINTER(_IterationOptions), ct.POINTER(_Callbacks)]
        args = [shape, arrays, sizes, ct.byref(config), ct.byref(energy) if energy is not None else None,
                ct.byref(energy_control) if energy_control is not None else None,
                ct.byref(model_h) if model_h is not None else None, ct.byref(callbacks)]
        self.creation_version = 1 if cpu_threads is None else 2
        if cpu_threads is not None:
            common.insert(-1, ct.c_size_t)
            args.insert(-1, cpu_threads)
        super().__init__(library, common, args, callbacks, state)
