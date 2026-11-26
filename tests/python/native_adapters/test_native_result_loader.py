"""Check lazy result loading, float64/int32 normalization, and fixed warning rules."""
import ctypes as ct
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.cpp_interface import _native_result as native
from sjtu_tpmshx.cpp_interface import stage_libraries


ROOT = Path(__file__).resolve().parents[3]


class LibraryStub(SimpleNamespace):
    def __getitem__(self, name):
        return getattr(self, name)


def test_cold_import_and_archived_result_read_do_not_load_native_code(tmp_path):
    from sjtu_tpmshx.data_types.field_result import FieldResult
    from sjtu_tpmshx.file_io.result_io import save_result

    grid = dict(dimension=2, length_unit='m', axis_order=('x', 'y'),
                dx=np.array([.1]), dy=np.array([.2]),
                x_edges=np.array([0., .1]), y_edges=np.array([0., .2]))
    result = FieldResult('archived-result', 'case', 'cpp', grid=grid,
        fields={'Ta': np.array([[310.]])},
        field_metadata={'Ta': dict(unit='K', axes=('x', 'y'), location='cell', state='raw last return')},
        run_status={'execution': 'completed', 'converged': False}, metadata={'dimension': 2})
    path = save_result(result, tmp_path / 'archived.h5')
    environment = dict(os.environ, TPMSHX_RESULT_LIBRARY=str(tmp_path / 'absent-result-image'))
    child = subprocess.run([sys.executable, '-c', r'''
import ctypes
import sys
import h5py
import numpy


def forbidden(*args, **kwargs):
    raise AssertionError('a cold import or file read attempted CDLL loading')


ctypes.CDLL = forbidden
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.cpp_interface import _native_result as native
from sjtu_tpmshx.file_io.result_io import load_result
result = load_result(sys.argv[1])
assert result.result_id == 'archived-result'
assert result.fields['Ta'][0, 0] == 310.
assert result.run_status['converged'] is False
assert native.result_library.load.cache_info().currsize == 0
for prefix in ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess',
               'CoolProp', 'PySide6', 'PyQt5', 'PyQt6'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
''', str(path)], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stdout + child.stderr


@pytest.mark.parametrize('system,machine,host,name', [
    ('darwin', 'arm64', 'macos-arm64', 'libtpmshx_result_shared.dylib'),
    ('win32', 'AMD64', 'windows-x64', 'tpmshx_result_shared.dll'),
    ('linux', 'x86_64', 'linux-x86_64', 'libtpmshx_result_shared.so'),
])
def test_default_and_frozen_paths_use_only_the_result_image(tmp_path, monkeypatch, system, machine, host, name):
    monkeypatch.delenv('TPMSHX_RESULT_LIBRARY', raising=False)
    monkeypatch.setattr(stage_libraries.sys, 'platform', system)
    monkeypatch.setattr(stage_libraries.platform, 'machine', lambda: machine)
    monkeypatch.setattr(stage_libraries, 'PUBLISHED_LIBRARY_DIR', tmp_path / 'solvers/native/lib')
    monkeypatch.setattr(stage_libraries.sys, 'frozen', False, raising=False)
    selected = tmp_path / 'solvers/native/lib' / host / name
    selected.parent.mkdir(parents=True)
    selected.write_bytes(b'path-selection fixture')
    assert native.result_library.path() == str(selected.resolve())
    frozen = tmp_path / 'bundle/native' / name
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(b'path-selection fixture')
    monkeypatch.setattr(stage_libraries.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(stage_libraries.sys, '_MEIPASS', str(frozen.parent.parent), raising=False)
    assert native.result_library.path() == str(frozen.resolve())


def test_missing_or_empty_override_is_a_deployment_error(tmp_path, monkeypatch):
    monkeypatch.setenv('TPMSHX_RESULT_LIBRARY', str(tmp_path / 'absent'))
    with pytest.raises(OSError, match='prebuilt native result library is missing'):
        native.result_library.get()
    monkeypatch.setenv('TPMSHX_RESULT_LIBRARY', ' ')
    with pytest.raises(RuntimeError, match='must name a prebuilt result library'):
        native.result_library.get()


@pytest.mark.parametrize('version', [0, 1, 2, 4])
def test_abi_mismatch_is_a_runtime_error(monkeypatch, version):
    handle = LibraryStub(tpmshx_result_abi_version_v1=lambda: version)
    monkeypatch.setattr(native.ct, 'CDLL', lambda path: handle)
    with pytest.raises(RuntimeError, match='unsupported native result ABI'):
        native.result_library.open('/prebuilt-result')


def test_missing_symbol_and_load_failure_are_deployment_errors(monkeypatch):
    monkeypatch.setattr(native.ct, 'CDLL', lambda path: LibraryStub())
    with pytest.raises(RuntimeError, match='lacks tpmshx_result_abi_version_v1'):
        native.result_library.open('/prebuilt-result')
    handle = LibraryStub(tpmshx_result_abi_version_v1=lambda: 3)
    monkeypatch.setattr(native.ct, 'CDLL', lambda path: handle)
    owner = native.result_library.open('/prebuilt-result')
    with pytest.raises(RuntimeError, match='lacks a_required_result_symbol'):
        owner.bind('a_required_result_symbol', [])

    def fail(path):
        raise OSError('wrong architecture')

    monkeypatch.setattr(native.ct, 'CDLL', fail)
    with pytest.raises(OSError, match='cannot load prebuilt native result library /prebuilt-result: wrong architecture'):
        native.result_library.open('/prebuilt-result')


def test_float64_array_normalization_preserves_shape_and_nonfinite_values():
    native_source = np.array([[1.25, np.nan], [np.inf, -np.inf]], dtype=np.float64)
    packed = native.array(native_source)
    assert np.shares_memory(packed.owner, native_source)
    assert packed.raw.rank == 2 and tuple(packed.raw.shape[:2]) == (2, 2)
    restored = np.frombuffer(ct.string_at(packed.raw.data, native_source.nbytes), dtype=np.float64).reshape(2, 2)
    np.testing.assert_array_equal(restored, native_source)

    strided = np.arange(24, dtype='>f4').reshape(4, 6)[::-1, ::2]
    packed_strided = native.array(strided)
    assert packed_strided.owner.dtype == np.float64 and packed_strided.owner.flags['C_CONTIGUOUS']
    np.testing.assert_array_equal(packed_strided.owner, strided.astype(np.float64))

    scalar_array = native.array(3.5)
    assert scalar_array.raw.rank == 0 and scalar_array.owner.shape == () and scalar_array.owner[()] == 3.5

    empty = native.array(np.empty((0, 3), dtype=np.float32))
    assert empty.raw.data is None and empty.raw.rank == 2 and tuple(empty.raw.shape[:2]) == (0, 3)


@pytest.mark.parametrize('value', [True, np.bool_(False), np.array([True, False]),
                                   1. + 2.j, np.array([1. + 2.j]), 'text', np.array(['a']),
                                   np.array([1.], dtype=object), None])
def test_float64_array_rejects_non_real_types(value):
    with pytest.raises(TypeError):
        native.array(value)


def test_int32_labels_normalization_and_bounds():
    source = np.array([[0, 2], [-1, 5]], dtype=np.int32)
    packed = native.labels(source)
    assert np.shares_memory(packed.owner, source)
    assert packed.raw.rank == 2 and tuple(packed.raw.shape[:2]) == (2, 2)
    packed_i64 = native.labels(np.array([0, 1, 2], dtype=np.int64)[::-1])
    assert packed_i64.owner.dtype == np.int32 and packed_i64.owner.flags['C_CONTIGUOUS']
    np.testing.assert_array_equal(packed_i64.owner, [2, 1, 0])
    with pytest.raises(ValueError, match='int32'):
        native.labels(np.array([2**31], dtype=np.int64))
    with pytest.raises(ValueError, match='int32'):
        native.labels(np.array([2**31], dtype=np.uint64))


@pytest.mark.parametrize('value', [True, np.array([True]), 1.5, np.array([1.0]),
                                   1. + 2.j, '0', np.array([0], dtype=object)])
def test_int32_labels_reject_non_integer_types(value):
    with pytest.raises(TypeError):
        native.labels(value)


@pytest.mark.parametrize('value,expected', [
    (1.25, 1.25), (3, 3.0), (np.float32(1.5), 1.5), (np.int64(-7), -7.0),
    (np.array(2.25), 2.25), (float('inf'), float('inf')),
])
def test_scalar_normalizes_real_numbers_to_float(value, expected):
    result = native.scalar(value)
    assert type(result) is float and result == expected


def test_scalar_allows_nan_and_rejects_invalid_types():
    assert np.isnan(native.scalar(float('nan')))
    for bad in (True, np.bool_(True), 1. + 2.j, '3.5', None, object(), np.array([1.]), np.array(True)):
        with pytest.raises(TypeError):
            native.scalar(bad)


def test_fixed_warning_rule_ignores_numpy_errstate_and_underflow():
    diagnostics = native._Diagnostics()
    diagnostics.event_count = 2
    diagnostics.events[0].flags, diagnostics.events[0].operation, diagnostics.events[0].scalar = 15, 4, 0
    diagnostics.events[1].flags, diagnostics.events[1].operation, diagnostics.events[1].scalar = 6, 3, 1

    calls = []
    previous_handler = np.geterrcall()
    np.seterrcall(lambda msg, flag: calls.append((msg, flag)))
    try:
        with warnings.catch_warnings(record=True) as emitted, np.errstate(all='raise'):
            warnings.simplefilter('always')
            native.notify(diagnostics, stacklevel=2)
    finally:
        np.seterrcall(previous_handler)

    assert calls == []
    assert [(item.category, str(item.message)) for item in emitted] == [
        (RuntimeWarning, 'divide by zero encountered in divide'),
        (RuntimeWarning, 'overflow encountered in divide'),
        (RuntimeWarning, 'invalid value encountered in divide'),
        (RuntimeWarning, 'overflow encountered in scalar multiply'),
    ]
    assert all(item.filename == __file__ for item in emitted)


def test_wire_fp_events_precede_the_terminal_numeric_cause(monkeypatch):
    class Owner:
        def bind(self, name, signature):
            def fail(*arguments):
                diagnostics = ct.cast(arguments[-3], ct.POINTER(native._Diagnostics)).contents
                diagnostics.event_count = 1
                diagnostics.events[0].flags, diagnostics.events[0].operation = 10, 3
                diagnostics.python_cause = 3
                arguments[-2].value = b'later numerical cause'
                return 4

            return fail

    monkeypatch.setattr(native.result_library, 'get', lambda: Owner())
    with warnings.catch_warnings(record=True) as emitted, np.errstate(all='raise'):
        warnings.simplefilter('always')
        with pytest.raises(ValueError, match='later numerical cause'):
            native.call('named_test_leaf', [])
    assert [str(item.message) for item in emitted] == [
        'overflow encountered in multiply', 'invalid value encountered in multiply']
