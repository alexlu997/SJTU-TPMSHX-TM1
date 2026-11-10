"""Explicit publication preserves the working library until validation succeeds."""
import json
from pathlib import Path, PureWindowsPath

import pytest

from engineering.scripts import build_native_dependencies as native


GEOMETRY_LIBRARY = "libtpmshx_geometry_shared.dylib"
GEOMETRY_RECORD = "geometry-build.json"


def _published_state(target):
    paths = (target, target.with_name("build.json"), target.with_name(GEOMETRY_LIBRARY),
             target.with_name(GEOMETRY_RECORD))
    return {path: path.read_bytes() if path.is_file() else None for path in paths}


def test_coolprop_cpm_paths_are_safe_in_generated_cmake(monkeypatch):
    commands = []
    monkeypatch.setattr(native, "run", lambda command, *args, **kwargs: commands.append(command))
    monkeypatch.setattr(native, "verify_sources", lambda cache: None)
    monkeypatch.setattr(native, "apply_lu_patch", lambda cache: None)
    monkeypatch.setattr(native, "cmake_path", lambda *args: PureWindowsPath("C:/cmake.exe"))
    cache = PureWindowsPath("D:/a/project/.cache/native-deps")
    native.build(cache, "windows-x64", PureWindowsPath("C:/python.exe"),
                 Path("engineering/requirements/base.txt"), "coolprop")
    configure = next(command for command in commands if "-S" in command)
    assert "-DCPM_Eigen_SOURCE=D:/a/project/.cache/native-deps/src/Eigen-5.0.1" in configure
    assert all("\\" not in option for option in configure
               if isinstance(option, str) and option.startswith("-DCPM_"))


@pytest.fixture
def publication(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "ROOT", tmp_path)
    events = []
    monkeypatch.setattr(native, "build", lambda *args: events.append("build"))
    monkeypatch.setattr(native, "verify", lambda *args: events.append("verify"))
    monkeypatch.setattr(native, "run", lambda command, *args, **kwargs:
                        "test-commit\n" if "rev-parse" in command else "")
    cache = tmp_path / ".cache/native-deps"
    name = "libtpmshx_solver_shared.dylib"
    source = cache / "build/pilot-macos-arm64" / name
    source.parent.mkdir(parents=True)
    source.write_bytes(b"new verified library")
    source.with_name(GEOMETRY_LIBRARY).write_bytes(b"new verified geometry")
    target = tmp_path / "sjtu_tpmshx/solvers/native/lib/macos-arm64" / name
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previous qualified library")
    target.with_name("build.json").write_text('{"source_commit": "previous"}\n')
    target.with_name(GEOMETRY_LIBRARY).write_bytes(b"previous qualified geometry")
    target.with_name(GEOMETRY_RECORD).write_text('{"source_commit": "previous-geometry"}\n')
    return cache, source, target, events


def test_publish_rebuilds_verifies_and_preserves_previous_library(publication):
    cache, source, target, events = publication
    actual = native.publish(cache, "macos-arm64", Path("/python"), Path("engineering/requirements/base.txt"))
    assert events == ["build", "verify"]
    assert actual == target and target.read_bytes() == source.read_bytes()
    backup = target.parent / "previous"
    assert (backup / target.name).read_bytes() == b"previous qualified library"
    assert json.loads((backup / "build.json").read_text())["source_commit"] == "previous"
    record = json.loads(target.with_name("build.json").read_text())
    assert record["source_commit"] == "test-commit"
    assert record["configuration"] == "Release"
    assert record["target_library"] == str(target)
    geometry = target.with_name(GEOMETRY_LIBRARY)
    assert geometry.read_bytes() == source.with_name(GEOMETRY_LIBRARY).read_bytes()
    geometry_record = json.loads(target.with_name(GEOMETRY_RECORD).read_text())
    assert geometry_record["component"] == "geometry"
    assert geometry_record["target_library"] == str(geometry)
    assert geometry_record["dependencies"] == {}
    assert (backup / GEOMETRY_LIBRARY).read_bytes() == b"previous qualified geometry"
    assert json.loads((backup / GEOMETRY_RECORD).read_text())["source_commit"] == "previous-geometry"
    native.publish(cache, "macos-arm64", Path("/python"), Path("engineering/requirements/base.txt"))
    assert (backup / target.name).read_bytes() == b"previous qualified library"
    assert (backup / GEOMETRY_LIBRARY).read_bytes() == b"previous qualified geometry"


@pytest.mark.parametrize("stage", ["build", "verify", "copy"])
def test_failed_publication_keeps_current_library_and_record(publication, monkeypatch, stage):
    cache, _, target, _ = publication
    before = _published_state(target)

    def fail(*args, **kwargs):
        raise RuntimeError("publication failure")

    if stage == "copy":
        monkeypatch.setattr(native.shutil, "copy2", fail)
    else:
        monkeypatch.setattr(native, stage, fail)
    with pytest.raises(RuntimeError, match="publication failure"):
        native.publish(cache, "macos-arm64", Path("/python"), Path("engineering/requirements/base.txt"))
    assert target.read_bytes() == b"previous qualified library"
    assert json.loads(target.with_name("build.json").read_text())["source_commit"] == "previous"
    assert _published_state(target) == before
    assert not (target.parent / "previous").exists()
    assert not list(target.parent.glob(".publish-*"))


@pytest.mark.parametrize("stage", ["build.json", "libtpmshx_solver_shared.dylib"])
@pytest.mark.parametrize("existing_record", [True, False])
def test_failed_final_replace_restores_build_record(publication, monkeypatch, stage, existing_record):
    cache, _, target, _ = publication
    metadata = target.with_name("build.json")
    if not existing_record:
        metadata.unlink()
    before = _published_state(target)
    replace = Path.replace

    def fail_selected(path, destination):
        if path.name == stage:
            raise PermissionError("library is in use")
        return replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_selected)
    with pytest.raises(PermissionError, match="library is in use"):
        native.publish(cache, "macos-arm64", Path("/python"), Path("engineering/requirements/base.txt"))
    assert target.read_bytes() == b"previous qualified library"
    assert metadata.is_file() == existing_record
    if existing_record:
        assert json.loads(metadata.read_text())["source_commit"] == "previous"
    assert _published_state(target) == before
    assert not list(target.parent.glob(".publish-*"))


def test_geometry_only_publication_preserves_solver_and_run_state(publication):
    cache, _, target, _ = publication
    source = cache / "build/geometry-macos-arm64" / GEOMETRY_LIBRARY
    source.parent.mkdir(parents=True)
    source.write_bytes(b"standalone verified geometry")
    previous = target.parent / "previous"
    previous.mkdir()
    protected = (target, target.with_name("build.json"), target.with_name("run-state.checkpoint"),
                 previous / target.name, previous / "build.json")
    protected[2].write_bytes(b"accepted run state")
    protected[3].write_bytes(b"older solver")
    protected[4].write_bytes(b"older solver record")
    before = {path: path.read_bytes() for path in protected}

    actual = native.publish(cache, "macos-arm64", Path("/python"),
                            Path("engineering/requirements/bo-macos.txt"), "geometry")

    assert actual == target.with_name(GEOMETRY_LIBRARY)
    assert actual.read_bytes() == source.read_bytes()
    assert {path: path.read_bytes() for path in protected} == before
    assert (previous / GEOMETRY_LIBRARY).read_bytes() == b"previous qualified geometry"
    record = json.loads(target.with_name(GEOMETRY_RECORD).read_text())
    assert record["component"] == "geometry"
    assert record["source_library"] == str(source)
    assert record["python_lock"] == str(Path("engineering/requirements/bo-macos.txt"))


def test_missing_second_source_keeps_both_current_libraries(publication):
    cache, source, target, _ = publication
    before = _published_state(target)
    source.with_name(GEOMETRY_LIBRARY).unlink()
    with pytest.raises(FileNotFoundError):
        native.publish(cache, "macos-arm64", Path("/python"), Path("engineering/requirements/base.txt"))
    assert _published_state(target) == before
    assert not (target.parent / "previous").exists()
    assert not list(target.parent.glob(".publish-*"))


@pytest.mark.parametrize("stage", [GEOMETRY_LIBRARY, GEOMETRY_RECORD])
@pytest.mark.parametrize("existing_record", [True, False])
def test_second_library_replace_failure_restores_both_records(publication, monkeypatch, stage, existing_record):
    cache, _, target, _ = publication
    if not existing_record:
        target.with_name(GEOMETRY_RECORD).unlink()
    before = _published_state(target)
    replace = Path.replace

    def fail_selected(path, destination):
        if path.name == stage:
            raise PermissionError("geometry library is in use")
        return replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_selected)
    with pytest.raises(PermissionError, match="geometry library is in use"):
        native.publish(cache, "macos-arm64", Path("/python"), Path("engineering/requirements/base.txt"))
    assert _published_state(target) == before
    assert not list(target.parent.glob(".publish-*"))


@pytest.mark.parametrize("component", ["solver", "geometry"])
def test_interrupt_after_real_replace_restores_both_libraries(publication, monkeypatch, component):
    cache, _, target, _ = publication
    before = _published_state(target)
    replace = Path.replace

    def interrupt_after_replace(path, destination):
        result = replace(path, destination)
        if path.name == f"libtpmshx_{component}_shared.dylib":
            raise KeyboardInterrupt("interrupted after replacement")
        return result

    monkeypatch.setattr(Path, "replace", interrupt_after_replace)
    with pytest.raises(KeyboardInterrupt, match="interrupted after replacement"):
        native.publish(cache, "macos-arm64", Path("/python"), Path("engineering/requirements/base.txt"))
    assert _published_state(target) == before
    assert not list(target.parent.glob(".publish-*"))


def test_failed_rollback_retains_recovery_files_and_restores_other_records(publication, monkeypatch, capsys):
    cache, _, target, _ = publication
    before = _published_state(target)
    replace = Path.replace

    def fail_geometry_and_solver_restore(path, destination):
        if path.name == GEOMETRY_LIBRARY:
            raise PermissionError("geometry library is in use")
        if path.name == "old-" + target.name:
            raise PermissionError("solver restore is blocked")
        return replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_geometry_and_solver_restore)
    with pytest.raises(RuntimeError, match="Publication rollback failed") as error:
        native.publish(cache, "macos-arm64", Path("/python"), Path("engineering/requirements/base.txt"))
    recovery, = target.parent.glob(".publish-*")
    assert str(recovery) in str(error.value)
    assert str(recovery) in capsys.readouterr().err
    assert (recovery / ("old-" + target.name)).read_bytes() == before[target]
    assert target.read_bytes() == b"new verified library"
    for path, contents in before.items():
        if path != target:
            assert path.read_bytes() == contents
