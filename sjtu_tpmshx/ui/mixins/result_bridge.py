"""ResultBridgeMixin — legacy attribute-name bridges onto ResultCache.

Extracted verbatim from main.py (openspec split-ui-main, 2026-07-03).
Mixed into Main_Menu; the @property/@setter pairs keep the legacy
attribute names (``_compute_results``, ``_result_3d``, ``_has_results*``,
``_drawn_tabs``) reading/writing through ``self.cache``. Keep the inline
comments — they document the no-op-True setter trap.
"""
from __future__ import annotations


class ResultBridgeMixin:
    # ─── Audit C5 Phase 5 (L-b, 2026-05-28): ResultCache bridges ──
    # Storage moves wholesale to ``self.cache`` (ResultCache); these
    # properties keep the legacy attribute names working at every
    # existing call site (~50 sites in main.py + runs/ + ui/ +
    # finalize_plots), so the migration costs zero call-site churn.
    # Behaviour is single-source-of-truth: there is no longer a
    # parallel inline dict + the cache; the inline name reads/writes
    # through the cache.

    @property
    def _compute_results(self) -> dict:
        """2D mode result dict — bridges to ``self.cache``."""
        r = self.cache.get_result('2d')
        return r if r is not None else {}

    @_compute_results.setter
    def _compute_results(self, value) -> None:
        # An empty dict ``{}`` was used as a "clear" sentinel in some
        # call sites; treat that identically to ``None``.
        self.cache.set_result('2d', value if value else None)

    @property
    def _result_3d(self):
        """3D mode result dict — bridges to ``self.cache``."""
        return self.cache.get_result('3d')

    @_result_3d.setter
    def _result_3d(self, value) -> None:
        self.cache.set_result('3d', value)

    @property
    def _has_results_2d(self) -> bool:
        return self.cache.has_results('2d')

    @_has_results_2d.setter
    def _has_results_2d(self, value: bool) -> None:
        # Writing ``True`` is a no-op (presence of the result dict
        # already drives the flag).  Writing ``False`` clears the
        # cached 2D result so the next ``has_results('2d')`` returns
        # False, matching the legacy paired-write pattern.
        if not value:
            self.cache.set_result('2d', None)

    @property
    def _has_results_3d(self) -> bool:
        return self.cache.has_results('3d')

    @_has_results_3d.setter
    def _has_results_3d(self, value: bool) -> None:
        if not value:
            self.cache.set_result('3d', None)

    @property
    def _has_results(self) -> bool:
        return self.cache.has_any_results()

    @_has_results.setter
    def _has_results(self, value: bool) -> None:
        if not value:
            self.cache.clear()

    @property
    def _drawn_tabs(self) -> set:
        """Copy of the rendered-tab names. Use cache.mark_drawn() for one
        tab or assign a complete set through the setter below."""
        return self.cache.get_drawn_tabs()

    @_drawn_tabs.setter
    def _drawn_tabs(self, value: set) -> None:
        self.cache.replace_drawn_tabs(value)
    # ─── end Phase 5 bridges ──────────────────────────────────────
