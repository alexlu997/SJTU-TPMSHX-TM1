"""Check native test library selection and missing-library outcomes."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from sjtu_tpmshx.tests.native import shared_library


@pytest.mark.parametrize('platform, host, name', [
    ('nt', 'windows-x64', 'tpmshx_solver_shared.dll'),
    ('posix', 'macos-arm64', 'libtpmshx_solver_shared.dylib'),
])
def test_default_library_path(monkeypatch, tmp_path, platform, host, name):
    path = tmp_path / '.cache/native-deps/build' / ('pilot-' + host) / name
    path.parent.mkdir(parents=True)
    path.touch()
    monkeypatch.setattr(shared_library, 'ROOT', tmp_path)
    monkeypatch.setattr(shared_library, 'os', SimpleNamespace(name=platform, environ={}))
    assert shared_library.library_path() == path


def test_override_keeps_relative_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    path = Path('selected-library')
    path.touch()
    monkeypatch.setenv('TPMSHX_NATIVE_SOLVER_LIBRARY', str(path))
    monkeypatch.setenv('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS', '1')
    assert shared_library.library_path() == path


@pytest.mark.parametrize('required', [False, True])
@pytest.mark.parametrize('override', [False, True])
def test_missing_library_policy(monkeypatch, tmp_path, required, override):
    monkeypatch.setattr(shared_library, 'ROOT', tmp_path)
    monkeypatch.delenv('TPMSHX_NATIVE_SOLVER_LIBRARY', raising=False)
    if override:
        monkeypatch.setenv('TPMSHX_NATIVE_SOLVER_LIBRARY', str(tmp_path / 'missing'))
    monkeypatch.setenv('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS', '1' if required else '0')
    exception = pytest.fail.Exception if required else pytest.skip.Exception
    with pytest.raises(exception, match='native full library unavailable:'):
        shared_library.library_path()
