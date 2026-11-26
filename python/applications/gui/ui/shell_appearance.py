"""Shell appearance, theme, layout chrome, and settings popover owner."""
from __future__ import annotations

import os
import sys
from typing import Any, Callable, Mapping

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sjtu_tpmshx.applications.gui.controllers.user_storage import save_appearance_setting
from sjtu_tpmshx.applications.gui.ui.colormap_popover import ToggleSwitch
from sjtu_tpmshx.applications.gui.ui.microanim import (
    is_reduced_motion,
    reveal,
    set_reduced_motion as set_global_reduced_motion,
)
from sjtu_tpmshx.applications.gui.ui.nav_rail import EXPANDED_RAIL_WIDTH
from sjtu_tpmshx.applications.gui.ui.theme import (
    RADIUS_BTN,
    get_density,
    get_theme,
    get_theme_name,
    set_accent_override,
    set_density,
    set_theme,
)

_COMPACT_BREAKPOINT = 1360


class _PopoverHairline(QWidget):
    """Single-device-pixel horizontal rule inside the settings popover."""

    def __init__(self, color_hex: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color_hex)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(self._color, 0.5))
        painter.drawLine(QPointF(0.0, 0.25), QPointF(float(self.width()), 0.25))
        painter.end()


class _SettingsPopover(QFrame):
    """Style P2 floating settings popover opened from the rail settings action."""

    def __init__(
        self,
        appearance: ShellAppearance,
        tokens: Mapping[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._appearance = appearance
        self._tokens = dict(tokens)
        self.setObjectName("settingsPopover")
        self.setFixedWidth(308)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(1)
        self._build()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setBrush(QColor(self._tokens["popover"]))
        painter.setPen(QPen(QColor(self._tokens["border_strong"]), 0.5))
        painter.drawRoundedRect(rect, 11.0, 11.0)
        painter.end()

    def closeEvent(self, event) -> None:
        rail = getattr(self._appearance.window, "nav_rail", None)
        if rail is not None and not self._appearance.is_rail_expanded():
            rail.set_open_action(None)
        super().closeEvent(event)

    def _add_group(self, title: str) -> None:
        lab = QLabel(title)
        lab.setContentsMargins(10, 7, 10, 3)
        lab.setStyleSheet(
            f"color: {self._tokens['tert']}; font-size: 11px; font-weight: 600; "
            "background: transparent;"
        )
        self._layout.addWidget(lab)

    def _add_separator(self) -> None:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(wrap)
        vl.setContentsMargins(4, 4, 4, 4)
        vl.addWidget(_PopoverHairline(self._tokens["border"]))
        self._layout.addWidget(wrap)

    def _add_segment_row(
        self,
        label_text: str,
        options: list[tuple[str, str]],
        active_key: str,
        on_select: Callable[[str], None],
    ) -> None:
        t = self._tokens
        row = QFrame()
        row.setFixedHeight(34)
        row.setStyleSheet("background: transparent; border: none;")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(10, 0, 8, 0)
        hl.setSpacing(8)

        lbl = QLabel(label_text)
        lbl.setStyleSheet(
            f"color: {t['fg']}; font-size: 12px; font-weight: 400; background: transparent;"
        )
        hl.addWidget(lbl)
        hl.addStretch(1)

        seg = QFrame()
        seg.setStyleSheet(
            f"QFrame {{ background: {t['sunken']}; border: none; border-radius: {RADIUS_BTN}px; }}"
        )
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(2, 2, 2, 2)
        sl.setSpacing(2)
        for key, text in options:
            btn = QPushButton(text)
            btn.setFixedHeight(22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if key == active_key:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {t['seg_on']}; color: {t['fg']}; "
                    f"border: 1px solid {t['border']}; border-radius: 5px; "
                    "padding: 0 8px; font-size: 12px; font-weight: 600; }"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; color: {t['sub']}; "
                    "border: none; border-radius: 5px; padding: 0 8px; "
                    "font-size: 12px; font-weight: 400; }"
                    f"QPushButton:hover {{ color: {t['fg']}; }}"
                )
            btn.clicked.connect(lambda _=False, k=key: self._invoke(lambda: on_select(k)))
            sl.addWidget(btn)
        hl.addWidget(seg)
        self._layout.addWidget(row)

    def _add_toggle_row(
        self,
        label_text: str,
        checked: bool,
        on_toggle: Callable[[bool], None],
    ) -> None:
        t = self._tokens
        row = QFrame()
        row.setFixedHeight(34)
        row.setStyleSheet("background: transparent; border: none;")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(10, 0, 8, 0)
        hl.setSpacing(8)
        lbl = QLabel(label_text)
        lbl.setStyleSheet(
            f"color: {t['fg']}; font-size: 12px; font-weight: 400; background: transparent;"
        )
        hl.addWidget(lbl)
        hl.addStretch(1)
        sw = ToggleSwitch(checked=checked, tokens=t)
        sw.toggled.connect(on_toggle)
        hl.addWidget(sw)
        self._layout.addWidget(row)

    def _add_action_row(
        self,
        label_text: str,
        callback: Callable[[], None],
        shortcut: str = "",
    ) -> None:
        t = self._tokens
        btn = QPushButton()
        btn.setFixedHeight(31)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; "
            f"border-radius: {RADIUS_BTN}px; text-align: left; }}"
            f"QPushButton:hover {{ background: {t['row_hover']}; }}"
        )
        hl = QHBoxLayout(btn)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setSpacing(8)
        lbl = QLabel(label_text)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lbl.setStyleSheet(
            f"color: {t['fg']}; font-size: 12px; font-weight: 400; background: transparent;"
        )
        hl.addWidget(lbl)
        hl.addStretch(1)
        if shortcut:
            kbd = QLabel(shortcut)
            kbd.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            kbd.setStyleSheet(
                f"color: {t['tert']}; font-size: 11px; background: {t['sunken']}; "
                f"border: 1px solid {t['border']}; border-radius: 4px; padding: 1px 5px;"
            )
            hl.addWidget(kbd)
        btn.clicked.connect(lambda _=False: self._invoke(callback))
        self._layout.addWidget(btn)

    def _invoke(self, callback: Callable[[], None]) -> None:
        self.hide()
        callback()

    def _build(self) -> None:
        window = self._appearance.window
        self._add_group("外观")
        self._add_segment_row(
            "主题",
            [("light", "浅色"), ("dark", "深色")],
            get_theme_name(),
            self._appearance.toggle_theme,
        )
        self._add_segment_row(
            "温度单位",
            [("K", "K"), ("C", "°C")],
            getattr(window, "_temp_unit", "K"),
            self._set_temp_unit,
        )
        self._add_segment_row(
            "界面密度",
            [("compact", "紧凑"), ("cozy", "适中"), ("comfortable", "宽松")],
            get_density(),
            self._appearance.set_density,
        )
        self._add_toggle_row(
            "减少动态效果",
            is_reduced_motion(),
            self._appearance.set_reduced_motion,
        )

        self._add_separator()
        self._add_group("工具")
        if hasattr(window, "_toggle_coord_inspector"):
            self._add_action_row("坐标探针", window._toggle_coord_inspector, "Ctrl+I")
        self._add_action_row("会话总览…", window.dialogs.show_overview, "Ctrl+D")
        self._add_action_row("历史记录…", window.history.show_full_timeline)
        self._add_action_row("复制为 Python 脚本", window.history.copy_inputs_as_python)
        self._add_action_row("复制复现链接", window.history.copy_reproducible_link)
        self._add_action_row("加载复现链接…", window.history.load_reproducible_link)

        self._add_separator()
        self._add_group("帮助")
        self._add_action_row("快捷键列表…", window.dialogs.show_shortcuts, "Ctrl+?")
        self._add_action_row("快速上手", window.dialogs.show_quick_tour)
        self._add_action_row("关于 SJTU-TPMSHX…", window.dialogs.show_about)
        self.adjustSize()

    def _set_temp_unit(self, target: str) -> None:
        window = self._appearance.window
        if getattr(window, "_temp_unit", "K") != target:
            window._toggle_temp_unit()


class ShellAppearance:
    """Owner of theme, density, reduced motion, drawer, rail overlay, and focus state."""

    def __init__(self, window) -> None:
        self.window = window
        self._initial_reveal_scheduled = False
        self._focused = False
        self._drawer_open = True
        self._rail_expanded = False
        self._settings_popover: _SettingsPopover | None = None

    def is_focused(self) -> bool:
        """Return True when canvas focus mode hides surrounding chrome."""
        return self._focused

    def is_drawer_open(self) -> bool:
        """Return True when the right inspector drawer is open."""
        return self._drawer_open

    def is_rail_expanded(self) -> bool:
        """Return True when the 232 px navigation rail overlay is visible."""
        return self._rail_expanded

    def schedule_initial_reveal(self) -> None:
        """Warm up reveal transitions once on first window appearance."""
        if self._initial_reveal_scheduled:
            return
        self._initial_reveal_scheduled = True

        def _do_reveal() -> None:
            target = getattr(self.window, "inspector_drawer", None)
            if target is not None and target.isVisible():
                reveal(target)

        QTimer.singleShot(0, self.window, _do_reveal)

    def pick_accent_color(self) -> None:
        """Save the chosen accent in the user configuration directory."""
        cur = get_theme().get("accent", "#0E6275")
        col = QColorDialog.getColor(QColor(cur), self.window, "选择强调色")
        if not col.isValid():
            return
        if not save_appearance_setting("accent", col.name()):
            QMessageBox.warning(
                self.window, "设置未保存", "无法写入强调色设置，请检查用户配置目录。"
            )
            return
        set_accent_override(col.name())
        self.offer_restart(f"强调色已保存为 {col.name()}。")

    def set_density(self, name: str) -> None:
        """Persist density; padded styles take effect after restarting."""
        if name not in ("compact", "cozy", "comfortable"):
            return
        if not save_appearance_setting("density", name):
            QMessageBox.warning(
                self.window, "设置未保存", "无法写入界面密度设置，请检查用户配置目录。"
            )
            return
        set_density(name)
        label = {"compact": "紧凑", "cozy": "适中", "comfortable": "宽松"}[name]
        self.offer_restart(f"界面密度已保存为{label}。")

    def toggle_theme(self, target: str | None = None) -> None:
        """Save the selected palette before offering a safe process restart."""
        current = get_theme_name()
        new = target if target in ("light", "dark") else ("light" if current == "dark" else "dark")
        if new == current:
            return
        if not save_appearance_setting("theme", new):
            QMessageBox.warning(
                self.window, "设置未保存", "无法写入主题设置，请检查用户配置目录。"
            )
            return
        set_theme(new)
        self.offer_restart("主题已保存为浅色。" if new == "light" else "主题已保存为深色。")

    def set_reduced_motion(self, enabled: bool) -> bool:
        """Persist and apply reduced motion immediately across UI and 3D camera."""
        enabled = bool(enabled)
        if not set_global_reduced_motion(enabled, persist=True):
            QMessageBox.warning(
                self.window, "设置未保存", "无法写入减少动态效果设置，请检查用户配置目录。"
            )
            return False
        self.window.statusBar().showMessage(
            "已开启减少动态效果" if enabled else "已恢复动态效果", 3000
        )
        return True

    def toggle_reduced_motion(self) -> bool:
        """Toggle reduced motion and persist the new preference."""
        return self.set_reduced_motion(not is_reduced_motion())

    def offer_restart(self, text: str) -> None:
        """Offer an immediate safe restart after saving an appearance preference."""
        msg = QMessageBox(self.window)
        msg.setWindowTitle("外观设置已保存")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(text + "重启软件后完整生效。")
        restart_btn = msg.addButton("立即重启", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("稍后", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is restart_btn:
            self.restart()

    def restart(self) -> None:
        """Never replace a process with live work or unsaved input fields."""
        from sjtu_tpmshx.applications.gui.ui.background_tasks import has_active_tasks

        if has_active_tasks(self.window):
            QMessageBox.information(
                self.window,
                "任务仍在运行",
                "外观设置已保存。请等待当前任务结束后重启软件。",
            )
            return
        try:
            saved = bool(self.window.case_files.save_session())
        except Exception:
            saved = False
        if not saved:
            QMessageBox.warning(
                self.window,
                "会话未保存",
                "外观设置已保存，但当前输入保存失败。已取消重启，请先保存当前配置。",
            )
            return
        command = [sys.executable]
        if not getattr(sys, "frozen", False):
            command.extend(["-m", "sjtu_tpmshx.main"])
        command.extend(sys.argv[1:])
        try:
            os.execv(sys.executable, command)
        except OSError as exc:
            QMessageBox.warning(self.window, "重启失败", f"请手动重启软件：{exc}")

    def _page_uses_drawer(self) -> bool:
        window = self.window
        if getattr(window, "page_stack", None) is not None:
            if window.page_stack.currentWidget() is window.quick_design:
                return False
        return window.workbench.active_tab != "pareto"

    def sync_drawer_visibility(self) -> None:
        """Reconcile drawer visibility with focus state, page type, and open flag."""
        window = self.window
        drawer = getattr(window, "inspector_drawer", None)
        if drawer is None:
            return
        show_drawer = self._drawer_open and not self._focused and self._page_uses_drawer()
        drawer.set_open(show_drawer)
        btn = getattr(window, "btn_toggle_drawer", None)
        if btn is not None:
            btn.setVisible(self._page_uses_drawer() and not self._focused)
            btn.setToolTip("收起检查器  Ctrl+]" if show_drawer else "展开检查器  Ctrl+]")
            btn.setChecked(show_drawer)

    def set_drawer_open(self, opened: bool) -> None:
        """Open or close the push inspector drawer without rebuilding fields."""
        previous = self._drawer_open
        self._drawer_open = bool(opened)
        self.sync_drawer_visibility()
        refresh_nav = getattr(self.window, "_refresh_workbench_navigation", None)
        if refresh_nav is not None:
            refresh_nav()
        if not previous and self._drawer_open and not self._focused and self._page_uses_drawer():
            drawer = getattr(self.window, "inspector_drawer", None)
            if drawer is not None:
                reveal(drawer)

    def toggle_drawer(self) -> None:
        """Toggle the right inspector drawer, exiting focus mode first if active."""
        if self._focused:
            self.toggle_focus()
            if not self._drawer_open:
                self.set_drawer_open(True)
            return
        self.set_drawer_open(not self._drawer_open)

    def set_rail_expanded(self, expanded: bool) -> None:
        """Show or hide the 232 px expanded navigation rail overlay."""
        expanded = bool(expanded)
        self._rail_expanded = expanded
        scrim = getattr(self.window, "_rail_scrim", None)
        overlay = getattr(self.window, "expanded_nav_rail", None)
        rail = getattr(self.window, "nav_rail", None)
        if rail is not None:
            rail.set_open_action("expand" if expanded else None)
        if scrim is None or overlay is None:
            return
        if expanded:
            self._sync_overlay_geometry()
            refresh_nav = getattr(self.window, "_refresh_workbench_navigation", None)
            if refresh_nav is not None:
                refresh_nav()
            scrim.show()
            scrim.raise_()
            overlay.show()
            overlay.raise_()
            reveal(overlay)
        else:
            overlay.hide()
            scrim.hide()

    def toggle_rail(self) -> None:
        """Toggle the 232 px expanded navigation rail overlay."""
        self.set_rail_expanded(not self._rail_expanded)

    def toggle_focus(self) -> None:
        """Give the current canvas maximum room without changing saved preferences."""
        from sjtu_tpmshx.applications.gui.ui.builders_sidebar import update_result_sidebar_visibility

        window = self.window
        focused = not self._focused
        if focused and self._rail_expanded:
            self.set_rail_expanded(False)
        self._focused = focused
        self.sync_drawer_visibility()
        btn_focus = getattr(window, "btn_focus_view", None)
        if btn_focus is not None:
            btn_focus.setChecked(focused)
            btn_focus.setText("退出专注" if focused else "专注")
        card = getattr(window, "_run_status_card", None)
        if card is not None:
            card.setVisible((not focused and self._page_uses_drawer()) or not window.single_run.is_idle())
        update_result_sidebar_visibility(window)
        window.statusBar().showMessage(
            "专注当前画布 · 按 F 退出" if focused else "已恢复工作台布局", 3000
        )

    def sync_viewport_layout(self) -> None:
        """Adjust compact drawer width, readout strip density, and rail overlay geometry."""
        window = self.window
        compact = window.width() < _COMPACT_BREAKPOINT
        drawer = getattr(window, "inspector_drawer", None)
        if drawer is not None:
            drawer.set_compact(compact)
        strip = getattr(window, "readout_strip", None)
        if strip is not None:
            strip.set_compact(compact)
        self._sync_overlay_geometry()

    def _sync_overlay_geometry(self) -> None:
        central = self.window.centralWidget()
        if central is None:
            return
        rect = central.rect()
        scrim = getattr(self.window, "_rail_scrim", None)
        if scrim is not None:
            scrim.setGeometry(rect)
        overlay = getattr(self.window, "expanded_nav_rail", None)
        if overlay is not None:
            overlay.setGeometry(0, 0, EXPANDED_RAIL_WIDTH, rect.height())

    def show_settings_popover(self, anchor: QWidget | None = None) -> None:
        """Open the Style P2 settings popover beside the rail settings button."""
        if self._rail_expanded:
            self.set_rail_expanded(False)
        rail = getattr(self.window, "nav_rail", None)
        if anchor is None and rail is not None:
            anchor = rail.action_anchor("more")
        if rail is not None:
            rail.set_open_action("more")
        pop = _SettingsPopover(self, get_theme(), parent=self.window)
        self._settings_popover = pop
        if anchor is not None:
            pos = anchor.mapToGlobal(QPoint(anchor.width() + 8, anchor.height() - pop.height()))
            win_pos = self.window.mapToGlobal(QPoint(0, 8))
            pos.setY(max(win_pos.y(), pos.y()))
            pop.move(pos)
        pop.show()
