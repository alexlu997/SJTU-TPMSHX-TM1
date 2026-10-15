"""Keep fixed source checks when a native dependency fetch is interrupted."""
from pathlib import Path
import subprocess

import pytest

from scripts import build_native_dependencies as native


OVERLOAD = "fatal: remote error: GitLab is currently unable to handle this request due to load (ID test)"
RETRY_ERRORS = (
    OVERLOAD,
    "error: RPC failed; HTTP 503 curl 22 The requested URL returned error: 503",
    "fatal: unable to access 'https://eigen.googlesource.com/mirror/': The requested URL returned error: 503",
)


@pytest.fixture
def source_fetch(tmp_path, monkeypatch):
    spec = dict(repository="https://gitlab.com/libeigen/eigen.git",
                commit="fixed-revision", directory="Eigen-test")
    monkeypatch.setattr(native, "LOCK", {"sources": {"eigen": spec}})
    cache = tmp_path / "cache"
    source = cache / "src" / spec["directory"]
    state = dict(ready=False, revision=spec["commit"], errors=[], fetches=[], commands=[], dirty="")
    delays = []
    monkeypatch.setattr(native.time, "sleep", delays.append)

    def process(command, **kwargs):
        state["commands"].append(command)
        code, output = 0, ""
        if command[1] == "init":
            (Path(command[2]) / ".git").mkdir()
        elif command[1] == "remote":
            pass
        elif command[1] == "rev-parse":
            code, output = (0, state["revision"] + "\n") if state["ready"] else (1, "")
        elif command[1] == "status":
            output = state["dirty"]
        elif command[1] == "fetch":
            state["fetches"].append(command)
            if state["errors"]:
                code, output = 128, state["errors"].pop(0)
        elif command[1] == "checkout":
            state["ready"] = True
            (source / "Eigen").mkdir()
            (source / "Eigen/SparseLU").write_text("fixed header\n")
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, code, output)

    monkeypatch.setattr(native.subprocess, "run", process)
    return cache, source, spec, state, delays


@pytest.mark.parametrize("fetch_error", RETRY_ERRORS)
def test_load_retry_preserves_logs_and_reuses_completed_source(source_fetch, fetch_error):
    cache, source, spec, state, delays = source_fetch
    state["errors"] = [fetch_error, fetch_error]
    native.fetch_eigen(cache)
    assert delays == [10, 20]
    assert state["fetches"] == [["git", "fetch", "--depth", "1", spec["repository"], spec["commit"]]] * 3
    log = (cache / "logs/fetch-eigen.log").read_text()
    assert log.count(fetch_error) == 2 and log.count("exit=128") == 2
    assert (source / "Eigen/SparseLU").read_text() == "fixed header\n"
    native.fetch_eigen(cache)
    assert len(state["fetches"]) == 3


@pytest.mark.parametrize("fetch_error", RETRY_ERRORS)
def test_retry_limit_leaves_a_checkout_that_the_next_call_can_resume(source_fetch, fetch_error):
    cache, source, _, state, delays = source_fetch
    state["errors"] = [fetch_error] * 5
    with pytest.raises(RuntimeError, match="GitLab is currently unable|The requested URL returned error: 503"):
        native.fetch_eigen(cache)
    assert delays == [10, 20, 40, 80]
    assert (source / ".git").is_dir() and not state["ready"]
    assert (cache / "logs/fetch-eigen.log").read_text().count(fetch_error) == 5
    native.fetch_eigen(cache)
    assert len(state["fetches"]) == 6 and state["ready"]
    assert sum(command[1] == "init" for command in state["commands"]) == 1


def test_other_fetch_errors_are_not_retried(source_fetch):
    cache, _, _, state, delays = source_fetch
    state["errors"] = ["fatal: authentication failed"]
    with pytest.raises(RuntimeError, match="authentication failed"):
        native.fetch_eigen(cache)
    assert len(state["fetches"]) == 1 and not delays
    assert not state["ready"]


def test_wrong_source_revision_is_not_replaced(source_fetch):
    cache, source, _, state, _ = source_fetch
    (source / ".git").mkdir(parents=True)
    state.update(ready=True, revision="different-revision")
    with pytest.raises(RuntimeError, match="source commit differs from the lock"):
        native.fetch_eigen(cache)
    assert not state["fetches"] and state["revision"] == "different-revision"


def test_incomplete_source_with_local_files_is_not_reset(source_fetch):
    cache, source, _, state, _ = source_fetch
    (source / ".git").mkdir(parents=True)
    local = source / "local.txt"
    local.write_text("keep this file\n")
    state["dirty"] = "?? local.txt\n"
    with pytest.raises(RuntimeError, match="contains local changes"):
        native.fetch_eigen(cache)
    assert not state["fetches"]
    assert local.read_text() == "keep this file\n"
