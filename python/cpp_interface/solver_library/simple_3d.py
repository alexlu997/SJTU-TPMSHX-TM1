"""C layouts shared by the SIMPLE and full 3D calls."""
import ctypes as ct

from ._simple_abi import _F2, _Mass, _Momentum


class _Config(ct.Structure):
    _fields_ = [*[(name, ct.c_size_t) for name in
        ('max_iterations', 'inner_sweeps', 'pressure_rebuild_every')],
        *[(name, ct.c_double) for name in
          ('alpha_velocity', 'alpha_pressure', 'alpha_density',
           'pressure_reference_absolute', 'gas_constant', 'pressure_diagonal_drift')],
        *[(name, ct.c_uint32) for name in
          ('ideal_gas', 'massflux_inlet', 'second_order_upwind',
           'adaptive_pressure_tolerance', 'track_momentum', 'ordering')],
        ('convergence', _F2)]


class _Pressure(ct.Structure):
    _fields_ = [('success', ct.c_uint32), *[(name, ct.c_size_t) for name in
        ('iterations', 'rebuild_count', 'hierarchy_bytes')], ('superlu_info', ct.c_int),
        *[(name, ct.c_double) for name in
          ('rhs_scale', 'relative_residual', 'absolute_residual', 'iterative_relative_residual',
           'pin_max_abs', 'diagonal_drift', 'build_seconds', 'solve_seconds')],
        ('method', ct.c_char*32), ('exit', ct.c_char*64), ('amg_exit', ct.c_char*64),
        ('rebuild_reason', ct.c_char*64), ('detail', ct.c_char*512)]


class _Result(ct.Structure):
    _fields_ = [*[(name, ct.c_uint32) for name in
        ('stop', 'converged', 'post_closure_measured', 'post_closure_certified', 'mass_faces_available')],
        *[(name, ct.c_size_t) for name in ('iterations', 'pressure_clip_hits', 'post_closure_rejections')],
        ('legacy_residual', ct.c_double), ('legacy_reference', ct.c_double),
        ('momentum', _Momentum), ('mass', _Mass), ('pressure', _Pressure)]


_STOPS = {1: 'tol', 2: 'stall', 3: 'max_iter', 4: 'nonfinite', 5: 'cancelled',
          6: 'pressure_failure', 7: 'post_closure'}
