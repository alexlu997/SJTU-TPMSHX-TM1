"""Qualify the NumPy binding without duplicating the native library builder."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.solvers.backends.python import thermal_native
from sjtu_tpmshx.tests.native.test_enthalpy_sweeps import (
    case_data,
    native_library as native_library,
    python_sweeps,
)


@pytest.fixture
def kernel(native_library):
    return thermal_native.NativeEnthalpySweeps(Path(native_library._name))


def _arguments(case, clips, sweeps=5, omega=0.6):
    a, b = case['a'], case['b']
    aa, bb = a['arrays'], b['arrays']
    return [*case['state'], aa[0], bb[0], aa[1], bb[1], aa[2], bb[2], aa[3], bb[3],
            *aa[5:], *bb[5:], aa[4], bb[4], case['kss'], *case['widths'],
            a['hin'], b['hin'], sweeps, omega, *a['bounds'], *b['bounds'], clips]


@pytest.mark.parametrize('shape', [(4, 3, 2), (5, 2, 1)])
def test_binding_matches_numba_with_readonly_shared_coefficients(kernel, shape):
    case = case_data(shape)
    case['b']['arrays'][1] = case['a']['arrays'][1]  # readonly coefficient sharing is valid
    case['a']['bounds'] = (290000., 310000.)
    case['b']['bounds'] = (320000., 330000.)
    for array in [*case['widths'], *case['a']['arrays'], *case['b']['arrays'], case['kss']]:
        array.flags.writeable = False
    expected, expected_clips = python_sweeps(case)
    clips = np.full(2, 99, dtype=np.int64)
    kernel(*_arguments(case, clips))
    np.testing.assert_array_equal(clips, expected_clips)
    assert np.any(clips > 0)
    # Original operator tolerances, fixed before this binding was introduced.
    for actual, target, atol in zip(case['state'], expected, (2e-8, 2e-8, 2e-11)):
        np.testing.assert_allclose(actual, target, rtol=2e-13, atol=atol)


@pytest.mark.parametrize('invalid', ['relative_path', 'missing_library', 'wrong_abi'])
def test_explicit_library_request_is_not_silently_replaced(tmp_path, monkeypatch, invalid):
    if invalid == 'relative_path':
        with pytest.raises(ValueError, match='absolute path'):
            thermal_native.NativeEnthalpySweeps('relative-thermal-library.so')
    elif invalid == 'missing_library':
        with pytest.raises(FileNotFoundError):
            thermal_native.NativeEnthalpySweeps(tmp_path / 'absent.so')
    else:
        library = tmp_path / 'wrong-abi.so'
        library.touch()
        fake = SimpleNamespace(tpmshx_thermal_abi_version=lambda: 2)
        monkeypatch.setattr(thermal_native.ctypes, 'CDLL', lambda path: fake)
        with pytest.raises(ValueError, match='ABI: 2; expected 1'):
            thermal_native.NativeEnthalpySweeps(library)


@pytest.mark.parametrize('invalid', [
    'dtype', 'face_shape', 'noncontiguous', 'unaligned', 'readonly_state',
    'state_alias', 'coefficient_alias', 'clip_alias', 'clip_stride_zero',
    'readonly_clips', 'negative_sweeps',
])
def test_invalid_buffers_are_rejected_before_entering_cpp(kernel, monkeypatch, invalid):
    case = case_data()
    clips = np.full(2, 99, dtype=np.int64)
    args = _arguments(case, clips)
    if invalid == 'dtype':
        args[0] = args[0].astype(np.float32)
    elif invalid == 'face_shape':
        args[11] = np.zeros(case['shape'])
    elif invalid == 'noncontiguous':
        args[0] = np.asfortranarray(args[0])
    elif invalid == 'unaligned':
        original = args[5]
        args[5] = np.ndarray(original.shape, dtype=np.float64,
                             buffer=bytearray(original.nbytes + 1), offset=1)
        args[5][:] = original
        assert args[5].flags.c_contiguous and not args[5].flags.aligned
    elif invalid == 'readonly_state':
        args[1].flags.writeable = False
    elif invalid == 'state_alias':
        args[1] = args[0]
    elif invalid == 'coefficient_alias':
        args[5] = args[0]
    elif invalid == 'clip_alias':
        args[-1] = args[0].view(np.int64).ravel()[:2]
    elif invalid == 'clip_stride_zero':
        args[-1] = np.ndarray((2,), dtype=np.int64,
                              buffer=np.zeros(1, dtype=np.int64), strides=(0,))
    elif invalid == 'readonly_clips':
        clips.flags.writeable = False
    else:
        args[25] = -1
    initial = [array.copy() for array in case['state']]

    def unexpected_native_call(*arguments):
        pytest.fail('invalid input reached the native kernel')

    monkeypatch.setattr(kernel, '_call', unexpected_native_call)
    with pytest.raises(ValueError):
        kernel(*args)
    np.testing.assert_array_equal(clips, [99, 99])
    for actual, target in zip(case['state'], initial):
        np.testing.assert_array_equal(actual, target)


@pytest.mark.parametrize('invalid', ['coefficient', 'overflow'])
def test_cpp_exception_keeps_original_message_and_does_not_fallback(kernel, monkeypatch, invalid):
    case = case_data((1, 1, 1))
    clips = np.full(2, 99, dtype=np.int64)
    if invalid == 'coefficient':
        case['a']['arrays'][1].fill(0.)
        exception, message = ValueError, 'invalid physical coefficient'
    else:
        case['widths'] = tuple(np.array([2.]) for _ in range(3))
        case['a']['arrays'][4].fill(1e308)
        exception, message = FloatingPointError, 'nonfinite fluid sweep equation'
    initial = [array.copy() for array in case['state']]

    def forbidden_fallback(*args, **kwargs):
        pytest.fail('native failure fell back to Numba')

    monkeypatch.setattr('sjtu_tpmshx.solvers.ltne_enthalpy_3d._gs_enthalpy_sweeps_3d',
                        forbidden_fallback)
    with pytest.raises(exception, match=message):
        kernel(*_arguments(case, clips, sweeps=1))
    np.testing.assert_array_equal(clips, [99, 99])
    if invalid == 'coefficient':
        for actual, target in zip(case['state'], initial):
            np.testing.assert_array_equal(actual, target)
    # Arithmetic failure may leave partially updated state; do not consume or retry it.
