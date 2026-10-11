"""ctypes callbacks shared by the native model-h and temperature drivers."""
import ctypes as ct


_Cancel = ct.CFUNCTYPE(ct.c_int, ct.c_void_p)
_Progress = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_size_t, ct.c_size_t)


class _Callbacks(ct.Structure):
    _fields_ = [('cancel', _Cancel), ('progress', _Progress), ('context', ct.c_void_p)]


def make_callbacks(cancel_check, progress):
    """Keep callback failures local to the call for re-raising after native return."""
    callback_errors = []

    @_Cancel
    def cancelled(_):
        if callback_errors:
            return 1
        try:
            return int(cancel_check()) if cancel_check is not None else 0
        except BaseException as error:
            callback_errors.append(error)
            return 1

    @_Progress
    def progressed(_, done, total):
        if callback_errors:
            return
        try:
            progress(done, total)
        except BaseException as error:
            callback_errors.append(error)

    return _Callbacks(cancelled, progressed if progress is not None else _Progress(), None), callback_errors
