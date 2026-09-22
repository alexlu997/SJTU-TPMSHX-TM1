"""Unit tests for controllers.session_manager.SessionManager.

Phase 2 of 2026-05-06 main.py refactor (audit fix #4). Uses tmp_path
fixture to isolate disk writes from the production package directory.
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication

from sjtu_tpmshx.controllers.session_manager import SessionManager, SCHEMA_VERSION


def _app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


@pytest.fixture
def sm(tmp_path):
    _app()
    return SessionManager(base_dir=tmp_path)


# ---------------------------------------------------------------- paths


def test_session_path_workspace_a_uses_legacy_filename(tmp_path):
    sm = SessionManager(base_dir=tmp_path)
    p = sm.session_path('A')
    assert p == tmp_path / '.last_session.json'


def test_session_path_workspaces_b_c(tmp_path):
    sm = SessionManager(base_dir=tmp_path)
    assert sm.session_path('B') == tmp_path / '.last_session_B.json'
    assert sm.session_path('C') == tmp_path / '.last_session_C.json'


def test_session_path_invalid_workspace_raises(sm):
    with pytest.raises(ValueError, match='unknown workspace'):
        sm.session_path('Z')


def test_default_base_dir_is_user_data_dir(tmp_path, monkeypatch):
    """Default construction uses the same stable directory as GUI history."""
    monkeypatch.setattr('sjtu_tpmshx.controllers.session_manager.user_data_dir',
                        lambda: tmp_path)
    sm = SessionManager()
    assert sm.base_dir == tmp_path


# ---------------------------------------------------------------- session io


def test_save_then_load_round_trip(sm):
    payload = {'temp_unit': 'K', 'line_edits': {'le_Nx': '20'},
               'combos': {'combo_dim': 1}, 'checks': {}}
    assert sm.save_session(payload, 'A')
    loaded = sm.load_session('A')
    assert loaded is not None
    # Round-trip preserves all keys + adds schema_version
    assert loaded['temp_unit'] == 'K'
    assert loaded['line_edits'] == {'le_Nx': '20'}
    assert loaded['combos'] == {'combo_dim': 1}
    assert loaded['schema_version'] == SCHEMA_VERSION


def test_load_missing_file_returns_none(sm):
    assert sm.load_session('A') is None


def test_load_malformed_json_returns_none(sm):
    sm.session_path('A').write_text('{ not valid json',
                                     encoding='utf-8')
    assert sm.load_session('A') is None


def test_load_non_dict_payload_returns_none(sm):
    """If file contains a list or string at top, return None (not crash)."""
    sm.session_path('A').write_text('[1, 2, 3]', encoding='utf-8')
    assert sm.load_session('A') is None


def test_load_legacy_file_without_schema_version_migrates_to_v0(sm):
    """Legacy file (no schema_version field) → migrated to v0 on read."""
    legacy = {'temp_unit': 'C', 'line_edits': {}, 'combos': {}}
    sm.session_path('A').write_text(json.dumps(legacy), encoding='utf-8')
    loaded = sm.load_session('A')
    assert loaded is not None
    assert loaded['schema_version'] == 0   # migration default
    assert loaded['temp_unit'] == 'C'      # other fields preserved


def test_save_stamps_schema_version(sm):
    sm.save_session({'a': 1}, 'A')
    raw = json.loads(sm.session_path('A').read_text(encoding='utf-8'))
    assert raw['schema_version'] == SCHEMA_VERSION






def test_save_session_rejects_non_dict(sm):
    with pytest.raises(TypeError, match='payload must be dict'):
        sm.save_session([1, 2, 3], 'A')


def test_workspaces_isolated(sm):
    sm.save_session({'mode': 'air'}, 'A')
    sm.save_session({'mode': 'water'}, 'B')
    a = sm.load_session('A')
    b = sm.load_session('B')
    assert a['mode'] == 'air'
    assert b['mode'] == 'water'


# ---------------------------------------------------------------- presets


def test_user_presets_round_trip(sm):
    presets = [
        {'name': 'Shanghai', 'line_edits': {'le_Nx': '20'}},
        {'name': 'Air-water', 'line_edits': {'le_Nx': '40'}},
    ]
    assert sm.save_user_presets(presets)
    loaded = sm.load_user_presets()
    assert len(loaded) == 2
    assert loaded[0]['name'] == 'Shanghai'


def test_load_presets_missing_file_returns_empty(sm):
    assert sm.load_user_presets() == []


def test_load_presets_malformed_returns_empty(sm):
    sm.presets_path().write_text('garbage{', encoding='utf-8')
    assert sm.load_user_presets() == []




def test_save_presets_rejects_non_list(sm):
    with pytest.raises(TypeError, match='presets must be list'):
        sm.save_user_presets({'wrong': 'type'})


# ---------------------------------------------------------------- workspace


def test_get_active_workspace_default_a(sm):
    assert sm.get_active_workspace() == 'A'


def test_set_get_active_workspace_round_trip(sm):
    assert sm.set_active_workspace('B')
    assert sm.get_active_workspace() == 'B'


def test_set_active_workspace_invalid_raises(sm):
    with pytest.raises(ValueError, match='unknown workspace'):
        sm.set_active_workspace('Z')


def test_get_active_workspace_falls_back_a_on_garbage(sm):
    sm.workspace_marker_path().write_text('not-a-workspace',
                                            encoding='utf-8')
    assert sm.get_active_workspace() == 'A'


def test_active_workspace_case_insensitive(sm):
    """Marker file with lowercase 'b' should resolve to 'B'."""
    sm.workspace_marker_path().write_text('b', encoding='utf-8')
    assert sm.get_active_workspace() == 'B'
