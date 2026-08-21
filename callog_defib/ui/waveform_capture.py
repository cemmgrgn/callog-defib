"""waveform_capture -- WaveformPage mixin, moved out of waveform_page.py to keep
that file to a manageable size.
"""

from callog_common import drivers
from callog_common import perms
from callog_common import testmodes
from callog_common import theme
from callog_common import waveform
from callog_common.acquisition import WaveformWorker
from callog_common.qt import Qt
from callog_common.qt import QtWidgets
from callog_common.ui.util import fit_table
from .. import defib
from callog_common.ui.waveform_common import _channel_label
from callog_common.ui.waveform_common import _close_quietly
from callog_common.ui.waveform_common import _column_name
from callog_common.ui.waveform_common import _open_path
from callog_common.ui.waveform_common import _restyle
from callog_common.ui.waveform_common import _safe_setup
from callog_common.ui.waveform_common import _screenshot_temp
import os


class _CaptureMixin:

    def _grab_csv(self):
        """Reads and saves the waveform currently on screen without waiting for a trigger.

        'Start capture' waits for an **event**; this button takes whatever
        is on the device right now. Needed so you don't have to fire
        another shock just because the signal is already on screen.
        """
        if not self.state.can(perms.WAVEFORM_CAPTURE):
            QtWidgets.QMessageBox.warning(
                self, "Yetki yok", perms.denial_message(perms.WAVEFORM_CAPTURE))
            return
        inst = self._current_instrument()
        if inst is None:
            return
        if self.worker is not None:
            QtWidgets.QMessageBox.information(
                self, "Yakalama sürüyor",
                "Tetikleme beklenirken CSV alınamaz. Önce 'Durdur' deyin.")
            return

        drv, owned = self._open_driver(inst)
        if drv is None:
            return

        mode = self.current_mode()
        channels = (drv.displayed_channels(force=("CHANnel1",))
                    if self.auto_chan_chk.isChecked()
                    else self._selected_channels()) or ["CHANnel1"]

        try:
            # Must stop before reading: if the channels are read one after
            # another while the device is sweeping, the two channels come
            # from DIFFERENT acquisitions and the shared time axis lies.
            drv.stop()
            times = None
            columns = {}
            for ch in channels:
                t, v = drv.read_waveform(ch, self.points_spin.value() or None)
                if times is None:
                    times = t
                columns[_column_name(ch)] = v
            setup_now = _safe_setup(drv, "CHANnel1")
            shot = _screenshot_temp(drv)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "CSV alınamadı", str(exc))
            return
        finally:
            try:
                drv.run()
            except Exception:
                pass
            if owned:
                _close_quietly(drv)

        chain = self._mode_chain()
        factor = testmodes.software_factor(chain["divider_ratio"],
                                           setup_now.get("probe_ratio"))
        scaled = dict((name, testmodes.scale(list(values), factor))
                      for name, values in columns.items())

        analysis, warning = self._analyze(mode, times, scaled, columns, chain)
        try:
            capture_id = waveform.save(
                times, scaled,
                instrument_id=inst["id"],
                operator_id=self.state.user["id"],
                dut_id=self.dut_combo.currentData(),
                outdir=self.outdir_edit.text().strip() or None,
                is_simulated=drivers.is_simulated(inst["driver"]),
                screenshot=shot,
                test_mode=mode.key,
                divider_ratio=chain["divider_ratio"],
                load_ohm=chain.get("load_ohm"),
                setup=setup_now,
                analysis=analysis,
                nominal_energy_j=self._nominal_energy(),
                notes="Tetiklemesiz elle alım (CSV al)")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Kaydedilemedi", str(exc))
            return

        self._plot(times, scaled)
        if mode.analyzer:
            self.analysis_box.setVisible(True)
            self._show_analysis(analysis, warning)
        self.reload()
        row = waveform.get(capture_id)
        self.status_label.setText(
            "Ekrandaki dalga alındı — %d nokta%s → %s"
            % (row["points"], " + ekran görüntüsü" if row["screenshot_path"] else "",
               os.path.basename(row["file_path"])))

    def _analyze(self, mode, times, scaled, raw_columns, chain):
        """Analysis + clipping warning. A failure here doesn't lose the capture.

        The waveform is already read from the device; writing it to file
        doesn't depend on the analysis succeeding. So the exception is
        consumed here and returned to the user as a warning message.
        """
        if not mode.analyzer or not scaled:
            return None, None
        first = list(scaled.keys())[0]
        try:
            analysis = mode.analyzer(list(times), scaled[first], chain)
            warning = testmodes.clipping_warning(
                raw_columns[first], self.vdiv_spin.value())
            return analysis, warning
        except Exception as exc:
            return None, "Çözümleme yapılamadı: %s" % exc

    def _grab_screenshot(self):
        """Saves the oscilloscope screen as-is, as a PNG."""
        inst = self._current_instrument()
        if inst is None:
            return
        directory = self.outdir_edit.text().strip() or waveform.default_dir()
        if not os.path.isdir(directory):
            os.makedirs(directory)
        from datetime import datetime
        name = "ekran_%s.png" % datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(directory, name)

        drv, owned = self._open_driver(inst)
        if drv is None:
            return
        try:
            drv.screenshot(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Ekran görüntüsü alınamadı", str(exc))
            return
        finally:
            if owned:
                _close_quietly(drv)

        self.status_label.setText("Ekran görüntüsü kaydedildi: %s" % name)
        self.state.status("Ekran görüntüsü: %s" % path)
        _open_path(path)

    def _show_analysis(self, result, warning=None):
        rows = defib.summary_rows(result) if result else []
        self.analysis_table.setRowCount(0)
        for label, value in rows:
            i = self.analysis_table.rowCount()
            self.analysis_table.insertRow(i)
            self.analysis_table.setItem(i, 0, QtWidgets.QTableWidgetItem(label))
            item = QtWidgets.QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.analysis_table.setItem(i, 1, item)
        fit_table(self.analysis_table, stretch_column=0)

        c = theme.colors()
        if warning:
            self.analysis_note.setText(
                "<span style='color:%s'>⚠ %s</span>" % (c["bad"], warning))
        elif result and result.get("found"):
            self.analysis_note.setText(
                "Değerler yakalanan dalgadan hesaplandı; sertifikalı bir "
                "defibrilatör analizörü ölçümü değildir.")
        else:
            self.analysis_note.setText("")

    def _start(self):
        if not self.state.can(perms.WAVEFORM_CAPTURE):
            QtWidgets.QMessageBox.warning(
                self, "Yetki yok", perms.denial_message(perms.WAVEFORM_CAPTURE))
            return
        if self.worker is not None:
            return
        inst = self._current_instrument()
        if inst is None:
            QtWidgets.QMessageBox.information(
                self, "Cihaz yok",
                "Dalga yakalayabilen bir osiloskop tanımlı değil.")
            return

        missing = self._missing_before_start()
        if missing:
            answer = QtWidgets.QMessageBox.warning(
                self, "Eksik ayar",
                "Aşağıdaki alanlar girilmedi:\n\n• %s\n\n"
                "Boş bırakılırsa yakalama hiçbir cihaza bağlanmaz ve/veya "
                "sertifika uygun/uygun değil kararı veremez.\n\n"
                "Yine de başlatılsın mı?" % "\n• ".join(missing),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Cancel)
            if answer != QtWidgets.QMessageBox.Yes:
                return

        mode = self.current_mode()

        # Starting with an unreachable threshold means sitting for minutes
        # showing "waiting for trigger" without ever capturing anything.
        # The reason is stated here.
        reach = testmodes.trigger_warning(self.trig_spin.value(),
                                          self.vdiv_spin.value())
        if reach and mode.key != testmodes.FREE:
            answer = QtWidgets.QMessageBox.warning(
                self, "Tetikleme eşiği ekran dışında",
                "%s\n\nYine de başlatılsın mı?" % reach,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Cancel)
            if answer != QtWidgets.QMessageBox.Yes:
                return

        if mode.warning and not self._confirm_chain(mode):
            return

        drv = self._driver_for(inst)
        if drv is None:
            return
        try:
            drv.connect()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Bağlantı kurulamadı", str(exc))
            return
        self._sync_sim_energy(drv)

        # In test mode, scale and trigger are applied right before capture:
        # capturing a shock with settings someone else left on the device
        # would produce a record with the peak clipped.
        self._applied_setup = None
        if mode.key != testmodes.FREE:
            try:
                # NORMal here: if no trigger arrives, the device must not
                # sweep on its own, or we'd mistake a blank screen for a
                # captured shock.
                self._applied_setup = drv.apply_setup(
                    trigger_sweep="NORMal", **self._mode_setup())
            except Exception as exc:
                drv.close()
                QtWidgets.QMessageBox.critical(
                    self, "Ayar uygulanamadı", str(exc))
                return
        else:
            self._applied_setup = _safe_setup(drv, "CHANnel1")

        if self.auto_chan_chk.isChecked():
            try:
                channels = drv.displayed_channels(force=("CHANnel1",))
            except Exception:
                channels = ["CHANnel1"]
            self.ch1_chk.setChecked("CHANnel1" in channels)
            self.ch2_chk.setChecked("CHANnel2" in channels)
        else:
            channels = self._selected_channels()

        if not channels:
            QtWidgets.QMessageBox.information(
                self, "Kanal seçilmedi", "En az bir kanal seçin.")
            drv.close()
            return

        self.driver = drv
        self._capture_dir = self.outdir_edit.text().strip() or None
        self._dut_id = self.dut_combo.currentData()
        self._mode = mode
        self._chain = self._mode_chain()
        self._setup_used = self._applied_setup or (
            self._mode_setup() if mode.key != testmodes.FREE else None)
        #: Analysis results for the series measurement — a summary is
        #: produced from these when it finishes.
        self._series = []
        # If multiple measurements were requested, they're all grouped
        # under one series key; the series report is generated from that
        # key. No key is given for a single capture: counting every
        # capture as a series of 1 would clutter the list with meaningless
        # series.
        target = self.count_spin.value()
        self._series_id = waveform.new_series_id() if target > 1 else None
        self._series_size = target if target > 1 else None

        self.worker = WaveformWorker(
            drv, channels,
            points=self.points_spin.value() or None,
            max_captures=self.count_spin.value(),
            timeout_s=self.timeout_spin.value() or None,
            shot_delay_s=self.shot_delay_spin.value(),
            parent=self)
        self.worker.captured.connect(self._on_captured)
        self.worker.error.connect(self._on_error)
        self.worker.status.connect(self.status_label.setText)
        self.worker.finished_run.connect(self._on_finished)
        self.worker.start()

        target = self.count_spin.value()
        self.rec_label.setText("● 0/%d" % target if target > 1 else "● YAKALIYOR")
        self.rec_label.setProperty("badge", "bad")
        _restyle(self.rec_label)
        self._update_buttons()
        series = (" · %d ölçümlük seri" % target) if target > 1 else ""
        self.state.status("Dalga yakalama başladı: %s%s"
                          % (", ".join(_channel_label(c) for c in channels),
                             series))

    def _stop(self):
        if self.worker is not None:
            self.status_label.setText("Durduruluyor…")
            self.worker.stop()

    def _on_captured(self, index, times, columns, shot=None):
        inst = self._current_instrument()
        mode = getattr(self, "_mode", None) or testmodes.get(testmodes.FREE)
        chain = getattr(self, "_chain", {}) or {}
        ratio = chain.get("divider_ratio", 1.0)

        # The file must record the real device voltage. But if the divider
        # ratio was reported to the device as probe attenuation, the device
        # **already** returns the real voltage; multiplying blindly again
        # would inflate the file by 1000x. Hence the factor is divider /
        # probe ratio.
        probe_on_scope = (getattr(self, "_applied_setup", None) or {}).get(
            "probe_ratio")
        factor = testmodes.software_factor(ratio, probe_on_scope)
        scaled = dict((name, testmodes.scale(list(values), factor))
                      for name, values in columns.items())

        analysis, warning = self._analyze(mode, times, scaled, columns, chain)

        # The screenshot is taken in the capture thread, right after the
        # trigger and before the device is re-armed, so it arrives here
        # ready-made. Taking it here instead would let `:SINGle` clear the
        # screen in between.
        try:
            capture_id = waveform.save(
                times, scaled,
                instrument_id=inst["id"],
                operator_id=self.state.user["id"],
                dut_id=self._dut_id,
                outdir=self._capture_dir,
                trigger_no=None,
                is_simulated=bool(self.driver and self.driver.is_simulated),
                screenshot=shot,
                test_mode=mode.key,
                divider_ratio=ratio,
                load_ohm=chain.get("load_ohm"),
                setup=getattr(self, "_setup_used", None),
                analysis=analysis,
                series_id=getattr(self, "_series_id", None),
                series_index=index,
                series_size=getattr(self, "_series_size", None),
                nominal_energy_j=self._nominal_energy())
        except Exception as exc:
            self._on_error("Yakalama kaydedilemedi: %s" % exc)
            self._stop()
            return

        self._plot(times, scaled)
        if mode.analyzer:
            self._show_analysis(analysis, warning)
        self._series.append(analysis)
        self.reload()
        row = waveform.get(capture_id)
        extra = " + ekran görüntüsü" if row["screenshot_path"] else ""
        target = self.count_spin.value()
        of_n = ("%d/%d" % (index, target)) if target else str(index)
        self.status_label.setText(
            "%s. yakalama kaydedildi — %d nokta%s → %s"
            % (of_n, row["points"], extra, os.path.basename(row["file_path"])))
        self.rec_label.setText("● %s" % of_n if target > 1 else "● YAKALIYOR")
        if warning:
            self.state.status(warning, 12000)

    def _on_error(self, message):
        self.status_label.setText(message)
        self.state.status(message)

    def _on_finished(self):
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.wait(3000)
            worker.deleteLater()
        if self.driver is not None:
            try:
                self.driver.run()      # put the device back into normal sweep
            except Exception:
                pass
            try:
                self.driver.close()
            except Exception:
                pass
            self.driver = None

        self.rec_label.setText("BEKLEMEDE")
        self.rec_label.setProperty("badge", "warn")
        _restyle(self.rec_label)
        self._update_buttons()

        summary = self._series_summary()
        self.status_label.setText("Yakalama durdu." + (
            "  " + summary if summary else ""))
        if summary:
            self.state.status(summary, 20000)

    def _series_summary(self):
        """Series measurement summary: capture count, energy and peak spread.

        Repeatability needs to be seen when the series finishes rather than
        capture by capture — the scatter between the energy of 10 shocks
        says far more about the device's stability than any single shock.
        """
        results = [a for a in getattr(self, "_series", []) or []
                   if a and a.get("found")]
        if len(results) < 2:
            return ""
        parts = ["%d ölçümlük seri:" % len(results)]
        for key, label, unit in (("energy_j", "enerji", "J"),
                                 ("peak_voltage", "tepe", "V")):
            values = [float(r[key]) for r in results
                      if r.get(key) is not None]
            if len(values) < 2:
                continue
            mean = sum(values) / len(values)
            spread = (sum((v - mean) ** 2 for v in values)
                      / (len(values) - 1)) ** 0.5
            rel = (" (%%%.2g)" % (100.0 * spread / mean)) if mean else ""
            parts.append("%s %.4g ± %.3g %s%s"
                         % (label, mean, spread, unit, rel))
        return "  ·  ".join(parts)
