"""Build and record the locked CoolProp archives, and derive their CI cache key.

The callers supply the lock and the command runner. The cache key covers only
the CoolProp inputs, so SuperLU and AMGCL changes keep a cached archive valid.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import tomllib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
LOCK_FILE = "engineering/native_build/dependencies-lock.toml"
HOST_OPTIONS = {"macos-arm64": "preparation-macos-options", "windows-x64": "windows-options"}

Run = Callable[..., str]


def coolprop_build_dir(cache: Path, host: str, role: str) -> Path:
    name = "coolprop-preparation" if role == "preparation" and host == "macos-arm64" else "coolprop"
    return cache / "build" / f"{name}-{host}"


def coolprop_library(cache: Path, host: str, role: str) -> Path:
    return coolprop_build_dir(cache, host, role) / (
        "Release/CoolProp.lib" if host == "windows-x64" else "libCoolProp.a")


def request_build_metadata(build_dir: Path) -> None:
    query = build_dir / ".cmake/api/v1/query"
    query.mkdir(parents=True, exist_ok=True)
    for name in ("codemodel-v2", "toolchains-v1"):
        (query / name).write_text("", encoding="utf-8")


def build_archives(cache: Path, host: str, python: Path, cmake: Path, lock: dict, run: Run, *,
                   request_metadata: Callable[[Path], None] = request_build_metadata,
                   record: Callable[[Path, str, str], None] | None = None) -> None:
    """Configure, build and record each CoolProp archive that this host needs.

    The caller can supply the metadata request and record steps; by default the
    record step uses ``record_coolprop_build`` with ``lock``.
    """
    spec = lock["sources"]["coolprop"]
    generator = ["-G", lock["cmake"][host]["generator"]]
    if host == "windows-x64":
        generator += ["-A", "x64"]
    options = [f"-D{value}" for value in spec["cmake-options"]]
    options += [f"-DPython_EXECUTABLE={python}"]
    options += ["-DFETCHCONTENT_FULLY_DISCONNECTED=ON"]
    options += [f"-DCPM_{dependency['cpm-name']}_SOURCE={(cache / 'src' / dependency['directory']).as_posix()}"
                for dependency in lock["sources"].values() if "cpm-name" in dependency]
    if host == "windows-x64":
        options += [f"-D{value}" for value in spec["windows-options"]]
    else:
        options += ["-DCMAKE_OSX_ARCHITECTURES=arm64"]
    roles = ("solver", "preparation") if host == "macos-arm64" else ("solver",)
    for role in roles:
        cp_build = coolprop_build_dir(cache, host, role)
        selected_options = list(options)
        if role == "preparation":
            selected_options += [f"-D{value}" for value in spec["preparation-macos-options"]]
        request_metadata(cp_build)
        run([cmake, "-S", cache / "src" / spec["directory"], "-B", cp_build,
             *generator, *selected_options], cache / "logs" / f"configure-{cp_build.name}.log")
        run([cmake, "--build", cp_build, "--config", "Release", "--parallel", "2"],
            cache / "logs" / f"build-{cp_build.name}.log")
        if record is None:
            record_coolprop_build(cache, host, role, lock)
        else:
            record(cache, host, role)


def record_coolprop_build(cache: Path, host: str, role: str, lock: dict) -> None:
    build_dir = coolprop_build_dir(cache, host, role)
    library = coolprop_library(cache, host, role)
    if not library.is_file():
        raise RuntimeError(f"CoolProp build did not produce {library}")
    reply = build_dir / ".cmake/api/v1/reply"
    indices = list(reply.glob("index-*.json"))
    if not indices:
        raise RuntimeError(f"Missing actual CoolProp CMake metadata: {reply}")
    index_path = max(indices, key=lambda path: path.stat().st_mtime_ns)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    objects = {}
    for kind in ("codemodel", "toolchains"):
        descriptor, = (item for item in index["objects"] if item["kind"] == kind)
        objects[kind] = json.loads((reply / descriptor["jsonFile"]).read_text(encoding="utf-8"))
    configuration, = (item for item in objects["codemodel"]["configurations"] if item["name"] == "Release")
    target_ref, = (item for item in configuration["targets"] if item["name"] == "CoolProp")
    target_path = reply / target_ref["jsonFile"]
    target = json.loads(target_path.read_text(encoding="utf-8"))
    if not any((build_dir / item["path"]).resolve() == library.resolve() for item in target["artifacts"]):
        raise RuntimeError("CoolProp CMake artifact differs from the built archive")
    groups = target["compileGroups"]
    if {item["language"] for item in groups} != {"C", "CXX"} or any(
            not item.get("compileCommandFragments") for item in groups):
        raise RuntimeError("CoolProp metadata omitted actual C/C++ compilation options")
    cache_values = {}
    for line in (build_dir / "CMakeCache.txt").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"(CMAKE_[A-Z0-9_]+):[^=]+=(.*)", line)
        if match and (match[1].startswith(("CMAKE_C_FLAGS", "CMAKE_CXX_FLAGS", "CMAKE_OSX_", "CMAKE_VS_"))
                      or match[1] in ("CMAKE_SYSTEM_VERSION", "CMAKE_MSVC_RUNTIME_LIBRARY", "CMAKE_GENERATOR")):
            cache_values[match[1]] = match[2]
    sdk = {"cmake_cache": cache_values}
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
    else:
        project = build_dir / "CoolProp.vcxproj"
        tree = ET.parse(project)
        sdk["visual_studio_project"] = str(project)
        sdk["windows_target_platform_versions"] = [item.text for item in tree.iter()
            if item.tag.rsplit("}", 1)[-1] == "WindowsTargetPlatformVersion"]
    spec = lock["sources"]["coolprop"]
    record = dict(role=role, platform=host, archive=str(library.resolve()), version=spec["version"],
                  revision=spec["commit"], configuration="Release", recorded_at=datetime.now(timezone.utc).isoformat(),
                  compile_groups=groups, toolchains=objects["toolchains"]["toolchains"], sdk=sdk,
                  evidence=dict(index=str(index_path), target=str(target_path),
                                cache=str(build_dir / "CMakeCache.txt")))
    (build_dir / "coolprop-build.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def coolprop_build_record(cache: Path, host: str, role: str, lock: dict) -> dict:
    archive_role = "preparation" if role == "preparation" and host == "macos-arm64" else "solver"
    library = coolprop_library(cache, host, role)
    record_path = coolprop_build_dir(cache, host, role) / "coolprop-build.json"
    if not library.is_file() or not record_path.is_file():
        raise RuntimeError(f"Build locked CoolProp archives and metadata first; missing {library} or {record_path}")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    spec = lock["sources"]["coolprop"]
    if (record["role"], record["platform"], record["version"], record["revision"]) != (
            archive_role, host, spec["version"], spec["commit"]):
        raise RuntimeError(f"CoolProp build record differs from the required role/source: {record_path}")
    groups = record["compile_groups"]
    if {item["language"] for item in groups} != {"C", "CXX"} or not record["toolchains"] or not record["sdk"]:
        raise RuntimeError(f"CoolProp build record omitted actual toolchain evidence: {record_path}")
    for group in groups:
        fragments = group.get("compileCommandFragments", [])
        if not fragments:
            raise RuntimeError(f"CoolProp build record omitted compilation options: {record_path}")
        if host == "macos-arm64":
            flags = shlex.split(" ".join(item["fragment"] for item in fragments))
            optimization = [value for value in flags if re.fullmatch(r"-O(?:[0-3sgz]|fast)", value)]
            expected = "-Os" if archive_role == "preparation" else "-O3"
            if not optimization or optimization[-1] != expected:
                raise RuntimeError(f"CoolProp effective optimization differs from {archive_role}: {record_path}")
    return dict(record, consumer_role=role, consumed_archive=str(library), record_source=str(record_path))


def coolprop_cache_digest(root: Path, lock: dict, host: str) -> str:
    """Return the SHA-256 key of the lock inputs that change a CoolProp archive on this host.

    A ``patch`` entry names repository files; the key includes their bytes.
    SuperLU and AMGCL have no ``cpm-name``, so they are not CoolProp inputs.
    """
    if host not in HOST_OPTIONS:
        raise ValueError(f"CoolProp archives are not built for {host}")
    coolprop = {key: value for key, value in lock["sources"]["coolprop"].items()
                if key not in HOST_OPTIONS.values() or key == HOST_OPTIONS[host]}
    dependencies = {name: spec for name, spec in sorted(lock["sources"].items()) if "cpm-name" in spec}
    patches = {}
    for name, spec in (("coolprop", coolprop), *dependencies.items()):
        files = spec.get("patch", [])
        for path in [files] if isinstance(files, str) else files:
            patches[f"{name}:{path}"] = hashlib.sha256((root / path).read_bytes()).hexdigest()
    inputs = dict(cmake=dict(version=lock["cmake"]["version"], generator=lock["cmake"][host]["generator"]),
                  coolprop=coolprop, dependencies=dependencies, patches=patches)
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    key = commands.add_parser("cache-key", help="Print the CoolProp CI cache key for one host.")
    key.add_argument("--host", required=True, choices=tuple(HOST_OPTIONS))
    args = parser.parse_args()
    lock = tomllib.loads((ROOT / LOCK_FILE).read_text(encoding="utf-8"))
    print(coolprop_cache_digest(ROOT, lock, args.host))


if __name__ == "__main__":
    main()
