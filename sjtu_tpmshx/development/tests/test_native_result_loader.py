"""Check lazy result loading, typed storage and NumPy FP policy."""
import ctypes as ct
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import warnings

import numpy as np
import pytest

from sjtu_tpmshx.shared import _native_result as native
from sjtu_tpmshx.shared._native_fp import floating_events


ROOT = Path(__file__).resolve().parents[3]


def test_cold_import_and_archived_result_read_do_not_load_native_code(tmp_path):
    from sjtu_tpmshx.shared.domain.field_result import FieldResult
    from sjtu_tpmshx.shared.io.result_io import save_result

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
from sjtu_tpmshx.shared import _native_result as native
from sjtu_tpmshx.shared.io.result_io import load_result
result = load_result(sys.argv[1])
assert result.result_id == 'archived-result'
assert result.fields['Ta'][0, 0] == 310.
assert result.run_status['converged'] is False
assert native._load_library.cache_info().currsize == 0
assert native._extended_format.cache_info().currsize == 0
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
    monkeypatch.setattr(native.sys, 'platform', system)
    monkeypatch.setattr(native.platform, 'machine', lambda: machine)
    monkeypatch.setattr(native, 'files', lambda package: tmp_path)
    monkeypatch.setattr(native.sys, 'frozen', False, raising=False)
    selected = tmp_path / 'solvers/native/lib' / host / name
    selected.parent.mkdir(parents=True)
    selected.write_bytes(b'path-selection fixture')
    assert native._library_path() == str(selected.resolve())
    frozen = tmp_path / 'bundle/native' / name
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(b'path-selection fixture')
    monkeypatch.setattr(native.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(native.sys, '_MEIPASS', str(frozen.parent.parent), raising=False)
    assert native._library_path() == str(frozen.resolve())


def test_missing_or_empty_override_is_a_deployment_error(tmp_path, monkeypatch):
    monkeypatch.setenv('TPMSHX_RESULT_LIBRARY', str(tmp_path / 'absent'))
    with pytest.raises(OSError, match='prebuilt native result library is missing'):
        native._library()
    monkeypatch.setenv('TPMSHX_RESULT_LIBRARY', ' ')
    with pytest.raises(RuntimeError, match='must name a prebuilt result library'):
        native._library()


@pytest.mark.parametrize('version', [0, 1, 3])
def test_abi_mismatch_is_a_runtime_error(monkeypatch, version):
    handle = SimpleNamespace(tpmshx_result_abi_version_v1=lambda: version)
    monkeypatch.setattr(native.ct, 'CDLL', lambda path: handle)
    with pytest.raises(RuntimeError, match='unsupported native result ABI'):
        native._Library('/prebuilt-result')


def test_missing_symbol_and_load_failure_are_deployment_errors(monkeypatch):
    monkeypatch.setattr(native.ct, 'CDLL', lambda path: SimpleNamespace())
    with pytest.raises(RuntimeError, match='lacks tpmshx_result_abi_version_v1'):
        native._Library('/prebuilt-result')
    handle = SimpleNamespace(tpmshx_result_abi_version_v1=lambda: 2)
    monkeypatch.setattr(native.ct, 'CDLL', lambda path: handle)
    owner = native._Library('/prebuilt-result')
    with pytest.raises(RuntimeError, match='lacks a_required_result_symbol'):
        owner.bind('a_required_result_symbol', [])

    def fail(path):
        raise OSError('wrong architecture')

    monkeypatch.setattr(native.ct, 'CDLL', fail)
    with pytest.raises(OSError, match='cannot load prebuilt native result library /prebuilt-result: wrong architecture'):
        native._Library('/prebuilt-result')


@pytest.mark.parametrize('value,origin', [
    (True, 4), (-(2**63), 3), (2**63 + 1, 3), (1.25, 0), (1. + 2.j, 5),
    (np.int64(-(2**63)), 1), (np.uint64(2**64 - 1), 1), (np.float32(1.25), 1),
    (np.array(2**64 - 1, dtype=np.uint64), 2),
    (np.array(1.25, dtype='>f8'), 2), (np.array(-(2**63), dtype='>i8'), 2),
])
def test_scalar_round_trip_preserves_origin_dtype_and_exact_storage(value, origin):
    packed = native.scalar(value)
    restored = native.restore_scalar(packed)
    assert packed.origin == origin
    assert type(restored) is type(value)
    np.testing.assert_array_equal(restored, value)
    if isinstance(value, np.ndarray):
        assert restored.shape == () and restored.dtype == value.dtype
    elif isinstance(value, np.generic):
        assert restored.dtype == value.dtype
    source = np.asarray(value)
    assert bytes(packed.data[:source.itemsize]) == source.tobytes()


def test_negative_stride_and_endian_array_metadata_round_trip():
    source = np.arange(24, dtype='>i8').reshape(4, 6)[::-1, ::2]
    packed = native.array(source)
    raw = packed.raw
    assert raw.origin == 2 and raw.dtype == 8
    assert raw.rank == 2 and tuple(raw.shape[:2]) == (4, 3)
    assert tuple(raw.strides[:2]) == (-48, 16)
    assert raw.offset == 144 and raw.bytes == 184
    backing = (ct.c_ubyte * raw.bytes).from_address(raw.data)
    restored = np.ndarray((4, 3), dtype='>i8', buffer=backing, offset=raw.offset,
                          strides=tuple(raw.strides[:2]))
    np.testing.assert_array_equal(restored, source)
    assert np.shares_memory(packed.owner, source)


def test_empty_and_broadcast_views_retain_metadata_without_copy():
    empty = native.array(np.empty((0, 3), dtype=np.uint64))
    assert empty.raw.data is None and empty.raw.bytes == 0 and empty.raw.offset == 0
    assert tuple(empty.raw.shape[:2]) == (0, 3) and empty.raw.dtype == 9
    source = np.broadcast_to(np.array(np.uint64(2**63 + 1)), (2, 3))
    packed = native.array(source)
    assert tuple(packed.raw.strides[:2]) == (0, 0) and packed.raw.bytes == 8
    backing = (ct.c_ubyte * 8).from_address(packed.raw.data)
    restored = np.ndarray((2, 3), dtype=np.uint64, buffer=backing, strides=(0, 0))
    np.testing.assert_array_equal(restored, source)


class Log:
    def __init__(self):
        self.lines = []

    def write(self, text):
        self.lines.append(text)


def numpy_events():
    np.divide(np.array([1., 1e308, 1e-308, 0.]), np.array([0., 1e-308, 1e308, 0.]))
    np.multiply(np.array([np.inf, np.finfo(float).max]), np.array([0., 2.]))


def native_events():
    floating_events([(15, 'divide'), (10, 'multiply')], stacklevel=2)


def capture_policy(function, policy, capfd, *, handler=True):
    callbacks, log = [], Log()
    previous_handler = np.geterrcall()
    np.seterrcall((lambda message, flags: callbacks.append((message, flags))) if handler else None)
    if handler and 'log' in policy.values():
        # A single handler supports mixed callback and log policy.
        class Handler:
            def __call__(self, message, flags):
                callbacks.append((message, flags))

            def write(self, text):
                log.write(text)

        np.seterrcall(Handler())
    try:
        capfd.readouterr()
        with warnings.catch_warnings(record=True) as emitted, np.errstate(**policy):
            warnings.simplefilter('always')
            try:
                function()
            except Exception as error:
                result = type(error).__name__, error.args
            else:
                result = None
        captured = capfd.readouterr()
        return (result, [(item.category.__name__, str(item.message)) for item in emitted],
                callbacks, log.lines, captured.out, captured.err)
    finally:
        np.seterrcall(previous_handler)


@pytest.mark.parametrize('mode', ['ignore', 'warn', 'raise', 'call', 'log', 'print'])
def test_numpy_fp_modes_keep_complete_flags_and_operation_order(mode, capfd):
    policy = dict.fromkeys(('divide', 'over', 'under', 'invalid'), mode)
    expected = capture_policy(numpy_events, policy, capfd)
    actual = capture_policy(native_events, policy, capfd)
    assert actual == expected


@pytest.mark.parametrize('policy', [
    dict(divide='call', over='warn', under='ignore', invalid='log'),
    dict(divide='ignore', over='log', under='print', invalid='warn'),
    dict(divide='print', over='log', under='call', invalid='ignore'),
])
def test_mixed_fp_modes_keep_full_callback_mask_and_shared_notice_order(policy, capfd):
    assert capture_policy(native_events, policy, capfd) == capture_policy(numpy_events, policy, capfd)


def test_callback_policy_and_handler_changes_follow_numpy_operation_boundaries():
    def observe(function):
        callbacks = []
        previous_policy, previous_handler = np.geterr(), np.geterrcall()
        changed = False

        def replacement(message, flags):
            callbacks.append(('replacement', message, flags))

        def initial(message, flags):
            nonlocal changed
            callbacks.append(('initial', message, flags))
            if not changed:
                changed = True
                np.seterr(all='ignore')
                np.seterrcall(replacement)

        np.seterr(all='call')
        np.seterrcall(initial)
        try:
            function()
            return callbacks, np.geterr(), np.geterrcall() is replacement
        finally:
            np.seterr(**previous_policy)
            np.seterrcall(previous_handler)

    expected = observe(numpy_events)
    actual = observe(native_events)
    assert expected[0]
    assert actual == expected


@pytest.mark.parametrize('mode', ['call', 'log'])
def test_missing_fp_handler_keeps_numpy_exception(mode, capfd):
    policy = dict.fromkeys(('divide', 'over', 'under', 'invalid'), mode)
    assert capture_policy(native_events, policy, capfd, handler=False) == capture_policy(
        numpy_events, policy, capfd, handler=False)


def test_fp_warn_uses_the_requested_call_site():
    with warnings.catch_warnings(record=True) as emitted, np.errstate(all='warn'):
        warnings.simplefilter('always')
        floating_events([(2, 'multiply')], stacklevel=2)
    assert len(emitted) == 1 and emitted[0].filename == __file__


@pytest.mark.parametrize('mode', ['warn', 'raise'])
def test_wire_fp_events_precede_the_terminal_numeric_cause(monkeypatch, mode):
    class Owner:
        def bind(self, name, signature):
            def fail(*arguments):
                diagnostics = ct.cast(arguments[-3], ct.POINTER(native._Diagnostics)).contents
                diagnostics.event_count = 1
                diagnostics.events[0] = native._Event(10, 3, 0, 0)
                diagnostics.python_cause = 3
                arguments[-2].value = b'later numerical cause'
                return 4

            return fail

    monkeypatch.setattr(native, '_library', lambda: Owner())
    expected = FloatingPointError if mode == 'raise' else ValueError
    message = 'overflow encountered in multiply' if mode == 'raise' else 'later numerical cause'
    with warnings.catch_warnings(record=True) as emitted, np.errstate(all=mode):
        warnings.simplefilter('always')
        with pytest.raises(expected, match=message):
            native.call('named_test_leaf', [])
    assert [str(item.message) for item in emitted] == ([] if mode == 'raise' else [
        'overflow encountered in multiply', 'invalid value encountered in multiply'])


def test_extended_precision_matches_the_actual_host():
    path = native._library_path()
    native._extended_format(path)
    expected = np.finfo(np.longdouble)
    value = np.longdouble('1.0000000000000000001')
    packed = native.scalar(value)
    restored = native.restore_scalar(packed)
    assert restored.dtype == value.dtype and restored == value
    if expected.nmant > np.finfo(np.float64).nmant:
        assert restored != np.longdouble(float(value))
    wider = np.array([expected.max], dtype=np.longdouble)
    owner = native.array(wider)
    assert owner.raw.dtype in (12, 13)
    assert np.isfinite(owner.owner[0])
    complex_value = np.clongdouble(value + np.clongdouble(1j))
    restored_complex = native.restore_scalar(native.scalar(complex_value))
    assert restored_complex.dtype == complex_value.dtype and restored_complex == complex_value
