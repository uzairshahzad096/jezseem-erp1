"""
PDF document generation.

One renderer produces every sales document — Service Invoice, Quotation,
Sales Tax Invoice, Sales Invoice, Delivery Note, Proforma Invoice — because
they share the Jezseem Traders letterhead, the Bill To block, a line table
and a totals block, and differ only in title, which columns appear and which
totals are shown.

Spec section 7 of the requirements doc: the figures on the PDF must always
match the figures stored in the system. They do, because both come from the
same persisted columns — the renderer never recalculates anything.

reportlab is used rather than an HTML-to-PDF engine so there are no system
libraries to install on Windows.
"""

import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)
from reportlab.lib.utils import ImageReader

from app.common import currency as cur

RED = colors.HexColor("#C0272D")
GREEN = colors.HexColor("#2BA24C")
INK = colors.HexColor("#1A1A1A")
GREY = colors.HexColor("#666666")
LINE = colors.HexColor("#BFBFBF")

# Artwork that belongs to the company rather than the code. Both are optional:
# when a file is absent the renderer falls back to type, so a fresh checkout
# still produces a usable document. See assets/README.md for the filenames.
ASSETS_DIR = Path(__file__).parent / "assets"
LOGO_FILE = ASSETS_DIR / "logo.png"
SIGNATURE_FILE = ASSETS_DIR / "signature.png"

# How large the artwork prints, in one place so every document agrees. The
# logo file carries the wordmark and the tagline together, so the tagline
# grows with it. Each image is scaled to fit its box, keeping its proportions.
LOGO_BOX = (92 * mm, 24 * mm)           # was 104 x 27; the owner asked for it a little smaller (14-Oct-2026)
SIGNATURE_BOX = (54 * mm, 34 * mm)      # signature with the company stamp; was 45 x 29
# The space above and below the stamp and between the blocks under it, all equal,
# and the space between lines inside a block.
BLOCK_GAP = 16
LINE_GAP = 3


def _image(path: Path, max_width: float, max_height: float) -> Image | None:
    """An Image flowable scaled to fit the box while keeping its proportions,
    or None when the file is missing or unreadable."""
    if not path.is_file():
        return None
    try:
        width, height = ImageReader(str(path)).getSize()
    except Exception:
        # A corrupt or unsupported file must not take the whole document down;
        # the caller falls back to the text letterhead.
        return None
    if not width or not height:
        return None

    scale = min(max_width / width, max_height / height)
    return Image(str(path), width=width * scale, height=height * scale)


@dataclass
class CompanyLetterhead:
    """Printed at the top of every document.

    REQUIRES BUSINESS CONFIRMATION: these values are transcribed from the
    Service Invoice screenshot supplied with the requirements. They should be
    moved into Company settings and verified before anything is sent to a
    customer.
    """
    name: str = "JEZSEEM TRADERS"
    tagline: str = '"We Help U to CUT Fabric Instead Of Profit"'
    # Two lines, broken exactly where the reference quotation breaks them.
    # Broken after the road so each line fits at the larger A4 type size.
    address: str = ("47A-Wadi-e-Sitara, Near Gutwala Toll Plaza,Sheikhupura Road,"
                    "<br/>Faisalabad 38000, Punjab, Pakistan")
    # The gate pass letterhead prints a short one-line address rather than
    # the full postal one an invoice carries.
    short_address: str = "47A-Wadi-e-Sitara, Faisalabad"
    ntn: str = "2760380-6"
    phone: str = "923418866222"
    bank_title: str = "JEZSEEM TRADERS"
    bank_account: str = "04310104617658"
    bank_name: str = "MEEZAN BANK EDEN SQAURE BRANCH"


# Which totals rows each document shows, whether it prices at all, and what
# its reference number is called in the header block — a quotation says
# "Quotation #", not "Invoice #".
DOCUMENT_PROFILES: dict[str, dict] = {
    "service_invoice":   {"title": "SERVICE INVOICE",   "priced": True,  "tax": True,  "number_label": "Invoice #"},
    "sales_tax_invoice": {"title": "SALES TAX INVOICE", "priced": True,  "tax": True,  "number_label": "Invoice #"},
    "sales_invoice":     {"title": "SALES INVOICE",     "priced": True,  "tax": False, "number_label": "Invoice #"},
    "proforma_invoice":  {"title": "PROFORMA INVOICE",  "priced": True,  "tax": True,  "number_label": "Invoice #"},
    "quotation":         {"title": "QUOTATION",         "priced": True,  "tax": True,  "number_label": "Quotation #"},
    "delivery_note":     {"title": "DELIVERY NOTE",     "priced": False, "tax": False, "number_label": "Invoice #",
                          "layout": "delivery", "party_label": "Ship To"},
    "outward_gate_pass": {"title": "OUTWARD GATE PASS", "priced": False, "tax": False, "number_label": "Gate Pass #",
                          "party_label": "Ship To"},
    "inward_gate_pass":  {"title": "INWARD GATE PASS",  "priced": False, "tax": False, "number_label": "Gate Pass #",
                          "party_label": "Ship To"},
    "credit_note":       {"title": "CREDIT NOTE",       "priced": True,  "tax": True,  "number_label": "Credit Note #"},
    "debit_note":        {"title": "DEBIT NOTE",        "priced": True,  "tax": True,  "number_label": "Debit Note #"},
    # Documents sent to a supplier: addressed to them, and without the
    # customer-facing bank details and closing lines.
    "purchase_order":    {"title": "PURCHASE ORDER",    "priced": True,  "tax": True,  "number_label": "Order #",
                          "party_label": "Supplier", "footer": False},
    "mrn":               {"title": "GOODS RECEIPT NOTE", "priced": True, "tax": False, "number_label": "GRN #",
                          "party_label": "Supplier", "footer": False},
}


def _styles():
    base = getSampleStyleSheet()
    return {
        "company": ParagraphStyle("company", parent=base["Normal"], fontName="Helvetica-Bold",
                                  fontSize=18, textColor=GREEN, leading=21),
        "tagline": ParagraphStyle("tagline", parent=base["Normal"], fontName="Helvetica-BoldOblique",
                                  fontSize=9.5, textColor=RED, leading=12),
        # Regular weight, as printed on the reference — only the tagline
        # inside the logo artwork is emphasised.
        "addr": ParagraphStyle("addr", parent=base["Normal"], fontName="Helvetica",
                               fontSize=9.5, textColor=INK, leading=12.5),
        "title": ParagraphStyle("title", parent=base["Normal"], fontName="Helvetica-Bold",
                                fontSize=19, textColor=RED, alignment=TA_RIGHT, leading=23),
        "meta": ParagraphStyle("meta", parent=base["Normal"], fontName="Helvetica",
                               fontSize=10.5, textColor=INK, leading=14),
        "metaLabel": ParagraphStyle("metaLabel", parent=base["Normal"], fontName="Helvetica-Bold",
                                    fontSize=10.5, textColor=INK, alignment=TA_RIGHT, leading=14),
        "billLabel": ParagraphStyle("billLabel", parent=base["Normal"], fontName="Helvetica-Bold",
                                    fontSize=10.5, textColor=INK, leading=13),
        "body": ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica",
                               fontSize=10, textColor=INK, leading=13),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontName="Helvetica",
                               fontSize=9.5, textColor=INK, leading=12),
        # Figures print in black, as on the supplied Quotation. Only the
        # document title is coloured.
        "num": ParagraphStyle("num", parent=base["Normal"], fontName="Helvetica",
                              fontSize=9.5, textColor=INK, leading=12, alignment=TA_CENTER),
        "numBold": ParagraphStyle("numBold", parent=base["Normal"], fontName="Helvetica-Bold",
                                  fontSize=9.5, textColor=INK, leading=12, alignment=TA_CENTER),
        "th": ParagraphStyle("th", parent=base["Normal"], fontName="Helvetica-Bold",
                             fontSize=9.5, textColor=INK, alignment=TA_CENTER, leading=12),
        "totalLabel": ParagraphStyle("totalLabel", parent=base["Normal"],
                                     fontName="Helvetica-Bold", fontSize=10.5,
                                     textColor=INK, alignment=TA_RIGHT, leading=13),
        "footer": ParagraphStyle("footer", parent=base["Normal"], fontName="Helvetica",
                                 fontSize=10.5, textColor=INK, alignment=TA_CENTER, leading=14),
        "bank": ParagraphStyle("bank", parent=base["Normal"], fontName="Helvetica",
                               fontSize=10.5, textColor=INK, leading=15),
    }


# Characters that have no WinAnsi equivalent but a clear ASCII intent. Folded
# rather than dropped so an address keeps its punctuation.
_FOLD = {
    "،": ",",   # Arabic comma
    "؛": ";",   # Arabic semicolon
    "′": "'",   # prime
    "″": '"',   # double prime
    "−": "-",   # minus sign
    " ": " ",   # no-break space
    "​": "",    # zero-width space
    "﻿": "",    # byte-order mark
}


def _safe(value) -> str:
    """Text the built-in PDF fonts can actually draw.

    reportlab's Helvetica is WinAnsi-encoded, so anything outside it prints as
    a black box — which is how a stray symbol appears in an address nobody
    typed one into. Known punctuation is folded to its ASCII equivalent and
    accents are stripped to their base letter, so the word survives; anything
    still undrawable is dropped rather than printed as a box.
    """
    text = str(value or "")
    for bad, good in _FOLD.items():
        text = text.replace(bad, good)

    out = []
    for char in text:
        try:
            char.encode("cp1252")
            out.append(char)
            continue
        except UnicodeEncodeError:
            pass
        stripped = "".join(
            c for c in unicodedata.normalize("NFKD", char)
            if not unicodedata.combining(c)
        )
        try:
            stripped.encode("cp1252")
            out.append(stripped)
        except UnicodeEncodeError:
            pass  # nothing sensible to draw
    return "".join(out)


def _text(value) -> str:
    """Stored text ready to go inside a Paragraph: drawable, and with the
    markup characters escaped so an "&" in a company name is printed rather
    than parsed."""
    return escape(_safe(value))


def _fmt(value, currency: str = "PKR") -> str:
    """An amount with its currency in front. A document written in dollars
    prints "$ 1,234.00"; PKR has no symbol on the reference documents and
    keeps its code."""
    if value is None:
        return ""
    return f"{cur.symbol(currency)} {Decimal(str(value)):,.2f}"


def _qty(value) -> str:
    """A figure written the way a person would: 3, not 3.0000 — but 1.5 keeps
    its half, and 100 does not become 1e+2.

    Used for quantities and for rates. `:g` looks like it would do this, but a
    Decimal carries its own precision, so 18.0000 formats as 18.0000; and
    `.normalize()` strips the zeros only to turn 100.0000 into 1E+2.
    """
    text = f"{Decimal(str(value or 0)):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def render_document(
    *,
    doc_kind: str,
    header: dict,
    customer: dict,
    lines: list[dict],
    totals: dict,
    letterhead: CompanyLetterhead | None = None,
) -> bytes:
    """Build the PDF and return its bytes.

    `header`, `customer`, `lines` and `totals` are plain dicts assembled by
    the caller from stored columns, so this module has no database access and
    can be unit-tested with fixed data.
    """
    profile = DOCUMENT_PROFILES.get(doc_kind)
    if profile is None:
        raise ValueError(f"Unknown document kind: {doc_kind}")

    lh = letterhead or CompanyLetterhead()
    st = _styles()
    currency = header.get("currency") or "PKR"

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=9 * mm,
        title=f"{header.get('title') or profile['title']} {header.get('doc_number', '')}".strip(),
        author=lh.name,
    )
    story = []

    # ---------- letterhead ----------
    # The supplied artwork carries the wordmark and the tagline together, so
    # when it is present it replaces both lines of type rather than sitting
    # above a duplicate of them.
    logo = _image(LOGO_FILE, *LOGO_BOX)
    if logo is not None:
        logo.hAlign = "LEFT"
        left = [logo, Spacer(1, 6)]
    else:
        left = [
            Paragraph(lh.name, st["company"]),
            Spacer(1, 2),
            Paragraph(lh.tagline, st["tagline"]),
            Spacer(1, 3),
        ]
    left += [
        Paragraph(_safe(lh.address), st["addr"]),
        Paragraph(f"NTN# {_text(lh.ntn)}", st["addr"]),
        Paragraph(_text(lh.phone), st["addr"]),
    ]

    # Bill To belongs to the same column as the letterhead, not to a band
    # underneath it: on the reference the customer block and the Date/Quotation
    # rows sit side by side, which is what keeps the header compact.
    party_label = profile.get("party_label", "Bill To")
    left += [Spacer(1, 9), Paragraph(f"<u>{party_label}:</u>", st["billLabel"]), Spacer(1, 2),
             Paragraph(_text(customer.get("name", "")), st["body"])]
    # Name, address, NTN, STN — the four lines the reference prints. The
    # customer's phone is held on the ledger account and shown in the form,
    # but the printed document does not carry it.
    for key, prefix in [("address", ""), ("ntn", "NTN# "), ("stn", "STN# ")]:
        if customer.get(key):
            left.append(Paragraph(f"{escape(prefix)}{_text(customer[key])}", st["body"]))

    meta_rows = [[Paragraph("Date", st["metaLabel"]), Paragraph(_text(header.get("doc_date", "")), st["meta"])]]
    # Number and Demand # always appear, blank if unset, as on the supplied
    # Quotation. Payment Terms only when there are any.
    meta_rows.append([Paragraph(profile["number_label"], st["metaLabel"]),
                      Paragraph(_text(header.get("doc_number") or ""), st["meta"])])
    if header.get("extra_meta") is not None:
        # The document names its own reference rows (a purchase order: expected
        # delivery and terms; a goods receipt: its order and the supplier's invoice).
        for label, value in header["extra_meta"]:
            if value:
                meta_rows.append([Paragraph(_text(label), st["metaLabel"]), Paragraph(_text(value), st["meta"])])
    elif profile.get("layout") == "delivery":
        # A delivery note is about the despatch, so it carries the customer's
        # order reference and who is taking it rather than payment wording.
        meta_rows.append([Paragraph("PO NO #", st["metaLabel"]),
                          Paragraph(_text(header.get("customer_po_number") or ""), st["meta"])])
        meta_rows.append([Paragraph("Delivery Person", st["metaLabel"]),
                          Paragraph(_text(header.get("delivery_person") or ""), st["meta"])])
    elif header.get("reference_is_po"):
        # Sales orders and their invoices carry the customer's PO; Demand # is
        # a quotation's reference only.
        meta_rows.append([Paragraph("PO NO #", st["metaLabel"]),
                          Paragraph(_text(header.get("customer_po_number") or ""), st["meta"])])
        if header.get("payment_terms"):
            meta_rows.append([Paragraph("Payment Terms", st["metaLabel"]),
                              Paragraph(_text(header["payment_terms"]), st["meta"])])
    else:
        meta_rows.append([Paragraph("Demand #", st["metaLabel"]),
                          Paragraph(_text(header.get("demand_number") or ""), st["meta"])])
        if header.get("payment_terms"):
            meta_rows.append([Paragraph("Payment Terms", st["metaLabel"]),
                              Paragraph(_text(header["payment_terms"]), st["meta"])])
    meta_table = Table(meta_rows, colWidths=[31 * mm, 41 * mm])
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        # ~17pt rows, measured off the reference: 8pt type on 12pt leading
        # with a couple of points either side.
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))

    # The caller may reword the heading for this one document: a sales invoice
    # on an order without sales tax is headed plain "INVOICE".
    title = header.get("title") or profile["title"]
    # A clear gap under the title, so the date and number read as their own block.
    right = [Paragraph(title, st["title"]), Spacer(1, 20), meta_table]

    # The left column has to be wide enough to hold the address on the two
    # lines the reference uses; the meta block needs only ~68mm.
    head = Table([[left, right]], colWidths=[110 * mm, 72 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(head)

    # A clear gap, no rule, between the header block and the item table (owner, 14-Oct-2026).
    story.append(Spacer(1, 12))

    # ---------- line table ----------
    # Proportions taken from the reference quotation: Description takes almost
    # half the page and the money columns are narrow enough that "PKR" sits on
    # its own line above the figure, exactly as printed.
    delivery = profile.get("layout") == "delivery"

    if profile["priced"]:
        headers = ["Description", "Quantity", "Rate", "Sale", "XTAX Amount", "STAX Amount", "Amount"]
        # Sale needs to hold "@18%" and the two tax columns a six-figure
        # amount; at the old widths they broke mid-number, printing "PKR 22,4"
        # above "28.00". Description gives up the millimetres, since it wraps
        # on whole words and reads fine either way.
        widths = [62 * mm, 17 * mm, 24 * mm, 15 * mm, 23 * mm, 21 * mm, 20 * mm]
    elif delivery:
        # A despatch document carries no money at all: what was ordered, what
        # is going out on this note, and what already went.
        headers = ["Item", "Quantity", "Deliver", "Already Send"]
        widths = [110 * mm, 22 * mm, 22 * mm, 28 * mm]
    else:
        headers = ["Description", "Item Code", "UOM", "Quantity"]
        widths = [92 * mm, 36 * mm, 20 * mm, 34 * mm]

    data = [[Paragraph(h, st["th"]) for h in headers]]
    for line in lines:
        if profile["priced"]:
            # "@18%" where the line carries sales tax. A document printed
            # without sales tax shows a bare "@", so the Sale column is never
            # left looking as if something failed to print.
            rate = Decimal(str(line.get("tax_percent") or 0))
            tax_label = f"@{_qty(rate)}%" if profile["tax"] and (rate or not header.get("without_sales_tax")) else "@"
            data.append([
                Paragraph(_text(line.get("description", "")), st["cell"]),
                Paragraph(_qty(line.get("quantity")), st["num"]),
                Paragraph(_fmt(line.get("unit_price"), currency), st["num"]),
                Paragraph(tax_label, st["num"]),
                Paragraph(_fmt(line.get("taxable_amount"), currency), st["num"]),
                Paragraph(_fmt(line.get("tax_amount"), currency), st["num"]),
                Paragraph(_fmt(line.get("net_amount"), currency), st["num"]),
            ])
        elif delivery:
            ordered = Decimal(str(line.get("quantity") or 0))
            already = Decimal(str(line.get("delivered_quantity") or 0))
            data.append([
                Paragraph(_text(line.get("description", "")), st["cell"]),
                Paragraph(_qty(ordered), st["num"]),
                Paragraph(_qty(max(ordered - already, Decimal("0"))), st["num"]),
                Paragraph(_qty(already), st["num"]),
            ])
        else:
            data.append([
                Paragraph(_text(line.get("description", "")), st["cell"]),
                Paragraph(_text(line.get("item_code") or ""), st["cell"]),
                Paragraph(_text(line.get("uom") or ""), st["cell"]),
                Paragraph(_qty(line.get("quantity")), st["num"]),
            ])

    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)

    # ---------- totals ----------
    if delivery:
        ordered = sum(Decimal(str(l.get("quantity") or 0)) for l in lines)
        already = sum(Decimal(str(l.get("delivered_quantity") or 0)) for l in lines)
        deliver = max(ordered - already, Decimal("0"))

        sub = Table(
            [[Paragraph("Sub Total", st["totalLabel"]),
              Paragraph(_qty(ordered), st["num"]),
              Paragraph(_qty(deliver), st["num"]),
              Paragraph(_qty(already), st["num"])],
             [Paragraph("Total", st["totalLabel"]), "", "",
              Paragraph(_qty(already), st["num"])]],
            colWidths=widths,
        )
        sub.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("SPAN", (0, 1), (2, 1)),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(sub)

    if profile["priced"]:
        rows = []
        if profile["tax"]:
            rows.append(["Value",
                         _fmt(totals.get("excluding_tax_value"), currency),
                         _fmt(totals.get("sales_tax_value"), currency),
                         _fmt(totals.get("gross_amount"), currency)])
        rows.append(["Freight", "", "", _fmt(totals.get("freight_amount"), currency)])
        rows.append(["Discount", "", "", _fmt(totals.get("discount_amount"), currency)])
        rows.append(["Total", "", "", _fmt(totals.get("net_total"), currency)])

        widths_t = [sum(widths[:4]), widths[4], widths[5], widths[6]]
        totals_table = Table(
            [[Paragraph(r[0], st["totalLabel"]),
              Paragraph(r[1], st["num"]),
              Paragraph(r[2], st["num"]),
              Paragraph(r[3], st["num"])] for r in rows],
            colWidths=widths_t,
        )
        totals_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(totals_table)

    story.append(Spacer(1, 10))

    remarks = Table([[Paragraph(f"<u><b>Remarks:</b></u>  {_text(header.get('remarks') or '')}", st["body"])]],
                    colWidths=[182 * mm])
    remarks.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story.append(remarks)
    story.append(Spacer(1, BLOCK_GAP))

    # ---------- signature and stamp ----------
    # Centred on the page between the Remarks box and Bank Details, as on the
    # reference.
    signature = _image(SIGNATURE_FILE, *SIGNATURE_BOX)
    if signature is not None:
        signature.hAlign = "CENTER"
        story.append(signature)
        story.append(Spacer(1, BLOCK_GAP))
    else:
        story.append(Spacer(1, 42 + BLOCK_GAP))

    # Bank details and the closing lines appear on every customer-facing
    # document, priced or not — the delivery note on the reference carries
    # them too.
    if profile.get("footer", True):
        # Three blocks, each clearly apart from the next: the stamp, the bank
        # details, and the closing lines.
        story.append(Paragraph("<b><u>Bank Details</u></b>", st["bank"]))
        story.append(Spacer(1, LINE_GAP))
        # Each detail on its own well-separated line, as on the reference,
        # rather than three lines run together.
        for detail in (f"Account Title:{lh.bank_title}",
                       f"Account #:{lh.bank_account}",
                       f"Bank:{lh.bank_name}"):
            story.append(Paragraph(detail, st["bank"]))
            story.append(Spacer(1, LINE_GAP))

        story.append(Spacer(1, BLOCK_GAP + 6))   # the closing lines stand further apart
        story.append(Paragraph("Thanks for your business!", st["footer"]))
        story.append(Spacer(1, LINE_GAP))
        story.append(Paragraph(f"Make All cheques payable to {lh.name.title()}.", st["footer"]))
        story.append(Spacer(1, LINE_GAP))
        story.append(Paragraph("Computer Generated no need sign &amp; stamp.", st["footer"]))

    doc.build(story)
    return buffer.getvalue()
