"""
Purchase Order print: its own layout, apart from the sales documents.

Portrait A4. The letterhead and the order's identity at the top; Supplier and
Deliver To side by side; the order terms; for an import order every import,
shipping, banking and customs detail on the order; the items with HS code,
discount and tax; totals in the order's currency with the rupee equivalent;
remarks; prepared / approved with the signature and stamp; and a page footer.
Figures come from the stored order only.
"""

from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.common import currency as cur
from app.documents.pdf import LOGO_BOX, LOGO_FILE, SIGNATURE_FILE, CompanyLetterhead, _image, _qty, _safe, _text

GREEN = colors.HexColor("#1E6B3A")
PALE = colors.HexColor("#EAF4EC")
RED = colors.HexColor("#C0272D")
GRID = colors.HexColor("#B9C7BD")
INK = colors.HexColor("#1A1A1A")
MUTED = colors.HexColor("#5F6B63")


def _money(value, currency: str) -> str:
    return f"{cur.symbol(currency)} {Decimal(str(value or 0)):,.2f}"


def render_purchase_order(order: dict, lines: list[dict]) -> bytes:
    base = getSampleStyleSheet()["Normal"]
    st = {
        # Red, as the invoices' and quotations' titles (owner, 19-Oct-2026).
        "title": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=20, textColor=RED,
                                alignment=TA_RIGHT, leading=23),
        "badge": ParagraphStyle("b", parent=base, fontName="Helvetica-Bold", fontSize=9, textColor=colors.white,
                                alignment=TA_CENTER, leading=11),
        "addr": ParagraphStyle("a", parent=base, fontName="Helvetica", fontSize=8.5, textColor=INK, leading=11),
        "metaL": ParagraphStyle("ml", parent=base, fontName="Helvetica", fontSize=8.5, textColor=MUTED,
                                alignment=TA_RIGHT, leading=11),
        "metaV": ParagraphStyle("mv", parent=base, fontName="Helvetica-Bold", fontSize=9, textColor=INK, leading=11),
        "band": ParagraphStyle("bd", parent=base, fontName="Helvetica-Bold", fontSize=9, textColor=colors.white,
                               leading=11),
        "boxT": ParagraphStyle("bt", parent=base, fontName="Helvetica-Bold", fontSize=10, textColor=INK, leading=13),
        "box": ParagraphStyle("bx", parent=base, fontName="Helvetica", fontSize=8.5, textColor=INK, leading=11),
        "gl": ParagraphStyle("gl", parent=base, fontName="Helvetica", fontSize=7.5, textColor=MUTED, leading=9),
        "gv": ParagraphStyle("gv", parent=base, fontName="Helvetica-Bold", fontSize=8.5, textColor=INK, leading=10.5),
        "th": ParagraphStyle("th", parent=base, fontName="Helvetica-Bold", fontSize=8, textColor=colors.white,
                             alignment=TA_CENTER, leading=10),
        "cell": ParagraphStyle("c", parent=base, fontName="Helvetica", fontSize=8, textColor=INK, leading=10),
        "num": ParagraphStyle("n", parent=base, fontName="Helvetica", fontSize=8, textColor=INK, leading=10,
                              alignment=TA_RIGHT),
        "totL": ParagraphStyle("tl", parent=base, fontName="Helvetica", fontSize=9, textColor=INK, alignment=TA_RIGHT),
        "totV": ParagraphStyle("tv", parent=base, fontName="Helvetica", fontSize=9, textColor=INK, alignment=TA_RIGHT),
        "grand": ParagraphStyle("g", parent=base, fontName="Helvetica-Bold", fontSize=10.5, textColor=colors.white,
                                alignment=TA_RIGHT),
        "sign": ParagraphStyle("s", parent=base, fontName="Helvetica-Bold", fontSize=9, textColor=INK,
                               alignment=TA_CENTER, leading=12),
        "signS": ParagraphStyle("ss", parent=base, fontName="Helvetica", fontSize=8, textColor=MUTED,
                                alignment=TA_CENTER, leading=10),
    }
    lh = CompanyLetterhead()
    width = A4[0] - 28 * mm
    currency = order["currency"] or "PKR"
    is_import = order["purchase_type"] == "Import"

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=11 * mm,
                            bottomMargin=15 * mm, title=f"Purchase Order {order['doc_number']}", author=lh.name)
    story = []

    # ---- letterhead | title and identity
    # The logo carries the tagline; printed at the invoices' size (owner, 18-Oct-2026).
    logo = _image(LOGO_FILE, *LOGO_BOX)
    left = [logo] if logo is not None else [Paragraph(lh.name, st["boxT"])]
    left += [Spacer(1, 4), Paragraph(_safe(lh.address), st["addr"]),
             Paragraph(f"NTN# {_text(lh.ntn)} · {_text(lh.phone)}", st["addr"])]
    badge = Table([[Paragraph(("IMPORT" if is_import else "LOCAL") + " PURCHASE", st["badge"])]],
                  colWidths=[40 * mm], rowHeights=[6 * mm])
    badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), RED if is_import else GREEN),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    badge.hAlign = "RIGHT"
    ident = Table([[Paragraph(k, st["metaL"]), Paragraph(_text(v or "—"), st["metaV"])] for k, v in (
        ("PO No.", order["doc_number"]), ("PO Date", order["doc_date"]), ("Priority", order["priority"]),
        ("Status", order["status"]))], colWidths=[24 * mm, 36 * mm])
    ident.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    ident.hAlign = "RIGHT"
    right = [Paragraph("PURCHASE ORDER", st["title"]), Spacer(1, 4), badge, Spacer(1, 6), ident]
    top = Table([[left, right]], colWidths=[width * 0.56, width * 0.44])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [top, Spacer(1, 7)]

    # ---- supplier | deliver to
    def box(title, rows):
        cells = [[Paragraph(title, st["band"])]] + [[Paragraph(r, st["box"])] for r in rows if r]
        t = Table(cells, colWidths=[width / 2 - 3 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), GREEN), ("BOX", (0, 0), (-1, -1), 0.6, GRID),
                               ("BACKGROUND", (0, 1), (-1, -1), PALE), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
        return t
    s = order["supplier"]
    supplier = box("SUPPLIER", [f"<b>{_text(s['name'])}</b>", _text(s.get("address") or ""),
                                _text(s.get("country") or ""),
                                f"NTN# {_text(s['ntn'])}" if s.get("ntn") else None,
                                f"Phone: {_text(s['phone'])}" if s.get("phone") else None,
                                f"Email: {_text(s['email'])}" if s.get("email") else None])
    deliver = box("DELIVER TO", [f"<b>{_text(lh.name)}</b>", f"Warehouse: {_text(order['warehouse'] or '—')}",
                                 _safe(lh.address),
                                 f"Buyer: {_text(order['purchaser'])}" if order.get("purchaser") else None])
    pair = Table([[supplier, deliver]], colWidths=[width / 2, width / 2])
    pair.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [pair, Spacer(1, 6)]

    # ---- grids of labelled values
    def grid(title, items, per_row=4):
        items = list(items)
        cells, row = [], []
        for label, value in items:
            row.append([Paragraph(label, st["gl"]), Paragraph(_text(value) if value else "—", st["gv"])])
            if len(row) == per_row:
                cells.append(row)
                row = []
        if row:
            cells.append(row + [""] * (per_row - len(row)))
        head = Table([[Paragraph(title, st["band"])]], colWidths=[width])
        head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GREEN), ("TOPPADDING", (0, 0), (-1, -1), 2),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        body = Table(cells, colWidths=[width / per_row] * per_row)
        body.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, GRID), ("INNERGRID", (0, 0), (-1, -1), 0.4, GRID),
                                  ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
        return [head, body, Spacer(1, 6)]

    story += grid("ORDER DETAILS", order["details"])
    if is_import:
        story += grid("IMPORT, SHIPPING & CUSTOMS DETAILS", order["import_details"])

    # ---- items
    cols = [7 * mm, 25 * mm, 0, 16 * mm, 11 * mm, 12 * mm, 21 * mm, 12 * mm, 12 * mm, 22 * mm]
    cols[2] = width - sum(cols)
    head = ["#", "Item Code", "Description", "HS Code", "UOM", "Qty", "Unit Price", "Disc %", "Tax %", "Amount"]
    data = [[Paragraph(h, st["th"]) for h in head]]
    for n, l in enumerate(lines, start=1):
        qty = _qty(l["quantity"])
        if Decimal(str(l.get("free_quantity") or 0)):
            qty += f" + {_qty(l['free_quantity'])} free"
        data.append([Paragraph(str(n), st["num"]), Paragraph(_text(l.get("item_code") or ""), st["cell"]),
                     Paragraph(_text(l["description"]), st["cell"]), Paragraph(_text(l.get("hs_code") or ""), st["cell"]),
                     Paragraph(_text(l.get("uom") or ""), st["cell"]), Paragraph(qty, st["num"]),
                     Paragraph(_money(l["unit_price"], currency), st["num"]),
                     Paragraph(_qty(l.get("discount_percent") or 0), st["num"]),
                     Paragraph(_qty(l.get("tax_percent") or 0), st["num"]),
                     Paragraph(_money(l["net_amount"], currency), st["num"])])
    items = Table(data, colWidths=cols, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), GREEN), ("GRID", (0, 0), (-1, -1), 0.4, GRID),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    style += [("BACKGROUND", (0, r), (-1, r), PALE) for r in range(2, len(data), 2)]
    items.setStyle(TableStyle(style))
    story += [items, Spacer(1, 6)]

    # ---- totals, right-aligned
    t = order["totals"]
    rows = [("Value excluding tax", t["excluding_tax_value"]), ("Tax", t["sales_tax_value"]),
            ("Gross amount", t["gross_amount"]), ("Freight", t["freight_amount"]), ("Discount", t["discount_amount"])]
    tot = [[Paragraph(k, st["totL"]), Paragraph(_money(v, currency), st["totV"])] for k, v in rows]
    tot.append([Paragraph("NET PAYABLE", st["grand"]), Paragraph(_money(t["net_payable"], currency), st["grand"])])
    if currency != "PKR":
        tot.append([Paragraph(f"PKR equivalent @ {Decimal(str(order['exchange_rate'])):,.4f}", st["totL"]),
                    Paragraph(_money(t["net_payable_base"], "PKR"), st["totV"])])
    grand = len(rows)
    totals = Table(tot, colWidths=[50 * mm, 36 * mm])
    totals.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.6, GRID), ("BACKGROUND", (0, grand), (-1, grand), GREEN),
                                ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))

    # ---- signatures beside the totals, so the order closes on one page
    stamp = _image(SIGNATURE_FILE, 40 * mm, 22 * mm)
    line = Paragraph("____________________", st["sign"])
    signs = Table([
        [Spacer(1, 22 * mm), stamp if stamp is not None else Spacer(1, 22 * mm)],
        [line, line],
        [Paragraph(f"Prepared By<br/><font size=8>{_text(order['prepared_by'] or '')}</font>", st["sign"]),
         Paragraph(f"Approved By<br/><font size=8>{_text(order['approved_by'] or '')}</font>", st["sign"])],
    ], colWidths=[(width - 90 * mm) / 2] * 2)
    signs.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                               ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    bottom = Table([[signs, totals]], colWidths=[width - 88 * mm, 88 * mm])
    bottom.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [bottom, Spacer(1, 8)]

    if order.get("remarks"):
        story += grid("REMARKS", [("", order["remarks"])], per_row=1)
    accept = Table([[Paragraph("Supplier's acceptance (signature &amp; stamp): ________________________________"
                               "&nbsp;&nbsp;&nbsp;Date: ______________", st["signS"])]], colWidths=[width])
    story += [accept]
    def footer(canvas, total, n):
        w = A4[0]
        canvas.setStrokeColor(GREEN)
        canvas.setLineWidth(1)
        canvas.line(14 * mm, 10 * mm, w - 14 * mm, 10 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(14 * mm, 6 * mm, f"{lh.name.title()} | Purchase Order {order['doc_number']}")
        canvas.drawRightString(w - 14 * mm, 6 * mm, f"Page {n} of {total}")

    class Numbered(Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            for n, state in enumerate(self._pages, start=1):
                self.__dict__.update(state)
                footer(self, len(self._pages), n)
                super().showPage()
            super().save()

    doc.build(story, canvasmaker=Numbered)
    return buffer.getvalue()
