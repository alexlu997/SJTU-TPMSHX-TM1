"""Fault injection for the no-solve GUI smoke entry points."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QComboBox, QPushButton, QVBoxLayout, QWidget

from sjtu_tpmshx.controllers.session_manager import SessionManager
from sjtu_tpmshx.controllers.user_storage import save_appearance_setting
from sjtu_tpmshx.runs.smokes import smoke_ui_offscreen as navigation
from sjtu_tpmshx.runs.smokes import smoke_ui_screenshots as screenshots


class SmokeWindow(QWidget):
    """Real Qt signals/visibility/storage; no solver or production window startup."""

    def __init__(self):
        super().__init__()
        self.sm = SessionManager(parent=self)
        layout = QVBoxLayout(self)
        self._active_tab = 'layout'
        self._canvas_cards = {key: QWidget(self) for key in ('layout', 'pareto')}
        for name, target in (('layout', 'layout'), ('result', None), ('pareto', 'pareto')):
            button = QPushButton(name, self)
            setattr(self, 'btn_tab_' + name, button)
            layout.addWidget(button)
            if target:
                button.clicked.connect(lambda checked=False, key=target: self.select(key))
            else:
                button.setEnabled(False)
        self.combo_dim = QComboBox(self)
        self.combo_dim.addItems(['2D', '3D'])
        layout.addWidget(self.combo_dim)
        for card in self._canvas_cards.values():
            layout.addWidget(card)
        self.select('layout')
        assert save_appearance_setting('theme', 'light')

    def select(self, key):
        self._active_tab = key
        for name, card in self._canvas_cards.items():
            card.setVisible(name == key)

    def closeEvent(self, event):
        assert self.sm.save_session({'smoke': True})
        super().closeEvent(event)


@pytest.fixture
def smoke_factory(monkeypatch, tmp_path):
    app = navigation._smoke_boot.get_app()
    user_dir = tmp_path / 'real-user'
    user_dir.mkdir()
    (user_dir / '.last_session.json').write_text('user session')
    (user_dir / '.theme').write_text('dark')
    monkeypatch.setattr('sjtu_tpmshx.controllers.session_manager.user_data_dir', lambda: user_dir)
    monkeypatch.setattr('sjtu_tpmshx.controllers.user_storage._appearance_dir', lambda: user_dir)
    created_dirs = []

    def install(fault=lambda window: None):
        def create():
            window = SmokeWindow()
            created_dirs.append(window.sm.base_dir)
            fault(window)
            return window
        monkeypatch.setitem(sys.modules, 'sjtu_tpmshx.main', SimpleNamespace(Main_Menu=create))

    install()
    yield install, app
    assert (user_dir / '.last_session.json').read_text() == 'user session'
    assert (user_dir / '.theme').read_text() == 'dark'
    assert all(not directory.exists() for directory in created_dirs)


def _invoke(tool, tmp_path):
    return tool.main(['--output', str(tmp_path / 'images')]) if tool is screenshots else tool.main()


@pytest.mark.parametrize('tool', [navigation, screenshots])
@pytest.mark.parametrize('fault', ['missing_entry', 'broken_navigation', 'missing_dimension'])
def test_required_ui_failure_returns_nonzero(tool, fault, smoke_factory, tmp_path, capsys):
    install, _app = smoke_factory

    def inject(window):
        if fault == 'missing_entry':
            del window.btn_tab_pareto
        elif fault == 'broken_navigation':
            window.btn_tab_pareto.clicked.disconnect()
        else:
            window.combo_dim.removeItem(window.combo_dim.findText('3D'))

    install(inject)
    assert _invoke(tool, tmp_path) == 1
    assert 'PASS' not in capsys.readouterr().out


@pytest.mark.parametrize('tool', [navigation, screenshots])
def test_qt_callback_exception_fails_and_restores_hook(tool, smoke_factory, tmp_path, capsys):
    install, _app = smoke_factory
    old_hook = sys.excepthook

    def explode():
        raise ValueError('injected Qt callback failure')

    install(lambda window: window.btn_tab_pareto.clicked.connect(explode))
    assert _invoke(tool, tmp_path) == 1
    assert sys.excepthook is old_hook
    output = capsys.readouterr()
    assert 'injected Qt callback failure' in output.err
    assert 'PASS' not in output.out


def test_failed_image_save_returns_nonzero(smoke_factory, tmp_path, capsys):
    install, _app = smoke_factory
    install(lambda window: setattr(window, 'grab', lambda: SimpleNamespace(save=lambda path: False)))
    assert _invoke(screenshots, tmp_path) == 1
    output = capsys.readouterr()
    assert 'Could not save screenshot' in output.err
    assert 'saved ' not in output.out
    assert 'PASS' not in output.out


def test_successful_tools_preserve_user_state_and_capture_optimizer(smoke_factory, tmp_path):
    assert _invoke(navigation, tmp_path) == 0
    assert _invoke(screenshots, tmp_path) == 0
    paths = sorted((tmp_path / 'images').glob('*.png'))
    assert len(paths) == 4
    assert paths[-1].name == '04_optimize_panel.png'
    assert all(path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n') for path in paths)


def test_default_screenshot_output_is_worktree_cache(smoke_factory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert screenshots.main([]) == 0
    assert (Path('.cache/ui-smoke-screenshots') / '04_optimize_panel.png').is_file()
    assert not Path('vault').exists()
