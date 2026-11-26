"""Keyboard shortcut registration and navigation actions owner."""
from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut


class ShellShortcuts:
    """Owner of main-window keyboard shortcuts."""

    def __init__(self, window) -> None:
        self.window = window
        self._scrub_idx = -1

    def track(self, key: str, slot) -> QShortcut:
        """Create a QShortcut on the window and register it with SignalRouter."""
        sc = QShortcut(QKeySequence(key), self.window)
        sc.activated.connect(slot)
        self.window.signals.adopt(sc.activated, slot, sender=sc)
        return sc

    def setup(self) -> None:
        """Bind all desktop workbench keyboard shortcuts."""
        window = self.window
        ts = self.track
        ts("Ctrl+R", window.single_run.submit)
        ts("Ctrl+Shift+R", window._reset_defaults)
        for key, name in (("Ctrl+1", "layout"), ("Ctrl+2", "result"), ("Ctrl+3", "pareto")):
            ts(key, lambda n=name: window.workbench.switch_tab(n))
        ts("Ctrl+4", window.workbench.toggle_result_view)
        ts("Ctrl+5", window.workbench.show_quick_design)
        ts("Ctrl+\\", window.appearance.toggle_rail)
        ts("Ctrl+]", window.appearance.toggle_drawer)
        ts("F", window.appearance.toggle_focus)
        ts("Ctrl+?", window.dialogs.show_shortcuts)
        ts("Ctrl+/", window.dialogs.show_shortcuts)
        for digit, fluid in ((1, "Air"), (2, "Water"), (3, "sCO₂")):
            ts(f"Alt+{digit}", lambda f=fluid: self.set_fluid("A", f))
            ts(f"Alt+Shift+{digit}", lambda f=fluid: self.set_fluid("B", f))
        ts("[", lambda: self.cycle_density(-1))
        ts("]", lambda: self.cycle_density(+1))
        ts("Alt+Up", lambda: self.scrub_recent(-1))
        ts("Alt+Down", lambda: self.scrub_recent(+1))
        ts("Ctrl+D", window.dialogs.show_overview)
        ts("Ctrl+Return", window.optimization.start)
        ts("Ctrl+Enter", window.optimization.start)
        ts("Ctrl+Up", lambda: self.cycle_tab(-1))
        ts("Ctrl+Down", lambda: self.cycle_tab(+1))

    def set_fluid(self, side: str, fluid_name: str) -> None:
        """Quick-switch channel A or B working fluid via Alt+digit."""
        combo = getattr(self.window, f"combo_fluid{side}", None)
        if combo is None:
            return
        idx = combo.findText(fluid_name)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def cycle_density(self, step: int) -> None:
        """Cycle compact / cozy / comfortable density with wraparound."""
        from sjtu_tpmshx.applications.gui.ui.theme import get_density

        order = ("compact", "cozy", "comfortable")
        cur = get_density()
        try:
            idx = order.index(cur)
        except ValueError:
            idx = 1
        self.window.appearance.set_density(order[(idx + step) % len(order)])

    def cycle_tab(self, step: int) -> None:
        """Cycle enabled workbench pages with Ctrl+Up / Ctrl+Down."""
        window = self.window
        order = ("layout", "result", "pareto", "qd")
        btn_map = {
            "layout": getattr(window, "btn_tab_layout", None),
            "result": getattr(window, "btn_tab_result", None),
            "pareto": getattr(window, "btn_tab_pareto", None),
            "qd": getattr(window, "btn_quick_design", None),
        }
        enabled = [k for k in order if btn_map.get(k) is not None and btn_map[k].isEnabled()]
        if not enabled:
            return
        if window.page_stack.currentWidget() is window.quick_design:
            cur = "qd"
        else:
            cur = window.workbench.active_tab
            if cur in ("temp", "pres", "vel", "3d"):
                cur = "result"
        try:
            idx = enabled.index(cur)
        except ValueError:
            idx = 0
        target = enabled[(idx + step) % len(enabled)]
        if target == "qd":
            window.workbench.show_quick_design()
        else:
            window.workbench.switch_tab(target)

    def scrub_recent(self, step: int) -> None:
        """Step through recent runs with Alt+Up / Alt+Down and load as preset."""
        window = self.window
        recents = list(window.history.recent_runs)
        if not recents:
            window.statusBar().showMessage("暂无可浏览的最近运行记录。", 3000)
            return
        idx = max(0, min(len(recents) - 1, self._scrub_idx + step))
        self._scrub_idx = idx
        entry = recents[idx]
        try:
            window.case_files.apply_user_preset(
                entry.get("preset") or {},
                source_name=entry.get("preset_source") or "",
            )
            window.statusBar().showMessage(
                f"最近运行 #{idx + 1}/{len(recents)} — {entry.get('label', '?')}"
                f"  ·  Q={entry.get('Q', '?')}",
                4000,
            )
        except Exception:
            pass
