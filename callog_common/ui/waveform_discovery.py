"""waveform_discovery -- WaveformPage mixin, moved out of waveform_page.py to keep
that file to a manageable size.
"""

from .. import audit
from .. import db
from .. import drivers
from .. import waveform
from ..drivers import discovery
from ..qt import QtWidgets
from .waveform_common import ScanThread
from .waveform_common import _open_path
from .waveform_common import _row_value
import os


class _DiscoveryMixin:

    def _reload_instruments(self):
        self.instrument_combo.blockSignals(True)
        self.instrument_combo.clear()
        for row in db.query(
            "SELECT * FROM instruments WHERE is_active = 1 ORDER BY id"
        ):
            if not drivers.supports_waveform(row["driver"]):
                continue
            label = "%s %s — %s" % (row["brand"], row["model"], row["serial_no"])
            if drivers.is_simulated(row["driver"]):
                label = "[SİMÜLASYON] " + label
            self.instrument_combo.addItem(label, row["id"])
        self.instrument_combo.blockSignals(False)
        self._on_instrument_changed()

    def _reload_duts(self):
        previous = self.dut_combo.currentData()
        self.dut_combo.blockSignals(True)
        self.dut_combo.clear()
        self.dut_combo.addItem("(bağlama)", None)
        for r in db.query(
            "SELECT id, manufacturer, model, serial_no FROM duts"
            " ORDER BY COALESCE(model, ''), serial_no"
        ):
            self.dut_combo.addItem(
                "%s %s — %s" % (r["manufacturer"] or "", r["model"] or "",
                                r["serial_no"]), r["id"])
        if previous is not None:
            i = self.dut_combo.findData(previous)
            if i >= 0:
                self.dut_combo.setCurrentIndex(i)
        self.dut_combo.blockSignals(False)

    def _driver_for(self, inst):
        """Builds the driver; if it can't, shows why and returns None.

        Auto-scan can also fail when the address is empty; handled here in
        one place instead of separately at every call site.
        """
        try:
            return self._build_driver(inst)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Cihaza ulaşılamadı", str(exc))
            self.status_label.setText(str(exc))
            return None

    def _open_driver(self, inst):
        """Returns (driver, ownership). Reuses the open one if a capture is running.

        Ownership matters: closing the connection that's open during a
        capture leaves the device in limbo, and the next command fails
        with "device busy".
        """
        if self.driver is not None:
            self._sync_sim_energy(self.driver)
            return self.driver, False
        drv = self._driver_for(inst)
        if drv is None:
            return None, False
        try:
            drv.connect()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Bağlantı kurulamadı", str(exc))
            return None, False
        self._sync_sim_energy(drv)
        return drv, True

    def _sync_sim_energy(self, drv):
        """Reports the current energy and load to the simulation driver.

        It's also given when the driver is built, but the operator can
        still change the energy after connecting; without refreshing it
        before every use, the simulation would keep producing shocks with
        the value from the moment it connected. Real drivers don't have
        these fields — silently skipped.
        """
        if drv is None or not hasattr(drv, "nominal_energy_j"):
            return
        drv.nominal_energy_j = self._nominal_energy()
        drv.load_ohm = self._mode_chain().get("load_ohm")

    def _current_instrument(self):
        iid = self.instrument_combo.currentData()
        if iid is None:
            return None
        return db.query_one("SELECT * FROM instruments WHERE id = ?", (iid,))

    def _on_instrument_changed(self):
        inst = self._current_instrument()
        if inst is None:
            self.address_edit.setEnabled(False)
            self.scan_addr_btn.setEnabled(False)
            self.outdir_edit.setText("")
            return
        is_sim = drivers.is_simulated(inst["driver"])
        self.address_edit.setEnabled(not is_sim)
        self.scan_addr_btn.setEnabled(not is_sim)
        self.address_edit.setText("SIM" if is_sim else (inst["address"] or ""))
        self.outdir_edit.setText(waveform.default_dir(self.dut_combo.currentData()))
        self.reload()

    def _build_driver(self, inst):
        kwargs = {}
        if drivers.is_simulated(inst["driver"]):
            address = "SIM"
            # The simulation driver should produce a waveform matching the
            # selected test: seeing a sine wave in defib mode makes the
            # trial pointless.
            kwargs["waveform"] = ("defib" if self.current_mode().analyzer
                                  else "sine")
            # The shock should be generated based on the set energy:
            # with a fixed peak voltage, selecting 200 J would measure 2 J
            # and the pass/fail decision couldn't be tried out.
            kwargs["nominal_energy_j"] = self._nominal_energy()
            kwargs["load_ohm"] = self._mode_chain().get("load_ohm")
        else:
            address = self.address_edit.text().strip()
            if not address:
                matched = self._auto_detect_address_sync(inst)
                if matched is None:
                    raise RuntimeError(
                        "VISA adresi boş ve otomatik tarama cihaz bulamadı. "
                        "USB kablosunu takıp 'Otomatik bul' ile tekrar deneyin.")
                address = matched.address
                self.address_edit.setText(address)
                self._persist_address(inst, address, idn=matched.idn)
                self.status_label.setText(
                    "Otomatik VISA adresi yakalandı: %s" % address)
        return drivers.create(inst["driver"], address, **kwargs)

    def _test_connection(self):
        inst = self._current_instrument()
        if inst is None:
            return
        drv = self._build_driver(inst)
        try:
            idn = drv.connect()
            channels = drv.displayed_channels()
            QtWidgets.QMessageBox.information(
                self, "Bağlantı başarılı",
                "Cihaz yanıtı:\n\n%s\n\nEkranda açık kanallar: %s"
                % (idn, ", ".join(channels) or "yok"))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Bağlantı kurulamadı", str(exc))
        finally:
            try:
                drv.close()
            except Exception:
                pass

    def _find_matching_device(self, inst, found):
        # inst is a sqlite3.Row: it has NO .get() method.
        serial = _row_value(inst, "serial_no")
        if serial:
            for f in found:
                if f.serial_no and f.serial_no.strip() == serial.strip():
                    return f
        driver_name = _row_value(inst, "driver")
        for f in found:
            if f.driver and f.driver == driver_name:
                return f
        for f in found:
            if f.recognized and drivers.supports_waveform(f.driver):
                return f
        return None

    def _persist_address(self, inst, address, idn=None):
        """Writes the found address to inventory, so it's ready next time."""
        upper = address.upper()
        if upper.startswith("ASRL"):
            iface = "serial"
        elif upper.startswith("USB"):
            iface = "usb"
        elif upper.startswith("TCPIP"):
            iface = "lan"
        else:
            iface = "gpib"
        db.execute("UPDATE instruments SET address = ?, iface = ? WHERE id = ?",
                   (address, iface, inst["id"]))
        audit.log("instrument.address_update", user_id=self.state.user["id"],
                  entity="instrument", entity_id=inst["id"],
                  detail={"address": address, "idn": idn, "auto_scan": True})

    def _auto_detect_address_sync(self, inst):
        try:
            found = discovery.scan()
        except Exception:
            return None
        if not found:
            return None
        return self._find_matching_device(inst, found)

    def _auto_scan_if_needed(self):
        inst = self._current_instrument()
        if inst is None or drivers.is_simulated(inst["driver"]):
            return
        if self.address_edit.text().strip():
            return
        self._scan_address()

    def _scan_address(self):
        inst = self._current_instrument()
        if inst is None or drivers.is_simulated(inst["driver"]):
            return
        if self._scan_thread is not None and self._scan_thread.isRunning():
            return

        self.scan_addr_btn.setEnabled(False)
        self.status_label.setText("VISA osiloskopları taranıyor…")

        self._scan_thread = ScanThread(self)
        self._scan_thread.progress.connect(self.status_label.setText)
        self._scan_thread.done.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self, found):
        # The whole body is guarded: this is a Qt signal handler, and an
        # exception raised here would be swallowed silently, giving the
        # impression that "Auto-detect does nothing".
        try:
            self._apply_scan_result(found)
        except Exception as exc:
            self.status_label.setText("Tarama sonucu işlenemedi: %s" % exc)
            self.state.status("Otomatik bul başarısız: %s" % exc)
        finally:
            self._scan_thread = None
            self._update_buttons()

    def _apply_scan_result(self, found):
        inst = self._current_instrument()
        if inst is None:
            return

        if not found:
            self.status_label.setText(
                "VISA cihazı bulunamadı. USB kablosunu ve Keysight IO "
                "Libraries (VISA) kurulumunu kontrol edin.")
            return

        matched = self._find_matching_device(inst, found)
        if matched is None:
            self.status_label.setText(
                "Yanıt veren %d cihazın hiçbiri osiloskop değil: %s"
                % (len(found), "; ".join((f.idn or f.address) for f in found)))
            return

        self.address_edit.setText(matched.address)
        self._persist_address(inst, matched.address, idn=matched.idn)
        self.status_label.setText(
            "Otomatik VISA adresi yakalandı: %s  (%s)"
            % (matched.address, matched.idn or "—"))
        self.state.status("Otomatik VISA adresi: %s" % matched.address)

    def _choose_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Yakalama klasörü", self.outdir_edit.text() or os.getcwd())
        if path:
            self.outdir_edit.setText(path)

    def _open_dir(self):
        path = self.outdir_edit.text().strip()
        if not path:
            return
        if not os.path.isdir(path):
            os.makedirs(path)
        _open_path(path)
