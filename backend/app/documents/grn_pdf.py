"""
Goods Receipt Note, printed to the company's GRN template
(Jezseem_Traders_GRN_Template): landscape A4, the company band, the header
grid, ITEM-WISE RECEIPT DETAILS (one row per item), the RECEIPT SUMMARY,
the inspection / discrepancy / stock-entry / finance block, the three
signatures and the receiving note, with "Jezseem Traders | GRN Report" and the
page count at the foot. Figures come from the stored receipt only.
"""

from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.documents.pdf import _text

NAVY = colors.HexColor("#17375E")
LABEL = colors.HexColor("#DCE6F1")
ZEBRA = colors.HexColor("#F2F5F8")
GRID = colors.HexColor("#A6A6A6")
INK = colors.HexColor("#1A1A1A")
MIN_ROWS = 10


def _n(value) -> str:
    v = Decimal(str(value or 0))
    return f"{v:,.2f}"


def render_grn(grn: dict, lines: list[dict]) -> bytes:
    base = getSampleStyleSheet()["Normal"]
    st = {
        "band": ParagraphStyle("band", parent=base, fontName="Helvetica-Bold", fontSize=15, textColor=colors.white,
                               alignment=TA_CENTER, leading=18),
        "sub": ParagraphStyle("sub", parent=base, fontName="Helvetica-Bold", fontSize=10, textColor=NAVY,
                              alignment=TA_CENTER, leading=13),
        "label": ParagraphStyle("label", parent=base, fontName="Helvetica-Bold", fontSize=7.5, textColor=NAVY, leading=9),
        "value": ParagraphStyle("value", parent=base, fontName="Helvetica", fontSize=8, textColor=INK, leading=10),
        "th": ParagraphStyle("th", parent=base, fontName="Helvetica-Bold", fontSize=7.5, textColor=colors.white,
                             alignment=TA_CENTER, leading=9),
        "cell": ParagraphStyle("cell", parent=base, fontName="Helvetica", fontSize=7.5, textColor=INK, leading=9),
        "num": ParagraphStyle("num", parent=base, fontName="Helvetica", fontSize=7.5, textColor=INK, leading=9,
                              alignment=TA_CENTER),
        "sumlabel": ParagraphStyle("sumlabel", parent=base, fontName="Helvetica-Bold", fontSize=8,
                                   textColor=colors.white, alignment=TA_CENTER),
        "sumnum": ParagraphStyle("sumnum", parent=base, fontName="Helvetica-Bold", fontSize=7.5, textColor=NAVY,
                                 alignment=TA_CENTER),
        "sign": ParagraphStyle("sign", parent=base, fontName="Helvetica-Bold", fontSize=8.5, textColor=NAVY,
                               alignment=TA_CENTER),
        "note": ParagraphStyle("note", parent=base, fontName="Helvetica-Oblique", fontSize=7, textColor=INK),
    }
    page_w = landscape(A4)[0]
    width = page_w - 24 * mm

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=8 * mm, bottomMargin=12 * mm, title=f"GRN {grn['doc_number']}",
                            author="Jezseem Traders")
    story = []

    band = Table([[Paragraph("JEZSEEM TRADERS", st["band"])]], colWidths=[width], rowHeights=[9 * mm])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [band, Spacer(1, 4),
              Paragraph("GOODS RECEIPT NOTE (GRN) / GOODS RECEIVING REPORT", st["sub"]), Spacer(1, 8)]

    # ---- header grid: label | value | label | value
    pairs = [
        ("GRN No.", grn["doc_number"], "GRN Date", grn["doc_date"]),
        ("Supplier", grn["supplier"], "Supplier Invoice / Challan", grn["supplier_invoice"]),
        ("Purchase Order", grn["purchase_order"], "PO Date", grn["po_date"]),
        ("Delivery Note / Challan No.", grn["delivery_note"], "Delivery Date", grn["delivery_date"]),
        ("Received At / Warehouse", grn["received_at"], "Received By", grn["received_by"]),
        ("Vehicle / Transporter", grn["vehicle"], "Import / GD Ref. (if applicable)", grn["gd_reference"]),
    ]
    head = Table([[Paragraph(a, st["label"]), Paragraph(_text(b or ""), st["value"]),
                   Paragraph(c, st["label"]), Paragraph(_text(d or ""), st["value"])] for a, b, c, d in pairs],
                 colWidths=[48 * mm, width / 2 - 48 * mm, 52 * mm, width / 2 - 52 * mm])
    head.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LABEL), ("BACKGROUND", (2, 0), (2, -1), LABEL),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, GRID), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story += [head, Spacer(1, 7)]

    # ---- item-wise receipt details
    cols = [14 * mm, 30 * mm, 62 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm, 22 * mm, 23 * mm]
    cols.append(width - sum(cols))
    headers = ["Sr. No.", "Item Code / Part No.", "Item Description / Brand / Model", "UOM", "PO Qty",
               "Received Qty", "Accepted Qty", "Short / Excess Qty", "Condition", "Remarks"]
    title_row = [Paragraph("ITEM-WISE RECEIPT DETAILS", st["th"])] + [""] * (len(cols) - 1)
    data = [title_row, [Paragraph(h, st["th"]) for h in headers]]
    totals = [Decimal(0)] * 4
    for i, l in enumerate(lines, start=1):
        po, rec, acc = (Decimal(str(l.get(k) or 0)) for k in ("ordered_quantity", "received_quantity", "accepted_quantity"))
        # Short / Excess against what was due on this receipt (the whole order
        # on a first receipt); negative is a shortage, positive an excess.
        due = Decimal(str(l.get("due_quantity") if l.get("due_quantity") is not None else po))
        diff = rec - due
        for n, v in enumerate((po, rec, acc, diff)):
            totals[n] += v
        data.append([Paragraph(str(i), st["num"]), Paragraph(_text(l.get("item_code") or ""), st["cell"]),
                     Paragraph(_text(l.get("description") or ""), st["cell"]), Paragraph(_text(l.get("uom") or ""), st["num"]),
                     Paragraph(_n(po), st["num"]), Paragraph(_n(rec), st["num"]), Paragraph(_n(acc), st["num"]),
                     Paragraph(_n(diff), st["num"]), Paragraph(_text(l.get("condition") or ""), st["num"]),
                     Paragraph(_text(l.get("remarks") or ""), st["cell"])])
    # One row per item received; no blank rows (owner, 15-Oct-2026).
    data.append([Paragraph("RECEIPT SUMMARY", st["sumlabel"]), "", "", ""]
                + [Paragraph(_n(v), st["sumnum"]) for v in totals] + ["", ""])
    last = len(data) - 1
    table = Table(data, colWidths=cols, repeatRows=2)
    style = [
        ("SPAN", (0, 0), (-1, 0)), ("BACKGROUND", (0, 0), (-1, 1), NAVY),
        ("TOPPADDING", (0, 0), (-1, 1), 4), ("BOTTOMPADDING", (0, 0), (-1, 1), 4),
        ("GRID", (0, 1), (-1, last - 1), 0.5, GRID), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 2), (-1, last - 1), 3), ("BOTTOMPADDING", (0, 2), (-1, last - 1), 3),
        ("SPAN", (0, last), (3, last)), ("BACKGROUND", (0, last), (3, last), NAVY),
        ("BACKGROUND", (4, last), (-1, last), LABEL), ("LINEABOVE", (0, last), (-1, last), 1.2, NAVY),
        ("LINEBELOW", (0, last), (-1, last), 1.2, NAVY),
    ]
    for row in range(2, last):
        if row % 2 == 1:
            style.append(("BACKGROUND", (0, row), (-1, row), ZEBRA))
    table.setStyle(TableStyle(style))
    story += [table, Spacer(1, 7)]

    # ---- inspection / discrepancy / stock entry / finance
    block = [("Inspection / Verification Notes", grn["inspection_notes"]),
             ("Discrepancy / Damage Details", grn["discrepancy_notes"]),
             ("Stock Entry / ERP Reference No.", grn["stock_entry"]),
             ("Supplier Bill Forwarded to Finance?", grn["bill_to_finance"])]
    notes = Table([[Paragraph(a, st["label"]), Paragraph(_text(b or ""), st["value"])] for a, b in block],
                  colWidths=[cols[0] + cols[1] + cols[2] + cols[3], width - (cols[0] + cols[1] + cols[2] + cols[3])])
    notes.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), LABEL), ("GRID", (0, 0), (-1, -1), 0.5, GRID),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story += [notes, Spacer(1, 12)]

    sign = lambda label, name: Paragraph(  # noqa: E731
        f"{label} {('<u>' + _text(name) + '</u>') if name else '__________________'}", st["sign"])
    signs = Table([[sign("Prepared By:", grn["prepared_by"]), sign("Checked By:", grn["checked_by"]),
                    sign("Approved By:", grn["approved_by"])]], colWidths=[width / 3] * 3)
    story += [signs, Spacer(1, 10),
              Paragraph("Note: Record actual quantities received. Any shortage, excess, damage, or mismatch must be "
                        "documented before stock posting and supplier invoice processing.", st["note"])]

    doc.build(story, canvasmaker=_footer_canvas)
    return buffer.getvalue()


class _footer_canvas(Canvas):
    """'Jezseem Traders | GRN Report' and 'Page n of m' on every page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for n, state in enumerate(self._pages, start=1):
            self.__dict__.update(state)
            w, _h = landscape(A4)
            self.setFont("Helvetica", 8)
            self.setFillColor(INK)
            self.drawCentredString(w / 2, 7 * mm, "Jezseem Traders | GRN Report")
            self.drawRightString(w - 12 * mm, 7 * mm, f"Page {n} of {total}")
            super().showPage()
        super().save()
