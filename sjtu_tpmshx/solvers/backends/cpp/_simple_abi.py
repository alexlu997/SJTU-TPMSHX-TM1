"""SIMPLE callbacks and ctypes layouts from native simple_c_api_types.h.

No preparation, solver equations, convergence decisions or fallback live here.
"""
import ctypes as ct


class _F2(ct.Structure):
    _fields_ = [*[(name, ct.c_double) for name in
        ('momentum_tolerance', 'local_mass_tolerance', 'global_mass_tolerance',
         'backflow_maximum', 'velocity_check_tolerance', 'stall_ratio')],
        *[(name, ct.c_size_t) for name in
          ('confirmations', 'momentum_interval', 'stall_window')]]


_Cancel = ct.CFUNCTYPE(ct.c_int, ct.c_void_p)
_Progress = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_size_t, ct.c_double)


class _Callbacks(ct.Structure):
    _fields_ = [('cancel', _Cancel), ('progress', _Progress), ('context', ct.c_void_p)]


def make_callbacks(cancel_check, progress):
    """Keep callback errors local until the native call returns."""
    callback_errors = []

    @_Cancel
    def cancelled(_):
        if callback_errors:
            return 1
        try:
            return int(bool(cancel_check())) if cancel_check is not None else 0
        except BaseException as error:
            callback_errors.append(error)
            return 1

    @_Progress
    def progressed(_, iteration, residual):
        if callback_errors:
            return
        try:
            progress(iteration, residual)
        except BaseException as error:
            callback_errors.append(error)

    return _Callbacks(
        cancelled if cancel_check is not None or progress is not None else _Cancel(),
        progressed if progress is not None else _Progress(), None), callback_errors


class _Momentum(ct.Structure):
    _fields_ = [('numerator', ct.c_double*3), ('denominator', ct.c_double*3),
                ('component', ct.c_double*3), ('maximum', ct.c_double)]


class _Mass(ct.Structure):
    _fields_ = [*[(name, ct.c_double) for name in
        ('local_residual', 'mass_in', 'mass_out', 'global_residual', 'backflow_fraction')],
        ('counted_cells', ct.c_size_t)]
