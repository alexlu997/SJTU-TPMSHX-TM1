"""Saved snapshots share storage without changing earlier evidence."""
import errno
from pathlib import Path
import shutil

import pytest

from sjtu_tpmshx.io import file_snapshot as snapshot
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.tests.test_workflow_recovery import stages as stages


def test_result_replacement_and_source_removal_preserve_the_snapshot(tmp_path, stages):
    from dataclasses import replace
    source, target = tmp_path / 'source.h5', tmp_path / 'target.h5'
    result = stages[2]
    save_result(result, source)
    snapshot.copy_snapshot(source, target)
    assert source.samefile(target)
    save_result(replace(result, result_id='replacement'), source)
    assert not source.samefile(target)
    assert load_result(target).result_id == result.result_id
    source.unlink()
    assert load_result(target).result_id == result.result_id


@pytest.mark.parametrize('code,winerror', [
    *((value, None) for value in (errno.EXDEV, errno.EPERM, errno.EACCES,
                                errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK)),
    (errno.EINVAL, 1), (errno.EINVAL, 50), (errno.EINVAL, 1142),
])
def test_unavailable_link_uses_an_independent_copy(tmp_path, monkeypatch, code, winerror):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'saved data')
    def fail(*args):
        error = OSError(code, 'link unavailable')
        if winerror is not None:
            error.winerror = winerror
        raise error
    monkeypatch.setattr(snapshot.os, 'link', fail)
    snapshot.copy_snapshot(source, target)
    assert target.read_bytes() == b'saved data'
    assert not source.samefile(target)
    source.write_bytes(b'changed source')
    assert target.read_bytes() == b'saved data'


def test_unrelated_invalid_argument_does_not_copy(tmp_path, monkeypatch):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'saved data')
    def fail(*args):
        raise OSError(errno.EINVAL, 'invalid argument')
    monkeypatch.setattr(snapshot.os, 'link', fail)
    monkeypatch.setattr(snapshot.shutil, 'copy2', lambda *args: pytest.fail('unexpected copy'))
    with pytest.raises(OSError, match='invalid argument'):
        snapshot.copy_snapshot(source, target)
    assert not target.exists()


@pytest.mark.parametrize('copy_failure', [False, True])
def test_storage_error_keeps_previous_target(tmp_path, monkeypatch, copy_failure):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'new data')
    target.write_bytes(b'previous data')
    def link(*args):
        raise OSError(errno.EXDEV if copy_failure else errno.EIO, 'link failed')
    def copy(source, target):
        Path(target).write_bytes(b'partial data')
        raise OSError(errno.ENOSPC, 'copy failed')
    monkeypatch.setattr(snapshot.os, 'link', link)
    monkeypatch.setattr(snapshot.shutil, 'copy2', copy)
    with pytest.raises(OSError, match='failed'):
        snapshot.copy_snapshot(source, target)
    assert target.read_bytes() == b'previous data'
    assert not list(tmp_path.glob('.tm1-publish-*'))


def test_mutable_build_is_separate_and_later_snapshots_share_it(tmp_path):
    source = tmp_path / 'build.dylib'
    first, second, third = [tmp_path / name for name in ('first', 'second', 'third')]
    source.write_bytes(b'first build')
    assert snapshot.retain_runtime(source, first) == first
    assert not source.samefile(first)
    assert snapshot.retain_runtime(source, second) == first
    assert first.samefile(second)
    source.write_bytes(b'second build')
    assert snapshot.retain_runtime(source, third) == third
    assert first.read_bytes() == second.read_bytes() == b'first build'
    assert third.read_bytes() == b'second build'
    snapshot.retain_runtime(source, second)
    assert first.read_bytes() == b'first build'
    assert second.samefile(third)


@pytest.mark.parametrize('target_kind', ['shared', 'independent', 'same_path'])
@pytest.mark.parametrize('known_runtime', [False, True])
def test_matching_loaded_runtime_is_not_replaced(tmp_path, monkeypatch, target_kind, known_runtime):
    source, first, target = [tmp_path / name for name in ('build.dll', 'first.dll', 'target.dll')]
    source.write_bytes(b'fixed runtime')
    snapshot.retain_runtime(source, first)
    if target_kind == 'shared':
        snapshot.copy_snapshot(first, target)
    elif target_kind == 'independent':
        shutil.copy2(first, target)
    else:
        source = target = first
    if not known_runtime:
        snapshot._runtime_files.pop(source.resolve())
    before = target.stat()
    def locked(*args):
        raise PermissionError('loaded Windows DLL cannot be replaced')
    monkeypatch.setattr(snapshot.os, 'replace', locked)
    assert snapshot.retain_runtime(source, target) == (first if known_runtime else target)
    assert target.stat().st_ino == before.st_ino
    assert target.read_bytes() == b'fixed runtime'
    assert not list(tmp_path.glob('.tm1-publish-*'))


def test_changed_build_during_copy_does_not_replace_previous_runtime(tmp_path, monkeypatch):
    source, target = tmp_path / 'build', tmp_path / 'retained'
    source.write_bytes(b'build')
    target.write_bytes(b'previous runtime')
    copy = shutil.copy2
    def changed(source, target):
        copy(source, target)
        source.write_bytes(b'changed build')
    monkeypatch.setattr(snapshot.shutil, 'copy2', changed)
    with pytest.raises(OSError, match='library changed'):
        snapshot.retain_runtime(source, target)
    assert target.read_bytes() == b'previous runtime'


def test_recovery_copy_shares_binaries_and_keeps_text_independent(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir()
    for name in ('case.h5', 'runtime.dll', 'run.json', 'solver.log'):
        (source / name).write_bytes(name.encode())
    shutil.copytree(source, target, copy_function=snapshot.copy_saved_file)
    assert (source / 'case.h5').samefile(target / 'case.h5')
    assert (source / 'runtime.dll').samefile(target / 'runtime.dll')
    (target / 'run.json').write_bytes(b'new status')
    with (target / 'solver.log').open('ab') as stream:
        stream.write(b'new log')
    assert (source / 'run.json').read_bytes() == b'run.json'
    assert (source / 'solver.log').read_bytes() == b'solver.log'
    shutil.rmtree(source)
    assert (target / 'case.h5').read_bytes() == b'case.h5'
