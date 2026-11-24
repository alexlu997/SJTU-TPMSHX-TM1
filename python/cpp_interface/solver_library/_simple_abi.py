"""SIMPLE ctypes layouts from native simple_c_api_types.h.

No preparation, solver equations, convergence decisions or fallback live here.
"""
import ctypes as ct


class _F2(ct.Structure):
    _fields_ = [*[(name, ct.c_double) for name in
        ('momentum_tolerance', 'local_mass_tolerance', 'global_mass_tolerance',
         'backflow_maximum', 'velocity_check_tolerance', 'stall_ratio')],
        *[(name, ct.c_size_t) for name in
          ('confirmations', 'momentum_interval', 'stall_window')]]


class _Momentum(ct.Structure):
    _fields_ = [('numerator', ct.c_double*3), ('denominator', ct.c_double*3),
                ('component', ct.c_double*3), ('maximum', ct.c_double)]


class _Mass(ct.Structure):
    _fields_ = [*[(name, ct.c_double) for name in
        ('local_residual', 'mass_in', 'mass_out', 'global_residual', 'backflow_fraction')],
        ('counted_cells', ct.c_size_t)]
