"""UI behaviour mixins extracted from the ``Main_Menu`` god object.

Each mixin is a cohesive slice of ``main.Main_Menu`` that depends only on
``self`` (the live window) at call time, never on ``main`` module globals at
import time. This keeps the import graph acyclic (``main`` -> ``ui.mixins.*``,
never back) so mixins can be unit-tested against a lightweight fake window.

Adoption: ``class Main_Menu(RunHistoryMixin, ..., QMainWindow)``.
"""

from sjtu_tpmshx.ui.mixins.run_history import RunHistoryMixin
from sjtu_tpmshx.ui.mixins.dialogs import DialogsMixin
from sjtu_tpmshx.ui.mixins.zone_panel import ZonePanelMixin
from sjtu_tpmshx.ui.mixins.optimize_ui import OptimizeUIMixin
from sjtu_tpmshx.ui.mixins.tab_view import TabViewMixin
from sjtu_tpmshx.ui.mixins.ui_builder import UIBuilderMixin
from sjtu_tpmshx.ui.mixins.fluid_input import FluidInputMixin
from sjtu_tpmshx.ui.mixins.run_controller import RunControllerMixin
from sjtu_tpmshx.ui.mixins.run_results import RunResultsMixin
from sjtu_tpmshx.ui.mixins.appearance import AppearanceMixin
from sjtu_tpmshx.ui.mixins.session_presets import SessionPresetsMixin
from sjtu_tpmshx.ui.mixins.shortcuts import ShortcutsMixin
from sjtu_tpmshx.ui.mixins.io_actions import IOActionsMixin

__all__ = ["RunHistoryMixin", "DialogsMixin", "ZonePanelMixin", "OptimizeUIMixin", "TabViewMixin", "UIBuilderMixin", "FluidInputMixin", "RunControllerMixin", "RunResultsMixin", "AppearanceMixin", "SessionPresetsMixin", "ShortcutsMixin", "IOActionsMixin"]
