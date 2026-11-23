"""Native closure evidence records shared by the full 2D and 3D result views."""
import ctypes as ct


class NuObservation(ct.Structure):
    _fields_ = [('available', ct.c_uint32), ('cells', ct.c_size_t), ('floor_cells', ct.c_size_t)]
    _fields_ += [(name, ct.c_double) for name in ('raw_min', 'raw_max', 're_min', 're_max', 'pr_min', 'pr_max',
                                               'temperature_min', 'temperature_max', 'pressure')]


class RangeObservation(ct.Structure):
    _fields_ = [(name, ct.c_char_p) for name in ('view', 'model', 'topology', 'stage', 'layout')]
    _fields_ += [(name, ct.c_uint32) for name in ('side', 'ndim', 'have_finite')]
    _fields_ += [('shape', ct.c_size_t * 3)]
    _fields_ += [(name, ct.c_size_t) for name in ('minimum_index', 'maximum_index', 'low', 'high', 'size', 'nonfinite')]
    _fields_ += [(name, ct.c_double) for name in ('lower', 'upper', 'minimum', 'maximum')]
