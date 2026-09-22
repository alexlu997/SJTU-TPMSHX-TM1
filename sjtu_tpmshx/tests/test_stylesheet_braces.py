"""Sanity check: every Qt stylesheet built by SJTU-TPMSHX must have balanced
`{`/`}` braces, and Qt must accept all of them at Main_Menu build time.

Origin: D-1 Bug 1 — three call sites in theme.py and ui_builders.py had a
Python f-string typo where `}}` appeared in a NON-f-string concatenation
segment, producing two literal `}` characters. The result was CSS like
`QComboBox QAbstractItemView{...outline:none;}}` — an unbalanced extra
closing brace that Qt's CSS parser rejected, leaving the affected widgets
without their intended styling. Kept as a permanent regression guard
against the same kind of typo recurring anywhere in the GUI.
"""
import os, sys
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _balanced(name, css):
    o = css.count('{')
    c = css.count('}')
    assert o == c, f"{name}: {{={o} vs }}={c} — unbalanced (extra {'closing' if c>o else 'opening'} brace)\n  CSS={css!r}"


def test_build_styles_braces_balanced():
    """Every Qt stylesheet returned by _build_styles must have matched braces."""
    from sjtu_tpmshx.ui.theme import _build_styles
    s = _build_styles()
    for key, css in s.items():
        if not isinstance(css, str):
            continue
        if '{' not in css and '}' not in css:
            continue  # plain property string, no selector block
        _balanced(f"light/{key}", css)
    print("test_build_styles_braces_balanced PASS")


def test_main_menu_no_qt_parse_warnings(tmp_path, monkeypatch):
    """Build Main_Menu; assert Qt prints no stylesheet parse failures."""
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtWidgets import QApplication

    from sjtu_tpmshx.controllers import session_manager
    monkeypatch.setattr(session_manager, 'user_data_dir', lambda: tmp_path)
    captured = []
    def _handler(msg_type, context, message):
        captured.append((msg_type, str(message)))
    previous_handler = qInstallMessageHandler(_handler)
    try:
        _app = QApplication.instance() or QApplication(sys.argv)
        from sjtu_tpmshx.main import Main_Menu
        w = Main_Menu()
        assert w.sm.base_dir == tmp_path
        w.close()
        assert w.sm.session_path(w._active_workspace).is_file()
        w.deleteLater()
    finally:
        qInstallMessageHandler(previous_handler)
    bad = [m for _, m in captured if 'Could not parse stylesheet' in m]
    assert not bad, f"Qt rejected {len(bad)} stylesheet(s); first:\n  {bad[0]}"
    print(f"test_main_menu_no_qt_parse_warnings PASS  ({len(captured)} qt msgs total, 0 stylesheet parse failures)")
