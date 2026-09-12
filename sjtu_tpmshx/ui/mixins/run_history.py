"""Run-history & reproducibility behaviour for ``Main_Menu``.

Extracted verbatim-in-behaviour from ``main.py`` (the recent-runs ring buffer,
the persistent session timeline, reproducible-link tokens, result provenance
tooltips, and the "copy inputs as Python" exporter). Splitting this slice out
of the 5346-line god object removes ~330 lines with zero numeric-path risk:
none of these methods touch the solver, only post-result UI glue.

Host contract — the live window MUST provide (all remain on ``Main_Menu``):
    methods : _capture_current_preset(label) -> dict
              _apply_user_preset(dict) -> None
    widgets : btn_recent (QToolButton), statusBar()
              _r_Q / _r_dP_A / _r_dP_B / _r_ToutA / _r_ToutB (result QLabels)
    run     : _run_provenance (accepted inputs and returned grid)
    state   : _SESSION_LINE_EDITS / _SESSION_COMBOS / _SESSION_CHECKS (lists)
              _active_preset_name (str, optional)
              _MAX_RECENT_RUNS (int, optional — defaults to 5)

The mixin owns ``self._recent_runs`` (a deque) lazily.
"""

from __future__ import annotations

from sjtu_tpmshx.ui.theme import _btn_styles

import base64
import collections
import datetime
import json
import zlib
from copy import deepcopy
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from sjtu_tpmshx.ui.ui_constants import TOAST_MS_SHORT

# Persistent session log lives next to main.py (project package root), NOT next
# to this module. Anchor to parents[2]: ui/mixins/run_history.py -> sjtu_tpmshx/.
_PKG_ROOT = Path(__file__).resolve().parents[2]
_TIMELINE_FILE = _PKG_ROOT / ".session_timeline.jsonl"


def _git_commit_hash() -> str:
    """Short commit of the running tree, or '' . Lazy-resolved from ``main`` so
    this module never imports ``main`` at load time (``main`` imports us).
    Tries both launch modes: ``python main.py`` and ``python -m sjtu_tpmshx.main``.
    """
    for mod in ("main", "sjtu_tpmshx.main"):
        try:
            return __import__(mod, fromlist=["_git_commit_hash"])._git_commit_hash()
        except Exception:
            continue
    return ""


class RunHistoryMixin:
    """Recent-runs menu, session timeline, reproducible links, provenance."""

    # ── recent-runs ring buffer ──────────────────────────────────────────
    def _push_recent_run(self):
        """Record the accepted run's input snapshot + headline numbers in a bounded
        ring buffer feeding the "Recent ▾" header menu, and append a slim row
        to the persistent JSONL timeline."""
        provenance = getattr(self, '_run_provenance', None)
        if provenance is None:
            return
        if not hasattr(self, "_recent_runs"):
            maxlen = getattr(self, "_MAX_RECENT_RUNS", 5)
            self._recent_runs = collections.deque(maxlen=maxlen)

        def _txt(attr):
            lbl = getattr(self, attr, None)
            try:
                return lbl.text() if lbl is not None else "—"
            except Exception:
                return "—"

        now = datetime.datetime.now()
        snap = deepcopy(provenance['preset'])
        snap['name'] = f"Recent @ {now.strftime('%H:%M:%S')}"
        entry = {
            "ts": now.isoformat(timespec="seconds"),
            "label": now.strftime("%H:%M:%S"),
            "Q": _txt("_r_Q"),
            "Q_unit": getattr(self, '_result_Q_unit', '?'),
            "dP_A": _txt("_r_dP_A"),
            "dP_B": _txt("_r_dP_B"),
            "ToutA": _txt("_r_ToutA"),
            "ToutB": _txt("_r_ToutB"),
            "preset": snap,
            "preset_source": provenance['preset_source'],
            "mode": provenance['mode'],
            "input_grid": list(provenance['input_grid']),
            "actual_grid": list(provenance['actual_grid']),
            "model_metadata": deepcopy(getattr(self, '_result_model_metadata', {})),
        }
        self._recent_runs.appendleft(entry)

        # E15 — persist everything except the bulky preset payload so the
        # timeline dialog can surface the full research-session log.
        try:
            slim = {k: v for k, v in entry.items() if k != "preset"}
            with open(_TIMELINE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(slim) + "\n")
        except Exception:
            pass

        if hasattr(self, "btn_recent"):
            self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        """Rebuild the header 载入 ▾ menu: user-saved presets, recent runs,
        and the save/clear actions.

        2026-07-03 (user request): the 标准工况 built-in section was REMOVED
        from this menu — the validated case loads via the empty-state
        「载入算例工况」 button instead. The `_BUILTIN_PRESETS` machinery
        itself stays (that button + command palette + tests depend on
        `_load_named_preset`); only the menu listing is gone."""
        from PySide6.QtWidgets import QMenu
        if not hasattr(self, "btn_recent"):
            return
        menu = QMenu(self)

        # — User-saved presets —
        try:
            user = self._load_user_presets()
        except Exception:
            user = []
        if user:
            uh = menu.addAction("我的预设")
            uh.setEnabled(False)
            for p in user:
                n = p.get('name')
                if not n:
                    continue
                act = menu.addAction(f"   ★ {n}")
                act.triggered.connect(
                    lambda _c=False, pp=p: self._load_user_preset(pp))

        # — Recent runs —
        entries = getattr(self, "_recent_runs", None) or []
        menu.addSeparator()
        rh = menu.addAction("最近运行")
        rh.setEnabled(False)
        if not entries:
            e0 = menu.addAction("   (暂无)")
            e0.setEnabled(False)
        else:
            for i, e in enumerate(entries):
                label = (f"   #{i + 1}  {e['label']}   "
                         f"Q={e['Q']} {e.get('Q_unit', '?')} · ΔP(A)={e['dP_A']}")
                act = menu.addAction(label)
                act.triggered.connect(
                    lambda _checked=False, entry=e: self._load_recent_run(entry))

        # — Actions —
        menu.addSeparator()
        load_file = menu.addAction("加载配置文件…")
        load_file.triggered.connect(self.load_config)
        save_file = menu.addAction("保存配置文件…")
        save_file.triggered.connect(self.save_config)
        save = menu.addAction("保存当前为预设…")
        save.triggered.connect(self._save_current_as_preset)
        if entries:
            clr = menu.addAction("清除最近")
            clr.triggered.connect(self._clear_recent_runs)
        self.btn_recent.setMenu(menu)

    def _load_user_preset(self, p):
        """Apply a user-saved preset dict + status note (header 载入 menu)."""
        try:
            self._apply_user_preset(p)
        except ValueError as e:
            QMessageBox.warning(self, "Preset load failed", str(e))
            return
        self.statusBar().showMessage(
            f"Loaded preset: {p.get('name', '?')}.", 5000)

    def _load_recent_run(self, entry):
        """Restore inputs from a recent-run snapshot. User hits Compute to
        re-run (same pattern as preset load)."""
        try:
            self._apply_user_preset(entry.get("preset") or {})
            self.statusBar().showMessage(
                f"Restored run from {entry.get('ts', '?')}.", 5000)
        except Exception as e:
            QMessageBox.warning(self, "Recent load failed", str(e))

    def _clear_recent_runs(self):
        if hasattr(self, "_recent_runs"):
            self._recent_runs.clear()
        self._rebuild_recent_menu()
        self.statusBar().showMessage("Recent runs cleared.", TOAST_MS_SHORT)

    # ── persistent session timeline ──────────────────────────────────────
    def _show_full_timeline(self):
        """E15 — viewer for the persistent .session_timeline.jsonl log."""
        entries = []
        if _TIMELINE_FILE.exists():
            try:
                with open(_TIMELINE_FILE, "r", encoding="utf-8") as f:
                    for line in f:
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
            QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
            QHeaderView, QHBoxLayout, QPushButton)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Session timeline — {len(entries)} runs")
        dlg.resize(760, 520)
        from sjtu_tpmshx.ui.theme import get_theme as _gt_tl
        _t = _gt_tl()
        dlg.setStyleSheet(
            f"QDialog{{background:{_t['bg']};}}"
            f"QTableWidget{{background:{_t['surface_raised']}; color:{_t['fg']};"
            f" gridline-color:{_t['card_border']}; border:1px solid {_t['card_border']};"
            f" border-radius:6px;}}"
            f"QTableWidget::item:selected{{background:{_t['combo_sel']};}}"
            f"QHeaderView::section{{background:{_t['surface_elevated']}; color:{_t['fg']};"
            f" border:none; border-right:1px solid {_t['card_border']};"
            f" border-bottom:1px solid {_t['card_border']}; padding:5px 8px; font-weight:600;}}"
            f"QScrollBar:vertical, QScrollBar:horizontal{{background:transparent; border:none;}}"
            f"QScrollBar::handle{{background:{_t['scroll_handle']}; border-radius:4px;"
            f" min-height:24px; min-width:24px;}}"
        )
        v = QVBoxLayout(dlg)
        table = QTableWidget(len(entries), 4)
        table.setHorizontalHeaderLabels(
            ["Timestamp", "Q", "ΔP_A [Pa]", "ΔP_B [Pa]"])
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        for r, e in enumerate(reversed(entries)):
            table.setItem(r, 0, QTableWidgetItem(str(e.get("ts", "—"))))
            table.setItem(r, 1, QTableWidgetItem(f"{e.get('Q', '—')} {e.get('Q_unit', '?')}"))
            table.setItem(r, 2, QTableWidgetItem(str(e.get("dP_A", "—"))))
            table.setItem(r, 3, QTableWidgetItem(str(e.get("dP_B", "—"))))
        v.addWidget(table)
        btn_row = QHBoxLayout(); btn_row.addStretch(1)
        btn_clear = QPushButton("Clear timeline")
        btn_close = QPushButton("Close")
        _styles = _btn_styles()
        btn_clear.setStyleSheet(_styles["tertiary"])
        btn_close.setStyleSheet(_styles["secondary"])

        def _clear():
            try:
                if _TIMELINE_FILE.exists():
                    _TIMELINE_FILE.unlink()
            except Exception:
                pass
            dlg.accept()
            self.statusBar().showMessage("Timeline cleared.", TOAST_MS_SHORT)

        btn_clear.clicked.connect(_clear)
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_clear); btn_row.addWidget(btn_close)
        v.addLayout(btn_row)
        dlg.exec()

    # ── reproducible links ───────────────────────────────────────────────
    def _copy_reproducible_link(self):
        """E14 — encode current inputs as a compact base64 token and copy to
        clipboard. Loadable in another window via `Load reproducible link…`."""
        preset = self._capture_current_preset("Repro link")
        blob = json.dumps(preset, separators=(",", ":")).encode("utf-8")
        compressed = zlib.compress(blob, level=9)
        b64 = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
        token = f"TPMSHX::{b64}"
        QApplication.clipboard().setText(token)
        self.statusBar().showMessage(
            f"Reproducible link copied ({len(token)} chars).", 5000)

    def _load_reproducible_link(self):
        """Inverse of `_copy_reproducible_link` — decode + apply a token."""
        from PySide6.QtWidgets import QInputDialog
        txt, ok = QInputDialog.getText(
            self, "Load reproducible link", "Paste a TPMSHX::... token:")
        if not ok or not txt.strip():
            return
        token = txt.strip()
        if not token.startswith("TPMSHX::"):
            QMessageBox.warning(self, "Bad token", "Expected TPMSHX:: prefix.")
            return
        try:
            payload = token[len("TPMSHX::"):]
            pad = "=" * (-len(payload) % 4)  # restore stripped base64 padding
            compressed = base64.urlsafe_b64decode(payload + pad)
            preset = json.loads(zlib.decompress(compressed))
            self._apply_user_preset(preset)
            self.statusBar().showMessage(
                "Reproducible link loaded. Click Compute to run.", 5000)
        except Exception as e:
            QMessageBox.warning(self, "Load failed", str(e))

    # ── provenance & export ──────────────────────────────────────────────
    def _stamp_result_provenance(self, elapsed):
        """Describe the run's inputs and returned grid, never the editable draft."""
        provenance = getattr(self, '_run_provenance', None)
        if provenance is None:
            return
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        commit = _git_commit_hash()
        grid = '×'.join(map(str, provenance['input_grid']))
        actual_grid = '×'.join(map(str, provenance['actual_grid']))
        if elapsed < 60:
            dur = f"{elapsed:.1f}s"
        else:
            dur = f"{int(elapsed // 60)}m{int(elapsed % 60):02d}s"
        from sjtu_tpmshx.ui.fmt import preset_display as _pd
        preset = _pd(provenance['preset_source'])
        tip = (f"Computed @ {ts}  ·  {dur}  ·  {provenance['mode'].upper()}"
               f"  ·  input grid {grid} (before refinement)"
               f"  ·  actual result grid {actual_grid}  ·  preset: {preset}"
               + (f"  ·  commit: {commit}" if commit else ""))
        for attr in ("_r_Q", "_r_dP_A", "_r_dP_B", "_r_ToutA", "_r_ToutB"):
            lbl = getattr(self, attr, None)
            if lbl is not None:
                try:
                    lbl.setToolTip(tip)
                except Exception:
                    pass

    def _copy_inputs_as_python(self):
        """Serialise the current left-panel inputs as a runnable Python snippet
        (a `cfg = {...}` dict) and copy to the clipboard."""
        lines = ["# Generated by SJTU-TPMSHX — reproducible input bundle"]
        commit = _git_commit_hash()
        if commit:
            lines.append(f"# commit: {commit}")
        lines.append(
            f"# exported: {datetime.datetime.now().isoformat(timespec='seconds')}")
        lines.append("")
        lines.append("cfg = {")
        for attr in self._SESSION_LINE_EDITS:
            le = getattr(self, attr, None)
            if le is None:
                continue
            try:
                v = le.text().strip()
            except Exception:
                continue
            if not v:
                continue
            lines.append(f"    {attr!r}: {v!r},")
        lines.append("    # combos")
        for attr in self._SESSION_COMBOS:
            cb = getattr(self, attr, None)
            if cb is None:
                continue
            try:
                lines.append(f"    {attr!r}: {int(cb.currentIndex())},"
                             f"  # {cb.currentText()!r}")
            except Exception:
                continue
        for attr in self._SESSION_CHECKS:
            cbx = getattr(self, attr, None)
            if cbx is None:
                continue
            try:
                lines.append(f"    {attr!r}: {bool(cbx.isChecked())!r},")
            except Exception:
                continue
        lines.append("}")
        lines.append("")
        lines.append("# Apply to a running SJTU-TPMSHX window:")
        lines.append("# window._apply_user_preset({'line_edits': {k: v for k, v in cfg.items()"
                     " if k.startswith('le_')}})")
        QApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage(
            "Copied current inputs as Python snippet to clipboard.", 5000)
