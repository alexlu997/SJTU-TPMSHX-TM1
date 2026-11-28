"""Fault injection for the no-solve GUI smoke entry points."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QComboBox, QPushButton, QVBoxLayout, QWidget

from tm1.applications.gui.controllers.session_manager import SessionManager
from tm1.applications.gui.controllers.user_storage import save_appearance_setting
from tm1.development.runs.smokes import smoke_ui_offscreen as navigation
from tm1.development.runs.smokes import smoke_ui_screenshots as screenshots


class SmokeWindow(QWidget):
    """Real Qt signals, visibility and storage, without a solver or the production window."""

    def __init__(self):
        super().__init__()
        self.store = SessionManager(parent=self)
        self.workbench = SimpleNamespace()
        layout = QVBoxLayout(self)
        self._canvas_cards = {key: QWidget(self) for key in ('layout', 'pareto')}
        for name in ('layout', 'result', 'pareto'):
            button = QPushButton(name, self)
            setattr(self, 'btn_tab_' + name, button)
            layout.addWidget(button)
            if name in self._canvas_cards:
                button.clicked.connect(lambda checked=False, key=name: self.select(key))
            else:
                button.setEnabled(False)
        self.combo_dim = QComboBox(self)
        self.combo_dim.addItems(['2D', '3D'])
        for widget in (self.combo_dim, *self._canvas_cards.values()):
            layout.addWidget(widget)
        self.select('layout')
        assert save_appearance_setting('theme', 'light')

    def select(self, key):
        self.workbench.active_tab = key
        for name, card in self._canvas_cards.items():
            card.setVisible(name == key)

    def closeEvent(self, event):
        assert self.store.save_session({'smoke': True})
        super().closeEvent(event)


@pytest.fixture
def install(monkeypatch, tmp_path):
    """Replace the production window and check that the tools keep the user state."""
    navigation._smoke_boot.get_app()
    user_dir = tmp_path / 'real-user'
    user_dir.mkdir()
    (user_dir / '.last_session.json').write_text('user session')
    (user_dir / '.theme').write_text('dark')
    monkeypatch.setattr('tm1.applications.gui.controllers.session_manager.user_data_dir', lambda: user_dir)
    monkeypatch.setattr('tm1.applications.gui.controllers.user_storage._appearance_dir', lambda: user_dir)
    created_dirs = []

    def install(fault=lambda window: None):
        def create():
            window = SmokeWindow()
            created_dirs.append(window.store.base_dir)
            fault(window)
            return window
        monkeypatch.setitem(sys.modules, 'tm1.applications.gui.ui.main_window', SimpleNamespace(Main_Menu=create))

    install()
    yield install
    assert (user_dir / '.last_session.json').read_text() == 'user session'
    assert (user_dir / '.theme').read_text() == 'dark'
    assert all(not directory.exists() for directory in created_dirs)


def _invoke(tool, tmp_path):
    return tool.main(['--output', str(tmp_path / 'images')]) if tool is screenshots else tool.main()


FAULTS = {
    'missing_entry': lambda window: delattr(window, 'btn_tab_pareto'),
    'broken_navigation': lambda window: window.btn_tab_pareto.clicked.disconnect(),
    'missing_dimension': lambda window: window.combo_dim.removeItem(window.combo_dim.findText('3D')),
}


@pytest.mark.parametrize('tool', [navigation, screenshots])
@pytest.mark.parametrize('fault', FAULTS)
def test_required_ui_failure_returns_nonzero(tool, fault, install, tmp_path, capsys):
    install(FAULTS[fault])
    assert _invoke(tool, tmp_path) == 1
    assert 'PASS' not in capsys.readouterr().out


@pytest.mark.parametrize('tool', [navigation, screenshots])
def test_qt_callback_exception_fails_and_restores_hook(tool, install, tmp_path, capsys):
    old_hook = sys.excepthook

    def explode():
        raise ValueError('injected Qt callback failure')

    install(lambda window: window.btn_tab_pareto.clicked.connect(explode))
    assert _invoke(tool, tmp_path) == 1
    assert sys.excepthook is old_hook
    output = capsys.readouterr()
    assert 'injected Qt callback failure' in output.err
    assert 'PASS' not in output.out


def test_failed_image_save_returns_nonzero(install, tmp_path, capsys):
    install(lambda window: setattr(window, 'grab', lambda: SimpleNamespace(save=lambda path: False)))
    assert _invoke(screenshots, tmp_path) == 1
    output = capsys.readouterr()
    assert 'Could not save screenshot' in output.err
    assert 'saved ' not in output.out
    assert 'PASS' not in output.out


def test_successful_tools_preserve_user_state_and_capture_optimizer(install, tmp_path):
    assert _invoke(navigation, tmp_path) == 0
    assert _invoke(screenshots, tmp_path) == 0
    paths = sorted((tmp_path / 'images').glob('*.png'))
    assert len(paths) == 4
    assert paths[-1].name == '04_optimize_panel.png'
    assert all(path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n') for path in paths)


def test_default_screenshot_output_is_worktree_cache(install, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert screenshots.main([]) == 0
    assert (Path('.cache/ui-smoke-screenshots') / '04_optimize_panel.png').is_file()
    assert not Path('vault').exists()
