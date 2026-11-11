"""Build isolated source and Python packages and check their actual contents."""
from __future__ import annotations

import argparse
from email.parser import Parser
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import traceback
import zipfile


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "sjtu_tpmshx"
NATIVE = PurePosixPath(PACKAGE) / "solvers/native"
TESTS = PurePosixPath(PACKAGE) / "development/tests"
FORBIDDEN_PARTS = {".cache", ".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".nbi", ".nbc", ".a", ".lib", ".dylib", ".dll", ".so",
                      ".o", ".obj", ".pdb", ".exe", ".h5", ".hdf5", ".npz", ".npy", ".checkpoint", ".ckpt"}
PRIVATE_FILES = {".venv-path", ".last_session.json", ".session_timeline.jsonl", ".first_run_done"}
GENERATED_HEADERS = {"native_state_build.hpp", "tpmshx/model_coefficients.hpp", "tpmshx/preparation_df_data.hpp"}
REQUIRED_RESOURCES = {
    f"{PACKAGE}/shared/configs/model_parameters_v1.json",
    f"{PACKAGE}/shared/configs/preparation_df_v1.json",
    f"{PACKAGE}/shared/configs/co2_segment2_v1.json",
    f"{PACKAGE}/shared/configs/sco2_effective_nu.json",
    f"{PACKAGE}/shared/configs/shanghai_baseline.json",
    f"{PACKAGE}/shared/df_surrogate/_prebuilt/cfd_full_core_3cell_fixed_v2.csv",
}


def forbidden(name: str) -> bool:
    path = PurePosixPath(name)
    return (bool(FORBIDDEN_PARTS.intersection(path.parts)) or "data" == path.parts[0]
            or path.name in PRIVATE_FILES or path.suffix.lower() in FORBIDDEN_SUFFIXES
            or path.is_relative_to(NATIVE / "lib"))


def retired_module(name: str) -> bool:
    path = PurePosixPath(name)
    return path.name == "local_heat_transfer.py" or "local_heat_transfer" in path.parts


def source_files(root: Path, directory: str) -> set[str]:
    return {path.relative_to(root).as_posix() for path in (root / directory).rglob("*")
            if path.is_file() and not forbidden(path.relative_to(root).as_posix())}


def expected_source_files(root: Path) -> set[str]:
    expected = {"pyproject.toml", "MANIFEST.in", "LICENSE", "README.md", "README.en.md", "requirements.txt"}
    for directory in (str(NATIVE), str(TESTS), "engineering", "docs", "examples"):
        expected.update(source_files(root, directory))
    expected.update(path.relative_to(root).as_posix() for path in (root / PACKAGE).rglob("*.py")
                    if not forbidden(path.relative_to(root).as_posix()))
    expected.update(declared_resources(root))
    return expected


def declared_resources(root: Path) -> set[str]:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = project["tool"]["setuptools"]["package-data"][PACKAGE]
    resources = {path.relative_to(root).as_posix() for pattern in patterns
                 for path in (root / PACKAGE).glob(pattern) if path.is_file()}
    missing = REQUIRED_RESOURCES - resources
    if missing:
        raise ValueError(f"Required runtime resources are not declared: {sorted(missing)}")
    return resources


def inspect_sdist(archive: Path, root: Path) -> tuple[str, list[str]]:
    with tarfile.open(archive) as source:
        members = [item.name for item in source.getmembers() if item.isfile()]
    tops = {PurePosixPath(name).parts[0] for name in members}
    if len(tops) != 1:
        raise ValueError("Source distribution must have one versioned root")
    top, = tops
    files = sorted(PurePosixPath(name).relative_to(top).as_posix() for name in members)
    invalid = [name for name in files if forbidden(name) or retired_module(name)]
    if invalid:
        raise ValueError(f"Source distribution includes excluded state or code: {invalid}")
    missing = expected_source_files(root) - set(files)
    if missing:
        raise ValueError(f"Source distribution omitted source/build inputs: {sorted(missing)}")
    return top, files


def check_native_closure(root: Path) -> dict:
    native = root / NATIVE
    checked, generated = 0, set()
    for path in native.rglob("*"):
        if not path.is_file() or path.suffix not in {".c", ".cpp", ".h", ".hpp", ".inc"}:
            continue
        text = path.read_text(encoding="utf-8")
        for include in re.findall(r'^\s*#\s*include\s*"([^"]+)"', text, flags=re.MULTILINE):
            if include in GENERATED_HEADERS:
                generated.add(include)
                continue
            candidates = (path.parent / include, native / "include" / include, native / "src" / include)
            if not any(candidate.is_file() for candidate in candidates):
                raise ValueError(f"Source distribution omitted local include {include} required by {path.relative_to(root)}")
            checked += 1
    cmake_inputs = set()
    for path in native.rglob("*"):
        if not path.is_file() or not (path.name == "CMakeLists.txt" or path.suffix == ".cmake"):
            continue
        text = path.read_text(encoding="utf-8")
        for relative in re.findall(r'\$\{TPMSHX_NATIVE_ROOT\}/([^"\s;)]+)', text):
            if "${" in relative:
                continue
            target = native / relative
            if not target.exists():
                raise ValueError(f"Source distribution omitted CMake input {relative} required by {path.relative_to(root)}")
            cmake_inputs.add(target.relative_to(root).as_posix())
    return dict(local_includes=checked, cmake_inputs=sorted(cmake_inputs),
                generated_headers=sorted(generated))


def inspect_wheel(archive: Path, root: Path) -> list[str]:
    resources = declared_resources(root)
    python = {name for name in source_files(root, PACKAGE) if name.endswith(".py")
              and not PurePosixPath(name).is_relative_to(NATIVE)
              and not PurePosixPath(name).is_relative_to(TESTS)}
    with zipfile.ZipFile(archive) as source:
        files = sorted(name for name in source.namelist() if not name.endswith("/"))
        metadata = {PurePosixPath(name).parts[0] for name in files if ".dist-info/" in name}
        if len(metadata) != 1:
            raise ValueError("Python wheel must have one package metadata directory")
        metadata_root, = metadata
        extra = [name for name in files if forbidden(name) or retired_module(name)
                 or PurePosixPath(name).is_relative_to(TESTS)
                 or (name not in python | resources and not name.startswith(metadata_root + "/"))]
        if extra:
            raise ValueError(f"Python wheel includes undeclared data, native code or state: {extra}")
        missing = (python | resources) - set(files)
        if missing:
            raise ValueError(f"Python wheel omitted modules or resources: {sorted(missing)}")
        for name in resources:
            if source.read(name) != (root / name).read_bytes():
                raise ValueError(f"Python wheel changed resource bytes: {name}")
        wheel = Parser().parsestr(source.read(metadata_root + "/WHEEL").decode())
        if wheel["Root-Is-Purelib"] != "true" or wheel.get_all("Tag") != ["py3-none-any"]:
            raise ValueError("Python wheel unexpectedly declares a native build")
    return files


def _source_copy(root: Path, destination: Path) -> None:
    def ignore(directory, names):
        ignored = []
        for name in names:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if (forbidden(relative) or any(part.endswith(".egg-info") for part in path.relative_to(root).parts)
                    or (path.is_symlink() and not path.resolve().is_relative_to(root))):
                ignored.append(name)
        return ignored
    shutil.copytree(root, destination, ignore=ignore)


def _build(python: Path, directory: Path, output: Path, kind: str, log: Path) -> Path:
    output.mkdir(parents=True)
    program = ("import sys; from setuptools import build_meta; "
               f"print(build_meta.build_{kind}(sys.argv[1]))")
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    environment.pop("PYTHONPATH", None)
    try:
        result = subprocess.run([str(python), "-c", program, str(output)], cwd=directory,
                                env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=300)
    except subprocess.TimeoutExpired as error:
        partial = error.stdout or ""
        log.write_text(partial.decode(errors="replace") if isinstance(partial, bytes) else partial,
                       encoding="utf-8")
        raise RuntimeError(f"{kind} build timed out; see {log}") from error
    log.write_text(result.stdout, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"{kind} build failed ({result.returncode}); see {log}")
    files = list(output.iterdir())
    if len(files) != 1 or not files[0].is_file():
        raise RuntimeError(f"{kind} build did not produce one archive in {output}")
    return files[0]


def check(output: Path) -> dict:
    if Path.cwd().resolve() != ROOT:
        raise RuntimeError("Run this check from the current repository root")
    configured = Path((ROOT / ".venv-path").read_text(encoding="utf-8-sig").splitlines()[0].strip())
    if not configured.is_absolute() or os.path.normcase(str(configured)) != os.path.normcase(sys.executable):
        raise RuntimeError("Use the absolute interpreter recorded in .venv-path")
    version = importlib.metadata.version("setuptools")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    if project["build-system"]["requires"] != [f"setuptools=={version}"]:
        raise RuntimeError("The active setuptools version differs from the declared build backend")
    output = output.resolve()
    if not output.is_relative_to(ROOT / ".cache"):
        raise ValueError("Distribution check outputs must remain in this worktree's .cache/")
    output.mkdir(parents=True, exist_ok=False)
    report = dict(status="running", interpreter=str(configured), setuptools=version,
                  source_root=str(ROOT), output_directory=str(output))
    working = output / "working"
    try:
        working.mkdir()
        source = working / "source"
        _source_copy(ROOT, source)
        sdist = _build(configured, source, output / "sdist", "sdist", output / "sdist.log")
        report["sdist"] = dict(archive=str(sdist))
        top, members = inspect_sdist(sdist, ROOT)
        report["sdist"] = dict(archive=str(sdist), files=members)
        direct = _build(configured, source, output / "wheel-direct", "wheel", output / "wheel-direct.log")
        direct_members = inspect_wheel(direct, ROOT)
        report["wheel_direct"] = dict(archive=str(direct), files=direct_members)
        unpacked = working / "unpacked"
        unpacked.mkdir()
        with tarfile.open(sdist) as archive:
            archive.extractall(unpacked, filter="data")
        restored = unpacked / top
        report["native_source_closure"] = check_native_closure(restored)
        rebuilt = _build(configured, restored, output / "wheel-from-sdist", "wheel", output / "wheel-from-sdist.log")
        rebuilt_members = inspect_wheel(rebuilt, ROOT)
        report["wheel_from_sdist"] = dict(archive=str(rebuilt), files=rebuilt_members)
        if direct_members != rebuilt_members:
            raise ValueError("Direct and sdist-derived wheel file inventories differ")
        report["status"] = "passed"
        shutil.rmtree(working)
        report["removed_working_tree"] = str(working)
    except BaseException:
        report.update(status="failed", traceback=traceback.format_exc())
        raise
    finally:
        (output / "inventory.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="A new directory under this worktree's .cache/")
    options = parser.parse_args()
    report = check(options.output_dir)
    print(json.dumps(dict(status=report["status"], inventory=str(options.output_dir / "inventory.json"))))


if __name__ == "__main__":
    main()
