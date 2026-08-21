"""waveform_setup -- WaveformPage mixin, moved out of waveform_page.py to keep
that file to a manageable size.
"""

from callog_common import testmodes
from callog_common import theme
from callog_common.qt import QtWidgets
from callog_common.ui.waveform_common import _close_quietly
from callog_common.ui.waveform_common import _estimate_vdiv_for_energy
from callog_common.ui.waveform_common import _si
from callog_common.ui.waveform_common import _volts


class _SetupMixin:

    def _on_mode_changed(self):
        mode = self.current_mode()
        self.mode_hint.setText(mode.description)

        is_test = mode.key != testmodes.FREE
        self.chain_box.setVisible(is_test)
        self.analysis_box.setVisible(bool(mode.analyzer))
        self.analysis_table.setRowCount(0)
        self.analysis_note.setText("")

        # Mode defaults are written to the fields; the operator can
        # overwrite them, and the values actually used are recorded.
        setup, capture, chain = mode.setup, mode.capture, mode.chain
        if setup.get("volts_per_div"):
            self.vdiv_spin.setValue(setup["volts_per_div"])
        if setup.get("time_per_div"):
            self.tdiv_spin.setValue(setup["time_per_div"])
        if setup.get("trigger_level") is not None:
            self.trig_spin.setValue(setup["trigger_level"])
        if setup.get("trigger_slope"):
            i = self.slope_combo.findData(setup["trigger_slope"])
            if i >= 0:
                self.slope_combo.setCurrentIndex(i)
        if chain.get("divider_ratio"):
            self.divider_spin.setValue(chain["divider_ratio"])
        if chain.get("load_ohm"):
            self.load_spin.setValue(chain["load_ohm"])
        if capture.get("points"):
            self.points_spin.setValue(capture["points"])
        if "count" in capture:
            self.count_spin.setValue(capture["count"])
        if "timeout_s" in capture:
            self.timeout_spin.setValue(capture["timeout_s"])

        # A defibrillator shock is a single-shot event: reading two channels
        # extends the transfer, and the second channel is usually just a
        # sync signal.
        if is_test:
            self.auto_chan_chk.setChecked(False)
            self.ch1_chk.setChecked(True)
            self.ch2_chk.setChecked(False)

        self._update_span_hint()
        if mode.warning:
            self.status_label.setText(mode.warning.split("\n")[0])

    def _mode_chain(self):
        return {"divider_ratio": self.divider_spin.value(),
                "load_ohm": self.load_spin.value()}

    def _nominal_energy(self):
        """The set energy (J); None if not entered.

        0 means "not entered", not "zero joules" (the field's special text
        says so too): there's no such thing as a 0 J defibrillator setting,
        but if 0 were recorded, the pass/fail calculation would divide by
        the nominal and produce a meaningless result.
        """
        value = self.nominal_spin.value()
        return value if value > 0 else None

    def _on_energy_changed(self, _value=None):
        if getattr(self, "auto_apply_chk", None) is not None \
                and self.auto_apply_chk.isChecked():
            self._apply_energy_scale()

    def _on_auto_apply_toggled(self, checked):
        # Applied as soon as it's checked: if the energy is already
        # entered, the user shouldn't have to click the box and then wait.
        if checked:
            self._apply_energy_scale()

    def _apply_energy_scale(self):
        """Updates the vertical scale (V/div) based on the set energy.

        Only writes a starting estimate — the clipping warning and 'Apply
        scales to device' both stay active, and the operator reviews the
        screen before capture. Leaves it alone if energy isn't entered
        (0 = 'not entered').
        """
        energy = self._nominal_energy()
        if energy is None:
            return
        load = self.load_spin.value() if hasattr(self, "load_spin") else 50.0
        vdiv = _estimate_vdiv_for_energy(energy, load)
        if vdiv:
            self.vdiv_spin.setValue(vdiv)

    def _mode_setup(self):
        return {
            "channel": "CHANnel1",
            "volts_per_div": self.vdiv_spin.value(),
            "time_per_div": self.tdiv_spin.value(),
            "time_position": self.delay_spin.value(),
            "trigger_level": self.trig_spin.value(),
            "trigger_slope": self.slope_combo.currentData(),
            "trigger_source": "CHANnel1",
            "coupling": self.current_mode().setup.get("coupling"),
            "probe_ratio": self.divider_spin.value(),
        }

    def _update_span_hint(self):
        """Writes the screen range and whether the trigger threshold is reachable."""
        if not hasattr(self, "span_hint"):
            return
        span = testmodes.screen_span(self.vdiv_spin.value())
        text = ("Ekran aralığı: ±%s · prob 1:%g olarak cihaza bildirilir"
                % (_volts(span), self.divider_spin.value()))
        warning = testmodes.trigger_warning(self.trig_spin.value(),
                                            self.vdiv_spin.value())
        if warning:
            text += "<br><span style='color:%s'>⚠ %s</span>" % (
                theme.colors()["bad"], warning)
        self.span_hint.setText(text)

    def _apply_setup(self):
        """Writes the scale and trigger values to the device."""
        inst = self._current_instrument()
        if inst is None:
            return
        drv, owned = self._open_driver(inst)
        if drv is None:
            return
        try:
            # AUTO sweep is deliberate: even if no trigger arrives while
            # applying settings, the device keeps sweeping and the signal
            # stays on screen. With NORMal, the screen freezes, the
            # operator loses the signal, and can't get it back without
            # pressing Auto Scale on the front panel.
            # Switches to NORMal when capture starts (see _start).
            drv.apply_setup(trigger_sweep="AUTO", **self._mode_setup())
            drv.run()
            applied = drv.read_setup("CHANnel1")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Ayar uygulanamadı", str(exc))
            return
        finally:
            if owned:
                _close_quietly(drv)
        self.status_label.setText(
            "Cihaz ayarlandı: %s/bölme · %s/bölme · tetikleme %.4g V · "
            "prob 1:%g — cihaz taramada, sinyal ekranda kalır."
            % (_volts(applied.get("volts_per_div") or self.vdiv_spin.value()),
               _si(applied.get("time_per_div") or self.tdiv_spin.value(), "s"),
               applied.get("trigger_level") if applied.get("trigger_level") is not None
               else self.trig_spin.value(),
               applied.get("probe_ratio") or self.divider_spin.value()))

    def _autoscale(self):
        """Runs the device's own Auto Scale and writes the resulting scale to the fields."""
        inst = self._current_instrument()
        if inst is None:
            return
        drv, owned = self._open_driver(inst)
        if drv is None:
            return
        try:
            # Probe ratio is reported first: Auto Scale picks its scale
            # based on the probe ratio; if it isn't reported, it scales to
            # the divided voltage and the result written to the fields
            # ends up 1000x too small.
            try:
                drv.apply_setup(channel="CHANnel1",
                                probe_ratio=self.divider_spin.value(),
                                trigger_sweep="AUTO")
            except Exception:
                pass
            applied = drv.autoscale("CHANnel1")
            drv.run()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Otomatik ölçekleme yapılamadı", str(exc))
            return
        finally:
            if owned:
                _close_quietly(drv)

        if applied.get("volts_per_div"):
            self.vdiv_spin.setValue(float(applied["volts_per_div"]))
        if applied.get("time_per_div"):
            self.tdiv_spin.setValue(float(applied["time_per_div"]))
        self._update_span_hint()
        self.status_label.setText(
            "Otomatik ölçekleme bitti: %s/bölme · %s/bölme. Değerler "
            "alanlara yazıldı; yakalamadan önce gözden geçirin."
            % (_volts(applied.get("volts_per_div")),
               _si(applied.get("time_per_div"), "s")))

    def _selected_channels(self):
        chans = []
        if self.ch1_chk.isChecked():
            chans.append("CHANnel1")
        if self.ch2_chk.isChecked():
            chans.append("CHANnel2")
        return chans

    def _missing_before_start(self):
        """Three commonly forgotten fields — see `_start`.

        A series with an empty `dut_id` doesn't drop out of the approval
        queue invisibly (see `certificate.pending`), but it stays
        unattached to any device and can't be found in the equipment
        register. If energy/measurement count is empty, no pass/fail
        decision or series grouping can be made at all.
        """
        missing = []
        if self.dut_combo.currentData() is None:
            missing.append("Kalibre edilen cihaz")
        if self.count_spin.value() == 0:
            missing.append("Ölçüm sayısı (seri)")
        if self.nominal_spin.value() <= 0.0:
            missing.append("Ayarlanan enerji")
        return missing

    def _confirm_chain(self, mode):
        """Shows the high-voltage warning and asks for confirmation.

        Once when capture starts, not on every capture: if the wiring is
        wrong, both the device and the operator are at risk on the very
        first shock.
        """
        text = "%s\n\nBölücü oranı 1:%g · Yük %g Ω\n\nBağlantı doğru mu?" % (
            mode.warning, self.divider_spin.value(), self.load_spin.value())
        answer = QtWidgets.QMessageBox.warning(
            self, "Yüksek gerilim — bağlantıyı doğrulayın", text,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel)
        return answer == QtWidgets.QMessageBox.Yes
