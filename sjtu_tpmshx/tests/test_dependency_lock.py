"""The supported Mac/Windows environment must match the shared exact lock."""

from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
import pytest

from sjtu_tpmshx.runs.tools.check_locked_environment import (
    LockFileError,
    environment_issues,
    installed_versions,
    read_lock,
)


_ROOT = Path(__file__).resolve().parents[2]


def test_declared_environment_is_fully_locked_and_installed():
    project = tomllib.loads(
        (_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    declared = list(project['dependencies'])
    for group in ('gui', 'test', 'dev', 'tools'):
        declared.extend(project['optional-dependencies'][group])

    locked = read_lock(_ROOT / 'requirements-lock.txt')

    missing = sorted(
        req.name for raw in declared
        if canonicalize_name((req := Requirement(raw)).name) not in locked)
    assert not missing, f'declared dependencies missing from lock: {missing}'

    issues = environment_issues(locked, check_extras=False)
    assert not issues, 'environment differs from lock: ' + ', '.join(issues)


def test_server_lock_includes_base_and_bo_dependencies():
    project = tomllib.loads(
        (_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    base = read_lock(_ROOT / 'requirements-lock.txt')
    server = read_lock(_ROOT / 'requirements-lock-server.txt')

    assert set(base) <= set(server)
    missing = sorted(
        req.name for raw in project['optional-dependencies']['bo']
        if canonicalize_name((req := Requirement(raw)).name) not in server)
    assert not missing, f'BO dependencies missing from server lock: {missing}'


def test_lock_reader_follows_includes_and_platform_markers(tmp_path):
    (tmp_path / 'base.txt').write_text(
        'alpha==1\ncolorama==0.4.6; sys_platform == "win32"\n',
        encoding='utf-8',
    )
    lock = tmp_path / 'server.txt'
    lock.write_text(
        '-r base.txt\n--extra-index-url https://example.invalid/simple\nbeta==2\n',
        encoding='utf-8',
    )

    assert set(read_lock(lock, {'sys_platform': 'darwin'})) == {'alpha', 'beta'}
    assert set(read_lock(lock, {'sys_platform': 'win32'})) == {
        'alpha', 'beta', 'colorama'}


def test_server_environment_requires_explicit_server_lock():
    base = read_lock(_ROOT / 'requirements-lock.txt', {'sys_platform': 'win32'})
    server = read_lock(_ROOT / 'requirements-lock-server.txt', {'sys_platform': 'win32'})
    installed = {name: {next(iter(req.specifier)).version} for name, req in server.items()}
    assert environment_issues(server, installed) == []
    issues = environment_issues(base, installed)
    assert issues and all(issue.startswith('unexpected package: ') for issue in issues)
    assert any(issue.startswith('unexpected package: botorch==') for issue in issues)


def test_lock_reader_rejects_non_exact_and_duplicate_pins(tmp_path):
    lock = tmp_path / 'lock.txt'
    lock.write_text('alpha>=1\n', encoding='utf-8')
    with pytest.raises(LockFileError, match='exact == pin'):
        read_lock(lock)

    lock.write_text('alpha==1\nAlpha==2\n', encoding='utf-8')
    with pytest.raises(LockFileError, match='duplicate pin'):
        read_lock(lock)


def test_environment_issues_report_drift_but_ignore_pip():
    locked = {
        'alpha': Requirement('alpha==1'),
        'beta': Requirement('beta==2'),
    }
    installed = {
        'alpha': {'0.9'},
        'extra': {'3'},
        'pip': {'99'},
    }

    assert environment_issues(locked, installed) == [
        'version mismatch: alpha==1 (installed 0.9)',
        'missing: beta==2',
        'unexpected package: extra==3',
    ]


def test_installed_versions_ignores_source_tree_metadata(tmp_path, monkeypatch):
    egg_info = tmp_path / 'source-tree-only.egg-info'
    egg_info.mkdir()
    (egg_info / 'PKG-INFO').write_text(
        'Metadata-Version: 2.1\nName: source-tree-only\nVersion: 1\n',
        encoding='utf-8',
    )
    monkeypatch.syspath_prepend(tmp_path)

    assert 'source-tree-only' not in installed_versions()
