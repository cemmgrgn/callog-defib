"""PDF font registration with Turkish character support.

reportlab's built-in Helvetica is limited to WinAnsi encoding: it has no
s-cedilla, g-breve, dotted/dotless I characters, and they come out broken in
the certificate. So a Unicode TTF is embedded instead.

Candidates are tried in order; the first one found is used. If none are
found, it falls back to Helvetica and returns ascii_fallback True so the
caller can warn about it.
"""

import os

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

#: Characters that cause problems in Turkish — font validation uses these
TR_CHARS = "çÇğĞıİöÖşŞüÜ"

_WIN_FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")

#: (family name, regular file, bold file) — in priority order
_CANDIDATES = (
    ("DejaVuSans", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    ("SegoeUI", "segoeui.ttf", "seguisb.ttf"),
    ("Arial", "arial.ttf", "arialbd.ttf"),
    ("Tahoma", "tahoma.ttf", "tahomabd.ttf"),
)

_registered = None


def _supports_turkish(path):
    """Verifies that the TTF file contains the Turkish characters."""
    try:
        font = TTFont("_probe", path)
        cmap = font.face.charToGlyph
        return all(ord(ch) in cmap for ch in TR_CHARS)
    except Exception:
        return False


def register():
    """Registers the Unicode font.

    Returns: (normal_font_name, bold_font_name, ascii_fallback)
    """
    global _registered
    if _registered is not None:
        return _registered

    for family, regular, bold in _CANDIDATES:
        reg_path = os.path.join(_WIN_FONTS, regular)
        if not os.path.exists(reg_path) or not _supports_turkish(reg_path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(family, reg_path))
        except Exception:
            continue

        bold_name = family
        bold_path = os.path.join(_WIN_FONTS, bold)
        if os.path.exists(bold_path):
            try:
                pdfmetrics.registerFont(TTFont(family + "-Bold", bold_path))
                bold_name = family + "-Bold"
                pdfmetrics.registerFontFamily(
                    family, normal=family, bold=bold_name,
                    italic=family, boldItalic=bold_name)
            except Exception:
                pass

        _registered = (family, bold_name, False)
        return _registered

    # No Unicode font found — Turkish characters will come out broken
    _registered = ("Helvetica", "Helvetica-Bold", True)
    return _registered
