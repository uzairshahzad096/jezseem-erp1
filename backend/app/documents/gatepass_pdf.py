"""
Gate pass print format.

Separate from app/documents/pdf.py because a gate pass is not an invoice: it
carries no money at all. What matters at the gate is what is leaving, how
much of it, in whose vehicle, and two signatures — so it gets its own layout
rather than a priced one with the columns switched off.

Laid out from the supplied OUTWARD GATEPASS: title centred at the top, the
letterhead under it on the left with the date and GP number opposite, a boxed
party/vehicle block, the goods table, and the signature lines at the foot.
"""

from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.documents.pdf import (
    GREEN, INK, LINE, RED, CompanyLetterhead, LOGO_FILE, _image, _qty, _text,
)

TITLES = {"outward": "OUTWARD GATEPASS", "inward": "INWARD GATEPASS"}

# Everything on the pass prints black. Only the document title is coloured,
# so the sheet stays legible on the mono printer at the gate.
GOODS_BLUE = INK
MAROON = INK


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Normal"], fontName="Helvetica-Bold",
                                fontSize=15, textColor=RED, alignment=TA_CENTER, leading=18),
        # "JEZSEEM" heavy and dark, "TRADERS" lighter beside it — the gate
        # pass sets the wordmark in type rather than using the logo artwork.
        "company": ParagraphStyle("c", parent=base["Normal"], fontName="Helvetica",
                                  fontSize=16, textColor=INK, leading=18),
        "tagline": ParagraphStyle("tg", parent=base["Normal"],
                                  fontName="Helvetica-BoldOblique", fontSize=7,
                                  textColor=GREEN, leading=9),
        "addr": ParagraphStyle("a", parent=base["Normal"], fontName="Helvetica",
                               fontSize=7, textColor=INK, leading=9),
        "meta": ParagraphStyle("m", parent=base["Normal"], fontName="Helvetica-Bold",
                               fontSize=8, textColor=INK, alignment=TA_RIGHT, leading=11),
        "label": ParagraphStyle("l", parent=base["Normal"], fontName="Helvetica-Bold",
                                fontSize=7.5, textColor=INK, leading=10),
        "value": ParagraphStyle("v", parent=base["Normal"], fontName="Helvetica",
                                fontSize=7.5, textColor=INK, leading=10),
        # Customer and address are picked out in dark red on the reference.
        "party": ParagraphStyle("pt", parent=base["Normal"], fontName="Helvetica",
                                fontSize=7.5, textColor=MAROON, leading=10),
        "vehicle": ParagraphStyle("vh", parent=base["Normal"], fontName="Helvetica",
                                  fontSize=7.5, textColor=INK, leading=10),
        "status": ParagraphStyle("st", parent=base["Normal"], fontName="Helvetica-Bold",
                                 fontSize=7.5, textColor=INK, leading=10),
        "th": ParagraphStyle("th", parent=base["Normal"], fontName="Helvetica-Bold",
                             fontSize=8, textColor=INK, alignment=TA_CENTER),
        "goods": ParagraphStyle("g", parent=base["Normal"], fontName="Helvetica",
                                fontSize=7.5, textColor=GOODS_BLUE, leading=10),
        "num": ParagraphStyle("n", parent=base["Normal"], fontName="Helvetica",
                              fontSize=8, textColor=INK, alignment=TA_CENTER, leading=10),
        # UOM is printed in the same blue as the goods description.
        "uomCell": ParagraphStyle("u", parent=base["Normal"], fontName="Helvetica",
                                  fontSize=7.5, textColor=GOODS_BLUE,
                                  alignment=TA_CENTER, leading=10),
        "totalLabel": ParagraphStyle("tl", parent=base["Normal"], fontName="Helvetica-Bold",
                                     fontSize=8, textColor=INK, alignment=TA_RIGHT),
        "sign": ParagraphStyle("s", parent=base["Normal"], fontName="Helvetica-Bold",
                               fontSize=8, textColor=INK, alignment=TA_CENTER),
    }


def _field(st, label: str, value, style: str = "value"):
    """One label/value pair inside the party block."""
    return [
        Paragraph(_text(label), st["label"]),
        Paragraph(_text(value) if value else "", st[style]),
    ]


def render_gate_pass(
    *,
    pass_type: str,
    header: dict,
    party: dict,
    lines: list[dict],
    letterhead: CompanyLetterhead | None = None,
) -> bytes:
    lh = letterhead or CompanyLetterhead()
    st = _styles()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
        title=f"{TITLES.get(pass_type, 'GATE PASS')} {header.get('doc_number', '')}".strip(),
        author=lh.name,
    )
    story = [
        Paragraph(TITLES.get(pass_type, "GATE PASS"), st["title"]),
        Spacer(1, 10),
    ]

    # ---------- letterhead, with the date and number opposite ----------
    # The same artwork the quotations and invoices use. It already carries the
    # tagline, so when it is present the typed wordmark and tagline are not
    # repeated underneath it.
    # A little smaller than on an invoice (88 x 22): the gate pass header is tighter.
    logo = _image(LOGO_FILE, max_width=74 * mm, max_height=18.5 * mm)
    if logo is not None:
        logo.hAlign = "LEFT"
        left = [logo, Spacer(1, 4)]
    else:
        wordmark, _, suffix = lh.name.partition(" ")
        left = [
            Paragraph(
                f'<b>{_text(wordmark)}</b> '
                f'<font size="10" color="#7A7A7A">{_text(suffix)}</font>',
                st["company"]),
            Spacer(1, 3),
            Paragraph(lh.tagline, st["tagline"]),
            Spacer(1, 1),
        ]
    left.append(Paragraph(f"{_text(lh.short_address)} | {_text(lh.phone)}", st["addr"]))

    right = [
        Paragraph(f"Date: {_text(header.get('doc_date', ''))}", st["meta"]),
        Paragraph(f"GP #: {_text(header.get('doc_number', ''))}", st["meta"]),
    ]

    head = Table([[left, right]], colWidths=[118 * mm, 64 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(head)
    story.append(Spacer(1, 6))

    # ---------- party / vehicle block ----------
    info = Table(
        [
            _field(st, "Customer:", party.get("name"), "party") +
            _field(st, "Vehicle No:", header.get("vehicle_number"), "vehicle"),
            _field(st, "Address:", party.get("address"), "party") +
            _field(st, "Driver:", header.get("driver")),
            _field(st, "Type:", header.get("issue_type")) +
            _field(st, "Status:", header.get("status"), "status"),
            _field(st, "Remarks:", header.get("remarks")) + ["", ""],
        ],
        colWidths=[20 * mm, 92 * mm, 20 * mm, 50 * mm],
    )
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        # All four sides are drawn by this table rather than the rule above
        # being a separate flowable: two flowables cannot be made to meet
        # exactly, which left the corners open.
        ("LINEABOVE", (0, 0), (-1, 0), 1.1, INK),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
        ("LINEBELOW", (0, -1), (-1, -1), 1.1, INK),
        ("LINEBEFORE", (0, 0), (0, -1), 0.4, LINE),
        ("LINEAFTER", (-1, 0), (-1, -1), 0.4, LINE),
    ]))
    story.append(info)
    story.append(Spacer(1, 12))

    # ---------- goods ----------
    widths = [12 * mm, 116 * mm, 22 * mm, 32 * mm]
    data = [[Paragraph(h, st["th"]) for h in
             ["Sr.", "Description of Goods", "UOM", "Qty"]]]

    total = Decimal("0")
    for index, line in enumerate(lines, start=1):
        quantity = Decimal(str(line.get("quantity") or 0))
        total += quantity
        data.append([
            Paragraph(str(index), st["num"]),
            Paragraph(_text(line.get("description", "")), st["goods"]),
            Paragraph(_text(line.get("uom") or ""), st["uomCell"]),
            Paragraph(_qty(quantity), st["num"]),
        ])

    # The label goes in the first cell: a span only draws its anchor, so a
    # label in the middle cell would silently vanish.
    data.append([
        Paragraph("Total Quantity:", st["totalLabel"]), "", "",
        Paragraph(_qty(total), ParagraphStyle(
            "tq", parent=st["num"], fontName="Helvetica-Bold")),
    ])

    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -2), 0.5, INK),
        ("BOX", (0, -1), (-1, -1), 0.5, INK),
        ("LINEBEFORE", (3, -1), (3, -1), 0.5, INK),
        ("SPAN", (0, -1), (2, -1)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)

    doc.build(story, onFirstPage=_signature_block, onLaterPages=_signature_block)
    return buffer.getvalue()


def _signature_block(canvas, doc) -> None:
    """Draw the two signature lines at the foot of the page.

    Drawn on the canvas rather than added to the story so they sit at the
    bottom of the sheet whether the pass carries one item or twenty — a gate
    pass is signed at the gate, and the lines belong where a pen expects them.
    """
    canvas.saveState()
    width, _height = A4
    y = 34 * mm
    half = 58 * mm

    for x in (doc.leftMargin, width - doc.rightMargin - half):
        canvas.setStrokeColor(INK)
        canvas.setLineWidth(0.6)
        canvas.line(x, y, x + half, y)

    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(INK)
    canvas.drawCentredString(doc.leftMargin + half / 2, y - 11, "Prepared By")
    canvas.drawCentredString(width - doc.rightMargin - half / 2, y - 11,
                             "Receiver's Signature")
    canvas.restoreState()


def _safe_one_line(address: str) -> str:
    """The letterhead address as a single line — the gate pass prints it
    inline rather than stacked."""
    return _text(address.replace("<br/>", " "))
