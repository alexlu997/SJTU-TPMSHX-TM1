"""Explicit publication preserves the working library until validation succeeds."""
import json
from pathlib import Path, PureWindowsPath

import pytest

from engineering.scripts import build_native_dependencies as native


SOLVER_LIBRARY = "libtpmshx_solver_shared.dylib"
SOLVER_RECORD = "build.json"
GEOMETRY_LIBRARY = "libtpmshx_geometry_shared.dylib"
GEOMETRY_RECORD = "geometry-build.json"
PREPARATION_LIBRARY = "libtpmshx_preparation_shared.dylib"
PREPARATION_RECORD = "preparation-build.json"
RESULT_LIBRARY = "libtpmshx_result_shared.dylib"
RESULT_RECORD = "result-build.json"
PUBLISHED = (SOLVER_LIBRARY, SOLVER_RECORD, GEOMETRY_LIBRARY, GEOMETRY_RECORD,
             PREPARATION_LIBRARY, PREPARATION_RECORD, RESULT_LIBRARY, RESULT_RECORD)
LOCK = Path("engineering/requirements/base.txt")


def _published_state(target):
    paths = [target.with_name(name) for name in PUBLISHED]
    return {path: path.read_bytes() if path.is_file() else None for path in paths}


def _publish(cache, *component):
    return native.publish(cache, "macos-arm64", Path("/python"), LOCK, *component)


def _fail_replace(monkeypatch, stage, error):
    replace = Path.replace

    def fail_selected(path, destination):
        if path.name == stage:
            raise error
        return replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_selected)


def test_coolprop_cpm_paths_are_safe_in_generated_cmake(monkeypatch):
    commands = []
    monkeypatch.setattr(native, "run", lambda command, *args, **kwargs: commands.append(command))
    monkeypatch.setattr(native, "verify_sources", lambda cache: None)
    monkeypatch.setattr(native, "apply_lu_patch", lambda cache: None)
    monkeypatch.setattr(native, "cmake_path", lambda *args: PureWindowsPath("C:/cmake.exe"))
    monkeypatch.setattr(native, "_request_build_metadata", lambda *args: None)
    monkeypatch.setattr(native, "_record_coolprop_build", lambda *args: None)
    cache = PureWindowsPath("D:/a/project/.cache/native-deps")
    native.build(cache, "windows-x64", PureWindowsPath("C:/python.exe"), LOCK, "coolprop")
    configure = next(command for command in commands if "-S" in command)
    assert "-DCPM_Eigen_SOURCE=D:/a/project/.cache/native-deps/src/Eigen-5.0.1" in configure
    assert all("\\" not in option for option in configure
               if isinstance(option, str) and option.startswith("-DCPM_"))


@pytest.mark.parametrize("host", ["macos-arm64", "windows-x64"])
def test_coolprop_build_has_only_the_required_archive_roles(tmp_path, monkeypatch, host):
    commands, records = [], []
    monkeypatch.setattr(native, "run", lambda command, *args, **kwargs: commands.append(tuple(map(str, command))))
    monkeypatch.setattr(native, "check_environment", lambda *args: None)
    monkeypatch.setattr(native, "verify_sources", lambda *args: None)
    monkeypatch.setattr(native, "apply_lu_patch", lambda *args: None)
    monkeypatch.setattr(native, "cmake_path", lambda *args: Path("/locked/cmake"))
    monkeypatch.setattr(native, "_request_build_metadata", lambda *args: None)
    monkeypatch.setattr(native, "_record_coolprop_build", lambda cache, host, role: records.append(role))
    native.build(tmp_path, host, Path("/python"), Path("/lock"), "coolprop")
    configure = [command for command in commands if "-S" in command]
    assert records == (["solver", "preparation"] if host == "macos-arm64" else ["solver"])
    original = configure[0]
    assert original[original.index("-B")+1] == str(tmp_path/"build"/f"coolprop-{host}")
    assert not any("-Os" in value or "/O1" in value for value in original)
    if host == "macos-arm64":
        preparation = configure[1]
        assert preparation[preparation.index("-B")+1] == str(tmp_path/"build/coolprop-preparation-macos-arm64")
        assert "-DCMAKE_C_FLAGS_RELEASE=-Os -DNDEBUG" in preparation
        assert "-DCMAKE_CXX_FLAGS_RELEASE=-Os -DNDEBUG" in preparation


@pytest.fixture
def publication(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "ROOT", tmp_path)
    (tmp_path / ".git").mkdir()
    events = []
    monkeypatch.setattr(native, "build", lambda *args: events.append("build"))
    monkeypatch.setattr(native, "verify", lambda *args: events.append("verify"))
    monkeypatch.setattr(native, "run", lambda command, *args, **kwargs:
                        "test-commit\n" if "rev-parse" in command else "")
    monkeypatch.setattr(native, "coolprop_build_record", lambda cache, host, role: dict(
        consumer_role=role, role=role, platform=host, version="8.0.0", revision="locked-source",
        consumed_archive=str(native.coolprop_library(cache, host, role)),
        compile_groups=[dict(language="CXX", compileCommandFragments=[dict(
            fragment="-Os -DNDEBUG" if role == "preparation" else "-O3 -DNDEBUG")])],
        toolchains=[dict(language="CXX", compiler=dict(id="ActualCompiler", version="21.0"))],
        sdk=dict(cmake_cache={"CMAKE_OSX_SYSROOT": "/actual/SDK"})))
    monkeypatch.setattr(native, "result_build_record", lambda cache, host: dict(
        platform=host, toolchains=[dict(language='CXX', compiler=dict(id='ActualCompiler', version='21.0'))],
        sdk=dict(cmake_cache={'CMAKE_OSX_SYSROOT': '/actual/SDK'})))
    cache = tmp_path / ".cache/native-deps"
    builds = {"pilot": (SOLVER_LIBRARY, GEOMETRY_LIBRARY, PREPARATION_LIBRARY),
              "preparation": (PREPARATION_LIBRARY,), "result": (RESULT_LIBRARY,)}
    for build, names in builds.items():
        directory = cache / f"build/{build}-macos-arm64"
        directory.mkdir(parents=True)
        for name in names:
            # The full publication takes preparation from its own build, not from the pilot build.
            (directory / name).write_bytes(f"new verified {build} {name}".encode())
    target = tmp_path / "sjtu_tpmshx/solvers/native/lib/macos-arm64" / SOLVER_LIBRARY
    target.parent.mkdir(parents=True)
    for name in PUBLISHED:
        target.with_name(name).write_bytes(
            f'{{"source_commit": "previous {name}"}}\n'.encode() if name.endswith(".json")
            else f"previous qualified {name}".encode())
    return cache, cache / "build/pilot-macos-arm64" / SOLVER_LIBRARY, target, events


def test_publish_rebuilds_verifies_and_preserves_previous_library(publication):
    cache, source, target, events = publication
    before = _published_state(target)
    assert _publish(cache) == target
    assert events == ["build", "verify"]
    backup = target.parent / "previous"
    sources = {SOLVER_LIBRARY: source, GEOMETRY_LIBRARY: source.with_name(GEOMETRY_LIBRARY),
               PREPARATION_LIBRARY: cache / "build/preparation-macos-arm64" / PREPARATION_LIBRARY,
               RESULT_LIBRARY: cache / "build/result-macos-arm64" / RESULT_LIBRARY}
    records = {}
    for (library, record_name), component in zip(zip(PUBLISHED[::2], PUBLISHED[1::2]),
                                                  ("solver", "geometry", "preparation", "result")):
        published = target.with_name(library)
        assert published.read_bytes() == sources[library].read_bytes()
        assert (backup / library).read_bytes() == before[published]
        assert (backup / record_name).read_bytes() == before[target.with_name(record_name)]
        record = records[component] = json.loads(target.with_name(record_name).read_text())
        assert record["source_commit"] == "test-commit" and record["source_changes"] == []
        assert record["target_library"] == str(published)
        assert record["source_library"] == str(sources[library])
    assert records["solver"]["configuration"] == "Release"
    assert records["geometry"]["component"] == "geometry" and records["geometry"]["dependencies"] == {}
    preparation = records["preparation"]
    assert preparation["component"] == "preparation"
    assert preparation["coolprop_build"]["role"] == "preparation"
    assert records["solver"]["coolprop_build"]["role"] == "solver"
    assert preparation["coolprop_build"]["compile_groups"] != records["solver"]["coolprop_build"]["compile_groups"]
    assert set(preparation["dependencies"]) == {
        name for name, spec in native.LOCK['sources'].items()
        if name == 'coolprop' or 'cpm-name' in spec}
    result = records["result"]
    assert result['component'] == 'result' and result['dependencies'] == {}
    assert 'coolprop_build' not in result
    assert result['result_build']['toolchains'][0]['compiler']['id'] == 'ActualCompiler'
    # A second publication must not replace the first qualified backup.
    _publish(cache)
    assert (backup / SOLVER_LIBRARY).read_bytes() == before[target]
    assert (backup / GEOMETRY_LIBRARY).read_bytes() == before[target.with_name(GEOMETRY_LIBRARY)]


def test_archive_publication_records_unavailable_git_source(publication, monkeypatch):
    cache, _, target, events = publication
    (native.ROOT / ".git").rmdir()

    def unexpected_run(command, *args, **kwargs):
        pytest.fail(f"Archive publication ran a command: {command}")

    monkeypatch.setattr(native, "run", unexpected_run)
    assert native.publish(cache, "macos-arm64", Path("/python"), Path("/lock")) == target
    assert events == ["build", "verify"]
    for name in PUBLISHED[1::2]:
        record = json.loads(target.with_name(name).read_text())
        assert record["source_commit"] is None
        assert record["source_changes"] is None


@pytest.mark.parametrize("stage", ["build", "verify", "run", "copy", "missing-geometry", "missing-result"])
def test_failed_publication_keeps_current_libraries_and_records(publication, monkeypatch, stage):
    cache, source, target, _ = publication
    before = _published_state(target)
    error = FileNotFoundError if stage.startswith("missing") else RuntimeError

    def fail(*args, **kwargs):
        raise RuntimeError("publication failure")

    if stage == "missing-geometry":
        source.with_name(GEOMETRY_LIBRARY).unlink()
    elif stage == "missing-result":
        (cache / "build/result-macos-arm64" / RESULT_LIBRARY).unlink()
    elif stage == "copy":
        monkeypatch.setattr(native.shutil, "copy2", fail)
    else:
        monkeypatch.setattr(native, stage, fail)
    with pytest.raises(error):
        _publish(cache)
    assert _published_state(target) == before
    assert not (target.parent / "previous").exists()
    assert not list(target.parent.glob(".publish-*"))


# Each row selects the component, the file whose replacement fails, and a record that is absent before publication.
REPLACE_FAILURES = [
    *(("all", stage, missing) for stage in (SOLVER_RECORD, SOLVER_LIBRARY) for missing in (None, SOLVER_RECORD)),
    *(("all", stage, missing) for stage in PUBLISHED[2:] for missing in (None, GEOMETRY_RECORD)),
    *(("result", stage, missing) for stage in (RESULT_LIBRARY, RESULT_RECORD) for missing in (None, RESULT_RECORD)),
]


@pytest.mark.parametrize("component, stage, missing", REPLACE_FAILURES)
def test_failed_replace_restores_all_libraries_and_records(publication, monkeypatch, component, stage, missing):
    cache, _, target, _ = publication
    if missing:
        target.with_name(missing).unlink()
    before = _published_state(target)
    _fail_replace(monkeypatch, stage, PermissionError("library is in use"))
    with pytest.raises(PermissionError, match="library is in use"):
        _publish(cache, component)
    assert _published_state(target) == before
    assert not list(target.parent.glob(".publish-*"))


@pytest.mark.parametrize("component", ["solver", "geometry", "preparation", "result"])
def test_interrupt_after_real_replace_restores_all_libraries(publication, monkeypatch, component):
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
        _publish(cache)
    assert _published_state(target) == before
    assert not list(target.parent.glob(".publish-*"))


@pytest.mark.parametrize("component, library, record_name", [
    ("geometry", GEOMETRY_LIBRARY, GEOMETRY_RECORD),
    ("preparation", PREPARATION_LIBRARY, PREPARATION_RECORD),
    ("result", RESULT_LIBRARY, RESULT_RECORD)])
def test_component_publication_preserves_other_components_and_run_state(
        publication, monkeypatch, component, library, record_name):
    cache, _, target, _ = publication
    source = cache / f"build/{component}-macos-arm64" / library
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(f"standalone verified {component}".encode())
    previous = target.parent / "previous"
    previous.mkdir()
    (previous / SOLVER_LIBRARY).write_bytes(b"older solver")
    (previous / SOLVER_RECORD).write_bytes(b"older solver record")
    target.with_name("run-state.checkpoint").write_bytes(b"accepted run state")
    protected = [path for path in (*_published_state(target), *previous.iterdir(),
                                   target.with_name("run-state.checkpoint"))
                 if path.name not in {library, record_name}]
    before = {path: path.read_bytes() for path in protected}
    if component == "result":
        monkeypatch.setattr(native, "coolprop_build_record",
                            lambda *args: pytest.fail("result publication requested CoolProp build metadata"))

    actual = _publish(cache, component)

    assert actual == target.with_name(library)
    assert actual.read_bytes() == source.read_bytes()
    assert {path: path.read_bytes() for path in protected} == before
    assert (previous / library).read_bytes() == f"previous qualified {library}".encode()
    record = json.loads(target.with_name(record_name).read_text())
    assert record["component"] == component
    assert record["source_library"] == str(source)
    assert record["python_lock"] == str(LOCK)
    assert ("coolprop_build" in record) is (component == "preparation")


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
        _publish(cache)
    recovery, = target.parent.glob(".publish-*")
    assert str(recovery) in str(error.value)
    assert str(recovery) in capsys.readouterr().err
    assert (recovery / ("old-" + target.name)).read_bytes() == before[target]
    assert target.read_bytes() == b"new verified pilot " + SOLVER_LIBRARY.encode()
    for path, contents in before.items():
        if path != target:
            assert path.read_bytes() == contents
