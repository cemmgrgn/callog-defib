"""Summary evaluation report — all energy levels in a single document.

The series report (`seriesreport`) evaluates n shocks at a single energy
setting: "what does the device deliver at 30 J". But a defibrillator's
calibration doesn't end at one point — it needs to be accurate across every
level from 2 J to 360 J. This module gathers those series into one document
and produces a **single decision** about the device.

The document is deliberately kept simple: no screenshots, overlay waveform
chart, or shock-by-shock tables here. Those already live in each series
report and are listed by number as source documents. The question here
isn't individual shocks but **the device's behavior across its whole
operating range**: how much each level deviates, whether the deviation
grows with energy, whether any level falls outside tolerance.

The decision rule is identical to the series report's
(`seriesreport.energy_verdict`): |x̄ − set value| + U ≤ tolerance. The
summary document doesn't introduce a new criterion of its own — **if even
one level fails, the document fails**, because the certificate states that
the device is usable at those levels, not that the levels average out.
"""

import hashlib
import json
import os
from datetime import datetime

from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.units import mm

from callog_common import audit, branding, certificate, db

from . import defib, seriesreport, shockreport

VERDICT_TR = certificate.VERDICT_TR

C_OK = colors.HexColor("#166534")
C_BAD = colors.HexColor("#B91C1C")
C_BAND = colors.HexColor("#DCFCE7")
C_AXIS = colors.HexColor("#666666")
C_GRID = colors.HexColor("#DDDDDD")
C_POINT = colors.HexColor("#185FA5")


def next_report_no(simulated=False):
    """The next summary report number — from its own series.

    Doesn't consume series or single-shock report numbers: the three
    document types are different things, and if their numbers mixed there'd
    be no way to answer "which one was …-0007".
    """
    prefix = "TOPLU-SOK-CAL-MED"
    if simulated:
        prefix = "SIM-" + prefix
    year = datetime.now().year
    like = "%s-%d-%%" % (prefix, year)
    row = db.query_one(
        "SELECT report_no FROM summary_reports WHERE report_no LIKE ?"
        " ORDER BY report_no DESC LIMIT 1", (like,))
    nxt = 1
    if row and row["report_no"]:
        try:
            nxt = int(row["report_no"].rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            nxt = 1
    return "%s-%d-%04d" % (prefix, year, nxt)


def collect(dut_id=None, series_ids=None):
    """Gathers the series to be covered and evaluates each one.

    If `series_ids` isn't given, every series measurement with a
    **non-deleted certificate** for the device is taken: what goes into the
    summary document is measurements that have an official document, not
    series left incomplete or rejected.

    Returns: (rows, dut, reference instrument). Rows are sorted by set
    energy.
    """
    sql = ("SELECT c.cert_no, c.issued_at, c.result AS cert_result,"
           "       c.approved_at, c.series_id"
           "  FROM certificates c"
           " WHERE c.series_id IS NOT NULL AND c.deleted_at IS NULL")
    params = []
    if series_ids:
        sql += " AND c.series_id IN (%s)" % ",".join("?" * len(series_ids))
        params.extend(series_ids)
    certs = db.query(sql, tuple(params))

    rows = []
    dut = None
    instrument = None
    for c in certs:
        caps = db.query(
            "SELECT * FROM waveform_captures WHERE series_id = ?"
            " ORDER BY series_index", (c["series_id"],))
        if not caps:
            continue
        head = caps[0]
        if dut_id is not None and head["dut_id"] != dut_id:
            continue
        if dut is None and head["dut_id"]:
            dut = db.query_one("SELECT * FROM duts WHERE id = ?",
                               (head["dut_id"],))
        if instrument is None and head["instrument_id"]:
            instrument = db.query_one(
                "SELECT * FROM instruments WHERE id = ?",
                (head["instrument_id"],))

        from callog_common import waveform as wave_mod
        # If there's no stored analysis, it's computed from the raw CSV —
        # same behavior as the series and single-shock reports. Without
        # this, a series whose analysis wasn't saved would silently drop
        # out of the summary document.
        analyses = []
        for cap in caps:
            stored = wave_mod.analysis_of(cap)
            if stored is None and os.path.isfile(cap["file_path"]):
                times, columns = wave_mod.read_csv(cap["file_path"])
                if times and columns:
                    stored = defib.analyze(
                        times, columns[list(columns.keys())[0]],
                        load_ohm=cap["load_ohm"] or 50.0)
            analyses.append(stored)
        nominal = head["nominal_energy_j"]
        result, detail = seriesreport.energy_verdict(analyses, nominal)
        stats = detail.get("stats")
        if stats is None:
            continue
        rows.append({
            "cert_no": c["cert_no"],
            "series_id": c["series_id"],
            "issued_at": c["issued_at"],
            "approved_at": c["approved_at"],
            "nominal": float(nominal) if nominal else None,
            "stats": stats,
            "tolerance": detail.get("tolerance"),
            "deviation": detail.get("deviation"),
            "result": result,
            "simulated": any(bool(r["is_simulated"]) for r in caps),
            "load_ohm": head["load_ohm"],
            "divider_ratio": head["divider_ratio"],
            "test_mode": head["test_mode"],
            "captured_at": head["captured_at"],
            "n_shocks": len(caps),
        })

    rows.sort(key=lambda r: (r["nominal"] is None, r["nominal"] or 0))
    return rows, dut, instrument


def overall_result(rows):
    """The document fails if even one level fails."""
    if not rows:
        return "info"
    results = [r["result"] for r in rows]
    if any(r == "fail" for r in results):
        return "fail"
    if all(r == "pass" for r in results):
        return "pass"
    return "info"


def deviation_chart(rows, width=165 * mm, height=68 * mm, font="Helvetica"):
    """Relative deviation (%) — against the set energy, with a tolerance band.

    This is deliberately the document's only chart: plotting absolute
    energy against set energy just gives a 45° line and tells the eye
    nothing. The **relative** form of the deviation shows at a glance which
    level the device struggles at, and whether the deviation grows with
    energy.

    The tolerance band is also drawn relative; at low energies the 3 J
    floor inflates the percentage, so the band widens there — that's the
    shape of IEC 60601-2-4's ±max(15%, 3 J) rule.
    """
    import math

    usable = [r for r in rows if r["nominal"] and r["deviation"] is not None]
    d = Drawing(width, height)
    if not usable:
        return d

    order = sorted(usable, key=lambda r: r["nominal"])
    left, right = 20 * mm, width - 6 * mm
    top, bottom = height - 9 * mm, 15 * mm
    plot_w, plot_h = right - left, top - bottom

    # X axis is **logarithmic**: levels run roughly geometrically from 2 J
    # to 360 J. On a linear axis, the 2-30 J range piled up on the left and
    # became unreadable, with labels overlapping.
    lx = [math.log10(r["nominal"]) for r in order]
    x_min, x_max = min(lx) - 0.08, max(lx) + 0.08

    # Y axis is scaled to **the data**: at low energies the tolerance's 3 J
    # floor pushes it up to 200%, and trying to fit the band squashed every
    # point onto the zero line. The scale is chosen from the deviations,
    # leaving enough room for the 15% ratio line to stay visible; any part
    # of the band beyond the scale is clamped to the top edge.
    devs = [100.0 * (r["deviation"] / r["nominal"]) for r in order]
    ratio_pct = 100.0 * defib.ENERGY_TOLERANCE_RATIO
    raw = max(max(abs(v) for v in devs) * 1.6, ratio_pct * 1.25, 5.0)
    for nice in (5, 10, 20, 25, 50, 100, 200, 500):
        if raw <= nice:
            raw = nice
            break
    y_lim = raw

    def px(v):
        return left + (math.log10(v) - x_min) / (x_max - x_min) * plot_w

    def py(v):
        v = max(-y_lim, min(y_lim, v))          # clamp out-of-scale to the edge
        return bottom + (v + y_lim) / (2.0 * y_lim) * plot_h

    # Grid + zero line
    for frac in (-1.0, -0.5, 0.0, 0.5, 1.0):
        v = y_lim * frac
        y = py(v)
        d.add(Line(left, y, right, y,
                   strokeColor=C_AXIS if v == 0 else C_GRID,
                   strokeWidth=0.7 if v == 0 else 0.35))
        d.add(String(left - 2, y - 2.4, "%+g%%" % v, fontName=font,
                     fontSize=6, fillColor=C_AXIS, textAnchor="end"))
    d.add(Line(left, bottom, left, top, strokeColor=C_AXIS, strokeWidth=0.7))

    # Tolerance band — envelope narrowing with energy (overflow is clipped)
    upper, lower = [], []
    for r in order:
        pct = 100.0 * (r["tolerance"] / r["nominal"])
        upper += [px(r["nominal"]), py(pct)]
        lower += [px(r["nominal"]), py(-pct)]
    if len(order) > 1:
        d.add(PolyLine(upper, strokeColor=C_OK, strokeWidth=0.9,
                       strokeDashArray=[3, 2]))
        d.add(PolyLine(lower, strokeColor=C_OK, strokeWidth=0.9,
                       strokeDashArray=[3, 2]))

    # Points + x labels (labels are skipped if they'd overlap)
    last_label = None
    for r, pct in zip(order, devs):
        x = px(r["nominal"])
        colour = C_POINT if r["result"] == "pass" else C_BAD
        d.add(Rect(x - 1.6, py(pct) - 1.6, 3.2, 3.2, fillColor=colour,
                   strokeColor=colour))
        if last_label is None or (x - last_label) > 7.0:
            d.add(String(x, bottom - 7.5, "%g" % r["nominal"], fontName=font,
                         fontSize=5.8, fillColor=C_AXIS, textAnchor="middle"))
            last_label = x

    d.add(String((left + right) / 2.0, 2.5, "Ayarlanan enerji (J) — log ölçek",
                 fontName=font, fontSize=6.5, fillColor=C_AXIS,
                 textAnchor="middle"))
    d.add(String(left, top + 3.5,
                 "Bağıl sapma (%) · kesikli: izin verilen tolerans "
                 "(düşük enerjide 3 J tabanı yüzünden ölçek dışına taşar)",
                 fontName=font, fontSize=6.5, fillColor=C_AXIS))
    return d


def build_pdf(dut_id=None, issued_by=None, series_ids=None, path=None,
              report_no=None):
    """Generates the summary evaluation report.

    Returns: (file path, report number, result)
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    from callog_common import pdffont

    rows, dut, instrument = collect(dut_id, series_ids)
    if not rows:
        raise ValueError("Toplu rapora girecek değerlendirilebilir seri yok.")

    result = overall_result(rows)
    simulated = any(r["simulated"] for r in rows)
    if report_no is None:
        report_no = next_report_no(simulated)

    font, font_bold, _ascii = pdffont.register()

    if path is None:
        directory = shockreport.report_dir()
        if not os.path.isdir(directory):
            os.makedirs(directory)
        path = os.path.join(directory, "%s.pdf" % report_no)

    base = getSampleStyleSheet()
    p_body = ParagraphStyle("govde", parent=base["BodyText"], fontName=font,
                            fontSize=8.5, leading=12)
    p_h1 = ParagraphStyle("baslik", parent=base["Title"], fontName=font_bold,
                          fontSize=15, leading=19, spaceAfter=2)
    p_h2 = ParagraphStyle("altbaslik", parent=base["Heading2"],
                          fontName=font_bold, fontSize=11.5, leading=15)
    p_h4 = ParagraphStyle("bolum", parent=base["Heading4"], fontName=font_bold,
                          fontSize=9.5, leading=13, spaceBefore=6, spaceAfter=2)

    doc = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=report_no, author=branding.org_name())

    def kv_table(kv, key_w=58 * mm):
        t = Table([[k, v] for k, v in kv], colWidths=(key_w, 160 * mm - key_w))
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#DDDDDD")),
        ]))
        return t

    def grid_table(data, widths, highlight=None):
        t = Table(data, colWidths=widths, repeatRows=1)
        style = [
            ("FONTNAME", (0, 0), (-1, 0), font_bold),
            ("FONTNAME", (0, 1), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F6")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#AAAAAA")),
            ("LINEBELOW", (0, 1), (-1, -2), 0.25, colors.HexColor("#DDDDDD")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             (colors.white, colors.HexColor("#FAFBFC"))),
        ]
        for i, ok in (highlight or []):
            style.append(("TEXTCOLOR", (-1, i), (-1, i), C_OK if ok else C_BAD))
            style.append(("FONTNAME", (-1, i), (-1, i), font_bold))
        t.setStyle(TableStyle(style))
        return t

    story = [
        Paragraph(branding.header_line(), p_h1),
        Paragraph("DEFİBRİLATÖR ENERJİ DOĞRULUĞU — TOPLU DEĞERLENDİRME RAPORU",
                  p_h2),
        Spacer(1, 4 * mm),
    ]

    if simulated:
        story += [
            Table([[Paragraph(
                "<b>SİMÜLASYON VERİSİ</b><br/>Bu belge simülasyon "
                "sürücüsüyle üretilmiş ölçümlere dayanır; resmî kalibrasyon "
                "belgesi değildir.", p_body)]],
                colWidths=[160 * mm],
                style=TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FCEBEB")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#A32D2D")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#A32D2D")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ])),
            Spacer(1, 4 * mm)]

    dates = sorted(r["captured_at"] for r in rows if r["captured_at"])
    story.append(Paragraph("Belge künyesi", p_h4))
    story.append(kv_table([
        ("Rapor no", report_no),
        ("Veriliş tarihi", db.utc_now()[:10]),
        ("Kapsanan kademe sayısı", "%d" % len(rows)),
        ("Toplam şok sayısı", "%d" % sum(r["n_shocks"] for r in rows)),
        ("Ölçüm tarih aralığı",
         "%s – %s" % (dates[0][:10], dates[-1][:10]) if dates else "—"),
        ("Enerji aralığı", "%g J – %g J"
         % (rows[0]["nominal"] or 0, rows[-1]["nominal"] or 0)),
    ]))

    if dut is not None:
        story.append(Paragraph("Test edilen cihaz", p_h4))
        story.append(kv_table([
            ("Şirket / müşteri", dut["company"]),
            ("Üretici firma", dut["manufacturer"]),
            ("Model", dut["model"]),
            ("Seri no", dut["serial_no"]),
            ("Cihaz tipi", dut["device_type"] or "—"),
        ]))

    loads = sorted({r["load_ohm"] for r in rows if r["load_ohm"]})
    dividers = sorted({r["divider_ratio"] for r in rows if r["divider_ratio"]})
    story.append(Paragraph("Ölçüm zinciri", p_h4))
    story.append(kv_table([
        ("Yük direnci", ", ".join("%g Ω" % v for v in loads) or "—"),
        ("Yüksek gerilim bölücü",
         ", ".join("1:%g" % v for v in dividers) or "—"),
    ]))

    if instrument is not None:
        story.append(Paragraph("Ölçümü yapan referans cihaz", p_h4))
        story.append(kv_table([
            ("Cihaz", "%s %s" % (instrument["brand"], instrument["model"])),
            ("Seri no", instrument["serial_no"]),
            ("Kalibrasyon sertifikası", instrument["cal_cert_no"] or "—"),
            ("Kalibrasyon geçerliliği", instrument["cal_due"] or "—"),
        ]))

    story.append(Paragraph("Yöntem ve karar kuralı", p_h4))
    story.append(Paragraph(
        "Her enerji kademesinde art arda alınan şokların yüke aktardığı "
        "enerji, gerilim kaydından E = ∫v²/R dt ile hesaplanmıştır. Kademe "
        "başına ortalama (x̄), örnek standart sapması (s) ve A tipi standart "
        "belirsizlikten türetilen genişletilmiş belirsizlik "
        "(U = 2·s/√n, k≈2, ≈%%95) verilmiştir.<br/><br/>"
        "<b>Karar kuralı:</b> ölçülen ortalamanın ayarlanan enerjiden sapması, "
        "ölçümün kendi belirsizliğiyle birlikte izin verilen toleransı "
        "aşmıyorsa kademe UYGUN'dur: |x̄ − ayarlanan| + U ≤ T. Tolerans "
        "IEC 60601-2-4'e göre ayarlanan değerin %%%d'i ya da %g J'den "
        "hangisi büyükse odur. <b>Bir kademe bile uygun değilse belge uygun "
        "değildir</b> — belge cihazın o kademelerde kullanılabilir olduğunu "
        "söyler, kademelerin ortalamasını değil."
        % (int(defib.ENERGY_TOLERANCE_RATIO * 100),
           defib.ENERGY_TOLERANCE_FLOOR_J), p_body))

    # --- main table --------------------------------------------------------
    head = ["Ayarlanan\n(J)", "n", "Ortalama\n(J)", "s\n(J)", "U (k=2)\n(J)",
            "Sapma\n(J)", "Sapma\n(%)", "Tolerans\n(J)", "Sonuç"]
    data = [head]
    highlight = []
    for i, r in enumerate(rows, start=1):
        st = r["stats"]
        nominal = r["nominal"]
        dev = r["deviation"]
        data.append([
            "%g" % nominal if nominal else "—",
            "%d" % st["n"],
            "%.4g" % st["mean"],
            "%.3g" % st["std"],
            "%.3g" % st["U"],
            "%+.3g" % dev if dev is not None else "—",
            "%+.2f" % (100.0 * dev / nominal) if (dev is not None and nominal)
            else "—",
            "%.3g" % r["tolerance"] if r["tolerance"] else "—",
            VERDICT_TR.get(r["result"], r["result"]),
        ])
        highlight.append((i, r["result"] == "pass"))

    story.append(Paragraph("Kademe kademe sonuçlar", p_h4))
    story.append(grid_table(
        data,
        [19 * mm, 8 * mm, 20 * mm, 17 * mm, 19 * mm, 18 * mm, 17 * mm,
         19 * mm, 23 * mm],
        highlight))

    story.append(Spacer(1, 5 * mm))
    story.append(KeepTogether([
        Paragraph("Aralık boyunca sapma", p_h4),
        deviation_chart(rows, font=font),
    ]))

    # --- overall result ------------------------------------------------------
    worst = max(
        (abs(100.0 * r["deviation"] / r["nominal"])
         for r in rows if r["deviation"] is not None and r["nominal"]),
        default=None)
    n_pass = sum(1 for r in rows if r["result"] == "pass")

    colour = C_OK if result == "pass" else (
        C_BAD if result == "fail" else colors.HexColor("#92400E"))
    summary_lines = [
        Paragraph("Genel değerlendirme", p_h4),
        Paragraph(
            "Cihaz <b>%g J – %g J</b> aralığında <b>%d kademede</b>, toplam "
            "<b>%d şok</b> ile değerlendirilmiştir. Kademelerin <b>%d/%d</b>'i "
            "izin verilen toleransın içindedir%s."
            % (rows[0]["nominal"] or 0, rows[-1]["nominal"] or 0, len(rows),
               sum(r["n_shocks"] for r in rows), n_pass, len(rows),
               "; en büyük bağıl sapma %%%.2f" % worst if worst is not None
               else ""), p_body),
        Spacer(1, 2 * mm),
        Table([[Paragraph(
            "<b>Sonuç: %s</b>" % VERDICT_TR.get(result, result),
            ParagraphStyle("sonuc", parent=p_body, fontName=font_bold,
                           fontSize=11, leading=15, textColor=colour))]],
            colWidths=[160 * mm],
            style=TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.8, colour),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ])),
    ]
    story.append(KeepTogether(summary_lines))

    story.append(Paragraph("Belirsizlik hakkında", p_h4))
    story.append(Paragraph(
        "Verilen genişletilmiş belirsizlik <b>yalnızca A tipi</b> bileşeni, "
        "yani şoktan şoka tekrarlanabilirliği içerir. Yük direncinin gerçek "
        "değeri, yüksek gerilim bölücünün oranı ve osiloskobun dikey "
        "doğruluğu bu bütçeye <b>dahil değildir</b>; bu katkılar dahil "
        "edildiğinde toplam belirsizlik büyür. Değerler yakalanan dalga "
        "biçiminden hesaplanmıştır, sertifikalı bir defibrilatör analizörü "
        "ölçümü değildir.", p_body))

    # --- source documents --------------------------------------------------
    src = [["Ayarlanan (J)", "Şok", "Seri raporu", "Ölçüm tarihi", "Sonuç"]]
    for r in rows:
        src.append([
            "%g" % r["nominal"] if r["nominal"] else "—",
            "%d" % r["n_shocks"],
            r["cert_no"],
            (r["captured_at"] or "")[:10],
            VERDICT_TR.get(r["result"], r["result"]),
        ])
    story.append(Paragraph("Kaynak seri raporları", p_h4))
    story.append(Paragraph(
        "Her kademenin ayrıntısı (bindirmeli dalga grafiği, şok şok tablo, "
        "cihaz ekran görüntüleri ve dosya özetleri) aşağıdaki belgelerde "
        "durur; bu rapor onların özetidir.", p_body))
    story.append(Spacer(1, 2 * mm))
    story.append(grid_table(
        src, [24 * mm, 14 * mm, 62 * mm, 30 * mm, 30 * mm]))

    story.append(Spacer(1, 10 * mm))
    sig = Table([["Ölçümü yapan", "Onaylayan"],
                 ["", ""], ["", ""]],
                colWidths=[80 * mm, 80 * mm], rowHeights=[6 * mm, 12 * mm, 6 * mm])
    sig.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LINEBELOW", (0, 1), (-1, 1), 0.4, colors.HexColor("#888888")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#555555")),
    ]))
    story.append(sig)

    doc.build(story)

    _register(report_no, dut_id if dut_id is not None
              else (dut["id"] if dut else None),
              [r["series_id"] for r in rows], result, issued_by, path)
    return path, report_no, result


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _register(report_no, dut_id, series_ids, result, issued_by, path):
    """Records the document in the register; updates it if regenerated with the same number."""
    existing = db.query_one(
        "SELECT id FROM summary_reports WHERE report_no = ?", (report_no,))
    digest = _sha256(path) if os.path.isfile(path) else None
    payload = json.dumps(series_ids, ensure_ascii=False)
    if existing:
        db.execute(
            "UPDATE summary_reports SET dut_id = ?, series_json = ?,"
            " result = ?, issued_at = ?, pdf_path = ?, pdf_sha256 = ?"
            " WHERE id = ?",
            (dut_id, payload, result, db.utc_now(), path, digest,
             existing["id"]))
        report_id = existing["id"]
    else:
        report_id = db.execute(
            "INSERT INTO summary_reports (report_no, dut_id, series_json,"
            " result, issued_at, issued_by, pdf_path, pdf_sha256)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (report_no, dut_id, payload, result, db.utc_now(), issued_by,
             path, digest))
    audit.log("summary.issue", user_id=issued_by, entity="summary_report",
              entity_id=report_id,
              detail={"report_no": report_no, "result": result,
                      "kademe": len(series_ids)})
    return report_id
