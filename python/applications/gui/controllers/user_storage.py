"""Desktop user files live outside the read-only application package."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import re

from PySide6.QtCore import QIODevice, QSaveFile, QStandardPaths

from tm1.postprocess.result_display import COLORMAP_CHOICES, COLORMAP_QUANTITIES

_APP_DIRECTORY = 'SJTU-TPMSHX-TM1'
_CMAP_SETTINGS = tuple(f'cmap_{quantity}' for quantity in COLORMAP_QUANTITIES)
_APPEARANCE_SETTINGS = ('theme', 'density', 'accent', 'reduced_motion', 'inspector', *_CMAP_SETTINGS)
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


def user_data_dir() -> Path:
    """Return the writable user data directory."""
    return _directory(QStandardPaths.StandardLocation.GenericDataLocation)


def _valid_appearance(name: str, value: str) -> bool:
    if name == 'theme':
        return value in ('dark', 'light')
    if name == 'density':
        return value in ('compact', 'cozy', 'comfortable')
    if name == 'accent':
        return re.fullmatch(r'#[0-9a-fA-F]{6}', value) is not None
    if name == 'reduced_motion':
        return value in ('true', 'false')
    if name == 'inspector':
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return False
        if not isinstance(parsed, dict):
            return False
        for page_key, entry in parsed.items():
            if page_key not in ('run', 'result', 'opt', 'qd') or not isinstance(entry, dict):
                return False
            if not isinstance(entry.get('open'), bool):
                return False
            tab = entry.get('tab')
            if not isinstance(tab, int) or isinstance(tab, bool) or tab < 0:
                return False
        return True
    if name in _CMAP_SETTINGS:
        return value in COLORMAP_CHOICES
    return False


def _appearance_dir() -> Path:
    return _directory(QStandardPaths.StandardLocation.GenericConfigLocation)


def load_appearance_settings() -> dict[str, str]:
    """Read the appearance files before widget creation."""
    path = _appearance_dir()
    values = {}
    for name in _APPEARANCE_SETTINGS:
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
