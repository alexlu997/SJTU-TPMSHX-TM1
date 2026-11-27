"""Launch the desktop GUI; compute.py owns the calculation sequence."""
import sys

from PySide6.QtWidgets import QApplication

from sjtu_tpmshx.applications.gui.ui.theme import (
    set_theme,
    apply_mpl_theme, set_density,
)


# ── Entry point ───────────────────────────────────────────────
def main(argv=None):
    """Start the desktop interface from source or an installed launcher."""
    import argparse
    from sjtu_tpmshx.applications.cli.cli_options import add_run_control_arguments, run_control_from_args
    parser = argparse.ArgumentParser(description=__doc__)
    add_run_control_arguments(parser)
    args, qt_args = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    control = run_control_from_args(args)
    # High-DPI + font smoothing before QApplication instantiation
    from PySide6.QtCore import Qt as _Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        _Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    import os as _os_main
    _os_main.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')
    app = QApplication.instance() or QApplication([sys.argv[0], *qt_args])
    from sjtu_tpmshx.applications.gui.controllers import main_thread_gc
    main_thread_gc.install(app)

    from sjtu_tpmshx.applications.gui.controllers.user_storage import load_appearance_settings
    from sjtu_tpmshx.applications.gui.ui.microanim import apply_saved_reduced_motion
    from sjtu_tpmshx.applications.gui.ui.theme import (
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
    from sjtu_tpmshx.applications.gui.ui.typography import apply_app_font
    apply_app_font(app)
    from sjtu_tpmshx.applications.gui.ui.main_window import Main_Menu
    apply_mpl_theme()
    window = Main_Menu(control=control)
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
