"""Explicit publication preserves the working library until validation succeeds."""
import json
from pathlib import Path

import pytest

from scripts import build_native_dependencies as native


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
    target = tmp_path / "native/lib/macos-arm64" / name
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previous qualified library")
    target.with_name("build.json").write_text('{"source_commit": "previous"}\n')
    return cache, source, target, events


def test_publish_rebuilds_verifies_and_preserves_previous_library(publication):
    cache, source, target, events = publication
    actual = native.publish(cache, "macos-arm64", Path("/python"), Path("requirements-lock.txt"))
    assert events == ["build", "verify"]
    assert actual == target and target.read_bytes() == source.read_bytes()
    backup = target.parent / "previous"
    assert (backup / target.name).read_bytes() == b"previous qualified library"
    assert json.loads((backup / "build.json").read_text())["source_commit"] == "previous"
    record = json.loads(target.with_name("build.json").read_text())
    assert record["source_commit"] == "test-commit"
    assert record["configuration"] == "Release"
    assert record["target_library"] == str(target)
    native.publish(cache, "macos-arm64", Path("/python"), Path("requirements-lock.txt"))
    assert (backup / target.name).read_bytes() == b"previous qualified library"


@pytest.mark.parametrize("stage", ["build", "verify", "copy"])
def test_failed_publication_keeps_current_library_and_record(publication, monkeypatch, stage):
    cache, _, target, _ = publication

    def fail(*args, **kwargs):
        raise RuntimeError("publication failure")

    if stage == "copy":
        monkeypatch.setattr(native.shutil, "copy2", fail)
    else:
        monkeypatch.setattr(native, stage, fail)
    with pytest.raises(RuntimeError, match="publication failure"):
        native.publish(cache, "macos-arm64", Path("/python"), Path("requirements-lock.txt"))
    assert target.read_bytes() == b"previous qualified library"
    assert json.loads(target.with_name("build.json").read_text())["source_commit"] == "previous"
    assert not (target.parent / "previous").exists()


@pytest.mark.parametrize("stage", ["build.json", "libtpmshx_solver_shared.dylib"])
@pytest.mark.parametrize("existing_record", [True, False])
def test_failed_final_replace_restores_build_record(publication, monkeypatch, stage, existing_record):
    cache, _, target, _ = publication
    metadata = target.with_name("build.json")
    if not existing_record:
        metadata.unlink()
    replace = Path.replace

    def fail_selected(path, destination):
        if path.name == stage:
            raise PermissionError("library is in use")
        return replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_selected)
    with pytest.raises(PermissionError, match="library is in use"):
        native.publish(cache, "macos-arm64", Path("/python"), Path("requirements-lock.txt"))
    assert target.read_bytes() == b"previous qualified library"
    assert metadata.is_file() == existing_record
    if existing_record:
        assert json.loads(metadata.read_text())["source_commit"] == "previous"
