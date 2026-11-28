"""Check actual archive boundaries without reading manifest rules as expectations."""
from io import BytesIO
import os
from pathlib import Path, PureWindowsPath
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import tarfile
import zipfile

import pytest

from engineering.scripts import check_distributions as distributions


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    for name in ("LICENSE", "README.md", "README.en.md", "requirements.txt", "MANIFEST.in", "CMakeLists.txt"):
        (root / name).write_text("source input\n")
    (root / "pyproject.toml").write_text(
        '[project]\ndependencies = ["h5py>=3.16"]\n'
        '[project.optional-dependencies]\noffline = ["CoolProp>=8.0"]\n'
        '[tool.setuptools.package-data]\ntm1 = ["model_configs/*.json", "physical_models/df_surrogate/_prebuilt/*.csv"]\n')
    for name in distributions.REQUIRED_RESOURCES:
        path = root / "python" / Path(name).relative_to("tm1")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"original resource\n")
    files = {
        "main.py": "",
        "tm1.py": "",
        "tests/__init__.py": "",
        "tests/python/__init__.py": "",
        "tests/python/native/reference.py": "value = 1\n",
        "tests/python/native/bridge.cpp": "/* Independent test bridge. */\n",
        "tests/python/_ci_shard0.txt": "test_case.py\n",
        "python/development/runs/tool.py": "value = 2\n",
        "python/development/validation/reference.py": "value = 3\n",
        "python/__init__.py": '"""Package."""\n',
        "numerics/fluid_properties.cpp": '#include "tpmshx/model_math.h"\n',
        "include/tpmshx/model_math.h": "/* Local declaration. */\n",
        "preprocess/CMakeLists.txt":
            'add_library(models "${TPMSHX_ROOT}/numerics/fluid_properties.cpp")\n',
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


def wheel_archive(root, output, *, extra=None, change_resource=False,
                  dependency_headers='Provides-Extra: offline\nRequires-Dist: h5py>=3.16\n'
                                     'Requires-Dist: CoolProp>=8.0; extra == "offline"\n'):
    with zipfile.ZipFile(output, "w") as archive:
        for name in ("__init__.py", "development/runs/tool.py", "development/validation/reference.py"):
            archive.writestr("tm1/" + name, (root / "python" / name).read_bytes())
        for name in distributions.declared_resources(root):
            value = (root / "python" / Path(name).relative_to("tm1")).read_bytes()
            if change_resource and name.endswith("preparation_df_v1.json"):
                value += b"changed"
            archive.writestr(name, value)
        archive.writestr("tm1-1.0.dist-info/METADATA",
                         "Name: tm1\nVersion: 1.0\n" + dependency_headers)
        archive.writestr("tm1-1.0.dist-info/WHEEL", "Root-Is-Purelib: true\nTag: py3-none-any\n")
        for name, value in (extra or {}).items():
            archive.writestr(name, value)


def test_source_archive_keeps_native_helper_and_its_local_build_closure(project, tmp_path):
    archive = tmp_path / "source.tar.gz"
    source_archive(project, archive, extra={"tm1.egg-info/PKG-INFO": b"generated metadata"})
    _, files = distributions.inspect_sdist(archive, project)
    assert "numerics/fluid_properties.cpp" in files
    assert "tests/python/native/reference.py" in files
    assert "tests/python/native/bridge.cpp" in files
    assert "tests/python/_ci_shard0.txt" in files
    assert distributions.check_native_closure(project)["local_includes"] == 1
    header = project / "include/tpmshx/model_math.h"
    header.unlink()
    with pytest.raises(ValueError, match="omitted local include"):
        distributions.check_native_closure(project)


def test_source_archive_excludes_local_cfd_output(project, tmp_path):
    name = "python/development/runs/_out/asym_cfd/asym_cfd_worklist.xlsx"
    path = project / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"local test data")
    archive = tmp_path / "source.tar.gz"
    source_archive(project, archive, omit={name})
    distributions.inspect_sdist(archive, project)
    source_archive(project, archive)
    with pytest.raises(ValueError, match="excluded state"):
        distributions.inspect_sdist(archive, project)


def test_source_archive_rejects_the_confirmed_native_source_omission(project, tmp_path):
    archive = tmp_path / "source.tar.gz"
    source_archive(project, archive, omit={"numerics/fluid_properties.cpp"})
    with pytest.raises(ValueError, match="omitted source/build inputs"):
        distributions.inspect_sdist(archive, project)


@pytest.mark.parametrize("name", ["python/physical_models/quick_design.py",
                                  "python/preprocess/thermal_geometry.py"])
def test_source_archive_rejects_retired_numerics(project, tmp_path, name):
    archive = tmp_path / "source.tar.gz"
    source_archive(project, archive, extra={name: b"retired code"})
    with pytest.raises(ValueError, match="excluded state or code"):
        distributions.inspect_sdist(archive, project)


@pytest.mark.parametrize("name", ["numerics/fluid_properties.cpp",
    "native/lib/macos-arm64/libtpmshx_preparation_shared.dylib",
    "tm1/physical_models/local_heat_transfer.py",
    "tm1/physical_models/quick_design.py",
    "tm1/preprocess/thermal_geometry.py",
    "main.py",
    "tm1.py",
    "tm1/development/tests/native/reference.py",
    "tests/python/__init__.py",
    "tests/python/native/reference.py",
    "tests/python/native/bridge.cpp"])
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
    assert "tm1/development/runs/tool.py" in files
    assert "tm1/development/validation/reference.py" in files
    assert not any(name.startswith("tests/") or "/development/tests/" in name for name in files)
    wheel_archive(project, archive, change_resource=True)
    with pytest.raises(ValueError, match="changed resource bytes"):
        distributions.inspect_wheel(archive, project)


def test_wheel_rejects_an_optional_dependency_in_core(project, tmp_path):
    archive = tmp_path / "package.whl"
    wheel_archive(project, archive, dependency_headers="Provides-Extra: offline\n"
                  "Requires-Dist: h5py>=3.16\nRequires-Dist: CoolProp>=8.0\n")
    with pytest.raises(ValueError, match="Wheel dependencies differ.*CoolProp"):
        distributions.inspect_wheel(archive, project)


def test_fresh_source_copy_does_not_use_or_remove_existing_root_build_outputs(project, tmp_path):
    for name in ("build", "dist", "tm1.egg-info"):
        directory = project / name
        directory.mkdir()
        (directory / "keep").write_text("unrelated output")
    copy = tmp_path / "isolated-source"
    distributions._source_copy(project, copy)
    for name in ("build", "dist", "tm1.egg-info"):
        assert (project / name / "keep").read_text() == "unrelated output"
        assert not (copy / name).exists()


@pytest.mark.parametrize("name", ["tests/python/native/reference.py",
    "tests/python/native/bridge.cpp", "tests/python/_ci_shard0.txt"])
def test_source_archive_requires_the_complete_test_tree(project, tmp_path, name):
    archive = tmp_path / "source.tar.gz"
    source_archive(project, archive, omit={name})
    with pytest.raises(ValueError, match="omitted source/build inputs"):
        distributions.inspect_sdist(archive, project)


@pytest.mark.parametrize("explicit", [False, True])
def test_manifest_tool_creates_the_selected_parent(tmp_path, monkeypatch, explicit):
    from tm1.development.runs.tools import build_fast_tier_manifest as manifest

    log = tmp_path / "durations.log"
    log.write_text("31.0s call test_case.py::test_case\n")
    output = tmp_path / "missing" / "tests" / "manifest.txt"
    monkeypatch.setattr(manifest, "_DEF_OUT", output)
    args = ["--log", str(log)] + (["--out", str(output)] if explicit else [])
    assert manifest.main(args) == 0
    assert output.read_text().endswith("test_case.py::test_case\n")


def test_manifest_tool_keeps_write_errors(tmp_path, monkeypatch):
    from tm1.development.runs.tools import build_fast_tier_manifest as manifest

    log = tmp_path / "durations.log"
    log.write_text("31.0s call test_case.py::test_case\n")
    def denied(*args, **kwargs):
        raise PermissionError("output is read-only")
    monkeypatch.setattr(Path, "write_text", denied)
    with pytest.raises(PermissionError, match="output is read-only"):
        manifest.main(["--log", str(log), "--out", str(tmp_path / "missing" / "out.txt")])


_INSTALLED_SMOKE = r"""
import importlib.util
from importlib.resources import files
import json
from pathlib import Path, PureWindowsPath
import sys

installed = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(installed))
import tm1
assert Path(tm1.__file__).resolve().is_relative_to(installed)
assert importlib.util.find_spec('tm1.development.tests') is None
package = files('tm1')
for name in json.loads(sys.argv[3]):
    assert package.joinpath(*name.split('/')[1:]).read_bytes()
from tm1.model_configs import load_shanghai_baseline
from tm1.model_configs.model_parameters import (
    load_model_parameters, load_co2_coefficients, load_preparation_df_parameters,
)
assert load_shanghai_baseline() and load_model_parameters()
from tm1.physical_models.co2_correlations import coefficients
assert coefficients() == load_co2_coefficients() and load_preparation_df_parameters()
from tm1.preprocess.offline import load_core, load_segments
assert callable(load_core) and callable(load_segments)
from tm1.development.validation.harness._order_fit import fit_order_loglog
assert abs(fit_order_loglog([1., .5, .25], [1., .25, .0625]).p - 2.) < 1e-12
from tm1.development.runs.tools import build_fast_tier_manifest as manifest
foreign = installed / 'tests/python/foreign.py'
foreign.parent.mkdir(parents=True)
foreign.write_text('raise AssertionError("unrelated tests")')
from tm1.development.runs.tools import audit_import_graph
assert foreign not in set(audit_import_graph.source_paths())
log = Path('durations.log')
log.write_text('31.0s call test_case.py::test_case\n')
assert manifest._DEF_OUT == installed / 'tm1/development/tests/_fast_tier_manifest.txt'
assert manifest.main(['--log', str(log)]) == 0
assert manifest._DEF_OUT.read_text().endswith('test_case.py::test_case\n')
from tm1.applications.cli.main import main
try:
    main(['--help'])
except SystemExit as error:
    assert error.code == 0
else:
    raise AssertionError('CLI help must exit successfully')
assert main([sys.argv[2], '--dry-run', '--json']) == 0
assert not {'PySide6', 'CoolProp', 'sympy', 'skimage'}.intersection(sys.modules)
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
        result = subprocess.run([sys.executable, "-m", "tm1.development.runs.cfd_asym.ingest_cfd_kappa", "--help"],
                                cwd=directory, env=dict(env, PYTHONPATH=str(target), PYTHONIOENCODING="cp1252:strict"),
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout


def test_wheel_check_accepts_windows_source_paths(project, tmp_path, monkeypatch):
    archive = tmp_path / "package.whl"
    wheel_archive(project, archive)
    rglob = Path.rglob

    def windows_paths(directory, pattern):
        for path in rglob(directory, pattern):
            yield SimpleNamespace(
                is_file=path.is_file,
                relative_to=lambda root, path=path: PureWindowsPath(path.relative_to(root)),
            )

    monkeypatch.setattr(Path, "rglob", windows_paths)
    assert distributions.inspect_wheel(archive, project)
