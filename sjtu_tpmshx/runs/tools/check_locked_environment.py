"""Fail when the active Python environment differs from a requirements lock."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from importlib import metadata
from pathlib import Path
import sys
from sysconfig import get_paths

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


class LockFileError(ValueError):
    """The lock is missing, ambiguous, or not exact."""


def read_lock(
    path: Path,
    marker_environment: Mapping[str, str] | None = None,
) -> dict[str, Requirement]:
    """Read active exact pins, following local ``-r`` includes."""
    environment = default_environment()
    if marker_environment:
        environment.update(marker_environment)

    locked: dict[str, Requirement] = {}
    locations: dict[str, str] = {}

    def visit(current: Path, stack: tuple[Path, ...]) -> None:
        current = current.resolve()
        if current in stack:
            chain = " -> ".join(str(item) for item in (*stack, current))
            raise LockFileError(f"recursive lock include: {chain}")
        try:
            lines = current.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise LockFileError(f"cannot read lock file {current}: {exc}") from exc

        for line_number, raw in enumerate(lines, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-r "):
                visit(current.parent / line[3:].strip(), (*stack, current))
                continue
            if line.startswith("--requirement "):
                visit(current.parent / line[14:].strip(), (*stack, current))
                continue
            if line.startswith("--extra-index-url ") or line.startswith(
                "--extra-index-url="
            ):
                continue
            if line.startswith("-"):
                raise LockFileError(
                    f"unsupported lock option at {current}:{line_number}: {line}"
                )

            try:
                requirement = Requirement(line)
            except InvalidRequirement as exc:
                raise LockFileError(
                    f"invalid requirement at {current}:{line_number}: {line}"
                ) from exc
            if requirement.marker and not requirement.marker.evaluate(
                environment=environment
            ):
                continue

            specifiers = list(requirement.specifier)
            if (
                requirement.url
                or requirement.extras
                or len(specifiers) != 1
                or specifiers[0].operator != "=="
                or "*" in specifiers[0].version
            ):
                raise LockFileError(
                    f"requirement must have one exact == pin at "
                    f"{current}:{line_number}: {line}"
                )

            name = canonicalize_name(requirement.name)
            location = f"{current}:{line_number}"
            if name in locked:
                raise LockFileError(
                    f"duplicate pin for {requirement.name} at {location}; "
                    f"first pinned at {locations[name]}"
                )
            locked[name] = requirement
            locations[name] = location

    visit(path, ())
    return locked


def installed_versions() -> dict[str, set[str]]:
    """Return every installed distribution, preserving duplicate versions."""
    installed: dict[str, set[str]] = {}
    site_packages = {get_paths()[key] for key in ("purelib", "platlib")}
    for distribution in metadata.distributions(path=site_packages):
        name = distribution.metadata.get("Name")
        if name:
            installed.setdefault(canonicalize_name(name), set()).add(
                distribution.version
            )
    return installed


def environment_issues(
    locked: Mapping[str, Requirement],
    installed: Mapping[str, set[str]] | None = None,
    *,
    allow_extra: Iterable[str] = (),
    check_extras: bool = True,
) -> list[str]:
    """Describe missing, mismatched, duplicate, and unexpected packages."""
    actual = installed_versions() if installed is None else installed
    issues: list[str] = []

    for name, requirement in locked.items():
        versions = actual.get(name)
        if not versions:
            issues.append(f"missing: {requirement.name}{requirement.specifier}")
        elif len(versions) != 1 or not all(
            requirement.specifier.contains(version, prereleases=True)
            for version in versions
        ):
            issues.append(
                f"version mismatch: {requirement.name}{requirement.specifier} "
                f"(installed {', '.join(sorted(versions))})"
            )

    if check_extras:
        allowed = {"pip", *(canonicalize_name(name) for name in allow_extra)}
        for name in sorted(set(actual) - set(locked) - allowed):
            issues.append(
                f"unexpected package: {name}=={','.join(sorted(actual[name]))}"
            )
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "lock",
        nargs="?",
        type=Path,
        default=Path("requirements/base.txt"),
    )
    parser.add_argument(
        "--allow-extra",
        action="append",
        default=[],
        metavar="PACKAGE",
        help="permit an installed package absent from the lock (repeatable)",
    )
    args = parser.parse_args(argv)

    try:
        locked = read_lock(args.lock)
    except LockFileError as exc:
        print(f"lock error: {exc}", file=sys.stderr)
        return 2

    issues = environment_issues(locked, allow_extra=args.allow_extra)
    if issues:
        print(f"environment differs from {args.lock}:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1

    print(f"environment matches {args.lock} ({len(locked)} active packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
