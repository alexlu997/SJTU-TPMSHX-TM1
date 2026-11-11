"""Check actual archive boundaries without reading manifest rules as expectations."""
from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
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
        "sjtu_tpmshx/development/tests/__init__.py": "",
        "sjtu_tpmshx/development/tests/native/reference.py": "value = 1\n",
        "sjtu_tpmshx/development/tests/native/bridge.cpp": "/* Independent test bridge. */\n",
        "sjtu_tpmshx/development/tests/_ci_shard0.txt": "test_case.py\n",
        "sjtu_tpmshx/development/runs/tool.py": "value = 2\n",
        "sjtu_tpmshx/development/validation/reference.py": "value = 3\n",
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
        for name in ("sjtu_tpmshx/__init__.py", "sjtu_tpmshx/development/runs/tool.py",
                     "sjtu_tpmshx/development/validation/reference.py"):
            archive.writestr(name, (root / name).read_bytes())
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
    assert "sjtu_tpmshx/development/tests/native/reference.py" in files
    assert "sjtu_tpmshx/development/tests/native/bridge.cpp" in files
    assert "sjtu_tpmshx/development/tests/_ci_shard0.txt" in files
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
    "sjtu_tpmshx/shared/models/local_heat_transfer.py",
    "sjtu_tpmshx/development/tests/__init__.py",
    "sjtu_tpmshx/development/tests/native/reference.py",
    "sjtu_tpmshx/development/tests/native/bridge.cpp"])
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
    assert "sjtu_tpmshx/development/runs/tool.py" in files
    assert "sjtu_tpmshx/development/validation/reference.py" in files
    assert not any("/development/tests/" in name for name in files)
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


@pytest.mark.parametrize("name", ["sjtu_tpmshx/development/tests/native/reference.py",
    "sjtu_tpmshx/development/tests/native/bridge.cpp", "sjtu_tpmshx/development/tests/_ci_shard0.txt"])
def test_source_archive_requires_the_complete_test_tree(project, tmp_path, name):
    archive = tmp_path / "source.tar.gz"
    source_archive(project, archive, omit={name})
    with pytest.raises(ValueError, match="omitted source/build inputs"):
        distributions.inspect_sdist(archive, project)


@pytest.mark.parametrize("explicit", [False, True])
def test_manifest_tool_creates_the_selected_parent(tmp_path, monkeypatch, explicit):
    from sjtu_tpmshx.development.runs.tools import build_fast_tier_manifest as manifest

    log = tmp_path / "durations.log"
    log.write_text("31.0s call test_case.py::test_case\n")
    output = tmp_path / "missing" / "tests" / "manifest.txt"
    monkeypatch.setattr(manifest, "_DEF_OUT", output)
    args = ["--log", str(log)] + (["--out", str(output)] if explicit else [])
    assert manifest.main(args) == 0
    assert output.read_text().endswith("test_case.py::test_case\n")


def test_manifest_tool_keeps_write_errors(tmp_path, monkeypatch):
    from sjtu_tpmshx.development.runs.tools import build_fast_tier_manifest as manifest

    log = tmp_path / "durations.log"
    log.write_text("31.0s call test_case.py::test_case\n")
    def denied(*args, **kwargs):
        raise PermissionError("output is read-only")
    monkeypatch.setattr(Path, "write_text", denied)
    with pytest.raises(PermissionError, match="output is read-only"):
        manifest.main(["--log", str(log), "--out", str(tmp_path / "missing" / "out.txt")])


_INSTALLED_SMOKE = r"""
import importlib.metadata
import importlib.util
from importlib.resources import files
import json
from pathlib import Path
import sys

installed = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(installed))
import sjtu_tpmshx
assert Path(sjtu_tpmshx.__file__).resolve().is_relative_to(installed)
assert importlib.util.find_spec('sjtu_tpmshx.development.tests') is None
package = files('sjtu_tpmshx')
for name in json.loads(sys.argv[3]):
    assert package.joinpath(*name.split('/')[1:]).read_bytes()
from sjtu_tpmshx.shared.configs import load_shanghai_baseline
from sjtu_tpmshx.shared.configs.model_parameters import (
    load_model_parameters, load_co2_coefficients, load_preparation_df_parameters,
)
assert load_shanghai_baseline() and load_model_parameters()
assert load_co2_coefficients() and load_preparation_df_parameters()
from sjtu_tpmshx.development.validation.harness._order_fit import fit_order_loglog
assert abs(fit_order_loglog([1., .5, .25], [1., .25, .0625]).p - 2.) < 1e-12
from sjtu_tpmshx.development.runs.tools import build_fast_tier_manifest as manifest
log = Path('durations.log')
log.write_text('31.0s call test_case.py::test_case\n')
assert manifest.main(['--log', str(log)]) == 0
assert manifest._DEF_OUT.read_text().endswith('test_case.py::test_case\n')
entry, = [item for item in importlib.metadata.distribution('sjtu-tpmshx').entry_points
          if item.group == 'console_scripts' and item.name == 'tpmshx-run']
main = entry.load()
try:
    main(['--help'])
except SystemExit as error:
    assert error.code == 0
else:
    raise AssertionError('CLI help must exit successfully')
assert main([sys.argv[2], '--dry-run', '--json']) == 0
assert not any(name.split('.')[0] in ('PySide6', 'CoolProp') for name in sys.modules)
print('installed CLI, resources and retained tools passed')
"""


@pytest.mark.parametrize("kind", ["wheel-direct", "wheel-from-sdist"])
def test_installed_wheel_runtime(kind):
    directory = os.environ.get("TM1_WHEEL_DIR")
    if directory is None:
        pytest.skip("requires the actual direct and sdist-derived wheels")
    import json

    wheel, = (Path(directory).resolve() / kind).glob("*.whl")
    root = Path(__file__).resolve().parents[3]
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    with TemporaryDirectory(prefix="tm1-wheel-") as directory:
        target = Path(directory) / "installed"
        subprocess.run([sys.executable, "-I", "-m", "pip", "install", "--no-deps", "--no-index",
                        "--no-compile", "--target", str(target), str(wheel)],
                       cwd=directory, env=env, check=True, capture_output=True, text=True, timeout=120)
        result = subprocess.run([sys.executable, "-I", "-c", _INSTALLED_SMOKE, str(target),
                                 str(root / "examples/three_module/air_2d.json"),
                                 json.dumps(sorted(distributions.declared_resources(root)))],
                                cwd=directory, env=env, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
