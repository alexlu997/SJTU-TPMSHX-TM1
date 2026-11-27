"""Shell appearance, theme, layout chrome, and settings popover owner."""
from __future__ import annotations

import json
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

from sjtu_tpmshx.applications.gui.controllers.user_storage import (
    load_appearance_settings,
    save_appearance_setting,
)
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
        *,
        enabled: bool = True,
    ) -> None:
        t = self._tokens
        btn = QPushButton()
        btn.setFixedHeight(31)
        btn.setEnabled(enabled)
        btn.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )
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
            f"color: {t['fg'] if enabled else t['tert']}; "
            "font-size: 12px; font-weight: 400; background: transparent;"
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
        self.close()
        callback()

    def rebuild(self, tokens: Mapping[str, Any]) -> None:
        """Refresh the settings popover in place without leaking duplicate popups."""
        self._tokens = dict(tokens)
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._build()

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

        has_log = bool((window.single_run.compute.last_log() or "").strip())
        has_result = window.cache.has_any_results()

        self._add_separator()
        self._add_group("工具")
        self._add_action_row("计算日志…", window.dialogs.show_solve_log, enabled=has_log)
        self._add_action_row("诊断详情…", window.results.show_diag_dialog, enabled=has_result)
        if hasattr(window, "_toggle_coord_inspector"):
            self._add_action_row("坐标探针", window._toggle_coord_inspector, "Ctrl+I")
        self._add_action_row("会话总览…", window.dialogs.show_overview, "Ctrl+D")
        self._add_action_row("历史记录…", window.history.show_full_timeline)
        self._add_action_row("复制为 Python 脚本", window.history.copy_inputs_as_python)
        self._add_action_row("复制复现链接", window.history.copy_reproducible_link)
        self._add_action_row("重置为默认参数", window._reset_defaults, "Ctrl+Shift+R")

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
        self._rail_expanded = False
        self._settings_popover: _SettingsPopover | None = None
        self._active_drawer_page: str | None = None
        self._syncing_drawer = False
        self._page_drawer: dict[str, dict[str, Any]] = {
            "run": {"open": True, "tab": 0},
            "result": {"open": True, "tab": 0},
            "opt": {"open": True, "tab": 0},
            "qd": {"open": False, "tab": 0},
        }
        raw = load_appearance_settings().get("inspector")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    for key in ("run", "result", "opt", "qd"):
                        entry = parsed.get(key)
                        if isinstance(entry, dict):
                            if isinstance(entry.get("open"), bool):
                                self._page_drawer[key]["open"] = entry["open"]
                            tab = entry.get("tab")
                            if isinstance(tab, int) and not isinstance(tab, bool) and tab >= 0:
                                limit = 2 if key == "run" else 1
                                self._page_drawer[key]["tab"] = min(tab, limit)
            except (TypeError, ValueError):
                pass

    def is_focused(self) -> bool:
        """Return True when canvas focus mode hides surrounding chrome."""
        return self._focused

    def _current_drawer_page(self) -> str | None:
        window = self.window
        if getattr(window, "page_stack", None) is not None:
            if window.page_stack.currentWidget() is window.quick_design:
                return "qd"
        tab = window.workbench.active_tab
        if tab == "pareto":
            return "opt"
        if tab in ("temp", "pres", "vel", "3d"):
            return "result"
        return "run"

    def is_drawer_open(self, page_key: str | None = None) -> bool:
        """Return True when the right inspector drawer is open for ``page_key``."""
        page = page_key or self._current_drawer_page() or "run"
        return bool(self._page_drawer.get(page, {}).get("open", True))

    def drawer_tab_for(self, page_key: str) -> int:
        """Return the remembered drawer strip tab index for ``page_key``."""
        return int(self._page_drawer.get(page_key, {}).get("tab", 0))

    def _save_inspector_prefs(self) -> None:
        save_appearance_setting("inspector", json.dumps(self._page_drawer, sort_keys=True))

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
        self.window.dialogs.notify(
            "已开启减少动态效果" if enabled else "已恢复动态效果",
            kind="info",
            duration_ms=3000,
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
        return self._current_drawer_page() is not None

    def record_drawer_tab(self, strip_index: int) -> None:
        """Remember the user-selected drawer tab for the active page."""
        if self._syncing_drawer:
            return
        page = self._current_drawer_page()
        if page is None:
            return
        limit = 2 if page == "run" else 1
        clamped = max(0, min(int(strip_index), limit))
        self._page_drawer[page]["tab"] = clamped
        if page == "run":
            self.window._param_page = clamped
        self._sync_result_param_subbar(page, clamped)
        self._save_inspector_prefs()

    def _sync_result_param_subbar(self, page: str | None, strip_index: int) -> None:
        subbar = getattr(self.window, "_result_param_subbar", None)
        if subbar is not None:
            show_sub = page == "result" and strip_index == 1
            subbar.setVisible(show_sub)
            if show_sub:
                sync_btns = getattr(self.window, "_sync_result_param_btns", None)
                if sync_btns is not None:
                    sync_btns()

    def sync_drawer_visibility(self) -> None:
        """Reconcile drawer tabs, visibility, and header toggle with active page preferences."""
        window = self.window
        drawer = getattr(window, "inspector_drawer", None)
        if drawer is None:
            return
        page = self._current_drawer_page()
        if page is None:
            drawer.set_open(False)
            self._sync_result_param_subbar(None, 0)
            btn = getattr(window, "btn_toggle_drawer", None)
            if btn is not None:
                btn.setVisible(False)
                btn.setChecked(False)
            return

        state = self._page_drawer[page]
        saved_tab = int(state["tab"])
        if page != self._active_drawer_page:
            self._syncing_drawer = True
            try:
                if page == "run":
                    entries = [("几何", 0), ("边界", 1), ("求解", 2)]
                    saved_tab = max(0, min(saved_tab, 2))
                    window._param_page = saved_tab
                elif page == "result":
                    param_idx = max(0, min(int(getattr(window, "_param_page", 0)), 2))
                    entries = [("结果", 3), ("参数", param_idx)]
                    saved_tab = max(0, min(saved_tab, 1))
                elif page == "opt":
                    entries = [("搜索配置", 4), ("所选方案", 5)]
                    saved_tab = max(0, min(saved_tab, 1))
                else:
                    entries = [("输入", 6), ("所选设计", 7)]
                    saved_tab = max(0, min(saved_tab, 1))
                drawer.set_strip_entries(entries, active_strip_index=saved_tab)
                self._active_drawer_page = page
            finally:
                self._syncing_drawer = False
        self._sync_result_param_subbar(page, drawer.strip_index())

        show_drawer = bool(state["open"]) and not self._focused
        drawer.set_open(show_drawer)
        btn = getattr(window, "btn_toggle_drawer", None)
        if btn is not None:
            btn.setVisible(not self._focused)
            btn.setToolTip("收起检查器  Ctrl+]" if show_drawer else "展开检查器  Ctrl+]")
            btn.setChecked(show_drawer)
        if page == "qd" and hasattr(window, "quick_design"):
            window.quick_design.on_drawer_visibility_changed(show_drawer)

    def select_drawer_tab(
        self,
        page_key: str,
        strip_index: int,
        *,
        open_drawer: bool | None = None,
    ) -> None:
        """Select a drawer tab for ``page_key`` and optionally open or close it."""
        if page_key not in self._page_drawer:
            return
        limit = 2 if page_key == "run" else 1
        clamped = max(0, min(int(strip_index), limit))
        self._page_drawer[page_key]["tab"] = clamped
        if open_drawer is not None:
            self._page_drawer[page_key]["open"] = bool(open_drawer)
        self._save_inspector_prefs()
        if self._current_drawer_page() == page_key:
            self._active_drawer_page = None
            self.sync_drawer_visibility()

    def set_drawer_open(self, opened: bool, page_key: str | None = None) -> None:
        """Open or close the push inspector drawer for the active or named page."""
        page = page_key or self._current_drawer_page() or "run"
        previous = bool(self._page_drawer[page]["open"])
        self._page_drawer[page]["open"] = bool(opened)
        self._save_inspector_prefs()
        self.sync_drawer_visibility()
        refresh_nav = getattr(self.window, "_refresh_workbench_navigation", None)
        if refresh_nav is not None:
            refresh_nav()
        if (
            not previous
            and self._page_drawer[page]["open"]
            and not self._focused
            and self._current_drawer_page() == page
        ):
            drawer = getattr(self.window, "inspector_drawer", None)
            if drawer is not None:
                reveal(drawer)

    def toggle_drawer(self) -> None:
        """Toggle the right inspector drawer for the active page, exiting focus first."""
        if self._focused:
            self.toggle_focus()
            if not self.is_drawer_open():
                self.set_drawer_open(True)
            return
        self.set_drawer_open(not self.is_drawer_open())

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
            show_card = not window.single_run.is_idle() or (
                card.state in ("running", "cancelling", "error", "cancelled", "paused")
                and not focused
                and self._current_drawer_page() in ("run", "result")
            )
            card.setVisible(show_card)
        update_result_sidebar_visibility(window)
        window.dialogs.notify(
            "专注当前画布 · 按 F 退出" if focused else "已恢复工作台布局",
            kind="info",
            duration_ms=3000,
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
        opt = getattr(window, "optimization", None)
        if opt is not None and hasattr(opt, "set_compact"):
            opt.set_compact(compact)
        qd = getattr(window, "quick_design", None)
        if qd is not None and hasattr(qd, "set_compact"):
            qd.set_compact(compact)
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
        pop = self._settings_popover
        if pop is None:
            pop = _SettingsPopover(self, get_theme(), parent=self.window)
            self._settings_popover = pop
        else:
            pop.rebuild(get_theme())
        if anchor is not None:
            pos = anchor.mapToGlobal(QPoint(anchor.width() + 8, anchor.height() - pop.height()))
            win_pos = self.window.mapToGlobal(QPoint(0, 8))
            pos.setY(max(win_pos.y(), pos.y()))
            pop.move(pos)
        pop.show()
