"""Desktop user files live outside the read-only application package."""
from __future__ import annotations

import logging
from pathlib import Path
import re

from PySide6.QtCore import QIODevice, QSaveFile, QStandardPaths


_APP_DIRECTORY = 'SJTU-TPMSHX-TM1'
_LEGACY_PACKAGE_DIR = Path(__file__).resolve().parents[1]
_DATA_FILES = (
    '.last_session.json', '.last_session_B.json', '.last_session_C.json',
    '.user_presets.json', '.workspace', '.session_timeline.jsonl', '.first_run_done',
)
_LOG = logging.getLogger(__name__)


def _directory(location, *parts: str) -> Path:
    base = QStandardPaths.writableLocation(location)
    if not base:
        raise OSError(f'No writable platform location for {location.name}')
    path = Path(base) / _APP_DIRECTORY
    path = path.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write(path: Path, data: bytes) -> None:
    target = QSaveFile(str(path))
    if not target.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(target.errorString())
    if target.write(data) != len(data) or not target.commit():
        raise OSError(target.errorString())


def _copy_missing(source: Path, destination: Path) -> None:
    if not destination.exists() and source.is_file():
        try:
            _write(destination, source.read_bytes())
        except OSError as exc:
            _LOG.warning('Could not import user file %s: %s', source, exc)


def user_data_dir() -> Path:
    """Return the stable user data directory; preserve existing legacy inputs.

    Copy only the known old files that are absent at the destination. The
    originals remain intact, and an existing user file always takes priority.
    """
    path = _directory(QStandardPaths.StandardLocation.GenericDataLocation)
    for name in _DATA_FILES:
        _copy_missing(_LEGACY_PACKAGE_DIR / name, path / name)
    return path


def _valid_appearance(name: str, value: str) -> bool:
    if name == 'theme':
        return value in ('dark', 'light')
    if name == 'density':
        return value in ('compact', 'cozy', 'comfortable')
    return name == 'accent' and re.fullmatch(r'#[0-9a-fA-F]{6}', value) is not None


def _appearance_dir() -> Path:
    return _directory(QStandardPaths.StandardLocation.GenericConfigLocation)


def load_appearance_settings() -> dict[str, str]:
    """Read the same files used by the appearance menu before widget creation."""
    path = _appearance_dir()
    values = {}
    for name in ('theme', 'density', 'accent'):
        try:
            value = (path / f'.{name}').read_text(encoding='utf-8').strip()
        except (OSError, UnicodeError):
            continue
        if _valid_appearance(name, value):
            values[name] = value
    return values


def save_appearance_setting(name: str, value: str) -> bool:
    if not _valid_appearance(name, value):
        raise ValueError(f'Invalid appearance setting: {name}={value!r}')
    try:
        _write(_appearance_dir() / f'.{name}', value.encode('utf-8'))
        return True
    except OSError as exc:
        _LOG.warning('Could not save %s preference: %s', name, exc)
        return False


def optimization_output_dir() -> Path:
    """GUI optimization results have a visible, writable Documents location."""
    return _directory(QStandardPaths.StandardLocation.DocumentsLocation, 'opt_runs')
