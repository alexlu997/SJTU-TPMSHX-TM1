"""Requested mixed-script fonts, shared by Qt widgets and Matplotlib figures.

Times New Roman supplies Latin letters and digits; Microsoft YaHei supplies
Chinese glyphs. Fonts remain on the user's machine and are never bundled.
"""
from functools import lru_cache
import logging
from pathlib import Path


REQUESTED_FAMILIES = ("Times New Roman", "Microsoft YaHei")
FONT_FAMILIES = (*REQUESTED_FAMILIES, "PingFang SC", "Noto Sans CJK SC", "DejaVu Sans")
FONT_STACK = ",".join(f"'{family}'" for family in FONT_FAMILIES)


@lru_cache(maxsize=1)
def _office_fonts() -> tuple[Path, ...]:
    """Office on macOS has application-local fonts absent from system lists."""
    for app_name in ("Word", "Excel", "PowerPoint"):
        directory = Path(f"/Applications/Microsoft {app_name}.app/Contents/Resources/DFonts")
        if directory.is_dir():
            return tuple(directory / name for name in (
                "msyh.ttc", "msyhbd.ttc", "times.ttf", "timesbd.ttf",
                "timesi.ttf", "timesbi.ttf",
            ) if (directory / name).is_file())
    return ()


def apply_app_font(app) -> str:
    """Register locally available fonts and expose missing requests explicitly."""
    from PySide6.QtGui import QFont, QFontDatabase

    available = set(QFontDatabase.families())
    if not set(REQUESTED_FAMILIES) <= available:
        for path in _office_fonts():
            QFontDatabase.addApplicationFont(str(path))
        available = set(QFontDatabase.families())
    missing = tuple(name for name in REQUESTED_FAMILIES if name not in available)
    families = [name for name in FONT_FAMILIES if name in available]
    font = QFont(app.font())
    if families:
        font.setFamilies(families)
    font.setPointSize(10)
    font.setWeight(QFont.Weight.Normal)
    app.setFont(font)
    app._mono_font_family = font.family()
    app._missing_font_families = missing
    if missing:
        logging.getLogger(__name__).warning(
            "Requested GUI fonts unavailable: %s; using available system fallback: %s",
            ", ".join(missing), ", ".join(font.families()),
        )
    return font.family()


@lru_cache(maxsize=1)
def matplotlib_font_families() -> tuple[str, ...]:
    """Resolve the same fonts for charts without requiring a QApplication."""
    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    if not set(REQUESTED_FAMILIES) <= available:
        for path in _office_fonts():
            font_manager.fontManager.addfont(str(path))
        available = {font.name for font in font_manager.fontManager.ttflist}
    missing = tuple(name for name in REQUESTED_FAMILIES if name not in available)
    if missing:
        logging.getLogger(__name__).warning(
            "Requested chart fonts unavailable: %s; using available system fallback",
            ", ".join(missing),
        )
    return tuple(name for name in FONT_FAMILIES if name in available)


def apply_vtk_font(text_property) -> None:
    """VTK's current Latin chart labels use the actual Times New Roman file."""
    from matplotlib import font_manager

    text_property.SetFontFamilyToTimes()
    if "Times New Roman" in matplotlib_font_families():
        text_property.SetFontFamily(4)  # VTK_FONT_FILE
        text_property.SetFontFile(font_manager.findfont(
            "Times New Roman", fallback_to_default=False))
