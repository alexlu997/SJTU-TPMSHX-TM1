"""Read-only info / help dialogs for ``Main_Menu``.

Extracted from the ``main`` god object: the overview-dashboard launcher and
the solve-log viewer. Pure presentation glue — no solver / numeric path.
Adopted via ``class Main_Menu(RunHistoryMixin, DialogsMixin, ..., QMainWindow)``;
methods resolve on the live window through the MRO, so external callers
(command palette, Ctrl+D shortcut) keep working unchanged.

Host contract: ``_last_solve_log`` (str, optional) and ``statusBar()``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox


from sjtu_tpmshx.ui.theme import _btn_styles, get_theme


class DialogsMixin:
    """Overview / test-info / solve-log modal dialogs."""

    def _show_overview(self):
        """Open the D7 session-overview dashboard dialog."""
        from sjtu_tpmshx.ui.session_overview import open_overview
        open_overview(self)

    def _show_solve_log(self):
        """Modal text viewer for the last captured solver stdout."""
        text = getattr(self, '_last_solve_log', None) or ""
        if not text.strip():
            QMessageBox.information(
                self, "Solve log",
                "No solve log captured yet — run Compute first.")
            return
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QPlainTextEdit, QPushButton, QHBoxLayout)
        dlg = QDialog(self)
        dlg.setWindowTitle("Solve log — SIMPLE / coupling output")
        dlg.resize(820, 640)
        from sjtu_tpmshx.ui.theme import get_theme as _gt_sl
        _tsl = _gt_sl()
        # Theme the dialog chrome too, not just the editor (else the surround
        # falls back to the parent palette and mismatches on the light theme).
        dlg.setStyleSheet(f"QDialog{{background:{_tsl['bg']};}}")
        v = QVBoxLayout(dlg)
        edit = QPlainTextEdit(text)
        edit.setReadOnly(True)
        edit.setStyleSheet(
            f"QPlainTextEdit{{background:{_tsl.get('surface_raised', _tsl['card_bg'])};"
            f"color:{_tsl['fg']}; border:1px solid {_tsl['card_border']};"
            f"font-family:{_tsl['mono_family']}; font-size:10pt;"
            "padding:8px;}")
        v.addWidget(edit, 1)
        btn_row = QHBoxLayout(); btn_row.addStretch(1)
        btn_copy = QPushButton("Copy all")
        btn_copy.clicked.connect(
            lambda: (QApplication.clipboard().setText(text),
                     self.statusBar().showMessage(
                         "Log copied to clipboard.", 3000)))
        btn_close = QPushButton("Close"); btn_close.clicked.connect(dlg.accept)
        _bs = _btn_styles()
        btn_copy.setStyleSheet(_bs['tertiary'])
        btn_close.setStyleSheet(_bs['secondary'])
        btn_row.addWidget(btn_copy); btn_row.addWidget(btn_close)
        v.addLayout(btn_row)
        dlg.exec()

    # About and onboarding remain owned by main.py; the help menu dispatches
    # to those methods through the window's MRO.

    _SHORTCUT_ROWS = (
        ("Command palette",        "Ctrl+K"),
        ("Overview dashboard",     "Ctrl+D"),
        ("Coordinate inspector",   "Ctrl+I"),
        ("Launch continuous-field optimize", "Ctrl+Enter"),
        ("Cycle tabs",             "Ctrl+↑ / Ctrl+↓"),
        ("Quick fluid (A / B)",    "Alt+1/2/3  ·  Alt+Shift+1/2/3"),
        ("Cycle density",          "[  /  ]"),
        ("Scrub recent runs",      "Alt+↑ / Alt+↓"),
        ("Compute",                "Ctrl+R"),
        ("Reset parameters",       "Ctrl+Shift+R"),
        ("Undo field edit",        "Ctrl+Z"),
        ("Redo field edit",        "Ctrl+Y"),
        ("页签 — 几何布局",         "Ctrl+1"),
        ("页签 — 结果",             "Ctrl+2"),
        ("页签 — 优化",             "Ctrl+3"),
        ("结果 2D|3D 切换",         "Ctrl+4"),
        ("专注当前画布",            "F"),
        ("收起/展开参数栏",          "Ctrl+\\"),
        ("Keyboard cheat sheet",   "Ctrl+?"),
    )

    def _show_shortcuts(self):
        """Popup dialog listing all keyboard shortcuts as a two-column table."""
        from PySide6.QtGui import QKeySequence

        mono = get_theme()['mono_family']
        edit_keys = {
            label: QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)
            for label, key in (
                ("Undo field edit", QKeySequence.StandardKey.Undo),
                ("Redo field edit", QKeySequence.StandardKey.Redo),
            )
        }
        rows_html = "".join(
            f"<tr><td style='padding:4px 16px 4px 0;'>{label}</td>"
            f'<td style="padding:4px 0; font-family:{mono};"><b>{edit_keys.get(label, key)}</b></td></tr>'
            for label, key in self._SHORTCUT_ROWS)
        html = (
            "<h3 style='margin:0 0 8px 0;'>Keyboard shortcuts</h3>"
            "<table style='border-collapse:collapse;'>"
            f"{rows_html}"
            "</table>")
        msg = QMessageBox(self)
        msg.setWindowTitle("Keyboard Shortcuts")
        msg.setIcon(QMessageBox.Icon.NoIcon)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _show_help_menu(self, anchor_btn=None):
        """Pop a menu at the Help button with About / Shortcuts / Quick tour."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        act_cmd = menu.addAction("&Command palette…\tCtrl+K")
        act_cmd.triggered.connect(self._open_command_palette)
        menu.addSeparator()
        act_about = menu.addAction("&About SJTU-TPMSHX…")
        act_about.triggered.connect(self._show_about)
        act_kb = menu.addAction("&Keyboard shortcuts…\tCtrl+?")
        act_kb.triggered.connect(self._show_shortcuts)
        menu.addSeparator()
        act_tour = menu.addAction("Quick &tour")
        act_tour.triggered.connect(self._show_quick_tour)
        if anchor_btn is not None:
            from PySide6.QtCore import QPoint
            pos = anchor_btn.mapToGlobal(QPoint(0, anchor_btn.height()))
            menu.exec(pos)
        else:
            menu.exec()

    def _open_command_palette(self):
        """Open the Ctrl+K command palette menu-driven (Help menu entry)."""
        pal = getattr(self, '_command_palette', None)
        if pal is None:
            from sjtu_tpmshx.ui.command_palette import CommandPalette
            pal = CommandPalette(self)
            self._command_palette = pal
        pal.open_palette()

    def _install_dialog_theme(self):
        """Apply a narrowly-scoped app-level stylesheet so transient
        QMessageBox / QInputDialog popups follow the active theme. The
        selectors only match those dialog classes, so the explicitly-styled
        main UI is unaffected. Rebuilt on the theme-switch restart (__init__).
        """
        from PySide6.QtWidgets import QApplication
        from sjtu_tpmshx.ui.theme import get_theme
        app = QApplication.instance()
        if app is None:
            return
        t = get_theme()
        app.setStyleSheet(
            f"QMessageBox{{background:{t['bg']};}}"
            f"QMessageBox QLabel{{color:{t['fg']}; background:transparent;}}"
            f"QInputDialog{{background:{t['bg']};}}"
            f"QInputDialog QLabel{{color:{t['fg']}; background:transparent;}}"
            f"QInputDialog QLineEdit{{background:{t['inp_bg']}; color:{t['inp_fg']};"
            f" border:1px solid {t['inp_border']}; border-radius:6px; padding:4px 8px;}}"
            f"QInputDialog QComboBox, QInputDialog QSpinBox{{background:{t['inp_bg']};"
            f" color:{t['inp_fg']}; border:1px solid {t['inp_border']};"
            f" border-radius:6px; padding:3px 6px;}}"
            f"QMessageBox QPushButton, QInputDialog QPushButton{{"
            f" background:transparent; color:{t['btn_sec_fg']};"
            f" border:1px solid {t['btn_sec_border']}; border-radius:6px;"
            f" padding:5px 16px; font-weight:600; min-width:72px;}}"
            f"QMessageBox QPushButton:hover, QInputDialog QPushButton:hover{{"
            f" background:{t['btn_sec_hover_bg']};}}"
        )

    def _show_status_log(self):
        """Pop up the last 50 status-bar messages in a read-only dialog."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QPlainTextEdit,
                                        QDialogButtonBox)
        from sjtu_tpmshx.ui.theme import get_theme
        dlg = QDialog(self)
        dlg.setWindowTitle("Status Log")
        dlg.resize(640, 380)
        # Theme the whole dialog (not just the text area) so the chrome around
        # the editor matches it in both palettes — otherwise the dialog
        # background falls back to the parent palette (white editor + dark
        # surround on the light theme).
        _t = get_theme()
        dlg.setStyleSheet(
            f"QDialog{{background:{_t['bg']};}}"
            f"QPlainTextEdit{{background:{_t['inp_bg']}; color:{_t['inp_fg']};"
            f" border:1px solid {_t['card_border']}; border-radius:6px;"
            f" font-family:{_t['mono_family']}; font-size:9pt;}}"
            f"QPushButton{{background:transparent; color:{_t['btn_sec_fg']};"
            f" border:1px solid {_t['btn_sec_border']}; border-radius:6px;"
            f" padding:5px 16px; font-weight:600;}}"
            f"QPushButton:hover{{background:{_t['btn_sec_hover_bg']};}}")
        lay = QVBoxLayout(dlg)
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        lines = list(getattr(self, '_log_history', []))
        txt.setPlainText("\n".join(lines) if lines
                         else "(no status messages yet)")
        lay.addWidget(txt)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        btns.button(QDialogButtonBox.StandardButton.Close).clicked.connect(
            dlg.accept)
        lay.addWidget(btns)
        dlg.exec()
