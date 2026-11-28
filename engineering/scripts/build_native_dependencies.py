"""Explicitly fetch, build, verify, or publish the locked native libraries.

No package installation, production binding, system PATH change or runtime
download. Run with the interpreter recorded on the first line of .venv-path.
The build command is offline; only fetch commands use the network.
"""
from __future__ import annotations

import argparse
import csv
import ctypes as ct
from datetime import datetime, timezone
import filecmp
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

if __package__:
    from . import build_coolprop
else:  # Script execution puts this directory first on sys.path.
    import build_coolprop


ROOT = Path(__file__).resolve().parents[2]
LOCK = tomllib.loads((ROOT / "engineering/native_build/dependencies-lock.toml").read_text())
PREPARATION_CALLERS = (
    "preparation_c_static", "preparation_c_shared",
    "preparation_case_c_static", "preparation_case_c_shared",
    "preparation_case_3d_c_static", "preparation_case_3d_c_shared",
    "quick_prepare_c_static", "quick_prepare_c_shared",
)
# Published images and their build records, in publication order.
PUBLISHED_LIBRARIES = (("solver", "build.json"), ("geometry", "geometry-build.json"),
                       ("preparation", "preparation-build.json"), ("result", "result-build.json"))


def run(command: list[str | Path], log: Path, *, cwd: Path = ROOT,
        input_text: str | None = None, env: dict[str, str] | None = None) -> str:
    """Preserve complete command output, including failures, in the cache."""
    command = [str(arg) for arg in command]
    print(subprocess.list2cmdline(command), flush=True)
    result = subprocess.run(command, cwd=cwd, input=input_text, text=True, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(subprocess.list2cmdline(command) + "\n" + result.stdout)
        stream.write(f"\nexit={result.returncode}\n")
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}); see {log}\n{result.stdout[-4000:]}")
    return result.stdout


def stage_native_notices(root: Path, destination: Path) -> list[Path]:
    """Copy the native notices and keep links between distributed files valid."""
    entries = [line.split("\t") for line in (root / "engineering/native_build/notice-files.tsv")
               .read_text(encoding="utf-8").splitlines()]
    for source, installed in entries:
        path = root / source
        target = destination / installed
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix != ".md":
            shutil.copyfile(path, target)
            continue
        document = path.read_text(encoding="utf-8")
        for other, packaged in entries:
            old = os.path.relpath(root / other, path.parent).replace(os.sep, "/")
            new = os.path.relpath(destination / packaged, target.parent).replace(os.sep, "/")
            document = document.replace(f"]({old})", f"]({new})").replace(f"]({old}#", f"]({new}#")
        target.write_text(document, encoding="utf-8")
    return [destination / installed for _, installed in entries]


def platform_name() -> str:
    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine == "arm64":
        return "macos-arm64"
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "windows-x64"
    if sys.platform == "linux" and machine in {"amd64", "x86_64"}:
        return "linux-x86_64"
    raise RuntimeError("Native builds support macOS arm64, Windows x64, and the Linux x86_64 result component")


def require_component(host: str, component: str) -> None:
    if host == "linux-x86_64" and component != "result":
        raise RuntimeError("Linux x86_64 supports only --component result")


def shared_library_name(host: str, component: str) -> str:
    if host == "windows-x64":
        return f"tpmshx_{component}_shared.dll"
    suffix = ".so" if host == "linux-x86_64" else ".dylib"
    return f"libtpmshx_{component}_shared{suffix}"


def configured_python() -> Path:
    lines = (ROOT / ".venv-path").read_text(encoding="utf-8-sig").splitlines()
    python = Path(lines[0].strip()) if lines else Path()
    if not python.is_absolute() or not python.is_file():
        raise RuntimeError(".venv-path must name an existing absolute interpreter")
    if os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(str(python)):
        raise RuntimeError(f"Run this script with the configured interpreter: {python}")
    return python


def download(url: str, target: Path) -> None:
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".partial")
    print(f"Download {url}", flush=True)
    with urllib.request.urlopen(url, timeout=120) as source, partial.open("wb") as output:
        shutil.copyfileobj(source, output)
    partial.replace(target)


def verify_sources(cache: Path, *, models_only: bool = False) -> None:
    for name, spec in LOCK["sources"].items():
        if models_only and name != "coolprop" and "cpm-name" not in spec:
            continue
        source = cache / "src" / spec["directory"]
        log = cache / "logs" / f"verify-source-{name}.log"
        actual = run(["git", "rev-parse", "HEAD"], log, cwd=source).strip()
        if actual != spec["commit"]:
            raise RuntimeError(f"{name}: source commit differs from the lock")
        if name == "superlu":
            changed = run(["git", "diff", "--name-only", "HEAD"], log, cwd=source).strip()
            if changed:
                verify_lu_patch(cache)
        else:
            run(["git", "diff", "--exit-code", "--ignore-submodules=untracked", "HEAD"], log, cwd=source)
        for module in spec.get("submodules", []):
            actual = run(["git", "rev-parse", "HEAD"], log,
                         cwd=source / module["path"]).strip()
            if actual != module["commit"]:
                raise RuntimeError(f"{name}/{module['path']}: submodule differs from the lock")
            run(["git", "diff", "--exit-code", "--ignore-submodules=untracked", "HEAD"], log,
                cwd=source / module["path"])


def scipy_patch(cache: Path) -> Path:
    version = LOCK["sources"]["superlu"]["scipy-version"]
    return cache / "downloads" / f"scipy-{version}-superlu-changes.patch"


def verify_lu_patch(cache: Path) -> None:
    """Compare the entire tracked tree with exactly the selected correction.

    The temporary index does not touch the source checkout's real Git index.
    This detects other edits even inside one of the three corrected files.
    """
    spec = LOCK["sources"]["superlu"]
    source = cache / "src" / spec["directory"]
    log = cache / "logs" / "verify-superlu-corrections.log"
    (cache / "build").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="verify-superlu-", dir=cache / "build") as temporary:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(temporary) / "index")}
        run(["git", "read-tree", "HEAD"], log, cwd=source, env=env)
        run(["git", "apply", "--cached", "-p6",
             *[f"--include={name}" for name in spec["scipy-patch-files"]], scipy_patch(cache)],
            log, cwd=source, env=env)
        run(["git", "diff", "--exit-code"], log, cwd=source, env=env)


def apply_lu_patch(cache: Path) -> None:
    spec = LOCK["sources"]["superlu"]
    source = cache / "src" / spec["directory"]
    patch = scipy_patch(cache)
    if not patch.is_file():
        raise RuntimeError("Missing locked SciPy correction; run fetch first")
    command = ["git", "apply", "-p6", *[f"--include={name}" for name in spec["scipy-patch-files"]]]
    # Accept precisely the selected patch either unapplied or already applied.
    ready = subprocess.run([*command, "--reverse", "--check", str(patch)], cwd=source,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if ready.returncode == 0:
        verify_lu_patch(cache)
        return
    log = cache / "logs" / "patch-superlu.log"
    run([*command, "--check", patch], log, cwd=source)
    run([*command, patch], log, cwd=source)
    verify_lu_patch(cache)


def fetch_source(cache: Path, name: str) -> Path:
    spec = LOCK["sources"][name]
    source = cache / "src" / spec["directory"]
    log = cache / "logs" / f"fetch-{name}.log"
    if not (source / ".git").exists():
        source.mkdir(parents=True, exist_ok=True)
        run(["git", "init", source], log)
        run(["git", "remote", "add", "origin", spec["repository"]], log, cwd=source)
    # A failed fetch leaves an initialized repository without HEAD.
    head = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=source,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if head.returncode == 1:
        if run(["git", "status", "--porcelain", "--untracked-files=all"], log, cwd=source).strip():
            raise RuntimeError(f"Incomplete {name} source contains local changes")
        for attempt in range(5):
            try:
                run(["git", "fetch", "--depth", "1", spec["repository"], spec["commit"]], log, cwd=source)
                break
            except RuntimeError as error:
                busy = ("GitLab is currently unable to handle this request due to load" in str(error)
                        or "The requested URL returned error: 503" in str(error))
                if attempt == 4 or not busy:
                    raise
                delay = 10 * 2**attempt
                print(f"Source server is busy; retry the fixed {name} fetch in {delay} seconds", flush=True)
                time.sleep(delay)
        run(["git", "checkout", "--detach", spec["commit"]], log, cwd=source)
    actual = run(["git", "rev-parse", "HEAD"], log, cwd=source).strip()
    if actual != spec["commit"]:
        raise RuntimeError(f"{name}: source commit differs from the lock")
    return source


def fetch_eigen(cache: Path) -> None:
    """Fetch only the fixed headers used by the EOS-free thermal library."""
    source = fetch_source(cache, "eigen")
    log = cache / "logs" / "fetch-eigen.log"
    changed = run(["git", "status", "--porcelain", "--untracked-files=all"], log, cwd=source).strip()
    if changed:
        raise RuntimeError("Eigen source worktree is not clean")
    if not (source / "Eigen/SparseLU").is_file():
        raise RuntimeError("Locked Eigen/SparseLU header is missing")


def fetch(cache: Path, host: str) -> None:
    require_component(host, "all")
    for name in LOCK["sources"]:
        fetch_source(cache, name)
    verify_sources(cache)
    superlu = LOCK["sources"]["superlu"]
    download(superlu["scipy-patch-url"], scipy_patch(cache))
    download(superlu["scipy-readme-url"],
             cache / "downloads" / f"scipy-{superlu['scipy-version']}-superlu-README")
    apply_lu_patch(cache)
    fetch_cmake(cache, host)


def fetch_cmake(cache: Path, host: str) -> None:
    """Fetch only the existing locked CMake tool, without solver sources."""
    spec = LOCK["cmake"][host]
    archive = cache / "downloads" / spec["url"].rsplit("/", 1)[1]
    download(spec["url"], archive)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != spec["sha256"]:
        raise RuntimeError(f"CMake archive differs from the official SHA-256: {archive}")
    tools = cache / "tools"
    if not (tools / spec["executable"]).is_file():
        tools.mkdir(parents=True, exist_ok=True)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as bundle:
                for name in bundle.namelist():
                    if not (tools / name).resolve().is_relative_to(tools):
                        raise RuntimeError("Unsafe path in CMake archive")
                bundle.extractall(tools)
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(tools, filter="data")


def cmake_path(cache: Path, host: str) -> Path:
    executable = cache / "tools" / LOCK["cmake"][host]["executable"]
    if not executable.is_file():
        raise RuntimeError("Locked portable CMake is missing; run fetch-cmake first")
    return executable


def check_model_h_history_input(solver_build: Path, *, qualification: bool) -> None:
    """Check whether the solver configuration loaded the model-h history script."""
    reply = solver_build / ".cmake/api/v1/reply"
    index = json.loads(max(reply.glob("index-*.json")).read_text(encoding="utf-8"))
    inputs_file = reply / index["reply"]["cmakeFiles-v1"]["jsonFile"]
    inputs = json.loads(inputs_file.read_text(encoding="utf-8"))["inputs"]
    observed = any(Path(item["path"]).name == "model_h_history.cmake" for item in inputs)
    if observed != qualification:
        raise RuntimeError(f"Expected model-h history input={qualification} in {solver_build}, got {observed}")


def check_environment(cache: Path, python: Path, lock: Path) -> None:
    log = cache / "logs" / "environment.log"
    run([python, "-m", "tm1.development.runs.tools.check_locked_environment", lock], log)
    run([python, "-m", "pip", "check"], log)


def coolprop_build_dir(cache: Path, host: str, role: str) -> Path:
    return build_coolprop.coolprop_build_dir(cache, host, role)


def coolprop_library(cache: Path, host: str, role: str) -> Path:
    return build_coolprop.coolprop_library(cache, host, role)


def _request_build_metadata(build_dir: Path) -> None:
    build_coolprop.request_build_metadata(build_dir)


def _record_coolprop_build(cache: Path, host: str, role: str) -> None:
    build_coolprop.record_coolprop_build(cache, host, role, LOCK)


def coolprop_build_record(cache: Path, host: str, role: str) -> dict:
    return build_coolprop.coolprop_build_record(cache, host, role, LOCK)


def build(cache: Path, host: str, python: Path, lock: Path, component: str) -> None:
    require_component(host, component)
    check_environment(cache, python, lock)
    if component == "result":
        build_result(cache, host)
        return
    if component == "geometry":
        cmake = cmake_path(cache, host)
        generated = cache / "generated"
        run([python, "-m", "engineering.scripts.generate_native_model_coefficients", "--output",
             generated / "tpmshx/model_coefficients.hpp"], cache / "logs" / "generate-model-coefficients.log")
        generator = ["-G", LOCK["cmake"][host]["generator"]]
        options = [f"-DTPMSHX_MODEL_INCLUDE_DIR={generated}", "-DCMAKE_BUILD_TYPE=Release",
                   "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", "-DTPMSHX_BUILD_QUALIFICATION=ON"]
        if host == "windows-x64":
            generator += ["-A", "x64"]
        else:
            options += ["-DCMAKE_OSX_ARCHITECTURES=arm64"]
        build_dir = cache / "build" / f"geometry-{host}"
        run([cmake, "-S", ROOT / "geometry", "-B", build_dir,
             *generator, *options], cache / "logs" / f"configure-geometry-{host}.log")
        run([cmake, "--build", build_dir, "--config", "Release", "--parallel", "2"],
            cache / "logs" / f"build-geometry-{host}.log")
        return
    if component == "preparation":
        verify_sources(cache, models_only=True)
    else:
        verify_sources(cache)
    if component != "preparation":
        apply_lu_patch(cache)
    cmake = cmake_path(cache, host)
    generator = ["-G", LOCK["cmake"][host]["generator"]]
    if host == "windows-x64":
        generator += ["-A", "x64"]
    if component in {"all", "coolprop"}:
        build_coolprop.build_archives(cache, host, python, cmake, LOCK, run,
                                      request_metadata=_request_build_metadata, record=_record_coolprop_build)
    if component in {"all", "pilot", "preparation"}:
        generated = cache / "generated"
        run([python, "-m", "engineering.scripts.generate_native_model_coefficients", "--output",
             generated / "tpmshx/model_coefficients.hpp", "--df-output",
             generated / "tpmshx/preparation_df_data.hpp"], cache / "logs" / "generate-model-coefficients.log")
        names = ("preparation",) if component == "preparation" else ("pilot", "preparation")
        for build_name in names:
            role = "preparation" if build_name == "preparation" else "solver"
            library = coolprop_library(cache, host, role)
            coolprop_build_record(cache, host, role)
            build_dir = cache / "build" / f"{build_name}-{host}"
            options = [f"-DTPMSHX_NATIVE_DEPS_ROOT={cache}", f"-DTPMSHX_COOLPROP_LIBRARY={library}",
                       f"-DTPMSHX_MODEL_INCLUDE_DIR={generated}", "-DTPMSHX_BUILD_QUALIFICATION=ON",
                       "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]
            if host == "macos-arm64":
                options += ["-DCMAKE_OSX_ARCHITECTURES=arm64"]
            source = "preprocess" if build_name == "preparation" else "solver"
            run([cmake, "-S", ROOT / source, "-B", build_dir,
                 *generator, *options], cache / "logs" / f"configure-{build_name}-{host}.log")
            command = [cmake, "--build", build_dir, "--config", "Release", "--parallel", "2"]
            if build_name == "preparation" and component != "preparation":
                # The solver build supplies the independent geometry callers.
                command += ["--target", *PREPARATION_CALLERS]
            run(command, cache / "logs" / f"build-{build_name}-{host}.log")
    if component == "all":
        build_result(cache, host)


def build_result(cache: Path, host: str) -> None:
    cmake = cmake_path(cache, host)
    build_dir = cache / "build" / f"result-{host}"
    generator = ["-G", LOCK["cmake"][host]["generator"]]
    options = ["-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", "-DTPMSHX_BUILD_QUALIFICATION=ON"]
    if host == "windows-x64":
        generator += ["-A", "x64"]
    elif host == "macos-arm64":
        options += ["-DCMAKE_OSX_ARCHITECTURES=arm64"]
    _request_build_metadata(build_dir)
    run([cmake, "-S", ROOT / "postprocess", "-B", build_dir,
         *generator, *options], cache / "logs" / f"configure-result-{host}.log")
    run([cmake, "--build", build_dir, "--config", "Release", "--parallel", "2"],
        cache / "logs" / f"build-result-{host}.log")
    record_result_build(cache, host)


def record_result_build(cache: Path, host: str) -> None:
    """Record the compiler, options and artifacts from the actual result build."""
    build_dir = cache / "build" / f"result-{host}"
    library = build_dir / shared_library_name(host, "result")
    if not library.is_file():
        raise RuntimeError(f"Result build did not produce {library}")
    reply = build_dir / ".cmake/api/v1/reply"
    indices = list(reply.glob("index-*.json"))
    if not indices:
        raise RuntimeError(f"Missing actual result CMake metadata: {reply}")
    index_path = max(indices, key=lambda path: path.stat().st_mtime_ns)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    objects = {}
    for kind in ("codemodel", "toolchains"):
        descriptor, = (item for item in index["objects"] if item["kind"] == kind)
        objects[kind] = json.loads((reply / descriptor["jsonFile"]).read_text(encoding="utf-8"))
    configuration, = (item for item in objects["codemodel"]["configurations"] if item["name"] == "Release")
    targets = {}
    for name in ("tpmshx_result", "tpmshx_result_c", "tpmshx_result_shared"):
        reference, = (item for item in configuration["targets"] if item["name"] == name)
        target = json.loads((reply / reference["jsonFile"]).read_text(encoding="utf-8"))
        groups = target["compileGroups"]
        languages = {"CXX"}
        if {item["language"] for item in groups} != languages or any(
                not item.get("compileCommandFragments") for item in groups):
            raise RuntimeError(f"Result metadata omitted required compilation options or languages for {name}: {sorted(languages)}")
        targets[name] = dict(compile_groups=groups, sources=target["sources"],
                             artifacts=target["artifacts"], link=target.get("link"))
    if not any((build_dir / item["path"]).resolve() == library.resolve()
               for item in targets["tpmshx_result_shared"]["artifacts"]):
        raise RuntimeError("Result CMake artifact differs from the built image")
    cache_values = {}
    for line in (build_dir / "CMakeCache.txt").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"(CMAKE_[A-Z0-9_]+):[^=]+=(.*)", line)
        if match and (match[1].startswith(("CMAKE_C_FLAGS", "CMAKE_CXX_FLAGS", "CMAKE_OSX_", "CMAKE_VS_"))
                      or match[1] in ("CMAKE_SYSTEM_VERSION", "CMAKE_MSVC_RUNTIME_LIBRARY", "CMAKE_GENERATOR")):
            cache_values[match[1]] = match[2]
    sdk = dict(cmake_cache=cache_values)
    if host == "macos-arm64":
        settings = []
        for toolchain in objects["toolchains"]["toolchains"]:
            includes = toolchain.get("compiler", {}).get("implicit", {}).get("includeDirectories", [])
            for directory in includes:
                match = re.search(r"^(.+\.sdk)(?:/|$)", directory)
                if match:
                    path = Path(match[1]).resolve() / "SDKSettings.json"
                    if path.is_file() and str(path) not in {item["path"] for item in settings}:
                        data = json.loads(path.read_text(encoding="utf-8"))
                        settings.append({"path": str(path), "version": data.get("Version"),
                                         "canonical_name": data.get("CanonicalName")})
        sdk["sdk_settings"] = settings
    elif host == "windows-x64":
        project = build_dir / "tpmshx_result_shared.vcxproj"
        tree = ET.parse(project)
        sdk.update(visual_studio_project=str(project), windows_target_platform_versions=[
            item.text for item in tree.iter() if item.tag.rsplit("}", 1)[-1] == "WindowsTargetPlatformVersion"])
    record = dict(platform=host, library=str(library.resolve()), configuration="Release",
                  recorded_at=datetime.now(timezone.utc).isoformat(), targets=targets,
                  toolchains=objects["toolchains"]["toolchains"], sdk=sdk,
                  evidence=dict(index=str(index_path), cache=str(build_dir / "CMakeCache.txt")))
    (build_dir / "result-toolchain.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def result_build_record(cache: Path, host: str) -> dict:
    build_dir = cache / "build" / f"result-{host}"
    library = build_dir / shared_library_name(host, "result")
    record_path = build_dir / "result-toolchain.json"
    if not library.is_file() or not record_path.is_file():
        raise RuntimeError(f"Build the result image and actual toolchain metadata first: {record_path}")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if (record["platform"], record["library"], record["configuration"]) != (
            host, str(library.resolve()), "Release"):
        raise RuntimeError(f"Result build record differs from the selected image: {record_path}")
    if not record["toolchains"] or not record["sdk"] or set(record["targets"]) != {
            "tpmshx_result", "tpmshx_result_c", "tpmshx_result_shared"}:
        raise RuntimeError(f"Result build record omitted actual toolchain evidence: {record_path}")
    return dict(record, record_source=str(record_path))


def verify_model_exports(build_dir: Path, host: str, component: str, log: Path) -> None:
    """Verify each image's C exports and dynamic library boundary."""
    folder = {'preparation': 'preprocess', 'result': 'postprocess'}.get(component, component)
    expected = set((ROOT / folder / (component + '.exports')).read_text().splitlines())
    if not expected or any(not name.startswith('_tpmshx_') for name in expected):
        raise RuntimeError(f'Invalid {component} C export list')
    if host == 'macos-arm64':
        library = build_dir / shared_library_name(host, component)
        symbols = run(['nm', '-gU', library], log)
        actual = {line.split()[-1] for line in symbols.splitlines() if line.strip()}
        undefined = run(['nm', '-gu', library], log)
        if re.search(r'_Z\S*(?:8CoolProp|6tpmshx)', undefined) or (
                component == 'result' and re.search(r'\b_tpmshx_', undefined)):
            raise RuntimeError(f'{component} imports private model symbols from another image')
        dependencies = run(['otool', '-L', library], log)
        imported = []
        for line in dependencies.splitlines()[2:]:
            dependency = line.strip().split(' (', 1)[0]
            imported.append(dependency)
            if not dependency.startswith(('/usr/lib/', '/System/Library/')):
                raise RuntimeError(f'{component} has a non-system dynamic dependency: {dependency}')
        if component == 'result' and not imported:
            raise RuntimeError(f'{component} has no actual system dynamic dependency listing')
    elif host == 'linux-x86_64':
        library = build_dir / shared_library_name(host, component)
        symbols = run(['nm', '-D', '--defined-only', library], log)
        actual = {'_' + line.split()[-1] for line in symbols.splitlines() if line.strip()}
        undefined = run(['nm', '-D', '--undefined-only', library], log)
        if re.search(r'(?:_Z\S*(?:8CoolProp|6tpmshx)|\btpmshx_)', undefined):
            raise RuntimeError(f'{component} imports private model symbols from another image')
        dependencies = run(['readelf', '-d', library], log)
        imported = re.findall(r'\(NEEDED\).*\[([^\]]+)\]', dependencies)
        system = {'libstdc++.so.6', 'libm.so.6', 'libgcc_s.so.1', 'libc.so.6', 'ld-linux-x86-64.so.2'}
        if not imported or any(name not in system for name in imported):
            raise RuntimeError(f'{component} has a non-system dynamic dependency: {imported}')
    else:
        library = build_dir / shared_library_name(host, component)
        symbols = run(['dumpbin', '/NOLOGO', '/EXPORTS', library], log)
        actual = {'_' + match for match in re.findall(
            r'^\s+\d+\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+(\S+)', symbols, re.MULTILINE)}
        if component == 'solver':
            # These original macOS C hooks were never DLL exports on Windows.
            expected = {name for name in expected if not name.startswith('_tpmshx_superlu_')}
        dependencies = run(['dumpbin', '/NOLOGO', '/DEPENDENTS', library], log)
        imported = re.findall(r'^\s+([^\s]+\.dll)\s*$', dependencies, re.MULTILINE | re.IGNORECASE)
        if any(re.search(r'(?:coolprop|tpmshx_(?:preparation|solver|geometry))', name, re.IGNORECASE)
               for name in imported):
            raise RuntimeError(f'{component} imports another numerical library image')
        if component == 'result' and (not imported or any(not re.fullmatch(
                r'(?:KERNEL32|MSVCP140(?:_\d+)?|VCRUNTIME140(?:_\d+)?|ucrtbase|'
                r'api-ms-win-[A-Za-z0-9-]+)\.dll', name, re.IGNORECASE) for name in imported)):
            raise RuntimeError(f'{component} has a non-system dynamic dependency: {imported}')
    if actual != expected:
        raise RuntimeError(f'{component} C exports differ: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}')


def verify(cache: Path, host: str, component: str = "all") -> None:
    require_component(host, component)
    geometry_only = component == "geometry"
    preparation_only = component == "preparation"
    result_only = component == "result"
    if not geometry_only and not result_only:
        if preparation_only:
            verify_sources(cache, models_only=True)
        else:
            verify_sources(cache)
    build_name = component if component in {"geometry", "preparation", "result"} else "pilot"
    log = cache / "logs" / f"verify-{build_name}-{host}.log"
    version = run([cmake_path(cache, host), "--version"], log)
    if version.splitlines()[0] != f"cmake version {LOCK['cmake']['version']}":
        raise RuntimeError("Portable CMake version differs from the lock")
    build_dir = cache / "build" / f"{build_name}-{host}"
    suffix = ".exe" if host == "windows-x64" else ""
    if result_only or component == "all":
        result_dir = cache / "build" / f"result-{host}"
        for caller in ("result_c_static", "result_c_shared", "result_kernel_smoke", "result_stage_smoke"):
            run([result_dir / f"{caller}{suffix}"], log)
        verify_model_exports(result_dir, host, "result", log)
        result_build_record(cache, host)
        if result_only:
            print(f"PASS: {host} locked CMake, independent result callers and system-only image", flush=True)
            return
    for caller in ("geometry_c_static", "geometry_c_shared", "geometry_kernel_smoke"):
        run([build_dir / f"{caller}{suffix}"], log)
    verify_model_exports(build_dir, host, "geometry", log)
    if geometry_only:
        print(f"PASS: {host} locked CMake, independent geometry callers and geometry exports", flush=True)
        return
    preparation_dir = cache / "build" / f"preparation-{host}"
    for caller in PREPARATION_CALLERS:
        run([preparation_dir / f"{caller}{suffix}"], log)
    prefix, shared_suffix = ("", ".dll") if host == "windows-x64" else ("lib", ".dylib")
    preparation = ct.CDLL(str(preparation_dir / (prefix + 'tpmshx_preparation_shared' + shared_suffix)))
    backend = preparation.tpmshx_preparation_property_backend_v1
    backend.argtypes = [ct.POINTER(ct.c_char), ct.c_size_t] * 3
    backend.restype = ct.c_int
    version, revision, error = ct.create_string_buffer(128), ct.create_string_buffer(128), ct.create_string_buffer(2048)
    if backend(version, len(version), revision, len(revision), error, len(error)):
        raise RuntimeError('Preparation EOS backend query failed: ' + error.value.decode('utf-8', errors='replace'))
    spec = LOCK['sources']['coolprop']
    if (version.value.decode(), revision.value.decode()) != (spec['version'], spec['commit']):
        raise RuntimeError('Preparation compiled CoolProp version/commit differs from the lock')
    verify_model_exports(preparation_dir, host, 'preparation', log)
    if preparation_only:
        print(f"PASS: {host} locked model inputs and independent preparation/geometry callers", flush=True)
        return
    verify_model_exports(build_dir, host, 'solver', log)
    eos = build_dir / f"eos_smoke{suffix}"
    version = run([eos, "--version"], log).strip().split("\t")
    spec = LOCK["sources"]["coolprop"]
    if version != [spec["version"], spec["commit"]]:
        raise RuntimeError("Compiled CoolProp version/commit differs from the lock")
    output = run([eos, "--tables", cache / "tables" / "verify", "--workers", "1"], log,
                 input_text="co2 HEOS CO2 TP 310 8000000\nwater HEOS Water TP 300 200000\n")
    data = "\n".join(line for line in output.splitlines() if not line.startswith("#"))
    rows = list(csv.DictReader(io.StringIO(data), delimiter="\t"))
    if len(rows) != 2 or {row["id"] for row in rows} != {"co2", "water"}:
        raise RuntimeError("EOS smoke omitted a requested state")
    for row in rows:
        if row["status"] != "0" or any(not math.isfinite(float(row[key])) or float(row[key]) <= 0
                for key in ("T_K", "rho_kg_m3", "cp_J_kgK", "mu_Pas", "k_W_mK")):
            raise RuntimeError(f"EOS smoke failed: {row}")
    pressure = json.loads(run([build_dir / f"pressure_smoke{suffix}"], log))
    if pressure["status"] != "passed":
        raise RuntimeError(f"Pressure smoke failed: {pressure}")
    for caller in ("enthalpy_driver_smoke", "conservative_energy_smoke", "conservative_energy_driver_smoke",
                   "simple_2d_smoke", "simple_3d_smoke", "simple_run_smoke", "model_h_2d_smoke", "model_h_3d_smoke",
                   "model_h_chunk_smoke", "model_h_run_smoke",
                   "temperature_driver_smoke", "temperature_staggered_smoke", "temperature_run_smoke",
                   "side_physics_smoke"):
        run([build_dir / f"{caller}{suffix}"], log)
    run([build_dir / f"conservative_energy_driver_smoke{suffix}", "8"], log)
    for storage in ("csc", "csr"):
        for case in ("allocations", "aborts", "singular", "concurrent"):
            run([build_dir / f"superlu_error_smoke{suffix}", "--case", case, "--format", storage], log)
    print(f"PASS: {host} locked sources, EOS, pressure, enthalpy/temperature/SIMPLE/model-h callers and SuperLU error boundary",
          flush=True)


def publish(cache: Path, host: str, python: Path, lock: Path, component: str = "all") -> Path:
    """Validate all selected libraries before replacement; retain their previous files."""
    require_component(host, component)
    selected_component = component if component in {"geometry", "preparation", "result"} else "all"
    build(cache, host, python, lock, selected_component)
    verify(cache, host, selected_component)
    destination = ROOT / "native/lib" / host
    libraries = ([(selected_component, selected_component + "-build.json")]
                 if selected_component != "all" else PUBLISHED_LIBRARIES)
    log = cache / "logs" / f"publish-{host}.log"
    source_commit = None
    source_changes = None
    # A source archive can be inside another Git checkout.
    if (ROOT / ".git").exists():
        git_env = {key: value for key, value in os.environ.items()
                   if key not in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE")}
        git_env["GIT_CEILING_DIRECTORIES"] = str(ROOT.parent)
        source_commit = run(["git", "rev-parse", "HEAD"], log, cwd=ROOT, env=git_env).strip()
        source_changes = run(["git", "status", "--porcelain", "--untracked-files=no"],
                             log, cwd=ROOT, env=git_env).splitlines()
    common = {
        "published_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": source_commit,
        "source_changes": source_changes,
        "platform": host,
        "python": str(python),
        "python_lock": str(lock),
        "cmake_version": LOCK["cmake"]["version"],
        "generator": LOCK["cmake"][host]["generator"],
        "configuration": "Release",
    }
    destination.mkdir(parents=True, exist_ok=True)
    selected = []
    staged = Path(tempfile.mkdtemp(prefix=".publish-", dir=destination))
    preserve_staged = False
    try:
        for kind, metadata_name in libraries:
            build_name = kind if kind in {"preparation", "result"} else (
                "geometry" if selected_component == "geometry" else "pilot")
            build_dir = cache / "build" / f"{build_name}-{host}"
            name = shared_library_name(host, kind)
            source, target = build_dir / name, destination / name
            metadata = destination / metadata_name
            record = dict(common, component=kind, source_library=str(source), target_library=str(target),
                          dependencies=({} if kind in {"geometry", "result"} else
                                        {name: spec for name, spec in LOCK["sources"].items()
                                         if kind == "solver" or name == "coolprop" or "cpm-name" in spec}),
                          verification=("independent geometry callers and kernel smoke passed" if kind == "geometry"
                                        else "independent result callers, exact C exports and system-only image passed" if kind == "result"
                                        else "independent preparation callers passed" if kind == "preparation"
                                        else "independent native callers and SuperLU error boundary passed"))
            if kind == "result":
                record["result_build"] = result_build_record(cache, host)
            elif kind != "geometry":
                record["coolprop_build"] = coolprop_build_record(
                    cache, host, "preparation" if kind == "preparation" else "solver")
            shutil.copy2(source, staged / name)
            (staged / metadata_name).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            for current in (target, metadata):
                if current.is_file():
                    shutil.copy2(current, staged / ("old-" + current.name))
            selected.append((name, metadata_name, target, metadata))
        for name, metadata_name, target, metadata in selected:
            if target.is_file() and not filecmp.cmp(staged / name, target, shallow=False):
                previous = destination / "previous"
                previous.mkdir(exist_ok=True)
                shutil.copy2(target, previous / name)
                if metadata.is_file():
                    shutil.copy2(metadata, previous / metadata_name)
                else:
                    (previous / metadata_name).write_text(
                        '{"provenance": "existing library without a build record"}\n', encoding="utf-8")
        replaced = []
        try:
            for name, metadata_name, target, metadata in selected:
                for staged_name, current in ((metadata_name, metadata), (name, target)):
                    replaced.append(current)
                    try:
                        (staged / staged_name).replace(current)
                    except OSError:
                        replaced.pop()
                        raise
        except BaseException as error:
            preserve_staged = True
            rollback_errors = []
            for current in reversed(replaced):
                original = staged / ("old-" + current.name)
                try:
                    if original.is_file():
                        original.replace(current)
                    else:
                        current.unlink(missing_ok=True)
                except OSError as rollback_error:
                    rollback_errors.append(f"{current}: {rollback_error}")
            if rollback_errors:
                raise RuntimeError(f"Publication rollback failed; recovery files remain at {staged}: "
                                   + "; ".join(rollback_errors)) from error
            preserve_staged = False
            raise
    finally:
        if preserve_staged:
            print(f"Publication recovery files retained: {staged}", file=sys.stderr, flush=True)
        else:
            shutil.rmtree(staged)
    for _, _, target, metadata in selected:
        print(f"Published verified library: {target}\nBuild record: {metadata}", flush=True)
    return selected[0][2]


def verify_published(directory: Path, host: str, component: str, log: Path) -> None:
    """Compare the selected published images with the export manifests.

    This is a qualification check. It does not build, load or replace an image.
    A different source commit, a dirty build or a missing or unreadable build
    record is reported. It does not fail an image whose exports agree.
    """
    libraries = [(kind, record) for kind, record in PUBLISHED_LIBRARIES if component in {"all", kind}]
    print(f"Published directory: {directory}", flush=True)
    failures = []
    for kind, metadata_name in libraries:
        library = directory / shared_library_name(host, kind)
        metadata = directory / metadata_name
        print(f"{kind}: {library}", flush=True)
        record = None
        if not metadata.is_file():
            print(f"  WARNING: build record missing ({metadata.name})", flush=True)
        else:
            try:
                record = json.loads(metadata.read_text(encoding="utf-8"))
                if not isinstance(record, dict):
                    raise ValueError("not a JSON object")
                if not isinstance(record.get("source_changes"), (list, type(None))):
                    raise ValueError("source_changes is not a list")
            except ValueError as error:
                record = None
                print(f"  WARNING: build record unreadable ({metadata.name}: {error})", flush=True)
        if record is not None:
            changes = record.get("source_changes")
            count = "unknown" if changes is None else len(changes)
            print(f"  build record: source_commit={record.get('source_commit')}, source_changes={count}",
                  flush=True)
            if changes:
                print(f"  WARNING: dirty build; the source checkout had {len(changes)} tracked changes",
                      flush=True)
        if not library.is_file():
            failures.append(kind)
            print("  exports: FAIL: the published image is missing", flush=True)
            continue
        try:
            verify_model_exports(directory, host, kind, log)
        except RuntimeError as error:
            failures.append(kind)
            print(f"  exports: FAIL: {error}", flush=True)
            continue
        print("  exports: agree with the manifest", flush=True)
    if failures:
        raise RuntimeError(f"Published image check failed for: {', '.join(failures)}")
    print(f"PASS: {host} published images agree with the export manifests", flush=True)


def verify_installed_sdk_headers(include_root: Path) -> None:
    """Check the files visible to SDK consumers against both public header tables."""
    installed = {path.relative_to(include_root).as_posix() for path in include_root.rglob("*")
                 if not path.is_dir() or path.is_symlink()}

    for name in ("native-stages.md", "native-stages.zh-CN.md"):
        guide = (ROOT / "docs" / name).read_text(encoding="utf-8")
        table = guide.partition('<a id="sdk-public-headers"></a>')[2].lstrip().split("\n\n", 1)[0]
        documented = {f"tpmshx/{header}" for header in re.findall(r"`([^`]+)`", table)}
        if not documented:
            raise RuntimeError(f"Missing public SDK header table in {name}")
        missing = sorted(header for header in documented if not (include_root / header).is_file())
        extra = sorted(installed - documented)
        if missing or extra:
            raise RuntimeError(f"Installed SDK headers differ from {name}: "
                               f"missing regular files={missing}, extra={extra}")


def check_stages(cache: Path, host: str, python: Path, lock: Path, component: str) -> None:
    """Build the installed public SDK and run callers outside the source tree."""
    require_component(host, component)
    if component not in {"all", "result"}:
        raise ValueError("check-stages supports only --component all or result")
    check_environment(cache, python, lock)
    cmake = cmake_path(cache, host)
    stage_build = cache / "build" / f"stages-{host}"
    solver_build = stage_build / "solver"
    log = cache / "logs" / f"check-stages-{host}.log"
    components = ["result"] if component == "result" else ["geometry", "preparation", "solver", "result"]
    options = [f"-DTPMSHX_COMPONENTS={';'.join(components)}",
               f"-DTPMSHX_NATIVE_DEPS_ROOT={cache}", f"-DTPMSHX_MODEL_INCLUDE_DIR={cache / 'generated'}"]
    for name in components:
        options.append(f"-DTPMSHX_{name.upper()}_BUILD_DIR={stage_build / name}")
    if component == "all":
        query = solver_build / ".cmake/api/v1/query"
        query.mkdir(parents=True, exist_ok=True)
        (query / "cmakeFiles-v1").touch()
        for role in ("solver", "preparation"):
            coolprop_build_record(cache, host, role)
            options.append(f"-DTPMSHX_{role.upper()}_COOLPROP_LIBRARY={coolprop_library(cache, host, role)}")
    generator = ["-G", LOCK["cmake"][host]["generator"]]
    if host == "windows-x64":
        generator += ["-A", "x64"]
    run([cmake, "-S", ROOT, "-B", stage_build,
         *generator, *options], log)
    if component == "all":
        # A direct qualification configure can reuse an SDK component build directory.
        run([cmake, "--build", stage_build, "--config", "Release", "--target", "tpmshx_solver_build-configure"], log)
        check_model_h_history_input(solver_build, qualification=False)
        run([cmake, "-S", ROOT / "solver", "-B", solver_build, "-DTPMSHX_BUILD_QUALIFICATION=ON"], log)
        check_model_h_history_input(solver_build, qualification=True)
    run([cmake, "--build", stage_build, "--config", "Release", "--parallel", "1"], log)
    if component == "all":
        check_model_h_history_input(solver_build, qualification=False)
    ctest = cmake.with_name("ctest.exe" if host == "windows-x64" else "ctest")
    with tempfile.TemporaryDirectory(prefix="tpmshx-stage-sdk-") as temporary:
        independent = Path(temporary)
        prefix = independent / "sdk"
        run([cmake, "--install", stage_build, "--config", "Release", "--prefix", prefix], log)
        package_config, = (path for path in prefix.rglob("tpmshxConfig.cmake") if path.is_file())
        include_query = independent / "sdk-include-root.cmake"
        include_query.write_text(
            'file(GENERATE OUTPUT "${CMAKE_BINARY_DIR}/sdk-include-root.txt"\n'
            '    CONTENT "$<TARGET_PROPERTY:tpmshx::result,INTERFACE_INCLUDE_DIRECTORIES>")\n',
            encoding="utf-8")
        shutil.copytree(ROOT / "examples/cpp", independent / "examples")
        sources = [("examples", [f"-DCMAKE_PROJECT_INCLUDE={include_query}"])]
        if component == "all":
            tests = independent / "tests"
            shutil.copytree(ROOT / "tests/cpp/stages", tests / "stages")
            for smoke in ("stage_run_smoke.cpp", "quick_design_stage_smoke.cpp",
                          "stage_run_3d_smoke.c", "geometry_c_smoke.c"):
                shutil.copy2(ROOT / "tests/cpp" / smoke, tests)
            sources.append(("tests/stages", []))
        env = {key: value for key, value in os.environ.items()
               if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"} and not key.startswith("TPMSHX_")}
        env["PATH"] = os.defpath
        for source, consumer_options in sources:
            build_dir = independent / (source.replace("/", "-") + "-build")
            run([cmake, "-S", independent / source, "-B", build_dir, *generator,
                 f"-DCMAKE_PREFIX_PATH={prefix}", f"-Dtpmshx_DIR={package_config.parent}", *consumer_options],
                log, cwd=independent)
            if source == "examples":
                include_root = (build_dir / "sdk-include-root.txt").read_text(encoding="utf-8")
                verify_installed_sdk_headers(Path(include_root))
            run([cmake, "--build", build_dir, "--config", "Release", "--parallel", "2"],
                log, cwd=independent)
            run([ctest, "--test-dir", build_dir, "-C", "Release", "--output-on-failure", "--no-tests=error"],
                log, cwd=independent, env=env)
            if source == "tests/stages":
                for name in ("stage-result", "quick-design-stage-result"):
                    shutil.copytree(build_dir / name, cache / "build" / name, dirs_exist_ok=True)
    print(f"PASS: {host} installed SDK and independent C++ stage callers", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fetch", "fetch-cmake", "fetch-eigen", "build", "verify", "publish",
                                           "check-stages", "verify-published"))
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/native-deps")
    parser.add_argument("--python-lock", type=Path, default=ROOT / "engineering/requirements/base.txt")
    parser.add_argument("--component", choices=("all", "coolprop", "pilot", "geometry", "preparation", "result"), default="all")
    parser.add_argument("--directory", type=Path,
                        help="verify-published only: published image directory (default: this checkout's host directory)")
    args = parser.parse_args()
    if args.directory is not None and args.action != "verify-published":
        parser.error("--directory applies only to verify-published")
    if args.action == "verify-published" and args.component in {"coolprop", "pilot"}:
        parser.error("verify-published accepts --component all, geometry, preparation or result")
    python, host, cache = configured_python(), platform_name(), args.cache.resolve()
    if not cache.is_relative_to(ROOT / ".cache"):
        raise RuntimeError("Native dependency outputs must remain under this worktree's .cache/")
    require_component(host, args.component)
    if host == "linux-x86_64" and args.action not in {"fetch-cmake", "build", "verify", "publish", "check-stages",
                                                      "verify-published"}:
        raise RuntimeError("Linux result builds allow only fetch-cmake, build, verify, publish, check-stages, "
                           "or verify-published")
    if args.action == "fetch":
        fetch(cache, host)
    elif args.action == "fetch-cmake":
        fetch_cmake(cache, host)
    elif args.action == "fetch-eigen":
        fetch_eigen(cache)
    elif args.action == "build":
        build(cache, host, python, args.python_lock.resolve(), args.component)
    elif args.action == "check-stages":
        check_stages(cache, host, python, args.python_lock.resolve(), args.component)
    elif args.action == "publish":
        publish(cache, host, python, args.python_lock.resolve(), args.component)
    elif args.action == "verify-published":
        directory = args.directory or ROOT / "native/lib" / host
        verify_published(directory.resolve(), host, args.component,
                         cache / "logs" / f"verify-published-{host}.log")
    else:
        check_environment(cache, python, args.python_lock.resolve())
        verify(cache, host, args.component)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"native dependency pilot: {error}", file=sys.stderr)
        raise SystemExit(1) from error
