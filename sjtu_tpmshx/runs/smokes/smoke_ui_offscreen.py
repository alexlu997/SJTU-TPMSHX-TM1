"""Check current GUI navigation and dimensions offscreen without solving.

Run from the repository root as
``python -m sjtu_tpmshx.runs.smokes.smoke_ui_offscreen``.
Uses temporary user state; missing controls, failed navigation or callback
exceptions return exit code 1. This does not qualify native 3D rendering.
"""
from __future__ import annotations
from contextlib import contextmanager
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import traceback
from unittest.mock import patch

from sjtu_tpmshx.runs import _smoke_boot   # sets QT_QPA=offscreen BEFORE any Qt import

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QPushButton, QToolButton, QComboBox


@contextmanager
def _smoke_window():
    """Use the existing session-directory override without touching user files."""
    app = _smoke_boot.get_app()
    if app.platformName() != 'offscreen':
        raise RuntimeError('UI smoke requires QT_QPA_PLATFORM=offscreen')
    cache = Path('.cache/ui-smoke')
    cache.mkdir(parents=True, exist_ok=True)
    caught = []

    def hook(exctype, value, tb):
        caught.append(''.join(traceback.format_exception(exctype, value, tb)))

    with TemporaryDirectory(dir=cache) as directory:
        state_dir = Path(directory)
        with patch('sjtu_tpmshx.controllers.session_manager.user_data_dir',
                   return_value=state_dir), \
             patch('sjtu_tpmshx.controllers.user_storage._appearance_dir',
                   return_value=state_dir), \
             patch.dict(os.environ, {'QT_REDUCED_MOTION': '1'}), \
             patch.object(sys, 'excepthook', hook):
            from sjtu_tpmshx.main import Main_Menu
            win = Main_Menu()
            try:
                win.resize(1600, 1000)
                win.show()
                app.processEvents()
                yield app, win
            finally:
                closed = win.close()
                app.processEvents()
                win.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                if not closed:
                    raise RuntimeError('Smoke window did not close')
            if caught:
                raise RuntimeError('Unhandled Qt callback exceptions:\n' + '\n'.join(caught))


def _inspect_window(app, win):
    print("[1/5] Constructed Main_Menu", flush=True)
    print(f"      window title: {win.windowTitle()}", flush=True)
    print(f"      size: {win.size().width()}x{win.size().height()}", flush=True)

    # Enumerate buttons
    print("\n[2/5] Enumerating QPushButton + QToolButton:", flush=True)
    btns = win.findChildren(QPushButton) + win.findChildren(QToolButton)
    print(f"      total: {len(btns)} buttons", flush=True)
    visible_enabled = sum(1 for b in btns if b.isVisible() and b.isEnabled())
    visible_disabled = sum(1 for b in btns if b.isVisible() and not b.isEnabled())
    hidden = sum(1 for b in btns if not b.isVisible())
    print(f"      visible+enabled:  {visible_enabled}", flush=True)
    print(f"      visible+disabled: {visible_disabled}", flush=True)
    print(f"      hidden:           {hidden}", flush=True)

    # List visible-enabled non-toolbar buttons by text
    interesting = []
    for b in btns:
        if not (b.isVisible() and b.isEnabled()): continue
        text = b.text() or b.toolTip() or repr(b.objectName())
        interesting.append((text, b))
    print("\n      first 15 visible+enabled by text:", flush=True)
    for text, b in interesting[:15]:
        oname = b.objectName() or '<no-name>'
        print(f"        - {text!r:<35} obj={oname}", flush=True)

    # Combo enumeration
    combos = win.findChildren(QComboBox)
    print(f"\n[3/5] QComboBox count: {len(combos)}", flush=True)
    for c in combos:
        if c.isVisible() and c.isEnabled():
            print(f"      {c.objectName() or '<no-name>'}: "
                  f"current = {c.currentText()!r}, items = {c.count()}", flush=True)

    # Result exists but is normally disabled before any calculation.
    print("\n[4/5] Tab navigation test", flush=True)
    tab_attrs = ['btn_tab_layout', 'btn_tab_result', 'btn_tab_pareto']
    for t in tab_attrs:
        b = getattr(win, t, None)
        if b is None:
            raise RuntimeError(f'Required navigation entry is missing: {t}')
        state = 'visible' if b.isVisible() else 'hidden'
        en = 'enabled' if b.isEnabled() else 'DISABLED'
        print(f"      {t}: {state} {en}  text={b.text()!r}", flush=True)
        if not b.isVisible():
            raise RuntimeError(f'Required navigation entry is hidden: {t}')
        if t != 'btn_tab_result':
            if not b.isEnabled():
                raise RuntimeError(f'Required navigation entry is disabled: {t}')
            b.click()
            app.processEvents()
            expected = 'layout' if t == 'btn_tab_layout' else 'pareto'
            if win._active_tab != expected or not win._canvas_cards[expected].isVisibleTo(win):
                raise RuntimeError(f'Navigation did not show {expected}')

    # Combo dim switch (2D ↔ 3D)
    print("\n[5/5] 2D ↔ 3D switching", flush=True)
    combo_dim = getattr(win, 'combo_dim', None)
    if combo_dim is None:
        raise RuntimeError('Required dimension selector is missing')
    for target in ('2D', '3D'):
        index = combo_dim.findText(target)
        if index < 0:
            raise RuntimeError(f'Dimension selector has no {target} option')
        combo_dim.setCurrentIndex(index)
        app.processEvents()
        if combo_dim.currentText() != target:
            raise RuntimeError(f'Dimension did not change to {target}')
        print(f"      dimension = {target}: OK", flush=True)


def main():
    try:
        with _smoke_window() as (app, win):
            _inspect_window(app, win)
    except Exception:
        traceback.print_exc()
        print('UI smoke FAIL', flush=True)
        return 1
    print('UI smoke PASS', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
