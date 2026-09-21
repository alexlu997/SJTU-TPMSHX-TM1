"""Check rendered font choices instead of only checking requested family names."""
import os
import subprocess
import sys

import pytest

from sjtu_tpmshx.ui.typography import (
    FONT_FAMILIES, FONT_STACK, REQUESTED_FAMILIES, apply_app_font, matplotlib_font_families,
)


def _check_native_sans_glyphs():
    from PySide6.QtGui import QFontDatabase, QTextLayout
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance()
    previous_font = app.font()
    try:
        apply_app_font(app)
        label = QLabel()
        label.setStyleSheet(f"font-family:{FONT_STACK};")
        label.ensurePolished()
        for text, expected in (("温度出口", FONT_FAMILIES[1]),
                               ("Q = 123.45 W", FONT_FAMILIES[0])):
            expected_available = (expected in QFontDatabase.families()
                                  or expected.startswith('.Apple'))
            if text == "温度出口" and not expected_available:
                continue  # Linux CI may lack CJK fonts; still exercise Latin below.
            layout = QTextLayout(text, label.font())
            layout.beginLayout()
            layout.createLine()
            layout.endLayout()
            runs = layout.glyphRuns()
            assert runs
            fonts = [run.rawFont() for run in runs]
            assert all(font.isValid() for font in fonts)
            families = {font.familyName() for font in fonts}
            if expected_available:
                assert families == {expected}
            assert not families.intersection({"Times New Roman", "DejaVu Serif"})
            assert all(glyph != 0 for run in runs for glyph in run.glyphIndexes())
    finally:
        app.setFont(previous_font)


def test_qt_interface_uses_native_sans_glyphs():
    if sys.platform == 'win32':
        # Windows offscreen uses Qt's generic FreeType database, not the
        # native GDI/DirectWrite engines supported by QRawFont. Test the real
        # Windows engine in its own QApplication; never replace the suite's
        # already-created offscreen application. A native fault must fail this
        # test with its exit code, rather than kill an xdist worker and hang CI.
        result = subprocess.run(
            [sys.executable, '-c',
             'from PySide6.QtWidgets import QApplication; '
             'app = QApplication(["font-probe", "-platform", "windows"]); '
             'from sjtu_tpmshx.tests.test_ui_typography import _check_native_sans_glyphs; '
             '_check_native_sans_glyphs()'],
            env={**os.environ, 'QT_QPA_PLATFORM': 'windows'},
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    else:
        _check_native_sans_glyphs()


def test_native_interface_does_not_require_office_fonts(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from sjtu_tpmshx.ui import typography

    app = QApplication.instance()
    previous_font = app.font()
    def unexpected_office_lookup():
        pytest.fail("Native interface fonts must not depend on Office being installed")
    monkeypatch.setattr(typography, "_office_fonts", unexpected_office_lookup)
    try:
        apply_app_font(app)
        assert app.font().pointSize() == 11
        assert 'Times New Roman' not in app.font().families()
    finally:
        app.setFont(previous_font)


def test_vtk_renders_latin_labels_from_times_new_roman():
    from matplotlib.ft2font import FT2Font
    from vtkmodules.vtkRenderingCore import vtkTextProperty, vtkTextRenderer
    from vtkmodules.vtkCommonDataModel import vtkImageData
    import vtkmodules.vtkRenderingFreeType  # noqa: F401 (register text renderer)
    from sjtu_tpmshx.ui.typography import apply_vtk_font

    if "Times New Roman" not in matplotlib_font_families():
        pytest.skip("Host lacks Times New Roman")
    prop = vtkTextProperty()
    prop.SetFontSize(14)
    apply_vtk_font(prop)
    assert FT2Font(prop.GetFontFile()).family_name == "Times New Roman"
    image = vtkImageData()
    dimensions = [0, 0]
    assert vtkTextRenderer.GetInstance().RenderString(
        prop, "Temperature 123.45", image, dimensions, 96)
    assert all(size > 0 for size in dimensions)


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_chart_glyphs_mathtext_and_theme(theme_name):
    import matplotlib as mpl
    from matplotlib import font_manager
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.mathtext import MathTextParser
    from sjtu_tpmshx.ui.theme import apply_mpl_theme, get_theme, get_theme_name, set_theme

    families = matplotlib_font_families()
    if not set(REQUESTED_FAMILIES) <= set(families):
        pytest.skip("Host lacks requested chart fonts")
    previous_theme = get_theme_name()
    try:
        with mpl.rc_context():
            set_theme(theme_name)
            apply_mpl_theme()
            # The locked Matplotlib renderer exposes its actual per-glyph map.
            paths = font_manager.fontManager._find_fonts_by_props(font_manager.FontProperties())
            font_map = font_manager.get_font(paths)._get_fontmap("温度Q123")
            assert {font_map[c].family_name for c in "温度"} == {"Microsoft YaHei"}
            assert {font_map[c].family_name for c in "Q123"} == {"Times New Roman"}
            parsed = MathTextParser("path").parse(r"$T_a + \mathbf{Q} + 123$")
            assert {glyph[0].family_name for glyph in parsed.glyphs} == {"Times New Roman"}

            fig = Figure(figsize=(4, 3))
            FigureCanvasAgg(fig)
            ax = fig.add_subplot()
            ax.set_title("温度 / Temperature 123")
            ax.set_xlabel(r"$T_a + \mathbf{Q}$")
            ax.plot([0, 1], [1, 2])
            fig.canvas.draw()
            palette = get_theme()
            assert fig.get_facecolor() == mpl.colors.to_rgba(palette['fig_bg'])
    finally:
        set_theme(previous_theme)
