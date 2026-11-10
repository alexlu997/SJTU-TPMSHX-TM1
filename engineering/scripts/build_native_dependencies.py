"""Explicitly fetch, build, verify, or publish the locked native libraries.

No package installation, production binding, system PATH change or runtime
download. Run with the interpreter recorded on the first line of .venv-path.
The build command is offline; only fetch commands use the network.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import filecmp
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[2]
LOCK = tomllib.loads((ROOT / "sjtu_tpmshx/solvers/native/dependencies-lock.toml").read_text())


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


def platform_name() -> str:
    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine == "arm64":
        return "macos-arm64"
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "windows-x64"
    raise RuntimeError("Only the locked macOS arm64 and Windows x64 pilots are supported")


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


def verify_sources(cache: Path) -> None:
    for name, spec in LOCK["sources"].items():
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


def check_environment(cache: Path, python: Path, lock: Path) -> None:
    log = cache / "logs" / "environment.log"
    run([python, "-m", "sjtu_tpmshx.development.runs.tools.check_locked_environment", lock], log)
    run([python, "-m", "pip", "check"], log)


def build(cache: Path, host: str, python: Path, lock: Path, component: str) -> None:
    check_environment(cache, python, lock)
    if component == "geometry":
        cmake = cmake_path(cache, host)
        generated = cache / "generated"
        run([python, "-m", "engineering.scripts.generate_native_model_coefficients", "--output",
             generated / "tpmshx/model_coefficients.hpp"], cache / "logs" / "generate-model-coefficients.log")
        generator = ["-G", LOCK["cmake"][host]["generator"]]
        options = [f"-DTPMSHX_MODEL_INCLUDE_DIR={generated}", "-DCMAKE_BUILD_TYPE=Release",
                   "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]
        if host == "windows-x64":
            generator += ["-A", "x64"]
        else:
            options += ["-DCMAKE_OSX_ARCHITECTURES=arm64"]
        build_dir = cache / "build" / f"geometry-{host}"
        run([cmake, "-S", ROOT / "sjtu_tpmshx/solvers/native/geometry", "-B", build_dir,
             *generator, *options], cache / "logs" / f"configure-geometry-{host}.log")
        run([cmake, "--build", build_dir, "--config", "Release", "--parallel", "2"],
            cache / "logs" / f"build-geometry-{host}.log")
        return
    verify_sources(cache)
    apply_lu_patch(cache)
    cmake = cmake_path(cache, host)
    spec = LOCK["sources"]["coolprop"]
    cp_build = cache / "build" / f"coolprop-{host}"
    generator = ["-G", LOCK["cmake"][host]["generator"]]
    if host == "windows-x64":
        generator += ["-A", "x64"]
        library = cp_build / "Release" / "CoolProp.lib"
    else:
        library = cp_build / "libCoolProp.a"
    if component in {"all", "coolprop"}:
        options = [f"-D{value}" for value in spec["cmake-options"]]
        options += [f"-DPython_EXECUTABLE={python}"]
        options += ["-DFETCHCONTENT_FULLY_DISCONNECTED=ON"]
        options += [f"-DCPM_{dependency['cpm-name']}_SOURCE={(cache / 'src' / dependency['directory']).as_posix()}"
                    for dependency in LOCK["sources"].values() if "cpm-name" in dependency]
        if host == "windows-x64":
            options += [f"-D{value}" for value in spec["windows-options"]]
        else:
            options += ["-DCMAKE_OSX_ARCHITECTURES=arm64"]
        run([cmake, "-S", cache / "src" / spec["directory"], "-B", cp_build,
             *generator, *options], cache / "logs" / f"configure-coolprop-{host}.log")
        run([cmake, "--build", cp_build, "--config", "Release", "--parallel", "2"],
            cache / "logs" / f"build-coolprop-{host}.log")
    if component in {"all", "pilot"}:
        if not library.is_file():
            raise RuntimeError(f"Build CoolProp first; missing {library}")
        pilot = cache / "build" / f"pilot-{host}"
        generated = cache / "generated"
        run([python, "-m", "engineering.scripts.generate_native_model_coefficients", "--output",
             generated / "tpmshx/model_coefficients.hpp"], cache / "logs" / "generate-model-coefficients.log")
        options = [f"-DTPMSHX_NATIVE_DEPS_ROOT={cache}", f"-DTPMSHX_COOLPROP_LIBRARY={library}",
                   f"-DTPMSHX_MODEL_INCLUDE_DIR={generated}",
                   "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]
        if host == "macos-arm64":
            options += ["-DCMAKE_OSX_ARCHITECTURES=arm64"]
        run([cmake, "-S", ROOT / "sjtu_tpmshx/solvers/native/dependency-pilot", "-B", pilot,
             *generator, *options], cache / "logs" / f"configure-pilot-{host}.log")
        run([cmake, "--build", pilot, "--config", "Release", "--parallel", "2"],
            cache / "logs" / f"build-pilot-{host}.log")


def verify(cache: Path, host: str, component: str = "all") -> None:
    geometry_only = component == "geometry"
    if not geometry_only:
        verify_sources(cache)
    build_name = "geometry" if geometry_only else "pilot"
    log = cache / "logs" / f"verify-{build_name}-{host}.log"
    version = run([cmake_path(cache, host), "--version"], log)
    if version.splitlines()[0] != f"cmake version {LOCK['cmake']['version']}":
        raise RuntimeError("Portable CMake version differs from the lock")
    build_dir = cache / "build" / f"{build_name}-{host}"
    suffix = ".exe" if host == "windows-x64" else ""
    for caller in ("geometry_c_static", "geometry_c_shared", "geometry_kernel_smoke"):
        run([build_dir / f"{caller}{suffix}"], log)
    if geometry_only:
        print(f"PASS: {host} locked CMake and independent geometry callers", flush=True)
        return
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
    for caller in ("quick_design_c_static", "quick_design_c_shared",
                   "enthalpy_c_static", "enthalpy_c_shared", "enthalpy_driver_smoke",
                   "conservative_energy_smoke", "conservative_energy_driver_smoke",
                   "simple_2d_smoke", "simple_3d_smoke", "simple_run_smoke", "simple_2d_c_static", "simple_2d_c_shared",
                   "simple_3d_c_static", "simple_3d_c_shared", "model_h_2d_smoke", "model_h_3d_smoke",
                   "model_h_chunk_smoke", "model_h_run_smoke",
                   "model_h_c_static", "model_h_c_shared", "temperature_c_static", "temperature_c_shared",
                   "temperature_staggered_smoke", "temperature_run_smoke", "full_2d_c_static", "full_2d_c_shared",
                   "full_3d_c_static", "full_3d_c_shared", "side_physics_smoke"):
        run([build_dir / f"{caller}{suffix}"], log)
    run([build_dir / f"conservative_energy_driver_smoke{suffix}", "8"], log)
    for storage in ("csc", "csr"):
        for case in ("allocations", "aborts", "singular", "concurrent"):
            run([build_dir / f"superlu_error_smoke{suffix}", "--case", case, "--format", storage], log)
    print(f"PASS: {host} locked sources, EOS, pressure, Quick Design/enthalpy/temperature/SIMPLE/model-h callers and SuperLU error boundary",
          flush=True)


def publish(cache: Path, host: str, python: Path, lock: Path, component: str = "all") -> Path:
    """Validate all selected libraries before replacement; retain their previous files."""
    geometry_only = component == "geometry"
    build(cache, host, python, lock, "geometry" if geometry_only else "all")
    verify(cache, host, "geometry" if geometry_only else "all")
    prefix, suffix = ("", ".dll") if host == "windows-x64" else ("lib", ".dylib")
    build_dir = cache / "build" / f"{'geometry' if geometry_only else 'pilot'}-{host}"
    destination = ROOT / "sjtu_tpmshx/solvers/native/lib" / host
    libraries = [("geometry", "geometry-build.json")]
    if not geometry_only:
        libraries.insert(0, ("solver", "build.json"))
    log = cache / "logs" / f"publish-{host}.log"
    common = {
        "published_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": run(["git", "rev-parse", "HEAD"], log).strip(),
        "source_changes": run(["git", "status", "--porcelain", "--untracked-files=no"], log).splitlines(),
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
            name = prefix + f"tpmshx_{kind}_shared" + suffix
            source, target = build_dir / name, destination / name
            metadata = destination / metadata_name
            record = dict(common, component=kind, source_library=str(source), target_library=str(target),
                          dependencies={} if kind == "geometry" else LOCK["sources"],
                          verification=("independent geometry callers and kernel smoke passed" if kind == "geometry"
                                        else "independent native callers and SuperLU error boundary passed"))
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fetch", "fetch-cmake", "fetch-eigen", "build", "verify", "publish"))
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/native-deps")
    parser.add_argument("--python-lock", type=Path, default=ROOT / "engineering/requirements/base.txt")
    parser.add_argument("--component", choices=("all", "coolprop", "pilot", "geometry"), default="all")
    args = parser.parse_args()
    python, host, cache = configured_python(), platform_name(), args.cache.resolve()
    if not cache.is_relative_to(ROOT / ".cache"):
        raise RuntimeError("Native dependency outputs must remain under this worktree's .cache/")
    if args.action == "fetch":
        fetch(cache, host)
    elif args.action == "fetch-cmake":
        fetch_cmake(cache, host)
    elif args.action == "fetch-eigen":
        fetch_eigen(cache)
    elif args.action == "build":
        build(cache, host, python, args.python_lock.resolve(), args.component)
    elif args.action == "publish":
        publish(cache, host, python, args.python_lock.resolve(), args.component)
    else:
        check_environment(cache, python, args.python_lock.resolve())
        verify(cache, host, args.component)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"native dependency pilot: {error}", file=sys.stderr)
        raise SystemExit(1) from error
