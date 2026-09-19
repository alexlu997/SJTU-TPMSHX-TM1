"""Check rendered font choices instead of only checking requested family names."""
import pytest

from sjtu_tpmshx.ui.typography import (
    FONT_STACK, REQUESTED_FAMILIES, apply_app_font, matplotlib_font_families,
)


def test_qt_mixed_script_uses_requested_glyph_fonts():
    from PySide6.QtGui import QTextLayout
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance()
    previous_font = app.font()
    try:
        apply_app_font(app)
        if app._missing_font_families:
            pytest.skip(f"Host lacks requested fonts: {app._missing_font_families}")
        label = QLabel()
        label.setStyleSheet(f"font-family:{FONT_STACK};")
        label.ensurePolished()
        for text, expected in (("温度出口", "Microsoft YaHei"),
                               ("Q = 123.45 W", "Times New Roman")):
            layout = QTextLayout(text, label.font())
            layout.beginLayout()
            layout.createLine()
            layout.endLayout()
            runs = layout.glyphRuns()
            assert runs
            assert {run.rawFont().familyName() for run in runs} == {expected}
            assert all(glyph != 0 for run in runs for glyph in run.glyphIndexes())
    finally:
        app.setFont(previous_font)


def test_missing_requested_fonts_are_reported(monkeypatch, caplog):
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    from sjtu_tpmshx.ui import typography

    app = QApplication.instance()
    previous_font = app.font()
    previous_missing = getattr(app, '_missing_font_families', ())
    monkeypatch.setattr(QFontDatabase, "families", lambda: ["DejaVu Sans"])
    monkeypatch.setattr(typography, "_office_fonts", lambda: ())
    try:
        apply_app_font(app)
        assert app._missing_font_families == REQUESTED_FAMILIES
        assert "Times New Roman, Microsoft YaHei" in caplog.text
        assert "unavailable" in caplog.text
    finally:
        app.setFont(previous_font)
        app._missing_font_families = previous_missing


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
