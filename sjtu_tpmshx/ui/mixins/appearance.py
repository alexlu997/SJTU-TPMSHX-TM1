"""AppearanceMixin — theme / density / accent / panel-layout toggles.

Extracted verbatim from main.py (openspec arch-b-c-e batch E, 2026-07-02).
Mixed into Main_Menu; methods keep their exact names and behaviour.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from sjtu_tpmshx.controllers.user_storage import save_appearance_setting

from sjtu_tpmshx.ui.theme import (get_theme, get_theme_name, set_theme, set_density,
                      set_accent_override)


class AppearanceMixin:
    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, '_initial_reveal_scheduled', False):
            self._initial_reveal_scheduled = True
            from PySide6.QtCore import QTimer
            from sjtu_tpmshx.ui.microanim import reveal
            # Pay native animation/effect initialization on first appearance,
            # instead of adding its cold cost to the first parameter click.
            QTimer.singleShot(0, self, lambda: reveal(
                self._param_rail if getattr(self, '_left_collapsed', False)
                else self._param_scroll.viewport()))

    def _pick_accent_color(self):
        """Save the chosen accent in the platform user configuration directory."""
        from PySide6.QtWidgets import QColorDialog
        from PySide6.QtGui import QColor
        cur = get_theme().get('accent_primary', '#3B82F6')
        col = QColorDialog.getColor(QColor(cur), self, "Pick accent colour")
        if not col.isValid():
            return
        if not save_appearance_setting('accent', col.name()):
            QMessageBox.warning(self, "设置未保存", "无法写入强调色设置，请检查用户配置目录。")
            return
        set_accent_override(col.name())
        self._offer_appearance_restart(f"强调色已保存为 {col.name()}。")

    def _set_density(self, name):
        """Persist density; padded styles take effect after restarting."""
        if name not in ('compact', 'cozy', 'comfortable'):
            return
        if not save_appearance_setting('density', name):
            QMessageBox.warning(self, "设置未保存", "无法写入界面密度设置，请检查用户配置目录。")
            return
        set_density(name)
        self._offer_appearance_restart(f"界面密度已保存为 {name}。")

    def _toggle_theme(self):
        """Save the new palette before offering a safe process restart."""
        new = 'light' if get_theme_name() == 'dark' else 'dark'
        if not save_appearance_setting('theme', new):
            QMessageBox.warning(self, "设置未保存", "无法写入主题设置，请检查用户配置目录。")
            return
        set_theme(new)
        self._offer_appearance_restart("主题已保存为浅色。" if new == 'light' else "主题已保存为深色。")

    def _offer_appearance_restart(self, text):
        msg = QMessageBox(self)
        msg.setWindowTitle("外观设置已保存")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(text + "重启软件后完整生效。")
        restart = msg.addButton("立即重启", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("稍后", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is restart:
            self._restart_for_appearance()

    def _restart_for_appearance(self):
        """Never replace a process with live work or unsaved input fields."""
        from sjtu_tpmshx.ui.background_tasks import has_active_tasks
        if has_active_tasks(self):
            QMessageBox.information(
                self, "任务仍在运行", "外观设置已保存。请等待计算、优化或快速设计结束后重启软件。")
            return
        try:
            saved = bool(self._save_session())
        except Exception:
            saved = False
        if not saved:
            QMessageBox.warning(
                self, "会话未保存", "外观设置已保存，但当前输入保存失败。已取消重启，请先保存当前配置。")
            return
        import os
        import sys
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command.extend(['-m', 'sjtu_tpmshx.main'])
        command.extend(sys.argv[1:])
        try:
            os.execv(sys.executable, command)
        except OSError as exc:
            QMessageBox.warning(self, "重启失败", f"请手动重启软件：{exc}")

    def _toggle_3d_immersive(self):
        """Give the current canvas more room without changing saved preferences."""
        from sjtu_tpmshx.ui.builders_sidebar import update_result_sidebar_visibility

        focused = not getattr(self, '_3d_immersive', False)
        if focused and not getattr(self, '_left_collapsed', False):
            self._param_width = self._parameter_host.width()
        self._3d_immersive = focused
        self._parameter_host.setVisible(not focused)
        if not focused:
            self._set_parameter_panel_collapsed(getattr(self, '_left_collapsed', False))
        self.btn_focus_view.setChecked(focused)
        self.btn_focus_view.setText('退出专注' if focused else '专注')
        # A running solve keeps its progress and cancel action visible.
        self._run_status_card.setVisible(
            not focused or getattr(self, '_compute_running', False))
        update_result_sidebar_visibility(self)
        self.statusBar().showMessage(
            '专注当前画布 · 按 F 退出' if focused else '已恢复工作台布局', 3000)

    def _set_parameter_panel_collapsed(self, collapsed):
        """Resize the existing parameter host; never rebuild or reparent fields."""
        host = self._parameter_host
        previous = getattr(self, '_left_collapsed', False)
        if collapsed and not getattr(self, '_left_collapsed', False):
            self._param_width = max(320, min(520, host.width()))
        self._left_collapsed = bool(collapsed)
        self._param_panel.setVisible(not collapsed)
        self._param_rail.setVisible(collapsed)
        if collapsed:
            host.setFixedWidth(56)
            width = 56
        else:
            host.setMinimumWidth(320)
            host.setMaximumWidth(520)
            width = max(320, min(520, self._param_width))
        total = self._splitter.width() - self._splitter.handleWidth()
        self._splitter.setSizes([width, max(0, total - width)])
        self._refresh_workbench_navigation()
        self.btn_toggle_left.setToolTip('展开参数栏' if collapsed else '收起参数栏')
        if previous != collapsed and not collapsed:
            from sjtu_tpmshx.ui.microanim import reveal
            # Keep the canvas at its final size throughout the transition.
            reveal(self._param_scroll.viewport())

    def _toggle_left_panel(self):
        """Toggle the parameter rail, preserving width, page and scroll position."""
        if getattr(self, '_3d_immersive', False):
            self._toggle_3d_immersive()
        self._set_parameter_panel_collapsed(not getattr(self, '_left_collapsed', False))
