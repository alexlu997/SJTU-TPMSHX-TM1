"""Run history, load/save menus, reproducible links, and run-info provenance owner."""
from __future__ import annotations

import base64
import collections
import datetime
import json
import zlib
from copy import deepcopy
from pprint import pformat

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox

from sjtu_tpmshx.applications.gui.ui.fmt import duration as fmt_duration
from sjtu_tpmshx.applications.gui.ui.fmt import preset_display
from sjtu_tpmshx.applications.gui.ui.nav_rail import RecentRunItem
from sjtu_tpmshx.applications.gui.ui.run_info_popover import RunInfoData, RunInfoRow
from sjtu_tpmshx.applications.gui.ui.theme import (
    RADIUS_CARD,
    RADIUS_INPUT,
    _btn_styles,
    get_theme,
)
from sjtu_tpmshx.applications.gui.ui.ui_constants import TOAST_MS_SHORT
from sjtu_tpmshx.run_control.provenance import SOURCE_ROOT, repository_revision


def _menu_stylesheet() -> str:
    """Return Style P2 QMenu QSS for the active light or dark theme."""
    t = get_theme()
    return (
        f"QMenu {{ background: {t['popover']}; color: {t['fg']}; "
        f"border: 1px solid {t['border_strong']}; border-radius: {RADIUS_CARD}px; "
        f"padding: 6px; font-size: 12px; }}"
        f"QMenu::item {{ padding: 6px 14px; border-radius: {RADIUS_INPUT}px; }}"
        f"QMenu::item:selected {{ background: {t['accent_soft']}; color: {t['accent_fg']}; }}"
        f"QMenu::item:disabled {{ color: {t['tert']}; font-size: 11px; padding: 4px 14px; }}"
        f"QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}"
    )


def _history_status(entry) -> tuple[str, str]:
    """Describe recorded evidence without inferring success for older rows."""
    converged = entry.get("converged")
    statuses = entry.get("metric_status", {})
    reasons = entry.get("metric_reasons", {})
    metrics = ("Q", "dP_A", "dP_B", "T_out_A", "T_out_B")
    unavailable = [key for key in metrics if key in statuses and statuses[key] != "available"]
    if converged is True:
        label = "已收敛"
    elif converged is False:
        label = "未收敛"
    else:
        label = "收敛状态未知"
    if unavailable:
        label += " · 指标不可用"
    elif not all(key in statuses for key in metrics):
        label = (
            "状态未知"
            if converged is None and not statuses
            else label + " · 指标状态未知"
        )
    qualification = entry.get("qualification", {})
    design = qualification.get("design", {})
    label += " · 设计" + {"eligible": "合格", "rejected": "不合格"}.get(
        design.get("status"), "未核实"
    )
    details = [label, f"结果 ID：{entry.get('source_result_id') or '未知'}"]
    for key in unavailable:
        reason = reasons.get(key)
        details.append(f"{key}: {statuses[key]}" + (f" — {reason}" if reason else ""))
    return label, "\n".join(details)


class RunHistory:
    """Owner of recent runs, load/save menus, timeline, links, and run info."""

    MAX_RECENT_RUNS = 5

    def __init__(self, window) -> None:
        self.window = window
        self.recent_runs: collections.deque = collections.deque(maxlen=self.MAX_RECENT_RUNS)
        self._load_menu: QMenu | None = None
        self._save_menu: QMenu | None = None
        self._last_provenance_tip: str = ""
        self._last_run_ts: str = ""

    def push_recent_run(self) -> None:
        """Record the accepted run snapshot into the bounded ring buffer and timeline."""
        window = self.window
        result = window.cache.get_result()
        provenance = result.metadata.get("run_provenance") if result is not None else None
        if provenance is None:
            return

        from sjtu_tpmshx.applications.gui.ui.builders_sidebar import result_metric_texts

        values = result_metric_texts(window)
        now = datetime.datetime.now()
        self._last_run_ts = now.strftime("%H:%M:%S")
        snap = deepcopy(provenance["preset"])
        if snap is not None:
            snap["name"] = f"Recent @ {self._last_run_ts}"
        entry = {
            "ts": now.isoformat(timespec="seconds"),
            "label": self._last_run_ts,
            "Q": values["Q"],
            "Q_unit": values["Q_unit"],
            "dP_A": values["dP_A"],
            "dP_B": values["dP_B"],
            "ToutA": values["ToutA"],
            "ToutB": values["ToutB"],
            "preset": snap,
            "preset_source": provenance["preset_source"],
            "mode": provenance["mode"],
            "input_grid": list(provenance["input_grid"]),
            "actual_grid": list(provenance["actual_grid"]),
            "converged": result.converged,
            "qualification": deepcopy(result.metadata.get("qualification", {})),
            "runtime_resources": deepcopy(result.metadata.get("runtime_resources", {})),
            "source_result_id": result.metadata.get("source_result_id"),
            "metric_status": dict(result.metadata.get("metric_status", {})),
            "metric_reasons": dict(result.metadata.get("metric_reasons", {})),
            "model_metadata": {
                key: deepcopy(result.metadata[key])
                for key in (
                    "darcy_forchheimer",
                    "sco2_nu",
                    "enthalpy_eos",
                    "sco2_enthalpy_eos",
                    "co2",
                )
                if key in result.metadata
            },
        }
        self.recent_runs.appendleft(entry)

        try:
            slim = {k: v for k, v in entry.items() if k != "preset"}
            with open(
                window.case_files.store.base_dir / ".session_timeline.jsonl",
                "a",
                encoding="utf-8",
            ) as fh:
                fh.write(json.dumps(slim) + "\n")
        except Exception:
            pass

        self.rebuild_recent_menu()

    def build_load_menu(self) -> QMenu:
        """Build the load menu containing files, presets, recent runs, and workspaces."""
        window = self.window
        menu = self._load_menu
        if menu is None:
            menu = QMenu(window)
            self._load_menu = menu
        else:
            menu.clear()
        menu.setStyleSheet(_menu_stylesheet())
        menu.setToolTipsVisible(True)

        # File actions
        load_file = menu.addAction("加载配置文件…")
        load_file.triggered.connect(window.case_files.load_config)
        resume = menu.addAction("继续已保存的计算…")
        resume.triggered.connect(lambda: window.single_run.resume())
        load_link = menu.addAction("载入可复现链接…")
        load_link.triggered.connect(window.history.load_reproducible_link)

        # User-saved presets
        menu.addSeparator()
        uh = menu.addAction("我的预设")
        uh.setEnabled(False)
        preset_err = None
        try:
            user = window.case_files.store.load_user_presets()
            preset_err = getattr(window.case_files.store, "last_user_presets_error", None)
        except Exception as exc:
            preset_err = str(exc)
            user = ()
        if preset_err:
            err_act = menu.addAction("   (预设读取失败)")
            err_act.setEnabled(False)
            err_act.setToolTip(str(preset_err))
        for p in user:
            name = p.get("name")
            if not name:
                continue
            act = menu.addAction(f"   ★ {name}")
            act.triggered.connect(lambda _c=False, pp=p: self.load_user_preset(pp))
        save_preset = menu.addAction("保存当前为预设…")
        save_preset.triggered.connect(window.case_files.save_current_as_preset)

        # Recent runs
        entries = list(self.recent_runs)
        menu.addSeparator()
        rh = menu.addAction("最近运行")
        rh.setEnabled(False)
        if not entries:
            empty = menu.addAction("   (暂无)")
            empty.setEnabled(False)
        else:
            for i, e in enumerate(entries):
                status, details = _history_status(e)
                raw_ts = str(e.get("label") or "")
                ts_short = raw_ts[-8:-3] if len(raw_ts) >= 8 and ":" in raw_ts else raw_ts
                mode_tag = str(e.get("mode", "")).upper()
                prefix_parts = [p for p in (ts_short, mode_tag) if p]
                label = (
                    f"   #{i + 1} {' · '.join(prefix_parts)}  {status}  "
                    f"Q={e['Q']} {e.get('Q_unit', '?')}"
                )
                act = menu.addAction(label)
                if e.get("preset") is None:
                    act.setEnabled(False)
                    details += "\n没有 GUI 输入预设；可从保存的检查点继续计算。"
                act.setToolTip(details)
                act.triggered.connect(
                    lambda _checked=False, entry=e: self.load_recent_run(entry)
                )
        if entries:
            clr = menu.addAction("清除最近")
            clr.triggered.connect(self.clear_recent_runs)

        # Workspaces
        ws_list = window.case_files.WORKSPACES
        active_ws = window.case_files.active_workspace
        menu.addSeparator()
        wh = menu.addAction("工作区")
        wh.setEnabled(False)
        for ws_name in ws_list:
            prefix = "✓ " if ws_name == active_ws else "   "
            act = menu.addAction(f"{prefix}工作区 {ws_name}")
            act.triggered.connect(
                lambda _c=False, name=ws_name: window.case_files.switch_workspace(name)
            )
        return menu

    def build_save_menu(self) -> QMenu:
        """Build the save/export menu opened from the rail save action."""
        window = self.window
        menu = self._save_menu
        if menu is None:
            menu = QMenu(window)
            self._save_menu = menu
        else:
            menu.clear()
        menu.setStyleSheet(_menu_stylesheet())

        act_cfg = menu.addAction("保存配置文件…")
        act_cfg.triggered.connect(window.case_files.save_config)
        act_preset = menu.addAction("保存当前为预设…")
        act_preset.triggered.connect(window.case_files.save_current_as_preset)
        menu.addSeparator()
        act_png = menu.addAction("导出当前视图图片…")
        act_png.setEnabled(bool(getattr(window, "btn_export", None) and window.btn_export.isEnabled()))
        act_png.triggered.connect(window.result_export.export_figure)
        act_data = menu.addAction("导出完整计算数据…")
        act_data.setEnabled(window.cache.has_any_results())
        act_data.triggered.connect(window.result_export.export_results)
        menu.addSeparator()
        act_dir = menu.addAction("打开运行目录")
        act_dir.setEnabled(window.dialogs.resolve_output_directory() is not None)
        act_dir.triggered.connect(lambda: window.dialogs.open_output_folder())
        return menu

    def rebuild_recent_menu(self) -> None:
        """Rebuild the load/save menus and update recent-run entries in the expanded rail."""
        menu = self.build_load_menu()
        btn_recent = getattr(self.window, "btn_recent", None)
        if btn_recent is not None and hasattr(btn_recent, "setMenu"):
            btn_recent.setMenu(menu)
        btn_save = getattr(self.window, "btn_save", None)
        if btn_save is not None and hasattr(btn_save, "setMenu"):
            btn_save.setMenu(self.build_save_menu())
        expanded = getattr(self.window, "expanded_nav_rail", None)
        if expanded is not None:
            items = []
            for i, entry in enumerate(self.recent_runs):
                raw_ts = str(entry.get("label") or entry.get("ts") or "?")
                ts_short = raw_ts[-8:-3] if len(raw_ts) >= 8 and ":" in raw_ts else raw_ts[:5]
                mode_str = str(entry.get("mode", "")).upper()
                q_val = entry.get("Q", "—")
                q_unit = entry.get("Q_unit", "")
                summary = f"<i>Q</i> = {q_val}\u202f{q_unit}".strip()
                items.append(
                    RecentRunItem(
                        run_id=str(i),
                        label=f"{ts_short} · {mode_str}" if mode_str else ts_short,
                        summary_html=summary,
                    )
                )
            expanded.set_recent_runs(items)

    def show_load_menu(self, anchor=None) -> None:
        """Pop the load menu beside the rail open action."""
        window = self.window
        if window.appearance.is_rail_expanded():
            window.appearance.set_rail_expanded(False)
        rail = getattr(window, "nav_rail", None)
        if anchor is None and rail is not None:
            anchor = rail.action_anchor("open")
        menu = self.build_load_menu()
        if rail is not None:
            rail.set_open_action("open")
        try:
            menu.adjustSize()
            if anchor is not None:
                origin = anchor.mapToGlobal(QPoint(anchor.width() + 8, 0))
                win_bottom = window.mapToGlobal(QPoint(0, window.height() - 12)).y()
                y = min(origin.y(), max(window.mapToGlobal(QPoint(0, 56)).y(), win_bottom - menu.height()))
                menu.exec(QPoint(origin.x(), y))
            else:
                menu.exec()
        finally:
            if rail is not None and not window.appearance.is_rail_expanded():
                rail.set_open_action(None)

    def show_save_menu(self, anchor=None) -> None:
        """Pop the save menu beside the rail save action."""
        window = self.window
        if window.appearance.is_rail_expanded():
            window.appearance.set_rail_expanded(False)
        rail = getattr(window, "nav_rail", None)
        if anchor is None and rail is not None:
            anchor = rail.action_anchor("save")
        menu = self.build_save_menu()
        if rail is not None:
            rail.set_open_action("save")
        try:
            menu.adjustSize()
            if anchor is not None:
                origin = anchor.mapToGlobal(QPoint(anchor.width() + 8, 0))
                win_bottom = window.mapToGlobal(QPoint(0, window.height() - 12)).y()
                y = min(origin.y(), max(window.mapToGlobal(QPoint(0, 56)).y(), win_bottom - menu.height()))
                menu.exec(QPoint(origin.x(), y))
            else:
                menu.exec()
        finally:
            if rail is not None and not window.appearance.is_rail_expanded():
                rail.set_open_action(None)

    def load_recent_by_index(self, run_id: str) -> None:
        """Load a recent run selected by its index string from the expanded rail."""
        try:
            idx = int(run_id)
        except ValueError:
            return
        entries = list(self.recent_runs)
        if 0 <= idx < len(entries):
            self.load_recent_run(entries[idx])

    def load_user_preset(self, preset) -> None:
        """Apply a user-saved preset dictionary."""
        try:
            self.window.case_files.apply_user_preset(preset)
        except ValueError as exc:
            QMessageBox.warning(self.window, "加载预设失败", str(exc))
            return
        self.window.statusBar().showMessage(
            f"已载入预设：{preset.get('name', '?')}。", 5000
        )

    def load_recent_run(self, entry) -> None:
        """Restore inputs from a recent-run snapshot."""
        if entry.get("preset") is None:
            QMessageBox.information(
                self.window,
                "没有 GUI 输入预设",
                "此记录来自已保存算例，可从检查点继续计算。",
            )
            return
        try:
            self.window.case_files.apply_user_preset(
                entry.get("preset") or {},
                source_name=entry.get("preset_source") or "",
            )
            self.window.statusBar().showMessage(
                f"已恢复运行记录：{entry.get('ts', '?')}。", 5000
            )
        except Exception as exc:
            QMessageBox.warning(self.window, "加载最近运行失败", str(exc))

    def clear_recent_runs(self) -> None:
        """Clear the in-memory recent-runs ring buffer."""
        self.recent_runs.clear()
        self.rebuild_recent_menu()
        self.window.statusBar().showMessage("已清除最近运行记录。", TOAST_MS_SHORT)

    def show_full_timeline(self) -> None:
        """Display the persistent `.session_timeline.jsonl` run log."""
        entries = []
        timeline_file = self.window.case_files.store.base_dir / ".session_timeline.jsonl"
        if timeline_file.exists():
            try:
                with open(timeline_file, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            continue
            except Exception:
                pass
        from PySide6.QtWidgets import (
            QDialog,
            QHBoxLayout,
            QHeaderView,
            QPushButton,
            QTableWidget,
            QTableWidgetItem,
            QVBoxLayout,
        )

        dlg = QDialog(self.window)
        dlg.setWindowTitle(f"历史记录 — 共 {len(entries)} 次运行")
        dlg.resize(760, 520)
        t = get_theme()
        dlg.setStyleSheet(
            f"QDialog{{background:{t['window']};}}"
            f"QTableWidget{{background:{t['panel']}; color:{t['fg']};"
            f" gridline-color:{t['border']}; border:1px solid {t['border']};"
            f" border-radius:6px;}}"
            f"QTableWidget::item:selected{{background:{t['accent_soft']};}}"
            f"QHeaderView::section{{background:{t['sunken']}; color:{t['fg']};"
            f" border:none; border-right:1px solid {t['border']};"
            f" border-bottom:1px solid {t['border']}; padding:5px 8px; font-weight:600;}}"
            f"QScrollBar:vertical, QScrollBar:horizontal{{background:transparent; border:none;}}"
            f"QScrollBar::handle{{background:{t['border_strong']}; border-radius:4px;"
            f" min-height:24px; min-width:24px;}}"
        )
        v = QVBoxLayout(dlg)
        table = QTableWidget(len(entries), 5)
        table.setHorizontalHeaderLabels(["时间", "状态", "换热量 Q", "ΔP_A [Pa]", "ΔP_B [Pa]"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for column in (0, 1):
            table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        for row_idx, entry in enumerate(reversed(entries)):
            status, details = _history_status(entry)
            status_item = QTableWidgetItem(status)
            status_item.setToolTip(details)
            table.setItem(row_idx, 0, QTableWidgetItem(str(entry.get("ts", "—"))))
            table.setItem(row_idx, 1, status_item)
            table.setItem(
                row_idx,
                2,
                QTableWidgetItem(f"{entry.get('Q', '—')} {entry.get('Q_unit', '?')}"),
            )
            table.setItem(row_idx, 3, QTableWidgetItem(str(entry.get("dP_A", "—"))))
            table.setItem(row_idx, 4, QTableWidgetItem(str(entry.get("dP_B", "—"))))
        v.addWidget(table)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_clear = QPushButton("清空记录")
        btn_close = QPushButton("关闭")
        styles = _btn_styles()
        btn_clear.setStyleSheet(styles["tertiary"])
        btn_close.setStyleSheet(styles["secondary"])

        def _clear() -> None:
            try:
                timeline_file.write_text("", encoding="utf-8")
            except Exception:
                pass
            dlg.accept()
            self.window.statusBar().showMessage("已清空历史记录。", TOAST_MS_SHORT)

        btn_clear.clicked.connect(_clear)
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_clear)
        btn_row.addWidget(btn_close)
        v.addLayout(btn_row)
        dlg.exec()

    def copy_reproducible_link(self) -> None:
        """Encode current inputs as a compact TPMSHX:: base64 token on clipboard."""
        preset = self.window.case_files.capture_current_preset("Repro link")
        blob = json.dumps(preset, separators=(",", ":")).encode("utf-8")
        compressed = zlib.compress(blob, level=9)
        b64 = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
        token = f"TPMSHX::{b64}"
        QApplication.clipboard().setText(token)
        self.window.statusBar().showMessage(
            f"已复制复现链接（{len(token)} 字符）。", 5000
        )

    def load_reproducible_link(self) -> None:
        """Decode and apply a TPMSHX:: token entered by the user."""
        txt, ok = QInputDialog.getText(
            self.window, "加载复现链接", "粘贴 TPMSHX::… 复现口令："
        )
        if not ok or not txt.strip():
            return
        token = txt.strip()
        if not token.startswith("TPMSHX::"):
            QMessageBox.warning(self.window, "格式错误", "复现口令应以 TPMSHX:: 开头。")
            return
        try:
            payload = token[len("TPMSHX::") :]
            pad = "=" * (-len(payload) % 4)
            compressed = base64.urlsafe_b64decode(payload + pad)
            preset = json.loads(zlib.decompress(compressed))
            self.window.case_files.apply_user_preset(preset)
            self.window.statusBar().showMessage("已加载复现链接，请点击“开始计算”。", 5000)
        except Exception as exc:
            QMessageBox.warning(self.window, "加载失败", str(exc))

    def stamp_result_provenance(self, elapsed: float | None) -> None:
        """Describe the completed run's inputs and returned grid on result tooltips."""
        result = self.window.cache.get_result()
        provenance = result.metadata.get("run_provenance") if result is not None else None
        if provenance is None:
            return
        recorded_ts = str(provenance.get("completed_at") or "").strip()
        if recorded_ts:
            self._last_run_ts = recorded_ts
        result_rev = (
            (result.metadata.get("provenance") or {}).get("revision")
            if isinstance(result.metadata.get("provenance"), dict)
            else None
        )
        commit = str(result_rev or provenance.get("commit") or "").strip()[:7]
        grid = "×".join(map(str, provenance.get("input_grid") or ()))
        actual_grid = "×".join(map(str, provenance.get("actual_grid") or ()))
        dur = fmt_duration(elapsed) if isinstance(elapsed, (int, float)) else "—"
        preset = preset_display(provenance.get("preset_source") or "")
        tip = (
            f"Computed @ {recorded_ts or '—'}  ·  {dur}  ·  {str(provenance.get('mode') or '').upper()}"
            f"  ·  input grid {grid or '—'}"
            f"  ·  actual result grid {actual_grid or '—'}  ·  preset: {preset}"
            + (f"  ·  commit: {commit}" if commit else "")
        )
        self._last_provenance_tip = tip
        strip = getattr(self.window, "readout_strip", None)
        if strip is not None:
            strip.setToolTip(tip)
        for key in ("status", "iters"):
            lbl = getattr(self.window, "_sb_labels", {}).get(key)
            if lbl is not None:
                lbl.setToolTip(tip)

    def build_run_info_data(self) -> RunInfoData:
        """Assemble metadata strictly from the accepted result and its recorded provenance."""
        from sjtu_tpmshx.applications.gui.ui.builders_sidebar import evaluate_result_status

        window = self.window
        result = window.cache.get_result()
        provenance = result.metadata.get("run_provenance") if result is not None else None
        if not isinstance(provenance, dict):
            provenance = None
        summary = window.results.summary() if result is not None else {}

        _FLUID_LABELS = ("Air", "Water", "sCO₂", "CO₂")
        _FLUID_TYPE_MAP = {"air": "Air", "water": "Water", "sco2": "sCO₂", "co2": "CO₂"}
        _TPMS_LABELS = ("Diamond", "Gyroid")

        info_rows: list[RunInfoRow] = []
        if result is not None:
            saved_preset = provenance.get("preset") if provenance else None
            cfg_snap = (
                (provenance.get("config_snapshot") if provenance else None)
                or result.metadata.get("config_snapshot")
            )
            mode_text = str((provenance or {}).get("mode") or summary.get("mode") or "").upper()
            preset_name = preset_display((provenance or {}).get("preset_source") or "")
            info_rows.append(RunInfoRow("预设", preset_name or "—"))
            info_rows.append(RunInfoRow("维度", mode_text or "—"))

            topo = ""
            fluids_text = ""
            domain_text = ""
            cell_text = ""
            if isinstance(cfg_snap, dict):
                geom = cfg_snap.get("geometry") or {}
                topo = str(geom.get("tpms") or "")
                fa = _FLUID_TYPE_MAP.get(str((cfg_snap.get("fluid_A") or {}).get("type", "")).lower(), "")
                fb = _FLUID_TYPE_MAP.get(str((cfg_snap.get("fluid_B") or {}).get("type", "")).lower(), "")
                if fa or fb:
                    fluids_text = f"{fa or '—'} / {fb or '—'}"
                L_m = geom.get("L_dom_m")
                H_m = geom.get("H_dom_m")
                Lz_m = geom.get("Lz_m")
                if isinstance(L_m, (int, float)) and isinstance(H_m, (int, float)):
                    if mode_text == "3D" and isinstance(Lz_m, (int, float)):
                        domain_text = f"{L_m * 1000:g} × {H_m * 1000:g} × {Lz_m * 1000:g}\u202fmm"
                    else:
                        domain_text = f"{L_m * 1000:g} × {H_m * 1000:g}\u202fmm"
                lc = geom.get("L_cell_mm")
                tw = geom.get("t_wall_mm")
                if isinstance(lc, (int, float)) and isinstance(tw, (int, float)):
                    cell_text = f"L {lc:g}\u202fmm · t {tw:g}\u202fmm"
            elif isinstance(saved_preset, dict):
                combos = saved_preset.get("combos") or {}
                edits = saved_preset.get("line_edits") or {}
                t_idx = combos.get("combo_tpms")
                if isinstance(t_idx, int) and 0 <= t_idx < len(_TPMS_LABELS):
                    topo = _TPMS_LABELS[t_idx]
                fa_idx = combos.get("combo_fluidA")
                fb_idx = combos.get("combo_fluidB")
                if isinstance(fa_idx, int) and isinstance(fb_idx, int):
                    fa = _FLUID_LABELS[fa_idx] if 0 <= fa_idx < len(_FLUID_LABELS) else "—"
                    fb = _FLUID_LABELS[fb_idx] if 0 <= fb_idx < len(_FLUID_LABELS) else "—"
                    fluids_text = f"{fa} / {fb}"
                try:
                    L_mm = float(edits["le_L"]) * 1000.0
                    H_mm = float(edits["le_H"]) * 1000.0
                    if mode_text == "3D" and edits.get("le_Lz"):
                        Lz_mm = float(edits["le_Lz"]) * 1000.0
                        domain_text = f"{L_mm:g} × {H_mm:g} × {Lz_mm:g}\u202fmm"
                    else:
                        domain_text = f"{L_mm:g} × {H_mm:g}\u202fmm"
                except (KeyError, TypeError, ValueError):
                    pass
                lc_txt = str(edits.get("le_Lcell", "")).strip()
                tw_txt = str(edits.get("le_t", "")).strip()
                if lc_txt and tw_txt:
                    cell_text = f"L {lc_txt}\u202fmm · t {tw_txt}\u202fmm"

            if topo:
                info_rows.append(RunInfoRow("拓扑", topo))
            if fluids_text:
                info_rows.append(RunInfoRow("流体 A / B", fluids_text))
            if domain_text:
                info_rows.append(RunInfoRow("计算域", domain_text))
            if cell_text:
                info_rows.append(RunInfoRow("胞元参数", cell_text))

            if provenance is not None:
                in_grid = "×".join(map(str, provenance.get("input_grid", ())))
                act_grid = "×".join(map(str, provenance.get("actual_grid", ())))
                grid_val = act_grid if in_grid == act_grid else f"{in_grid} → {act_grid}"
                if grid_val:
                    info_rows.append(RunInfoRow("网格", grid_val))
                completed_at = str(provenance.get("completed_at") or "").strip()
                if completed_at:
                    info_rows.append(RunInfoRow("完成时间", completed_at))
            from sjtu_tpmshx.applications.gui.ui.field_results import recorded_elapsed_s

            elapsed = recorded_elapsed_s(result)
            if isinstance(elapsed, (int, float)):
                info_rows.append(RunInfoRow("耗时", fmt_duration(elapsed)))

            co2_meta = result.metadata.get("co2")
            if isinstance(co2_meta, dict):
                sides = [str(s) for s in (co2_meta.get("sides") or ()) if s]
                common_geom = str(co2_meta.get("common_geometry") or "").strip()
                label = "CO₂ CFD 查表"
                if common_geom and "cfd" not in common_geom.lower():
                    label = f"{label} · {common_geom}"
                if sides:
                    label = f"{label} ({', '.join(sides)})"
                info_rows.append(
                    RunInfoRow("CO₂ 几何来源", label, tone="accent_fg", weight=600)
                )

            result_rev = (
                (result.metadata.get("provenance") or {}).get("revision")
                if isinstance(result.metadata.get("provenance"), dict)
                else None
            )
            recorded_rev = result_rev or (provenance.get("commit") if provenance else None)
            if recorded_rev:
                info_rows.append(
                    RunInfoRow("版本", str(recorded_rev)[:7], tone="tert", weight=400)
                )
        else:
            info_rows.append(RunInfoRow("状态", "尚未完成计算", tone="tert", weight=400))

        status_rows: list[RunInfoRow] = []
        if not window.single_run.is_idle():
            status_kind = "run"
            status_text = "正在求解"
        else:
            status_kind, status_text = evaluate_result_status(result, summary)
            if result is not None:
                qualification = summary.get("qualification", {})
                design_ok = qualification.get("design", {}).get("eligible")
                rel = summary.get("closure_rel")
                if isinstance(rel, (int, float)) and rel == rel:
                    phys_ok = qualification.get("physical", {}).get("passed")
                    status_rows.append(
                        RunInfoRow(
                            "能量闭合",
                            f"{abs(rel) * 100:.2f}\u202f%",
                            tone="ok" if phys_ok else ("warn" if phys_ok is False else "fg"),
                        )
                    )
                iters = (summary.get("iters") or {}).get("iter_outer")
                if iters is not None:
                    status_rows.append(RunInfoRow("外迭代", str(iters)))
                if design_ok is not None:
                    status_rows.append(
                        RunInfoRow(
                            "设计资格",
                            "合格" if design_ok else "未通过",
                            tone="ok" if design_ok else "warn",
                        )
                    )

        has_log = bool((window.single_run.compute.last_log() or "").strip())
        has_diag = result is not None
        has_folder = window.dialogs.resolve_output_directory(scope="accepted_result") is not None
        return RunInfoData(
            info_rows=tuple(info_rows),
            status_kind=status_kind,
            status_text=status_text,
            status_rows=tuple(status_rows),
            can_show_log=has_log,
            can_show_diagnostics=has_diag,
            can_open_folder=has_folder,
        )

    def copy_inputs_as_python(self) -> None:
        """Copy a complete GUI preset and its window restore call as Python."""
        preset = self.window.case_files.capture_current_preset("Python inputs")
        lines = [
            "# Generated by SJTU-TPMSHX — complete GUI input preset",
            "# Run with an existing SJTU-TPMSHX window named `window`.",
            "# This is a GUI preset, not a solver ComputeConfig or CLI input.",
        ]
        commit = (repository_revision(SOURCE_ROOT)["revision"] or "")[:7]
        if commit:
            lines.append(f"# commit: {commit}")
        lines.append(f"# exported: {datetime.datetime.now().isoformat(timespec='seconds')}")
        lines.append("")
        lines.append("cfg = " + pformat(preset, width=88, sort_dicts=False))
        lines.append("")
        lines.append("window.case_files.apply_user_preset(cfg)")
        QApplication.clipboard().setText("\n".join(lines))
        self.window.statusBar().showMessage(
            "已将当前输入参数复制为 Python 脚本。", 5000
        )
