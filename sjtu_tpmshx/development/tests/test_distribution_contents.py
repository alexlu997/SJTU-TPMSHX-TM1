"""Check actual archive boundaries without reading manifest rules as expectations."""
from io import BytesIO
import tarfile
import zipfile

import pytest

from engineering.scripts import check_distributions as distributions


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    for name in ("LICENSE", "README.md", "README.en.md", "requirements.txt", "MANIFEST.in"):
        (root / name).write_text("source input\n")
    (root / "pyproject.toml").write_text(
        '[tool.setuptools.package-data]\nsjtu_tpmshx = ["shared/configs/*.json", "shared/df_surrogate/_prebuilt/*.csv"]\n')
    for name in distributions.REQUIRED_RESOURCES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"original resource\n")
    files = {
        "sjtu_tpmshx/__init__.py": '"""Package."""\n',
        "sjtu_tpmshx/solvers/native/src/model_complex_log.c": '#include "tpmshx/model_math.h"\n',
        "sjtu_tpmshx/solvers/native/include/tpmshx/model_math.h": "/* Local declaration. */\n",
        "sjtu_tpmshx/solvers/native/preparation/CMakeLists.txt":
            'add_library(models "${TPMSHX_NATIVE_ROOT}/src/model_complex_log.c")\n',
        "engineering/scripts/build_native_dependencies.py": '"""Explicit source build."""\n',
        "docs/build.md": "Source instructions.\n",
        "examples/input.json": "{}\n",
    }
    for name, contents in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    return root


def source_archive(root, output, *, omit=(), extra=None):
    with tarfile.open(output, "w:gz") as archive:
        for path in root.rglob("*"):
            name = path.relative_to(root).as_posix()
            if path.is_file() and name not in omit:
                archive.add(path, arcname="project-1.0/" + name)
        for name, value in (extra or {}).items():
            item = tarfile.TarInfo("project-1.0/" + name)
            item.size = len(value)
            archive.addfile(item, BytesIO(value))


def wheel_archive(root, output, *, extra=None, change_resource=False):
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("sjtu_tpmshx/__init__.py", (root / "sjtu_tpmshx/__init__.py").read_bytes())
        for name in distributions.declared_resources(root):
            value = (root / name).read_bytes()
            if change_resource and name.endswith("preparation_df_v1.json"):
                value += b"changed"
            archive.writestr(name, value)
        archive.writestr("sjtu_tpmshx-1.0.dist-info/METADATA", "Name: sjtu-tpmshx\nVersion: 1.0\n")
        archive.writestr("sjtu_tpmshx-1.0.dist-info/WHEEL", "Root-Is-Purelib: true\nTag: py3-none-any\n")
        for name, value in (extra or {}).items():
            archive.writestr(name, value)


def test_source_archive_keeps_native_helper_and_its_local_build_closure(project, tmp_path):
    archive = tmp_path / "source.tar.gz"
    source_archive(project, archive, extra={"sjtu_tpmshx.egg-info/PKG-INFO": b"generated metadata"})
    _, files = distributions.inspect_sdist(archive, project)
    assert "sjtu_tpmshx/solvers/native/src/model_complex_log.c" in files
    assert distributions.check_native_closure(project)["local_includes"] == 1
    header = project / "sjtu_tpmshx/solvers/native/include/tpmshx/model_math.h"
    header.unlink()
    with pytest.raises(ValueError, match="omitted local include"):
        distributions.check_native_closure(project)


def test_source_archive_rejects_the_confirmed_native_source_omission(project, tmp_path):
    archive = tmp_path / "source.tar.gz"
    source_archive(project, archive, omit={"sjtu_tpmshx/solvers/native/src/model_complex_log.c"})
    with pytest.raises(ValueError, match="omitted source/build inputs"):
        distributions.inspect_sdist(archive, project)


@pytest.mark.parametrize("name", ["sjtu_tpmshx/solvers/native/src/model_complex_log.c",
    "sjtu_tpmshx/solvers/native/lib/macos-arm64/libtpmshx_preparation_shared.dylib",
    "sjtu_tpmshx/shared/models/local_heat_transfer.py"])
def test_wheel_rejects_native_sources_binaries_and_retired_module(project, tmp_path, name):
    archive = tmp_path / "package.whl"
    wheel_archive(project, archive, extra={name: b"unexpected content"})
    with pytest.raises(ValueError, match="undeclared data, native code or state"):
        distributions.inspect_wheel(archive, project)


def test_wheel_keeps_declared_resource_bytes(project, tmp_path):
    archive = tmp_path / "package.whl"
    wheel_archive(project, archive)
    files = distributions.inspect_wheel(archive, project)
    assert distributions.REQUIRED_RESOURCES.issubset(files)
    wheel_archive(project, archive, change_resource=True)
    with pytest.raises(ValueError, match="changed resource bytes"):
        distributions.inspect_wheel(archive, project)


def test_fresh_source_copy_does_not_use_or_remove_existing_root_build_outputs(project, tmp_path):
    for name in ("build", "dist", "sjtu_tpmshx.egg-info"):
        directory = project / name
        directory.mkdir()
        (directory / "keep").write_text("unrelated output")
    copy = tmp_path / "isolated-source"
    distributions._source_copy(project, copy)
    for name in ("build", "dist", "sjtu_tpmshx.egg-info"):
        assert (project / name / "keep").read_text() == "unrelated output"
        assert not (copy / name).exists()
