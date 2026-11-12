"""Use the published result C ABI in raw primitive regression tests."""
import ctypes as ct

from sjtu_tpmshx.shared import _native_result as core

_D = ct.c_double
_AP = ct.POINTER(core._Array)
_DP = ct.POINTER(_D)


def _call(name, argtypes, *arguments):
    return core.call(f'tpmshx_result_{name}_v1', argtypes, *arguments)


def _packed(values):
    owners = [core.array(value) for value in values]
    return owners, (core._Array * len(owners))(*(item.raw for item in owners))


def boundary_mass(faces, dimension):
    owners, packed = _packed(faces)
    output = (ct.c_double * 2)()
    _call('boundary_mass_' + str(dimension) + 'd', [_AP, _DP], packed, output)
    return tuple(output)


def solid_mass(epsilon, density, widths):
    source, factor = core.array(epsilon), core.array(density)
    grid = [core.array(value) for value in widths]
    output = ct.c_double()
    _call('solid_mass_' + str(len(widths)) + 'd', [_AP, _AP] + [_AP] * len(grid) + [_DP],
          ct.byref(source.raw), ct.byref(factor.raw), *(ct.byref(item.raw) for item in grid), ct.byref(output))
    return output.value


def duty_magnitude(duty):
    output = ct.c_double()
    _call('duty_magnitude', [ct.c_double, _DP], duty, ct.byref(output))
    return output.value

class _Norms(ct.Structure):
    _fields_ = [('signed_sum', _D), ('l1', _D), ('cell_max', _D), ('cell_count', core._Size)]


class _Planes(ct.Structure):
    _fields_ = [('values', _D * 6), ('total', _D)]


def norm_record(value):
    return dict(signed_sum=value.signed_sum, l1=value.l1,
                cell_max=value.cell_max, cell_count=value.cell_count)


def norms(value):
    owner, output = core.array(value), _Norms()
    _call('balance_norms', [_AP, ct.POINTER(_Norms)], ct.byref(owner.raw), ct.byref(output))
    return norm_record(output)


def plane_sums(planes):
    owners = [core.array(plane) for plane in planes]
    inputs = (core._Array * len(owners))(*(owner.raw for owner in owners))
    output = _Planes()
    _call('balance_planes', [_AP, core._Size, ct.POINTER(_Planes)], inputs, len(owners), ct.byref(output))
    return output
