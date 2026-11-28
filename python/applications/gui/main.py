"""Launch the desktop GUI; compute.py owns the calculation sequence."""
import os
from pathlib import Path
import sys

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication


def configure_cache():
    """Keep plotting and library caches outside the application bundle."""
    root = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericCacheLocation)) / 'SJTU-TPMSHX-TM1'
    for name, directory in (('MPLCONFIGDIR', 'matplotlib'),
                            ('XDG_CACHE_HOME', 'libraries')):
        path = Path(os.environ.setdefault(name, str(root / directory)))
        path.mkdir(parents=True, exist_ok=True)


# ── Entry point ───────────────────────────────────────────────
def main(argv=None):
    """Start the desktop interface; the root main.py routes to this function."""
    # Set the cache paths before a module imports Matplotlib.
    configure_cache()
    import argparse
    from tm1.applications.gui.ui.theme import apply_mpl_theme, set_density, set_theme
    from tm1.applications.cli.cli_options import add_run_control_arguments, run_control_from_args
    parser = argparse.ArgumentParser(description=__doc__)
    add_run_control_arguments(parser)
    args, qt_args = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    control = run_control_from_args(args)
    # High-DPI + font smoothing before QApplication instantiation
    from PySide6.QtCore import Qt as _Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        _Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')
    app = QApplication.instance() or QApplication([sys.argv[0], *qt_args])
    from tm1.applications.gui.controllers import main_thread_gc
    main_thread_gc.install(app)

    from tm1.applications.gui.controllers.user_storage import load_appearance_settings
    from tm1.applications.gui.ui.microanim import apply_saved_reduced_motion
    from tm1.applications.gui.ui.theme import (
        apply_saved_colormaps,
        set_accent_override,
    )
    saved = load_appearance_settings()
    for name, setter in (('theme', set_theme), ('density', set_density),
                         ('accent', set_accent_override)):
        if name in saved:
            setter(saved[name])
    apply_saved_colormaps(saved)
    apply_saved_reduced_motion(saved)
    # Force grayscale anti-aliasing to eliminate sub-pixel color fringing
    from PySide6.QtGui import QFont
    font = app.font()
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    from tm1.applications.gui.ui.typography import apply_app_font
    apply_app_font(app)
    from tm1.applications.gui.ui.main_window import Main_Menu
    apply_mpl_theme()
    window = Main_Menu(control=control)
    window.showMaximized()
    return app.exec()
