"""
Calibration / Services prints, laid out on the company's own documents:

- the maintenance agreement (Maintenance Agreement TIGER HOSIERY MILLS), built
  from the contract's fields rather than typed out each time;
- the certificate of calibration (Auto-Cutter 01 Certification of Calibration).
"""

from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.calibration.models import BILLING_FREQUENCIES
from app.documents.import_po_pdf import _words
from app.documents.pdf import LOGO_FILE, SIGNATURE_FILE, CompanyLetterhead, _image, _text

RED = colors.HexColor("#E0312F")
INK = colors.HexColor("#1A1A1A")
GREY = colors.HexColor("#8C8C8C")
PINK = colors.HexColor("#F6DCDC")
LINK = colors.HexColor("#1F4FD1")
WEBSITE = "https://www.jezseemtraders.com/"
CONTACT = ["+92-345-88 66 222", "support@jezseemtraders.com", "47 Wadi-e-Sitara, Near Gutwala Toll Plaza",
           "Sheikhupura Road, Faisalabad, Pakistan", "www.jezseemtraders.com"]


def _styles():
    base = getSampleStyleSheet()["Normal"]
    s = lambda name, **kw: ParagraphStyle(name, parent=base, **{"textColor": INK, **kw})   # noqa: E731
    return {
        "body": s("body", fontName="Helvetica", fontSize=10.5, leading=15),
        "bodyj": s("bodyj", fontName="Helvetica", fontSize=10.5, leading=15, alignment=4),
        "bold": s("bold", fontName="Helvetica-Bold", fontSize=10.5, leading=15),
        "h": s("h", fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceBefore=8),
        "bullet": s("bullet", fontName="Helvetica", fontSize=10.5, leading=15, leftIndent=26, bulletIndent=14),
        "title": s("title", fontName="Helvetica-Bold", fontSize=15, leading=19, alignment=TA_CENTER, textColor=RED),
        "sub": s("sub", fontName="Helvetica", fontSize=10.5, leading=14, alignment=TA_CENTER),
        "right": s("right", fontName="Helvetica", fontSize=9.5, leading=12, alignment=TA_RIGHT),
        "addr": s("addr", fontName="Helvetica", fontSize=9.5, leading=12),
        "certTitle": s("ct", fontName="Helvetica-Bold", fontSize=25, leading=30, alignment=TA_CENTER, textColor=RED),
        "contact": s("contact", fontName="Helvetica", fontSize=10, leading=13.5, alignment=TA_RIGHT),
        "cell": s("cell", fontName="Helvetica-Bold", fontSize=10, leading=12.5),
        "cellc": s("cellc", fontName="Helvetica-Bold", fontSize=10, leading=12.5, alignment=TA_CENTER),
        "cellplain": s("cellplain", fontName="Helvetica", fontSize=10, leading=12.5),
        "small": s("small", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5),
        "note": s("note", fontName="Helvetica-Bold", fontSize=8, leading=11, alignment=TA_RIGHT),
    }


def _money(value) -> str:
    return f"{Decimal(str(value or 0)):,.0f}" if Decimal(str(value or 0)) == int(Decimal(str(value or 0))) \
        else f"{Decimal(str(value)):,.2f}"


# ------------------------------------------------------------------ agreement
#
# Laid out on the company's own agreement (Maintenance Agreement TIGER HOSIERY
# MILLS): its header banner and its brand strip at the foot are that document's
# own artwork, and the text sits where it puts it — Calibri 12, a red underlined
# Calibri title, numbered bold headings, bullets at 46pt with their text at
# 64pt — on a Letter page. Positions are measured off it, in points from the top.

AGR_PAGE = (612, 792)
AGR_HEADER = Path(__file__).parent / "assets" / "agreement_header.png"     # 0-70pt
AGR_FOOTER = Path(__file__).parent / "assets" / "agreement_footer.png"     # 727-792pt
AGR_LEFT, AGR_RIGHT = 28.4, 583.6
AGR_RED = colors.HexColor("#EB0000")
AGR_LINK = colors.HexColor("#0000FF")


def agreement_title(contract) -> str:
    frequency = {"HALF YEARLY": "Half Yearly"}.get(contract.billing_frequency, contract.billing_frequency.title())
    kind = {"CALIBRATION": "Calibration", "MAINTENANCE & CALIBRATION": "Maintenance & Calibration"}.get(
        contract.contract_type, "Maintenance")
    return f"{frequency} {kind} Agreement"


def render_agreement(contract, customer) -> bytes:
    regular, bold, _ = _cert_fonts()
    lh = CompanyLetterhead()
    base = getSampleStyleSheet()["Normal"]
    calibri = regular != "Helvetica"
    t = (lambda v: escape(str(v or ""))) if calibri else _text

    def style(name, font=regular, size=12, leading=14.65, **kw):
        return ParagraphStyle(name, parent=base, fontName=font, fontSize=size, leading=leading,
                              textColor=colors.black, **kw)

    st = {
        "body": style("body"), "just": style("just", alignment=4),
        "center": style("center", alignment=TA_CENTER),
        "head": style("head", font=bold, spaceBefore=16.5, spaceAfter=1.5),
        "bullet": style("bullet", leftIndent=36, bulletIndent=18, bulletFontName="Symbol",
                        bulletFontSize=10, spaceBefore=1.2),
        "name": style("name", font=bold, alignment=TA_CENTER),
        "head_tight": style("head_tight", font=bold, spaceBefore=0, spaceAfter=1.5),
        "closing": style("closing", leftIndent=131.6 - AGR_LEFT),
    }
    company = "JEZSEEM TRADERS"
    name = t(customer.name if customer else "")
    frequency = contract.billing_frequency.lower()
    kind = {"CALIBRATION": "calibration", "MAINTENANCE & CALIBRATION": "maintenance and calibration"}.get(
        contract.contract_type, "maintenance")
    place = f" at the {t(contract.division)}" if contract.division else ""

    def page(canvas, doc):
        """Header banner and brand strip on every page; the reference block and title on the first."""
        w, h = AGR_PAGE
        canvas.saveState()
        if AGR_HEADER.is_file():
            canvas.drawImage(str(AGR_HEADER), 0, h - 70, width=w, height=70)
        if AGR_FOOTER.is_file():
            canvas.drawImage(str(AGR_FOOTER), 0, 0, width=w, height=65)
        if doc.page == 1:
            canvas.setFillColor(AGR_LINK)
            canvas.setFont("Times-Roman", 12)
            canvas.drawRightString(592.7, h - 87.7, WEBSITE)
            canvas.setStrokeColor(AGR_LINK)
            canvas.setLineWidth(0.6)
            canvas.line(592.7 - canvas.stringWidth(WEBSITE, "Times-Roman", 12), h - 88.8, 592.7, h - 88.8)
            canvas.setFillColor(colors.black)
            canvas.setFont(regular, 11)
            canvas.drawString(456.4, h - 99.0, f"REF; {contract.reference or contract.contract_number}")
            title = agreement_title(contract)
            canvas.setFillColor(AGR_RED)
            canvas.setFont(bold, 16)
            canvas.drawCentredString(w / 2, h - 118.6, title)
            width = canvas.stringWidth(title, bold, 16)
            canvas.setStrokeColor(AGR_RED)
            canvas.setLineWidth(0.9)
            canvas.line(w / 2 - width / 2, h - 121.3, w / 2 + width / 2, h - 121.3)
            if contract.division:
                canvas.setFillColor(colors.black)
                canvas.setFont(regular, 12)
                canvas.drawCentredString(w / 2, h - 135.6, f"({contract.division})")
        canvas.restoreState()

    buffer = BytesIO()
    # The frame pads its content by 6pt on every side; the margins allow for it.
    doc = SimpleDocTemplate(buffer, pagesize=AGR_PAGE, leftMargin=AGR_LEFT - 6, rightMargin=AGR_PAGE[0] - AGR_RIGHT - 6,
                            topMargin=149.5, bottomMargin=64,
                            title=f"{agreement_title(contract)} {contract.contract_number}", author=company)
    story = [Paragraph(
        f"This Agreement is made between <b>{company}</b> and <b>{name}</b> for the {frequency} {kind} of the "
        f"equipment installed{place}.", st["body"])]

    section = 0

    def heading(text, gap=True):
        nonlocal section
        section += 1
        # The reference leaves no empty line above Service Coverage, straight after the equipment list.
        story.append(Paragraph(f'<font size="10">{section}. </font>{text}',
                               st["head"] if gap else st["head_tight"]))

    def bullet(text):
        story.append(Paragraph(text, st["bullet"], bulletText="•"))

    def month_year(day: date) -> str:
        return day.strftime("%B %Y") if day.day == 1 else f"{day.day} {day:%B %Y}"

    heading("Term")
    term = f"The Agreement shall be valid from {month_year(contract.start_date)}"
    if contract.end_date:
        term += f" to {contract.end_date.day} {contract.end_date:%B %Y}"
    story.append(Paragraph(term + ".", st["body"]))

    heading("Scope of Services")
    story.append(Paragraph(f"{company} will provide {kind} services during regular working hours for the "
                           f"following equipment installed{place}:", st["just"]))
    for line in contract.lines:
        quantity = f" ({line.quantity.normalize():f})" if line.quantity and line.quantity != 1 else ""
        bullet(f"{t(line.description)}{quantity}")

    heading("Service Coverage", gap=False)
    for point in [p.strip() for p in (contract.service_coverage or "").splitlines() if p.strip()]:
        bullet(t(point))
    if contract.response_hours:
        bullet(f"Any complaint or emergency call raised during working hours will be attended within "
               f"<b>{contract.response_hours} hours</b>, without additional charges.")
    if contract.spare_parts_by:
        who = name if contract.spare_parts_by.lower().startswith("customer") else company
        bullet(f"<b>{who}</b> will provide required spare parts and lubrication.")

    heading("Payment Terms")
    words = f"Rupees {_words(int(contract.charge_amount))}" if contract.currency == "PKR" \
        else f"{contract.currency} {_words(int(contract.charge_amount))}"
    symbol = "Rs." if contract.currency == "PKR" else contract.currency
    label = {"HALF YEARLY": "Half Yearly"}.get(contract.billing_frequency, contract.billing_frequency.title())
    charge = f"<b>{label} Charges: {symbol} {_money(contract.charge_amount)}/- ({words} Only)</b>"
    if contract.tax_applicable and contract.tax_percent:
        charge += f" plus sales tax @ {contract.tax_percent.normalize():f}%"
    blank = Spacer(1, 15.6)     # the empty lines the reference leaves between these blocks
    story.append(blank)
    bullet(charge)
    payable = f"The above {frequency} charges shall be payable to {company} account"
    story += [blank, Paragraph(payable + (" <b>without any tax deductions</b>," if contract.without_tax_deduction
                                          else "."), st["body"]), blank]
    indent = Table([[Paragraph(f"<b>Bank Details: Account Title:</b> {lh.bank_title}", st["body"])],
                    [Paragraph(f"<b>Account No.:</b> {lh.bank_account}, <b>Bank:</b> Meezan Bank (Eden Square Branch)",
                               st["body"])]], colWidths=[AGR_RIGHT - AGR_LEFT - 7.6], hAlign="RIGHT")
    indent.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story += [indent, blank,
              Paragraph(f"Payments shall be made <b>{frequency} basis</b> throughout the agreement period.", st["closing"])]

    extra = [p.strip() for p in (contract.additional_terms or "").splitlines() if p.strip()]
    if extra:
        heading("Other Terms")
        for point in extra:
            bullet(t(point))

    # ---- the stamp at 111pt from the left, and the two parties' names under it
    stamp = _image(SIGNATURE_FILE, 130, 70)
    flat = [("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]
    # Centred over the JEZSEEM TRADERS name (owner, 18-Oct-2026).
    stamp_row = Table([[stamp or Spacer(1, 70)]], colWidths=[223.2], hAlign="LEFT")
    stamp_row.setStyle(TableStyle(flat + [("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    names = Table([[Paragraph(company, st["name"]), "", Paragraph(name, st["name"])]],
                  colWidths=[223.2, 88.1, 200], hAlign="LEFT")
    names.setStyle(TableStyle(flat))
    # Just above the name it signs for, with the names where the reference has them.
    story.append(KeepTogether([Spacer(1, 46), stamp_row, Spacer(1, 14), names]))

    doc.build(story, onFirstPage=page, onLaterPages=page)
    return buffer.getvalue()


# ------------------------------------------------------------------ certificate
#
# Laid out on the company's own certificate (Auto-Cutter 01 Certification of
# Calibration): its artwork — logo, contact block, swirls, title, watermark and
# the brand strip at the foot — is that document's own background image, and
# the text sits where that document puts it, in Calibri, on a Letter page. The
# positions below are measured off it, in points.

CERT_PAGE = (612, 792)
CERT_BACKGROUND = Path(__file__).parent / "assets" / "certificate_background.jpg"
CERT_LEFT, CERT_RIGHT = 72, 542.6          # text margins
CERT_TABLE = 534.2 - 72                    # tables run 72 to 534
INSTRUMENT_COLS = [115.6, 115.6, 92.8, 138.2]      # rules at 72, 187.6, 303.2, 396, 534
CONDITION_COLS = [115.6, 115.6, 115.8, 115.0]      # rules at 72, 187.6, 303.2, 419, 534
TEST_COLS = [170.8, 90.0, 99.0, 102.2]             # rules at 72, 242.8, 332.8, 431.8, 534
ROW = 13.9
CERT_PINK = colors.HexColor("#F2DBDB")
TICKS = {"✓", "✔", "ok", "yes", "pass", "passed", "y", "√"}


def _cert_fonts() -> tuple[str, str, str | None]:
    """Calibri and Calibri Bold as on the reference, and a font with the tick;
    Helvetica where Calibri is not installed."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    registered = pdfmetrics.getRegisteredFontNames()
    fonts = Path(r"C:\Windows\Fonts")
    if "Calibri" not in registered and (fonts / "calibri.ttf").is_file() and (fonts / "calibrib.ttf").is_file():
        pdfmetrics.registerFont(TTFont("Calibri", str(fonts / "calibri.ttf")))
        pdfmetrics.registerFont(TTFont("Calibri-Bold", str(fonts / "calibrib.ttf")))
        # So <b> inside a paragraph switches to the bold face.
        pdfmetrics.registerFontFamily("Calibri", normal="Calibri", bold="Calibri-Bold",
                                      italic="Calibri", boldItalic="Calibri-Bold")
    if "SegoeSymbol" not in registered and (fonts / "seguisym.ttf").is_file():
        pdfmetrics.registerFont(TTFont("SegoeSymbol", str(fonts / "seguisym.ttf")))
    registered = pdfmetrics.getRegisteredFontNames()
    if "Calibri" in registered:
        return "Calibri", "Calibri-Bold", "SegoeSymbol" if "SegoeSymbol" in registered else None
    return "Helvetica", "Helvetica-Bold", None


def _ordinal(day: date | None) -> str:
    if day is None:
        return ""
    n = day.day
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f'{n}<super><font size="7">{suffix}</font></super> {day:%b %Y}'


class Tick(Flowable):
    """A drawn check mark, where no font with one is installed."""

    def wrap(self, available_width, available_height):
        self.box = available_width
        return available_width, 9

    def draw(self):
        c = self.canv
        x = self.box / 2 - 4
        c.setLineWidth(1.5)
        c.setStrokeColor(INK)
        path = c.beginPath()
        path.moveTo(x, 4.5)
        path.lineTo(x + 3, 1.5)
        path.lineTo(x + 8.5, 9)
        c.drawPath(path, stroke=1, fill=0)


def render_certificate(report, customer, machine, model) -> bytes:
    from reportlab.platypus import Image
    regular, bold, symbol = _cert_fonts()
    base = getSampleStyleSheet()["Normal"]

    def style(name, font=bold, size=11, leading=None, **kw):
        return ParagraphStyle(name, parent=base, fontName=font, fontSize=size, leading=leading or size * 1.22,
                              textColor=INK, **kw)

    st = {"b11": style("b11"), "b12": style("b12", size=12), "small": style("small", size=8, leading=9.75),
          "cell": style("cell", leading=11.5), "cellc": style("cellc", leading=11.5, alignment=TA_CENTER),
          "plain": style("plain", font=regular, leading=11.5),
          "right": style("right", alignment=TA_RIGHT), "note": style("note", alignment=TA_RIGHT)}

    def text(value) -> str:
        return _text(value) if regular == "Helvetica" else escape(str(value or ""))

    def reading(value):
        value = (value or "").strip()
        if value.lower() in TICKS:
            return Paragraph(f'<font name="{symbol}">✔</font>', st["cellc"]) if symbol else Tick()
        return Paragraph(text(value), st["cellc"])

    def page(canvas, doc):
        canvas.saveState()
        if CERT_BACKGROUND.is_file():
            canvas.drawImage(str(CERT_BACKGROUND), 0, 0, width=CERT_PAGE[0], height=CERT_PAGE[1])
        canvas.restoreState()

    def rule_under(paragraph, size=12):
        """A heading with the rule the reference draws under it, across the text width."""
        t = Table([[paragraph]], colWidths=[CERT_RIGHT + 0.4 - CERT_LEFT + 1])
        t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1, INK), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
        t.hAlign = "LEFT"
        return t

    def grid(rows, widths, header=False, values=False):
        t = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
        commands = [("GRID", (0, 0), (-1, -1), 0.5, INK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5.7), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 0.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8)]
        if header:
            commands.append(("BACKGROUND", (0, 0), (-1, 0), CERT_PINK))
        if values:
            # The smaller values sit on the same line as their labels.
            commands.append(("VALIGN", (0, 0), (-1, -1), "BOTTOM"))
        t.setStyle(TableStyle(commands))
        return t

    blank = lambda size=11: Spacer(1, size * 1.22)   # noqa: E731 — an empty line, as the reference spaces its blocks

    buffer = BytesIO()
    # The frame pads its content by 6pt on every side; the margins allow for it.
    doc = SimpleDocTemplate(buffer, pagesize=CERT_PAGE, leftMargin=CERT_LEFT - 6,
                            rightMargin=CERT_PAGE[0] - CERT_RIGHT - 7, topMargin=156, bottomMargin=144,
                            title=f"Certificate of Calibration {report.certificate_number}", author="JEZSEEM TRADERS")
    story = [Paragraph(f"Certificate No: {text(report.certificate_number)}", st["right"])]
    for label, value in (("Issued by", "JEZSEEM TRADERS"), ("Date of Issue", _ordinal(report.issue_date)),
                         ("Date of Expiry", _ordinal(report.expiry_date)),
                         ("Next Calibration Date", _ordinal(report.next_calibration_date))):
        if value:
            story.append(Paragraph(f"{label}: {value}", st["b11"]))

    story += [blank(), Paragraph("Customer:", st["b11"]),
              rule_under(Paragraph(f"{text(customer.name if customer else '')},", st["b12"]))]
    address = (customer.address or "") if customer else ""
    for line in [p.strip() for p in address.splitlines() if p.strip()]:
        story.append(Paragraph(text(line), st["b11"]))

    machine_id = (machine.machine_code if machine and machine.machine_code else
                  (model.machine_category if model else ""))
    # Labels as on the reference; the values a size smaller (owner, 18-Oct-2026).
    value_style = style("value", size=9.5, leading=10.5)
    cells = lambda rows: [[Paragraph(text(c), value_style if i % 2 else st["cell"]) for i, c in enumerate(r)]   # noqa: E731
                          for r in rows]
    story += [blank(), blank(12), Paragraph("Instrument:", st["b12"]), grid(cells([
        ["Machine ID:", machine_id, "Description:", model.description if model else ""],
        ["Manufacturer:", model.vendor_name if model else "", "Model Number:", model.model_number if model else ""],
        ["Serial Number:", machine.serial_number if machine else "", "Origin:", model.origin if model else ""],
    ]), INSTRUMENT_COLS, values=True)]
    story += [blank(12), Paragraph("Environmental Condition:", st["b12"]), grid(cells([
        ["Temperature:", report.temperature or "", "Main Voltage:", report.main_voltage or ""],
        ["Relative Humidity:", report.relative_humidity or "", "Main Frequency:", report.main_frequency or ""],
        ["Noise Level:", report.noise_level or "", "", ""],
    ]), CONDITION_COLS, values=True)]

    story += [blank(12), rule_under(Paragraph("Comments:", st["b12"]))]
    for line in [p.strip() for p in (report.comments or "").splitlines() if p.strip()]:
        story.append(Paragraph(text(line), st["small"]))

    rows = [[Paragraph("Test Title", st["cell"])] + [Paragraph(h, st["cellc"])
                                                     for h in ("Initial Reading", "Observed", "Uncertainties")]]
    for result in report.results:
        title = result.test_title + (f" ({result.unit})" if result.unit else "")
        rows.append([Paragraph(text(title), st["plain"]), reading(result.initial_reading),
                     reading(result.observed), Paragraph(text(result.uncertainty or ""), st["cellc"])])
    story += [blank(), grid(rows, TEST_COLS, header=True)]

    note = report.note or {
        "PASS": "CALIBRATION PASSED, INSTRUMENT IS CERTIFIED FOR OPERATION.",
        "FAIL": "CALIBRATION FAILED, INSTRUMENT IS NOT CERTIFIED FOR OPERATION.",
    }.get(report.overall_result)
    if note:
        story.append(Paragraph(f'Note: <font size="9">{text(note).upper()}</font>', st["note"]))

    doc.build(story, onFirstPage=page, onLaterPages=page)
    return buffer.getvalue()
