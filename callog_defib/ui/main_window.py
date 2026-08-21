"""CalLog Defib's main window: the shared `callog_common` window plus the
waveform-capture page.

Everything else (home, devices, sessions, measurement, approvals, history,
admin, theme/menu/backup machinery) comes from `BaseMainWindow` unchanged;
see that module's docstring for the override points used here.
"""

import os

from callog_common import db, perms
from callog_common.ui.main_window import MainWindow as BaseMainWindow
from callog_common.ui.main_window import has_active_scope
from .waveform_page import WaveformPage

#: The operator guide is placed under `data/` rather than the package,
#: since it contains screenshots specific to this institution: `data/` is
#: never shared anyway (see .gitignore). If the guide is missing (e.g. on
#: another setup that clones this repo) the menu action reports it gently
#: instead of crashing.
OPERATOR_GUIDE_PDF = os.path.join(
    db.DATA_DIR, "yerel", "CalLog-Defibrilator-Dalga-Olcumu-Kilavuzu.pdf")


class MainWindow(BaseMainWindow):

    def _app_title(self):
        return "CalLog Defib"

    def _app_version_info(self):
        from .. import __author__, __version__
        return __version__, __author__

    def _extra_page_available(self):
        return has_active_scope()

    def _extra_page_permission(self):
        return perms.VIEW_WAVEFORM

    def _build_extra_page(self):
        self.waveform = WaveformPage(self.state)
        return self.waveform

    def _extra_page_meta(self):
        return ("waveform", "Dalga yakalama", "wave",
                "Osiloskopta tetiklemeye bağlı CSV kaydı.")

    def _extra_page_shortcut_entry(self):
        return ("waveform", "Dalga yakalama")

    def _refresh_extra_appearance(self):
        if self._extra is not None:
            self._extra.apply_plot_theme()

    def _shutdown_extra(self):
        if self._extra is not None:
            self._extra.shutdown()

    def _operator_guides(self):
        return [("Operatör kılavuzu (PDF)", OPERATOR_GUIDE_PDF,
                 "Operatör Kılavuzu — Defibrilatör Dalga Ölçümü")]
