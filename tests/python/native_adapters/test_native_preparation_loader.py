"""Preparation library selection remains explicit and lazy."""
from tests.python.native_adapters.test_native_result_loader import LibraryStub

import pytest

from tm1.cpp_interface import stage_libraries as native


@pytest.mark.parametrize('system,machine,host,name', [
    ('darwin', 'arm64', 'macos-arm64', 'libtpmshx_preparation_shared.dylib'),
    ('win32', 'AMD64', 'windows-x64', 'tpmshx_preparation_shared.dll')])
def test_default_and_frozen_paths(tmp_path, monkeypatch, system, machine, host, name):
    monkeypatch.delenv('TPMSHX_PREPARATION_LIBRARY', raising=False)
    monkeypatch.setattr(native.sys, 'platform', system)
    monkeypatch.setattr(native.platform, 'machine', lambda: machine)
    monkeypatch.setattr(native, 'PUBLISHED_LIBRARY_DIR', tmp_path / 'native/lib')
    selected = tmp_path/'native/lib'/host/name
    selected.parent.mkdir(parents=True)
    selected.write_bytes(b'prebuilt placeholder')
    assert native.preparation_library.path() == str(selected.resolve())
    frozen = tmp_path/'bundle/native'/name
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(b'frozen prebuilt placeholder')
    monkeypatch.setattr(native.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(native.sys, '_MEIPASS', str(frozen.parent.parent), raising=False)
    assert native.preparation_library.path() == str(frozen.resolve())


def test_explicit_override_and_missing_runtime_errors(tmp_path, monkeypatch):
    selected = tmp_path/'selected library'
    selected.write_bytes(b'prebuilt placeholder')
    monkeypatch.setenv('TPMSHX_PREPARATION_LIBRARY', str(selected))
    assert native.preparation_library.path() == str(selected.resolve())
    monkeypatch.setenv('TPMSHX_PREPARATION_LIBRARY', '')
    with pytest.raises(ValueError, match='must name a prebuilt preparation library'):
        native.preparation_library.path()
    monkeypatch.setenv('TPMSHX_PREPARATION_LIBRARY', str(tmp_path/'absent'))
    with pytest.raises(FileNotFoundError, match='prebuilt native preparation library is missing'):
        native.preparation_library.path()


def test_unsupported_host_does_not_select_a_solver_runtime(monkeypatch):
    monkeypatch.delenv('TPMSHX_PREPARATION_LIBRARY', raising=False)
    monkeypatch.setattr(native.sys, 'platform', 'linux')
    monkeypatch.setattr(native.platform, 'machine', lambda: 'x86_64')
    with pytest.raises(RuntimeError, match='no default native preparation library'):
        native.preparation_library.path()


@pytest.mark.parametrize('version', [0, 2, 4])
def test_wrong_abi_is_rejected_before_function_binding(monkeypatch, version):
    handle = LibraryStub(tpmshx_preparation_abi_version_v1=lambda: version)
    monkeypatch.setattr(native.ct, 'CDLL', lambda _: handle)
    with pytest.raises(ValueError, match='unsupported native preparation ABI'):
        native.preparation_library.open('/prebuilt')


def test_missing_symbols_and_load_failure_are_explicit(monkeypatch):
    monkeypatch.setattr(native.ct, 'CDLL', lambda _: LibraryStub())
    with pytest.raises(ValueError, match='lacks tpmshx_preparation_abi_version_v1'):
        native.preparation_library.open('/prebuilt')
    handle = LibraryStub(tpmshx_preparation_abi_version_v1=lambda: 3)
    monkeypatch.setattr(native.ct, 'CDLL', lambda _: handle)
    owner = native.preparation_library.open('/prebuilt')
    with pytest.raises(ValueError, match='lacks a_required_function'):
        owner.bind('a_required_function', [])

    def fail(path):
        raise OSError('wrong architecture')

    monkeypatch.setattr(native.ct, 'CDLL', fail)
    with pytest.raises(OSError, match='cannot load prebuilt native preparation library /prebuilt: wrong architecture'):
        native.preparation_library.open('/prebuilt')
