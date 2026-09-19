"""AppearanceMixin — theme / density / accent / panel-layout toggles.

Extracted verbatim from main.py (openspec arch-b-c-e batch E, 2026-07-02).
Mixed into Main_Menu; methods keep their exact names and behaviour.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from sjtu_tpmshx.ui.theme import (get_theme, get_theme_name, set_theme, set_density,
                      set_accent_override)


class AppearanceMixin:
    def _pick_accent_color(self):
        """E13 — let user choose a custom accent_primary override.
        Stored to `.accent` next to main.py; read at startup."""
        from PySide6.QtWidgets import QColorDialog
        cur = get_theme().get('accent_primary', '#3B82F6')
        from PySide6.QtGui import QColor
        col = QColorDialog.getColor(QColor(cur), self, "Pick accent colour")
        if not col.isValid():
            return
        hex_ = col.name()
        set_accent_override(hex_)
        import os as _os_ac
        try:
            with open(_os_ac.path.join(
                    _os_ac.path.dirname(_os_ac.path.abspath(__file__)),
                    '.accent'), 'w', encoding='utf-8') as f:
                f.write(hex_)
        except Exception:
            pass
        msg = QMessageBox(self)
        msg.setWindowTitle("Accent changed")
        msg.setText(
            f"Accent set to {hex_}. "
            "Restart the app to apply everywhere.")
        restart = msg.addButton("Restart now",
                                 QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is restart:
            # 2026-05-20 UI sweep (Tier 20): mirror the theme-restart
            # save-guard so a session-write failure aborts execv
            # instead of losing the user's pending edits.
            _saved = False
            try:
                _saved = bool(self._save_session())
            except Exception:
                _saved = False
            if not _saved:
                QMessageBox.warning(
                    self, "Accent change — session not saved",
                    "The .accent file was written but persisting your "
                    "current inputs to the session failed. Restart was "
                    "cancelled to avoid losing pending edits. Save / "
                    "copy any values you need, then relaunch manually.")
                return
            import sys as _sys
            _os_ac.execv(_sys.executable, [_sys.executable] + _sys.argv)

    def _set_density(self, name):
        """Switch display density (compact / cozy / comfortable). Same
        restart pattern as `_toggle_theme` because padded QSS is captured
        at widget build time."""
        if name not in ('compact', 'cozy', 'comfortable'):
            return
        try:
            set_density(name)
        except Exception as e:
            QMessageBox.warning(self, "Density switch failed", str(e))
            return
        import os as _os_d
        try:
            with open(_os_d.path.join(
                    _os_d.path.dirname(_os_d.path.abspath(__file__)),
                    '.density'), 'w', encoding='utf-8') as f:
                f.write(name)
        except Exception:
            pass
        msg = QMessageBox(self)
        msg.setWindowTitle("Density changed")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(
            f"Display density set to {name}. "
            "Restart the app to apply everywhere.")
        restart = msg.addButton("Restart now",
                                 QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is restart:
            # 2026-05-20 UI sweep (Tier 20): same save-guard as
            # _toggle_theme / _pick_accent_color. Density change is
            # cosmetic; losing the user's inputs to it is not.
            _saved = False
            try:
                _saved = bool(self._save_session())
            except Exception:
                _saved = False
            if not _saved:
                QMessageBox.warning(
                    self, "Density change — session not saved",
                    "The .density file was written but persisting your "
                    "current inputs to the session failed. Restart was "
                    "cancelled to avoid losing pending edits. Save / "
                    "copy any values you need, then relaunch manually.")
                return
            import sys as _sys
            try:
                _os_d.execv(_sys.executable, [_sys.executable] + _sys.argv)
            except Exception as e:
                QMessageBox.warning(
                    self, "Restart failed",
                    f"Automatic restart failed ({e}).")

    def _toggle_theme(self):
        """Swap the active theme. Offers a "Restart now" path that saves the
        current session, writes the new theme to `.theme`, and relaunches
        the process in-place so every widget picks up the new palette.

        A live in-place rebuild is intentionally not attempted: QMatplotlib
        canvases, PyVistaQt's OpenGL context, the status-log message-hook,
        and the undo stack all hold token values captured at build time,
        and re-seating them cleanly is a larger engineering undertaking
        than re-exec'ing the process.
        """
        current = get_theme_name()
        new = 'light' if current == 'dark' else 'dark'
        try:
            set_theme(new)
        except Exception as e:
            QMessageBox.warning(self, "Theme switch failed", str(e))
            return
        import os as _os_t
        try:
            cfg_dir = _os_t.path.dirname(_os_t.path.abspath(__file__))
            with open(_os_t.path.join(cfg_dir, '.theme'), 'w',
                      encoding='utf-8') as f:
                f.write(new)
        except Exception:
            pass

        msg = QMessageBox(self)
        msg.setWindowTitle("Theme changed")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(
            f"Theme switched to {new}. "
            "Restart the app to apply the new palette everywhere.")
        restart = msg.addButton("Restart now",
                                 QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is restart:
            # 2026-05-20 UI sweep (Tier 18): the prior code called
            # `_save_session()` and then unconditionally invoked
            # `os.execv`, which replaces the current process image. If
            # the save IO failed (permission, disk full, locked file)
            # the user's pending edits were lost the instant execv
            # fired. Abort the restart on save failure and tell the
            # user explicitly so they can save manually first.
            _saved = False
            try:
                _saved = bool(self._save_session())
            except Exception:
                _saved = False
            if not _saved:
                QMessageBox.warning(
                    self, "Theme switch — session not saved",
                    "The theme change is queued (the .theme file is "
                    "written) but persisting your current inputs to "
                    "the session file failed. Restart was cancelled to "
                    "avoid losing pending edits. Please relaunch the "
                    "app manually once you have saved or copied any "
                    "values you need.")
                return
            import sys as _sys
            # os.execv replaces the current process image, so the new app
            # starts with a clean QApplication and the .theme file we just
            # wrote. Works on Windows via the CRT shim.
            try:
                _os_t.execv(_sys.executable, [_sys.executable] + _sys.argv)
            except Exception as e:
                QMessageBox.warning(
                    self, "Restart failed",
                    f"Automatic restart failed ({e}). Please relaunch "
                    "the app manually.")

    def _toggle_3d_immersive(self):
        """Full-bleed 3D: collapse left panel + expand 3D card to a tall
        immersive height. Pressing F again restores both. Scoped by
        `_active_tab == '3d'` so the shortcut is a no-op elsewhere.
        """
        if getattr(self, '_active_tab', None) != '3d':
            return
        card = self._canvas_cards.get('3d')
        if card is None:
            return
        default_h = self._canvas_default_h.get('3d', 1100)
        immersive_h = 1800
        if not getattr(self, '_3d_immersive', False):
            # Remember so we can restore left panel only if it was visible.
            self._3d_prev_left_collapsed = getattr(self, '_left_collapsed', False)
            if not self._3d_prev_left_collapsed:
                self._toggle_left_panel()
            card.setFixedHeight(immersive_h)
            self._3d_immersive = True
            self.statusBar().showMessage(
                "3D immersive mode — press F to exit.", 4000)
        else:
            card.setFixedHeight(default_h)
            if not getattr(self, '_3d_prev_left_collapsed', True):
                self._toggle_left_panel()
            self._3d_immersive = False
            self.statusBar().showMessage(
                "3D immersive mode off.", 3000)

    def _toggle_left_panel(self):
        """Collapse the parameter inspector; retain the existing shortcut name."""
        if not hasattr(self, '_param_panel'):
            return
        panel = self._param_panel
        collapsed = getattr(self, '_left_collapsed', False)
        if not collapsed:
            panel.hide()
            self._left_collapsed = True
            if hasattr(self, 'btn_toggle_left'):
                self.btn_toggle_left.setText("‹")
                self.btn_toggle_left.setToolTip("展开右侧参数")
        else:
            panel.show()
            self._left_collapsed = False
            if hasattr(self, 'btn_toggle_left'):
                self.btn_toggle_left.setText("›")
                self.btn_toggle_left.setToolTip("收起右侧参数")
