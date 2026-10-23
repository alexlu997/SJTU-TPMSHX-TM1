"""Owned native 3D runs with the shared typed state binding."""
import ctypes as ct

from .enthalpy import _EnergyOptionsV2
from .model_h import _IterationOptions
from ._full_3d_abi import _Callbacks, _Control, _Input, _Result
from .run_state import NativeRun


class NativeFull3DRun(NativeRun):
    api_prefix = 'tpmshx_full_3d_run'
    creation_version = 3
    advance_name = 'advance_step'
    result_type = _Result

    def __init__(self, library, data, controls, energy, callbacks, *, model_h=None, state=None, cpu_threads=None):
        common = [ct.POINTER(_Input), ct.POINTER(_Control), ct.POINTER(_EnergyOptionsV2),
                  ct.POINTER(_IterationOptions), ct.POINTER(_Callbacks)]
        args = [ct.byref(data), ct.byref(controls), ct.byref(energy) if energy is not None else None,
                ct.byref(model_h) if model_h is not None else None, ct.byref(callbacks)]
        self.creation_version = 2 if cpu_threads is None else 3
        if cpu_threads is not None:
            common.insert(-1, ct.c_size_t)
            args.insert(-1, cpu_threads)
        super().__init__(library, common, args, callbacks, state)
