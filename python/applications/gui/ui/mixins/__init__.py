"""Case form and desktop shell behavior."""

from sjtu_tpmshx.applications.gui.ui.mixins.run_history import RunHistoryMixin
from sjtu_tpmshx.applications.gui.ui.mixins.dialogs import DialogsMixin
from sjtu_tpmshx.applications.gui.ui.mixins.zone_panel import ZonePanelMixin
from sjtu_tpmshx.applications.gui.ui.mixins.ui_builder import UIBuilderMixin
from sjtu_tpmshx.applications.gui.ui.mixins.fluid_input import FluidInputMixin
from sjtu_tpmshx.applications.gui.ui.mixins.appearance import AppearanceMixin
from sjtu_tpmshx.applications.gui.ui.mixins.shortcuts import ShortcutsMixin

__all__ = [
    "RunHistoryMixin",
    "DialogsMixin",
    "ZonePanelMixin",
    "UIBuilderMixin",
    "FluidInputMixin",
    "AppearanceMixin",
    "ShortcutsMixin",
]
