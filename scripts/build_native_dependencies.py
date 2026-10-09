"""Explicitly fetch, build, verify, or publish the locked native solver.

No package installation, production binding, system PATH change or runtime
download. Run with the interpreter recorded on the first line of .venv-path.
The build command is offline; only fetch and fetch-eigen use the network.
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
import tomllib
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
LOCK = tomllib.loads((ROOT / "native/dependencies-lock.toml").read_text())


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
        run(["git", "fetch", "--depth", "1", "origin", spec["commit"]], log, cwd=source)
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
        raise RuntimeError("Locked portable CMake is missing; run fetch first")
    return executable


def build(cache: Path, host: str, python: Path, lock: Path, component: str) -> None:
    log = cache / "logs" / "environment.log"
    run([python, "-m", "sjtu_tpmshx.runs.tools.check_locked_environment", lock], log)
    run([python, "-m", "pip", "check"], log)
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
        run([python, "-m", "scripts.generate_native_model_coefficients", "--output",
             generated / "tpmshx/model_coefficients.hpp"], cache / "logs" / "generate-model-coefficients.log")
        options = [f"-DTPMSHX_NATIVE_DEPS_ROOT={cache}", f"-DTPMSHX_COOLPROP_LIBRARY={library}",
                   f"-DTPMSHX_MODEL_INCLUDE_DIR={generated}",
                   "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]
        if host == "macos-arm64":
            options += ["-DCMAKE_OSX_ARCHITECTURES=arm64"]
        run([cmake, "-S", ROOT / "native/dependency-pilot", "-B", pilot,
             *generator, *options], cache / "logs" / f"configure-pilot-{host}.log")
        run([cmake, "--build", pilot, "--config", "Release", "--parallel", "2"],
            cache / "logs" / f"build-pilot-{host}.log")


def verify(cache: Path, host: str) -> None:
    verify_sources(cache)
    log = cache / "logs" / f"verify-pilot-{host}.log"
    version = run([cmake_path(cache, host), "--version"], log)
    if version.splitlines()[0] != f"cmake version {LOCK['cmake']['version']}":
        raise RuntimeError("Portable CMake version differs from the lock")
    build_dir = cache / "build" / f"pilot-{host}"
    suffix = ".exe" if host == "windows-x64" else ""
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
                   "simple_2d_smoke", "simple_3d_smoke", "simple_2d_c_static", "simple_2d_c_shared",
                   "simple_3d_c_static", "simple_3d_c_shared", "model_h_2d_smoke", "model_h_3d_smoke",
                   "model_h_c_static", "model_h_c_shared", "temperature_c_static", "temperature_c_shared",
                   "temperature_staggered_smoke", "full_2d_c_static", "full_2d_c_shared",
                   "full_3d_c_static", "full_3d_c_shared"):
        run([build_dir / f"{caller}{suffix}"], log)
    for storage in ("csc", "csr"):
        for case in ("allocations", "aborts", "singular", "concurrent"):
            run([build_dir / f"superlu_error_smoke{suffix}", "--case", case, "--format", storage], log)
    print(f"PASS: {host} locked sources, EOS, pressure, Quick Design/enthalpy/temperature/SIMPLE/model-h callers and SuperLU error boundary",
          flush=True)


def publish(cache: Path, host: str, python: Path, lock: Path) -> Path:
    """Build offline, verify, then replace the folder-launch library with a backup."""
    build(cache, host, python, lock, "all")
    verify(cache, host)
    name = ("tpmshx_solver_shared.dll" if host == "windows-x64"
            else "libtpmshx_solver_shared.dylib")
    source = cache / "build" / f"pilot-{host}" / name
    target = ROOT / "native/lib" / host / name
    log = cache / "logs" / f"publish-{host}.log"
    record = {
        "published_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": run(["git", "rev-parse", "HEAD"], log).strip(),
        "source_changes": run(["git", "status", "--porcelain", "--untracked-files=no"], log).splitlines(),
        "platform": host,
        "source_library": str(source),
        "target_library": str(target),
        "python": str(python),
        "python_lock": str(lock),
        "cmake_version": LOCK["cmake"]["version"],
        "generator": LOCK["cmake"][host]["generator"],
        "configuration": "Release",
        "dependencies": LOCK["sources"],
        "verification": "independent native callers and SuperLU error boundary passed",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata = target.with_name("build.json")
    with tempfile.TemporaryDirectory(prefix=".publish-", dir=target.parent) as temporary:
        staged = Path(temporary)
        shutil.copy2(source, staged / name)
        (staged / "build.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        old_record = staged / "old-build.json"
        if metadata.is_file():
            shutil.copy2(metadata, old_record)
        if target.is_file() and not filecmp.cmp(source, target, shallow=False):
            previous = target.parent / "previous"
            previous.mkdir(exist_ok=True)
            shutil.copy2(target, previous / name)
            if metadata.is_file():
                shutil.copy2(metadata, previous / "build.json")
            else:
                (previous / "build.json").write_text(
                    '{"provenance": "existing library without a build record"}\n', encoding="utf-8")
        (staged / "build.json").replace(metadata)
        try:
            (staged / name).replace(target)
        except OSError:
            if old_record.is_file():
                old_record.replace(metadata)
            else:
                metadata.unlink()
            raise
    print(f"Published verified library: {target}\nBuild record: {metadata}", flush=True)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fetch", "fetch-eigen", "build", "verify", "publish"))
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/native-deps")
    parser.add_argument("--python-lock", type=Path, default=ROOT / "requirements-lock.txt")
    parser.add_argument("--component", choices=("all", "coolprop", "pilot"), default="all")
    args = parser.parse_args()
    python, host, cache = configured_python(), platform_name(), args.cache.resolve()
    if not cache.is_relative_to(ROOT / ".cache"):
        raise RuntimeError("Native dependency outputs must remain under this worktree's .cache/")
    if args.action == "fetch":
        fetch(cache, host)
    elif args.action == "fetch-eigen":
        fetch_eigen(cache)
    elif args.action == "build":
        build(cache, host, python, args.python_lock.resolve(), args.component)
    elif args.action == "publish":
        publish(cache, host, python, args.python_lock.resolve())
    else:
        verify(cache, host)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"native dependency pilot: {error}", file=sys.stderr)
        raise SystemExit(1) from error
