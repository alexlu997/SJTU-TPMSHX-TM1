"""Window dialogs, onboarding, output folder access, and command palette owner."""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from sjtu_tpmshx._version import __version__
from sjtu_tpmshx.applications.gui.ui.theme import _btn_styles, get_theme
from sjtu_tpmshx.run_control.provenance import SOURCE_ROOT, repository_revision


class ShellDialogs:
    """Owner of modal info dialogs, onboarding, command palette, and folder opening."""

    SHORTCUT_ROWS: tuple[tuple[str, str], ...] = (
        ("命令面板", "Ctrl+K"),
        ("会话总览", "Ctrl+D"),
        ("坐标探针", "Ctrl+I"),
        ("算例计算", "Ctrl+1"),
        ("计算结果", "Ctrl+2"),
        ("优化设计", "Ctrl+3"),
        ("结果 2D·3D 切换", "Ctrl+4"),
        ("快速设计", "Ctrl+5"),
        ("收起 / 展开导航栏", "Ctrl+\\"),
        ("收起 / 展开检查器", "Ctrl+]"),
        ("专注当前画布", "F"),
        ("开始计算", "Ctrl+R"),
        ("重置参数", "Ctrl+Shift+R"),
        ("开始优化", "Ctrl+Enter"),
        ("切换页面", "Ctrl+↑ / Ctrl+↓"),
        ("切换流体 (A / B)", "Alt+1/2/3  ·  Alt+Shift+1/2/3"),
        ("切换界面密度", "[  /  ]"),
        ("浏览最近运行", "Alt+↑ / Alt+↓"),
        ("撤销输入编辑", "Ctrl+Z"),
        ("重做输入编辑", "Ctrl+Y"),
        ("快捷键列表", "Ctrl+?"),
    )

    def __init__(self, window) -> None:
        self.window = window

    def show_overview(self) -> None:
        """Open the session-overview dashboard dialog."""
        from sjtu_tpmshx.applications.gui.ui.session_overview import open_overview

        open_overview(self.window)

    def show_solve_log(self) -> None:
        """Show a read-only viewer for the last captured solver stdout."""
        text = self.window.single_run.compute.last_log() or ""
        if not text.strip():
            QMessageBox.information(
                self.window,
                "计算日志",
                "尚未捕获求解日志，请先运行计算。",
            )
            return
        dlg = QDialog(self.window)
        dlg.setWindowTitle("计算日志 — SIMPLE / 耦合求解输出")
        dlg.resize(820, 640)
        t = get_theme()
        dlg.setStyleSheet(f"QDialog{{background:{t['window']};}}")
        v = QVBoxLayout(dlg)
        edit = QPlainTextEdit(text)
        edit.setReadOnly(True)
        edit.setStyleSheet(
            f"QPlainTextEdit{{background:{t['panel']};"
            f"color:{t['fg']}; border:1px solid {t['border']};"
            f"font-family:{t['mono_family']}; font-size:10pt; padding:8px;}}"
        )
        v.addWidget(edit, 1)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_copy = QPushButton("全部复制")
        btn_copy.clicked.connect(
            lambda: (
                QApplication.clipboard().setText(text),
                self.window.statusBar().showMessage("已复制计算日志到剪贴板。", 3000),
            )
        )
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        styles = _btn_styles()
        btn_copy.setStyleSheet(styles["tertiary"])
        btn_close.setStyleSheet(styles["secondary"])
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_close)
        v.addLayout(btn_row)
        dlg.exec()

    def resolve_output_directory(self, *, scope: str = "auto") -> Path | None:
        """Return the task-scoped run or optimization directory if it exists on disk."""
        window = self.window
        if scope == "auto":
            in_qd = (
                getattr(window, "page_stack", None) is not None
                and window.page_stack.currentWidget() is window.quick_design
            )
            scope = "optimization" if (not in_qd and window.workbench.active_tab == "pareto") else "single"

        candidates: list[object] = []
        if scope == "optimization":
            opt = getattr(window, "optimization", None)
            if opt is not None:
                job = getattr(opt, "_job", None)
                if job is not None:
                    candidates.append(getattr(job, "output_dir", None))
                candidates.append(getattr(opt, "last_output_dir", None))
        elif scope == "single":
            if not window.single_run.is_idle():
                candidates.append(getattr(window.single_run, "active_directory", None))
            result = window.cache.get_result()
            if result is not None:
                recovery = result.metadata.get("recovery")
                if isinstance(recovery, dict):
                    candidates.append(recovery.get("directory"))
        else:
            raise ValueError(f"Unknown output directory scope: {scope!r}")

        for raw in candidates:
            if not raw:
                continue
            path = Path(raw)
            if path.exists():
                return path if path.is_dir() else path.parent
        return None

    def open_output_folder(self, path: str | Path | None = None, *, scope: str = "auto") -> bool:
        """Open the task-scoped output folder in the system file manager."""
        folder = Path(path) if path is not None else self.resolve_output_directory(scope=scope)
        if folder is None or not folder.exists():
            QMessageBox.information(
                self.window,
                "运行目录",
                "当前还没有可用的运行输出目录。",
            )
            return False
        if folder.is_file():
            folder = folder.parent
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))
        if not ok:
            QMessageBox.warning(
                self.window,
                "无法打开目录",
                f"无法打开运行目录：{folder}",
            )
        return ok

    def show_shortcuts(self) -> None:
        """Show all keyboard shortcuts in a two-column dialog."""
        mono = get_theme()["mono_family"]
        edit_keys = {
            label: QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)
            for label, key in (
                ("撤销输入编辑", QKeySequence.StandardKey.Undo),
                ("重做输入编辑", QKeySequence.StandardKey.Redo),
            )
        }
        rows_html = "".join(
            f"<tr><td style='padding:4px 16px 4px 0;'>{label}</td>"
            f'<td style="padding:4px 0; font-family:{mono};">'
            f"<b>{edit_keys.get(label, key)}</b></td></tr>"
            for label, key in self.SHORTCUT_ROWS
        )
        html = (
            "<h3 style='margin:0 0 8px 0;'>快捷键列表</h3>"
            "<table style='border-collapse:collapse;'>"
            f"{rows_html}"
            "</table>"
        )
        msg = QMessageBox(self.window)
        msg.setWindowTitle("快捷键列表")
        msg.setIcon(QMessageBox.Icon.NoIcon)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def show_about(self) -> None:
        """Show version, commit, and runtime dependency information."""
        lines = [f"<b>SJTU-TPMSHX</b> v{__version__}"]
        commit = (repository_revision(SOURCE_ROOT)["revision"] or "")[:7]
        if commit:
            lines.append(f"Commit: <code>{commit}</code>")
        lines.append("")
        lines.append("上海交通大学 TPMS 换热器均质化求解与设计工具。")
        lines.append(
            "2D/3D D-F + SIMPLE 求解器，支持 qLogNEHVI / qLogNParEGO / Sobol 连续场优化。"
        )
        lines.append("")
        try:
            from PySide6 import __version__ as qt_ver
        except Exception:
            qt_ver = "?"
        try:
            import numpy as np_mod

            np_ver = np_mod.__version__
        except Exception:
            np_ver = "?"
        try:
            import scipy as sp_mod

            sp_ver = sp_mod.__version__
        except Exception:
            sp_ver = "?"
        try:
            import matplotlib as mpl_mod

            mpl_ver = mpl_mod.__version__
        except Exception:
            mpl_ver = "?"
        lines.append(f"Python {sys.version.split()[0]} · {platform.system()} {platform.release()}")
        lines.append(f"PySide6 {qt_ver} · NumPy {np_ver} · SciPy {sp_ver} · Matplotlib {mpl_ver}")
        lines.append("")
        lines.append("Author: alexlu997 &lt;alexlu997@hotmail.com&gt;")
        lines.append("Repo: github.com/alexlu997/SJTU-TPMSHX-TM1")
        msg = QMessageBox(self.window)
        msg.setWindowTitle("关于 SJTU-TPMSHX")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText("<br>".join(lines))
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def show_quick_tour(self) -> None:
        """Re-show the first-run onboarding dialog."""
        flag = self.window.case_files.store.base_dir / ".first_run_done"
        try:
            if os.path.exists(flag):
                os.remove(flag)
        except Exception:
            pass
        self.maybe_show_onboarding()

    def maybe_show_onboarding(self) -> None:
        """Show first-run guidance once and write `.first_run_done`."""
        flag = self.window.case_files.store.base_dir / ".first_run_done"
        if os.path.exists(flag):
            return
        if QApplication.instance().platformName() != "offscreen":
            msg = QMessageBox(self.window)
            msg.setWindowTitle("欢迎使用 SJTU-TPMSHX")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText(
                "快速上手\n\n"
                "1. 右侧参数检查器 — 在“几何”“边界”“求解”三个页签填写算例参数，按 Ctrl+] 可收起或展开。\n"
                "2. 开始计算 — 点击右上角“开始计算”按钮或按 Ctrl+R；"
                "“优化设计”支持多工况连续场搜索与芯体减重。\n"
                "3. 计算结果 — 查看温度、速度、压力场图与三维视图，底部读数条显示关键指标与外推提示。\n\n"
                "左侧导航栏可切换页面、搜索命令（Ctrl+K）、载入或保存配置，以及调整主题、温度单位与减少动态效果。"
                "本提示只显示一次。"
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
        try:
            with open(flag, "w", encoding="utf-8") as fh:
                fh.write("1")
        except Exception:
            pass

    def open_command_palette(self) -> None:
        """Open the Ctrl+K command palette."""
        pal = getattr(self.window, "_command_palette", None)
        if pal is None:
            from sjtu_tpmshx.applications.gui.ui.command_palette import CommandPalette

            pal = CommandPalette(self.window)
            self.window._command_palette = pal
        pal.open_palette()

    def install_dialog_theme(self) -> None:
        """Apply a scoped stylesheet so QMessageBox and QInputDialog match the theme."""
        app = QApplication.instance()
        if app is None:
            return
        t = get_theme()
        stylesheet = (
            f"QMessageBox{{background:{t['window']};}}"
            f"QMessageBox QLabel{{color:{t['fg']}; background:transparent;}}"
            f"QInputDialog{{background:{t['window']};}}"
            f"QInputDialog QLabel{{color:{t['fg']}; background:transparent;}}"
            f"QInputDialog QLineEdit{{background:{t['popover']}; color:{t['fg']};"
            f" border:1px solid {t['inp_border']}; border-radius:6px; padding:4px 8px;}}"
            f"QInputDialog QComboBox, QInputDialog QSpinBox{{background:{t['popover']};"
            f" color:{t['fg']}; border:1px solid {t['inp_border']};"
            f" border-radius:6px; padding:3px 6px;}}"
            f"QMessageBox QPushButton, QInputDialog QPushButton{{"
            f" background:transparent; color:{t['fg']};"
            f" border:1px solid {t['border_strong']}; border-radius:6px;"
            f" padding:5px 16px; font-weight:600; min-width:72px;}}"
            f"QMessageBox QPushButton:hover, QInputDialog QPushButton:hover{{"
            f" background:{t['hover']};}}"
        )
        if app.styleSheet() != stylesheet:
            app.setStyleSheet(stylesheet)

    def show_status_log(self) -> None:
        """Show the last 50 status-bar messages in a read-only dialog."""
        dlg = QDialog(self.window)
        dlg.setWindowTitle("状态记录")
        dlg.resize(640, 380)
        t = get_theme()
        dlg.setStyleSheet(
            f"QDialog{{background:{t['window']};}}"
            f"QPlainTextEdit{{background:{t['panel']}; color:{t['fg']};"
            f" border:1px solid {t['border']}; border-radius:6px;"
            f" font-family:{t['mono_family']}; font-size:9pt;}}"
            f"QPushButton{{background:transparent; color:{t['fg']};"
            f" border:1px solid {t['border_strong']}; border-radius:6px;"
            f" padding:5px 16px; font-weight:600;}}"
            f"QPushButton:hover{{background:{t['hover']};}}"
        )
        lay = QVBoxLayout(dlg)
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        lines = list(getattr(self.window, "_log_history", []))
        txt.setPlainText("\n".join(lines) if lines else "（尚无状态记录）")
        lay.addWidget(txt)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        btns.button(QDialogButtonBox.StandardButton.Close).clicked.connect(dlg.accept)
        lay.addWidget(btns)
        dlg.exec()
