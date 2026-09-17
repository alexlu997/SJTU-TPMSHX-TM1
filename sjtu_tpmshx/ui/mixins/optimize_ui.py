"""Multi-objective optimization + quick-design launchers for ``Main_Menu``.

Run/cancel and Pareto-pick callbacks delegate to ``ui.optimize_panel``;
the quick-design callback opens its dialog. Plotting, saving and loading
call the owning module functions directly.

Pure UI glue, no solver / numeric path. Adopted via
``class Main_Menu(..., OptimizeUIMixin, ..., QMainWindow)``; external callers
(ui/ui_builders.py button wiring, ui/command_palette.py, the Ctrl+Enter
shortcut, ui/optimize_panel.py's own getattr bind points) keep working because
the names still resolve on the live window through the MRO.

No module-level imports — every handler lazy-imports its callable exactly as
the originals did.
"""

from __future__ import annotations


class OptimizeUIMixin:
    """Zone-optimization panel handlers + quick-design launcher."""

    # ── multi-objective optimization (delegate to ui.optimize_panel) ──────
    def _run_optimize(self):
        from sjtu_tpmshx.ui.optimize_panel import run_optimize
        return run_optimize(self)

    def _cancel_optimize(self):
        from sjtu_tpmshx.ui.optimize_panel import cancel_optimize
        return cancel_optimize(self)

    def _on_pareto_pick(self, event):
        from sjtu_tpmshx.ui.optimize_panel import on_pareto_pick
        return on_pareto_pick(self, event)

    # ── quick-design tool (Phase 2 Task 4) ───────────────────────────────
    def _open_quick_design(self):
        from sjtu_tpmshx.ui.quick_design_panel import build_quick_design_dialog
        if getattr(self, "_qd_dialog", None) is None:
            self._qd_dialog = build_quick_design_dialog(self)
        self._qd_dialog.show()
        self._qd_dialog.raise_()
