"""Rejected session input remains recoverable after real Qt close/switch flows."""
import json
from pathlib import Path

import pytest

from sjtu_tpmshx.controllers.session_manager import SessionManager


@pytest.fixture
def session_window(tmp_path, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication, QMessageBox
    from sjtu_tpmshx.main import Main_Menu

    app = QApplication.instance() or QApplication(['pytest', '-platform', 'offscreen'])
    original_init = SessionManager.__init__
    monkeypatch.setattr(SessionManager, '__init__',
        lambda self, base_dir=None, parent=None: original_init(self, base_dir=tmp_path, parent=parent))
    messages, windows = [], []
    monkeypatch.setattr(QMessageBox, 'warning',
        lambda *args: messages.append(args[1:3]) or QMessageBox.StandardButton.Cancel)

    def build(payload, workspace='A'):
        path = SessionManager(base_dir=tmp_path).session_path(workspace)
        raw = (json.dumps(payload, ensure_ascii=False, indent=3) + '\n').encode()
        path.write_bytes(raw)
        window = Main_Menu()
        windows.append(window)
        app.processEvents()
        return window, path, raw, messages

    yield build
    for window in windows:
        monkeypatch.setattr(window, '_save_session', lambda: True)
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _bad_preset():
    return {'line_edits': {'le_L': '0.333', 'le_TinA': 'oops'}}


def test_semantic_restore_rejection_preserves_original_after_close(session_window):
    window, path, raw, messages = session_window(_bad_preset())
    assert window.le_L.text() != '0.333'
    assert window.le_TinA.text() != 'oops'
    window.le_L.setText('0.199')
    assert window.close()
    assert json.loads(path.read_text())['line_edits']['le_L'] == '0.199'
    backups = list(path.parent.glob(path.name + '.corrupt-*'))
    assert len(backups) == 1 and backups[0].read_bytes() == raw
    assert any('le_TinA' in text and str(backups[0]) in text for _, text in messages)


def test_workspace_switch_preserves_rejected_workspace_file(session_window):
    from PySide6.QtWidgets import QApplication
    window, path, raw, messages = session_window(_bad_preset(), 'B')
    window.le_L.setText('0.211')
    window._switch_workspace('B')
    QApplication.processEvents()
    assert window._active_workspace == 'B'
    assert window.le_L.text() != '0.333'
    window.le_L.setText('0.199')
    window._switch_workspace('C')
    assert window._active_workspace == 'C'
    assert json.loads(path.read_text())['line_edits']['le_L'] == '0.199'
    assert json.loads(window.sm.session_path('A').read_text())['line_edits']['le_L'] == '0.211'
    backups = list(path.parent.glob(path.name + '.corrupt-*'))
    assert len(backups) == 1 and backups[0].read_bytes() == raw
    assert any('le_TinA' in text for _, text in messages)


def test_failed_preservation_blocks_overwrite_then_retries(session_window, monkeypatch):
    original = SessionManager._quarantine_corrupt
    monkeypatch.setattr(SessionManager, '_quarantine_corrupt', lambda self, path: None)
    window, path, raw, messages = session_window(_bad_preset())
    window.le_L.setText('0.199')
    assert not window.close()
    window._switch_workspace('B')
    assert window._active_workspace == 'A'
    assert path.read_bytes() == raw
    assert any('会话未保存' == title for title, _ in messages)
    monkeypatch.setattr(SessionManager, '_quarantine_corrupt', original)
    assert window.close()
    assert json.loads(path.read_text())['line_edits']['le_L'] == '0.199'
    assert [p.read_bytes() for p in path.parent.glob(path.name + '.corrupt-*')] == [raw]


@pytest.mark.parametrize('content', ['[1, 2, 3]', '{ broken JSON', '\ufffd'])
def test_rejected_file_survives_failed_quarantine_and_later_save(tmp_path, monkeypatch, content):
    manager = SessionManager(base_dir=tmp_path)
    path = manager.session_path()
    raw = content.encode() if content != '\ufffd' else b'\xff\xfe'
    path.write_bytes(raw)
    original = manager._quarantine_corrupt
    monkeypatch.setattr(manager, '_quarantine_corrupt', lambda path: None)
    assert manager.load_session() is None
    assert not manager.save_session({'line_edits': {'le_L': '0.2'}})
    assert path.read_bytes() == raw
    monkeypatch.setattr(manager, '_quarantine_corrupt', original)
    assert manager.save_session({'line_edits': {'le_L': '0.2'}})
    assert [p.read_bytes() for p in tmp_path.glob(path.name + '.corrupt-*')] == [raw]
    assert manager.load_session()['line_edits']['le_L'] == '0.2'


def test_unreadable_session_is_preserved_before_replacement(tmp_path, monkeypatch):
    import builtins
    manager = SessionManager(base_dir=tmp_path)
    path = manager.session_path()
    raw = b'{"line_edits": {"le_L": "0.333"}}'
    path.write_bytes(raw)
    real_open = builtins.open

    def failed_read(file, mode='r', *args, **kwargs):
        if Path(file) == path and mode == 'r':
            raise PermissionError('injected session read failure')
        return real_open(file, mode, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'open', failed_read)
        assert manager.load_session() is None
    assert manager.save_session({'line_edits': {'le_L': '0.2'}})
    assert [p.read_bytes() for p in tmp_path.glob(path.name + '.corrupt-*')] == [raw]


def test_repeated_rejections_keep_every_original(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(time, 'time', lambda: 1234.)
    manager = SessionManager(base_dir=tmp_path)
    path = manager.session_path()
    originals = [b'{ broken first', b'{ broken second']
    for raw in originals:
        path.write_bytes(raw)
        assert manager.load_session() is None
    assert sorted(p.read_bytes() for p in tmp_path.glob(path.name + '.corrupt-*')) == sorted(originals)


def test_removed_rejected_file_does_not_prevent_new_session(tmp_path, monkeypatch):
    manager = SessionManager(base_dir=tmp_path)
    path = manager.session_path()
    path.write_text('[1]')
    monkeypatch.setattr(manager, '_quarantine_corrupt', lambda path: None)
    assert manager.load_session() is None
    path.unlink()  # The original was explicitly removed outside the app.
    assert manager.save_session({'line_edits': {'le_L': '0.2'}})
    assert manager.load_session()['line_edits']['le_L'] == '0.2'
