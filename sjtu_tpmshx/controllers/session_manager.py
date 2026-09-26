"""SessionManager — file-based session + preset persistence with versioning.

Phase 2 of 2026-05-06 main.py refactor (audit fix #4). Aggregates the IO
that was previously inlined in Main_Menu:

    Main_Menu method                  SessionManager method
    ──────────────────────────        ─────────────────────────────
    self._session_path(ws)            sm.session_path(ws)
    self._save_session()              sm.save_session(payload, ws)
    self._restore_session()           sm.load_session(ws)
    self._user_presets_path()         sm.presets_path()
    self._load_user_presets()         sm.load_user_presets()
    self._save_user_presets(presets)  sm.save_user_presets(presets)

File names under the platform user data directory:
    .last_session.json        ← workspace A
    .last_session_B.json      ← workspace B
    .last_session_C.json      ← workspace C
    .user_presets.json        ← named preset library
    .workspace               ← single-char active workspace marker

Schema version (NEW)
--------------------
All session/preset payloads now include `schema_version` (currently 1).
Older files without the field are treated as v0 and silently migrated on
load (no field changes yet — version stamp is forward-compat only).

`base_dir` remains configurable for isolated sessions and tests. The default
imports existing package-local user files without changing the originals.

Phase 2 of 2026-05-06 plan #4 refactor.
See vault/reports/refactor/2026-05-06-main-py-refactor-plan-CN.md.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from PySide6.QtCore import QObject

from sjtu_tpmshx.controllers.user_storage import user_data_dir
from sjtu_tpmshx.logutil import get_logger


_log = get_logger(__name__)


SCHEMA_VERSION = 1


class SessionManager(QObject):
    """Disk persistence for session state, user presets, and active workspace.

    Construct with no args to use the platform user data directory:
        sm = SessionManager()
        sm = SessionManager(parent=window) # Qt parent for cleanup

    Or override base_dir for isolated sessions and testing:
        sm = SessionManager(base_dir=tmp_path)

    """

    SCHEMA_VERSION = SCHEMA_VERSION
    VALID_WORKSPACES = ('A', 'B', 'C')


    def __init__(self, base_dir: Optional[os.PathLike] = None,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        if base_dir is None:
            base_dir = user_data_dir()
        self._base = Path(base_dir)
        self._unrestored_sessions: set[Path] = set()

    # ------------------------------------------------------------------ paths

    @property
    def base_dir(self) -> Path:
        return self._base

    def session_path(self, workspace: str = 'A') -> Path:
        """Path to .last_session_<ws>.json. Workspace A keeps legacy filename."""
        if workspace not in self.VALID_WORKSPACES:
            raise ValueError(
                f"unknown workspace: {workspace!r} "
                f"(expected one of {self.VALID_WORKSPACES})")
        if workspace == 'A':
            return self._base / '.last_session.json'
        return self._base / f'.last_session_{workspace}.json'

    def presets_path(self) -> Path:
        return self._base / '.user_presets.json'

    def workspace_marker_path(self) -> Path:
        return self._base / '.workspace'

    # ------------------------------------------------------------------ session

    def load_session(self, workspace: str = 'A') -> Optional[Dict[str, Any]]:
        """Return parsed session payload or None if file missing/malformed.

        Auto-migrates pre-v1 files (no schema_version field) on read by
        injecting `schema_version: 0` so caller can route by version.
        """
        path = self.session_path(workspace)
        if not path.exists():
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # robustness-hardening (2026-07-03): a corrupt session used to
            # silently revert the workspace to defaults AND be destroyed by
            # the next save. Quarantine it so the user's data stays
            # recoverable and the corruption is visible on disk.
            self.quarantine_session(workspace)
            return None
        except OSError as error:
            self._unrestored_sessions.add(path)
            _log.warning("Could not read session %s: %s", path, error)
            return None
        if not isinstance(payload, dict):
            self.quarantine_session(workspace)
            return None
        self._unrestored_sessions.discard(path)
        # Schema migration: legacy files missing the field → v0
        payload.setdefault('schema_version', 0)
        # Future: payload = self._migrate(payload) ...
        return payload

    def quarantine_session(self, workspace: str = 'A') -> Optional[Path]:
        """Preserve an unrestored session; failed preservation prevents overwriting it."""
        path = self.session_path(workspace)
        self._unrestored_sessions.add(path)
        if not path.exists():
            self._unrestored_sessions.discard(path)
            return None
        backup = self._quarantine_corrupt(path)
        if backup is not None:
            self._unrestored_sessions.discard(path)
        return backup

    def _quarantine_corrupt(self, path: Path) -> Optional[Path]:
        """Move an unreadable/rejected file to a unique sibling; retain it on failure."""
        backup = path.with_name(f"{path.name}.corrupt-{uuid4().hex}")
        try:
            path.rename(backup)
        except OSError as error:
            _log.warning("Could not preserve user file %s: %s", path, error)
            return None
        return backup

    def _atomic_write_json(self, path: Path, data: Any) -> bool:
        """Write JSON to ``path`` atomically.

        2026-05-20 UI sweep: previously the JSON dump went straight to the
        final path; a process crash mid-write (Qt segfault during compute
        teardown, power loss, or OOM kill) left the file half-written and
        unparseable on next launch — workspaces silently reverted to the
        baked-in defaults. Now we write to ``<path>.tmp`` first, fsync the
        bytes, then ``os.replace`` for a same-filesystem atomic swap.
        """
        tmp = path.with_suffix(path.suffix + '.tmp')
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except (OSError, AttributeError):
                    # fsync may fail on some virtual filesystems and is
                    # not available on every platform — tolerate it.
                    pass
            os.replace(tmp, path)
            return True
        except OSError:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            return False

    def save_session(self, payload: Dict[str, Any],
                     workspace: str = 'A') -> bool:
        """Write payload to disk. Returns True on success, False on IO error.

        Adds schema_version stamp before writing. Uses atomic
        write-to-temp + os.replace so a crash mid-write does not corrupt
        the prior session file.
        """
        if not isinstance(payload, dict):
            raise TypeError(f"payload must be dict, got {type(payload).__name__}")
        out = dict(payload)
        out['schema_version'] = SCHEMA_VERSION
        path = self.session_path(workspace)
        if path in self._unrestored_sessions:
            self.quarantine_session(workspace)
            if path in self._unrestored_sessions:
                return False
        if self._atomic_write_json(path, out):
            return True
        return False

    # ------------------------------------------------------------------ presets

    def load_user_presets(self) -> List[Dict[str, Any]]:
        """Return list of saved presets (possibly empty)."""
        path = self.presets_path()
        if not path.exists():
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return []
            presets = data.get('presets', [])
            return list(presets) if isinstance(presets, list) else []
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Same quarantine rationale as load_session — a corrupt preset
            # library must not be silently clobbered by the next save.
            self._quarantine_corrupt(path)
            return []
        except OSError:
            return []

    def save_user_presets(self, presets: List[Dict[str, Any]]) -> bool:
        """Persist preset list. Returns True on success.

        Uses atomic write so a crash mid-save does not erase the user's
        preset library.
        """
        if not isinstance(presets, list):
            raise TypeError(
                f"presets must be list, got {type(presets).__name__}")
        if self._atomic_write_json(
                self.presets_path(),
                {'schema_version': SCHEMA_VERSION, 'presets': presets}):
            return True
        return False

    # ------------------------------------------------------------------ workspace

    def get_active_workspace(self) -> str:
        """Read .workspace marker. Returns 'A' if missing/malformed."""
        path = self.workspace_marker_path()
        if not path.exists():
            return 'A'
        try:
            content = path.read_text(encoding='utf-8').strip().upper()
        except UnicodeDecodeError:
            self._quarantine_corrupt(path)
            return 'A'
        except OSError:
            return 'A'
        return content if content in self.VALID_WORKSPACES else 'A'

    def set_active_workspace(self, workspace: str) -> bool:
        """Persist active workspace marker. Returns True on success.

        2026-05-20 UI sweep: single-char marker now also uses
        write-tmp-then-rename so a power loss does not strand the
        workspace at the legacy 'A' default.
        """
        if workspace not in self.VALID_WORKSPACES:
            raise ValueError(
                f"unknown workspace: {workspace!r} "
                f"(expected one of {self.VALID_WORKSPACES})")
        path = self.workspace_marker_path()
        tmp = path.with_suffix(path.suffix + '.tmp')
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(workspace)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except (OSError, AttributeError):
                    pass
            os.replace(tmp, path)
            return True
        except OSError:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            return False

    # ------------------------------------------------------------------ misc

    def __repr__(self) -> str:
        return (f'<SessionManager base={self._base} '
                f'active_ws={self.get_active_workspace()} '
                f'schema_v{SCHEMA_VERSION}>')
