"""Explicit, prebuilt C++ true-h sweeps inside the Python solver backend."""
from __future__ import annotations

import ctypes
import operator
from pathlib import Path

import numpy as np

from sjtu_tpmshx.domain.run_environment import run_environment


def resolve_true_h_kernel(cfg, *, supported):
    """Resolve a frozen run choice once; unsupported/native errors never fall back."""
    name = run_environment(cfg, 'TPMSHX_TRUE_H_KERNEL', 'numba')
    if name == 'numba':
        return None
    if name != 'cpp_sweeps_v1':
        raise ValueError(f'unsupported TPMSHX_TRUE_H_KERNEL: {name!r}')
    if not supported:
        raise ValueError('cpp_sweeps_v1 requires a full two-fluid true-h solve')
    path = run_environment(cfg, 'TPMSHX_THERMAL_LIBRARY')
    if not path:
        raise ValueError('cpp_sweeps_v1 requires TPMSHX_THERMAL_LIBRARY')
    return NativeEnthalpySweeps(path)


class NativeEnthalpySweeps:
    """Borrow validated NumPy buffers for one native sweep chunk; no EOS or gate."""

    def __init__(self, path):
        path = Path(path)
        if not path.is_absolute():
            raise ValueError('TPMSHX_THERMAL_LIBRARY must be an absolute path')
        path = path.resolve(strict=True)
        self._library = ctypes.CDLL(str(path))
        version = self._library.tpmshx_thermal_abi_version
        version.argtypes = []
        version.restype = ctypes.c_uint32
        abi = int(version())
        if abi != 1:
            raise ValueError(f'unsupported thermal library ABI: {abi}; expected 1')
        self._call = self._library.tpmshx_enthalpy_sweeps_v1
        double_p = ctypes.POINTER(ctypes.c_double)
        self._call.argtypes = [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(double_p),
            ctypes.POINTER(ctypes.c_size_t), double_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]
        self._call.restype = ctypes.c_int
        self.metadata = dict(sweep_kernel='cpp_sweeps_v1', thermal_library=str(path),
                             thermal_abi=abi, energy_audit='python')

    def __call__(self, hA, hB, Ts, dhA, dhB, cpA, cpB, TA, TB, hA_star, hB_star,
                 FxA, FyA, FzA, FxB, FyB, FzB, hvA, hvB, Kss, dx, dy, dz,
                 h_in_A, h_in_B, n_sweep, omega, h_lo_A, h_hi_A, h_lo_B, h_hi_B,
                 clip_counts):
        if not isinstance(hA, np.ndarray) or hA.ndim != 3 or min(hA.shape) < 1:
            raise ValueError('native h_A must have a nonempty 3D cell shape')
        shape = hA.shape
        faces = tuple(tuple(n + (axis == i) for i, n in enumerate(shape))
                      for axis in range(3))
        arrays = [dx, dy, dz, hA, hB, Ts,
                  dhA, cpA, TA, hA_star, hvA, FxA, FyA, FzA,
                  dhB, cpB, TB, hB_star, hvB, FxB, FyB, FzB, Kss]
        expected = [*((n,) for n in shape), *([shape] * 3),
                    *([shape] * 5), *faces, *([shape] * 5), *faces, shape]
        for index, (array, wanted) in enumerate(zip(arrays, expected)):
            if (not isinstance(array, np.ndarray) or array.dtype != np.float64
                    or array.shape != wanted or not array.flags.c_contiguous
                    or not array.flags.aligned):
                raise ValueError(f'native array {index} must be aligned C-contiguous float64 with shape {wanted}')
        for index in (3, 4, 5):
            if not arrays[index].flags.writeable:
                raise ValueError('native mutable state must be writable')
            if any(np.shares_memory(arrays[index], array)
                   for other, array in enumerate(arrays) if other != index):
                raise ValueError('native mutable state must not alias other arrays')
        if (not isinstance(clip_counts, np.ndarray) or clip_counts.shape != (2,)
                or clip_counts.dtype != np.int64 or not clip_counts.flags.writeable
                or not clip_counts.flags.c_contiguous):
            raise ValueError('native clip counts must be writable contiguous int64 with shape (2,)')
        if any(np.shares_memory(clip_counts, array) for array in arrays):
            raise ValueError('native clip counts must not alias thermal arrays')
        sweeps = operator.index(n_sweep)
        if not 0 <= sweeps <= ctypes.c_size_t(-1).value:
            raise ValueError('native sweep count is outside size_t range')
        double_p = ctypes.POINTER(ctypes.c_double)
        pointers = (double_p * len(arrays))(*(a.ctypes.data_as(double_p) for a in arrays))
        sizes = (ctypes.c_size_t * len(arrays))(*(a.size for a in arrays))
        dimensions = (ctypes.c_size_t * 3)(*shape)
        scalars = (ctypes.c_double * 7)(h_in_A, h_in_B, h_lo_A, h_hi_A,
                                      h_lo_B, h_hi_B, omega)
        clips = (ctypes.c_uint64 * 2)()
        error = ctypes.create_string_buffer(1024)
        status = self._call(dimensions, pointers, sizes, scalars, sweeps, clips,
                            error, len(error))
        if status:
            exception = {1: ValueError, 2: FloatingPointError}.get(status, RuntimeError)
            raise exception(f'cpp_sweeps_v1 ({status}): {error.value.decode("utf-8", errors="replace")}')
        if max(clips) > np.iinfo(np.int64).max:
            raise OverflowError('native clipping count exceeds int64')
        clip_counts[:] = clips
