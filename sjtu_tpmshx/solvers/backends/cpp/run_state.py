"""Owned native runs and independent typed continuation records."""
import ctypes as ct

import numpy as np

from sjtu_tpmshx.models.fluid_props import WaterStateError


class _Field(ct.Structure):
    _fields_ = [('name', ct.c_char_p), ('type', ct.c_uint32),
                ('data', ct.c_void_p), ('count', ct.c_size_t)]


class _Snapshot(ct.Structure):
    _fields_ = [('fields', ct.POINTER(_Field)), ('count', ct.c_size_t), ('owner', ct.c_void_p)]


_DTYPES = (np.dtype('float64'), np.dtype('uint64'), np.dtype('int64'), np.dtype('uint8'))


class NativeRun:
    """Advance one native boundary at a time. Close each run after use."""

    advance_name = 'advance'
    error_types = {1: ValueError, 2: WaterStateError, 3: FloatingPointError}

    def __init__(self, library, common, args, callbacks, state):
        self.library = library
        self.handle = ct.c_void_p()
        self.callbacks = callbacks
        tail = [ct.POINTER(ct.c_void_p), ct.POINTER(ct.c_char), ct.c_size_t]
        signatures = {
            'create': common + tail,
            'restore': common + [ct.POINTER(_Field), ct.c_size_t] + tail,
            'advance': [ct.c_void_p, ct.POINTER(ct.c_uint32), *tail[-2:]],
            'phase': [ct.c_void_p, ct.POINTER(ct.c_uint32)],
            'snapshot': [ct.c_void_p, ct.POINTER(_Snapshot), *tail[-2:]],
            'take_result': [ct.c_void_p, ct.POINTER(self.result_type), *tail[-2:]],
            'release': [ct.POINTER(ct.c_void_p)],
        }
        try:
            for name, arguments in signatures.items():
                version = self.creation_version if name in ('create', 'restore') else 1
                entry = self.advance_name if name == 'advance' else name
                function = getattr(library, f'{self.api_prefix}_{entry}_v{version}')
                function.argtypes = arguments
                function.restype = None if name == 'release' else ct.c_int
                setattr(self, '_'+name, function)
            self._release_snapshot = library.tpmshx_run_state_release_v1
        except AttributeError as error:
            raise ValueError(f'native library lacks {self.api_prefix} continuation controls v{self.creation_version}') from error
        self._release_snapshot.argtypes = [ct.POINTER(_Snapshot)]
        self._release_snapshot.restype = None
        if state is None:
            self._call(self._create, *args, ct.byref(self.handle))
        else:
            fields, keepalive = self._fields(state)
            self._call(self._restore, *args, fields, len(fields), ct.byref(self.handle))
            del keepalive

    @staticmethod
    def _fields(state):
        fields = (_Field * len(state))()
        keepalive = []
        for index, (name, value) in enumerate(state.items()):
            if not isinstance(name, str) or not name or '\0' in name:
                raise ValueError('native state field names must be nonempty strings without NUL')
            encoded_name = name.encode('utf-8')
            keepalive.append(encoded_name)
            if isinstance(value, str):
                encoded = value.encode('utf-8')
                storage = ct.create_string_buffer(encoded)
                keepalive.append(storage)
                fields[index] = _Field(encoded_name, 4, ct.cast(storage, ct.c_void_p), len(encoded))
            else:
                if not isinstance(value, np.ndarray) or value.ndim != 1 or value.dtype not in _DTYPES:
                    raise ValueError('native state arrays must have one dimension and an exact supported dtype')
                storage = np.require(value, requirements=['C', 'A'])
                keepalive.append(storage)
                fields[index] = _Field(encoded_name, _DTYPES.index(storage.dtype), storage.ctypes.data, storage.size)
        return fields, keepalive

    def _call(self, function, *args):
        error = ct.create_string_buffer(2048)
        code = function(*args, error, len(error))
        if code:
            raise self.error_types.get(code, RuntimeError)(error.value.decode())

    @property
    def phase(self):
        value = ct.c_uint32()
        if self._phase(self.handle, ct.byref(value)):
            raise ValueError('native run is closed')
        return value.value

    def advance(self):
        phase = ct.c_uint32()
        self._call(self._advance, self.handle, ct.byref(phase))
        return phase.value

    def snapshot(self):
        result = _Snapshot()
        self._call(self._snapshot, self.handle, ct.byref(result))
        try:
            fields = {}
            for index in range(result.count):
                field = result.fields[index]
                name = field.name.decode('utf-8')
                if field.type == 4:
                    fields[name] = ct.string_at(field.data, field.count).decode('utf-8')
                elif field.type < len(_DTYPES):
                    dtype = _DTYPES[field.type]
                    if field.count:
                        pointer = ct.cast(field.data, ct.POINTER(np.ctypeslib.as_ctypes_type(dtype)))
                        fields[name] = np.ctypeslib.as_array(pointer, (field.count,)).copy()
                    else:
                        fields[name] = np.empty(0, dtype=dtype)
                else:
                    raise ValueError('native snapshot has an unknown field type')
            return fields
        finally:
            self._release_snapshot(ct.byref(result))

    def take_result(self):
        result = self.result_type()
        self._call(self._take_result, self.handle, ct.byref(result))
        return result

    def close(self):
        self._release(ct.byref(self.handle))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
