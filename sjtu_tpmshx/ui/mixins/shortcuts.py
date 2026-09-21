"""ShortcutsMixin — keyboard-shortcut wiring + shortcut-driven actions.

Extracted verbatim from main.py (openspec split-ui-main, 2026-07-03).
Mixed into Main_Menu; methods keep their exact names and behaviour.
QShortcut/QKeySequence stay method-local imports (as in main.py).
"""
from __future__ import annotations


class ShortcutsMixin:
    def _track_shortcut(self, key, slot, tag):
        """QShortcut + connect + SignalRouter.adopt — one call.

        Phase 5 follow-up (Plan #4 connect-migration). Builds a
        QShortcut parented on ``self`` (so its lifetime matches the
        window's), wires ``slot``, and registers the connection with
        ``self.signals`` so closeEvent's bulk disconnect covers it.
        Returns the QShortcut for further configuration.
        """
        from PySide6.QtGui import QShortcut, QKeySequence
        sc = QShortcut(QKeySequence(key), self)
        sc.activated.connect(slot)
        self.signals.adopt(sc.activated, slot, tag=tag, sender=sc)
        return sc

    def _setup_shortcuts(self):
        # Phase 5 follow-up: every shortcut routed through _track_shortcut
        # so closeEvent's signals.disconnect_all() picks them up. Lambdas
        # are bound to local names (not inline) so adopt() can hold them
        # for later disconnect.
        ts = self._track_shortcut
        ts("Ctrl+R", self.run_calculation, tag='sc-run')
        ts("Ctrl+Shift+R", self._reset_defaults, tag='sc-reset')
        # ui-shortcuts-persist: bindings match the visible 3-tab workbench
        # (几何布局|结果|优化); 'result' resolves via _result_view. Ctrl+4
        # flips 2D|3D inside 结果; the retired direct temp/pres/vel/3d
        # binds are gone.
        for key, name in (('Ctrl+1', 'layout'), ('Ctrl+2', 'result'),
                          ('Ctrl+3', 'pareto')):
            ts(key, (lambda n=name: self._switch_tab(n)),
                tag=f'sc-tab-{name}')
        ts("Ctrl+4", self._toggle_result_view, tag='sc-result-view')
        ts("Ctrl+\\", self._toggle_left_panel, tag='sc-parameter-panel')
        ts("F", self._toggle_3d_immersive, tag='sc-immersive')
        ts("Ctrl+?", self._show_shortcuts, tag='sc-help-q')
        ts("Ctrl+/", self._show_shortcuts, tag='sc-help-s')
        # D12 — fluid quick-presets
        for digit, fluid in ((1, 'Air'), (2, 'Water'), (3, 'sCO₂')):
            ts(f"Alt+{digit}",
                (lambda f=fluid: self._keyboard_set_fluid('A', f)),
                tag=f'sc-fluid-A-{digit}')
            ts(f"Alt+Shift+{digit}",
                (lambda f=fluid: self._keyboard_set_fluid('B', f)),
                tag=f'sc-fluid-B-{digit}')
        # D13 — density cycle
        ts("[", (lambda: self._cycle_density(-1)),
            tag='sc-density-prev')
        ts("]", (lambda: self._cycle_density(+1)),
            tag='sc-density-next')
        # D14 — Alt+↑/↓ scrub recent runs
        ts("Alt+Up", (lambda: self._scrub_recent(-1)),
            tag='sc-scrub-prev')
        ts("Alt+Down", (lambda: self._scrub_recent(+1)),
            tag='sc-scrub-next')
        # D7 — Ctrl+D overview dashboard
        ts("Ctrl+D", self._show_overview, tag='sc-overview')
        # qNEHVI launch
        ts("Ctrl+Return", self._run_optimize, tag='sc-opt-return')
        ts("Ctrl+Enter", self._run_optimize, tag='sc-opt-enter')
        # E18 — Ctrl+↑/↓ cycle tabs
        ts("Ctrl+Up", (lambda: self._cycle_tab(-1)),
            tag='sc-cycle-tab-prev')
        ts("Ctrl+Down", (lambda: self._cycle_tab(+1)),
            tag='sc-cycle-tab-next')

    def _keyboard_set_fluid(self, side, fluid_name):
        """Alt+digit quick-switch. Reuses `_apply_fluid_defaults` side-effect."""
        combo = getattr(self, f'combo_fluid{side}', None)
        if combo is None:
            return
        idx = combo.findText(fluid_name)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _cycle_density(self, step):
        """`[` / `]` cycle compact ↔ cozy ↔ comfortable with wraparound."""
        from sjtu_tpmshx.ui.theme import get_density
        order = ('compact', 'cozy', 'comfortable')
        cur = get_density()
        try:
            i = order.index(cur)
        except ValueError:
            i = 1
        self._set_density(order[(i + step) % len(order)])

    def _cycle_tab(self, step):
        """Ctrl+↑/↓ — walk the VISIBLE workbench tabs (几何布局|结果|优化).

        The result family (temp/pres/vel/3d) collapses to 'result' so
        cycling never lands on a hidden legacy button (ui-shortcuts-persist).
        """
        order = ('layout', 'result', 'pareto')
        btn_map = {
            'layout': getattr(self, 'btn_tab_layout', None),
            'result': getattr(self, 'btn_tab_result', None),
            'pareto': getattr(self, 'btn_tab_pareto', None),
        }
        enabled = [k for k in order if btn_map.get(k) is not None
                    and btn_map[k].isEnabled()]
        if not enabled:
            return
        cur = getattr(self, '_active_tab', enabled[0])
        if cur in ('temp', 'pres', 'vel', '3d'):
            cur = 'result'
        try:
            i = enabled.index(cur)
        except ValueError:
            i = 0
        new_tab = enabled[(i + step) % len(enabled)]
        self._switch_tab(new_tab)

    def _scrub_recent(self, step):
        """Alt+↑/↓ walk through `_recent_runs`, loading each as a preset."""
        recents = list(getattr(self, '_recent_runs', []) or [])
        if not recents:
            self.statusBar().showMessage(
                "No recent runs to scrub through.", 3000)
            return
        idx = getattr(self, '_scrub_idx', -1)
        idx = max(0, min(len(recents) - 1, idx + step))
        self._scrub_idx = idx
        entry = recents[idx]
        try:
            self._apply_user_preset(entry.get('preset') or {})
            self.statusBar().showMessage(
                f"Recent #{idx + 1}/{len(recents)} — {entry.get('label','?')}"
                f"  ·  Q={entry.get('Q','?')}", 4000)
        except Exception:
            pass
