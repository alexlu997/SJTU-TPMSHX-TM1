"""Check native test library selection and missing-library outcomes."""
from pathlib import Path

import pytest

from tests.python.native import shared_library


def test_default_library_path(monkeypatch, tmp_path):
    name = f'{shared_library.PREFIX}tpmshx_solver_shared{shared_library.SUFFIX}'
    path = tmp_path / name
    path.touch()
    monkeypatch.setattr(shared_library, 'PILOT', tmp_path)
    monkeypatch.delenv('TPMSHX_NATIVE_SOLVER_LIBRARY', raising=False)
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
    monkeypatch.setattr(shared_library, 'PILOT', tmp_path)
    monkeypatch.delenv('TPMSHX_NATIVE_SOLVER_LIBRARY', raising=False)
    if override:
        monkeypatch.setenv('TPMSHX_NATIVE_SOLVER_LIBRARY', str(tmp_path / 'missing'))
    monkeypatch.setenv('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS', '1' if required else '0')
    exception = pytest.fail.Exception if required else pytest.skip.Exception
    with pytest.raises(exception, match='native library unavailable:'):
        shared_library.library_path()
