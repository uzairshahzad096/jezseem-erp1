"""
Import Purchase Order, printed to the company's template
(Jezseem_Traders_Import_Purchase_Order_Template): the company heading on every
page, IMPORT PURCHASE ORDER and the buyer's legal name, the PO control table,
then sections 1-9 — buyer and supplier, order / delivery / shipping, items and
pricing, the commercial value summary with the amount in words, payment terms
and bank details, shipping and import documents, quality / warranty /
packing, special instructions and purchase terms, approval and the supplier's
acknowledgment — with "JEZSEEM TRADERS | IMPORT PURCHASE ORDER | Page n" at
the foot. The template's internal ERP notes are left off the supplier copy.
Figures come from the stored order only.
"""

from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.common import currency as cur
from app.documents.pdf import SIGNATURE_FILE, _image, _qty, _text

BLUE = colors.HexColor("#1F4E79")
HEAD = colors.HexColor("#DDEBF7")
INK = colors.HexColor("#111111")
LINE = colors.HexColor("#3A3A3A")

COMPANY = "JEZSEEM TRADERS"
ADDRESS = "47A-Wadi-e-Sitara, Near Gutwala Toll Plaza, Sheikhupura Road, Faisalabad 38000, Punjab, Pakistan"
WEBSITE = "jezseemtraders.com"
LEGAL_NAME = "Muhammad Naseem, Sole Proprietor, trading as Jezseem Traders"
NTN = "2760380-6"

CURRENCY_WORDS = {"USD": ("US Dollars", "Cents"), "EUR": ("Euros", "Cents"), "GBP": ("Pounds Sterling", "Pence"),
                  "CNY": ("Chinese Yuan", "Fen"), "AED": ("UAE Dirhams", "Fils"), "PKR": ("Pakistani Rupees", "Paisa"),
                  "JPY": ("Japanese Yen", "Sen"), "CHF": ("Swiss Francs", "Centimes")}
_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


class M(str):
    """A table cell that is already markup, printed as is."""


def _words(n: int) -> str:
    if n == 0:
        return "Zero"
    parts = []
    for value, name in ((10**9, "Billion"), (10**6, "Million"), (1000, "Thousand"), (1, "")):
        chunk, n = divmod(n, value)
        if not chunk:
            continue
        hundreds, rest = divmod(chunk, 100)
        words = []
        if hundreds:
            words.append(f"{_ONES[hundreds]} Hundred")
        if rest:
            words.append(_ONES[rest] if rest < 20 else f"{_TENS[rest // 10]} {_ONES[rest % 10]}".strip())
        parts.append(" ".join(words) + (f" {name}" if name else ""))
    return " ".join(parts)


def amount_in_words(value, currency: str) -> str:
    v = Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole, cents = int(v), int((v - int(v)) * 100)
    major, minor = CURRENCY_WORDS.get(currency, (currency, "Cents"))
    text = f"{major} {_words(whole)}"
    if cents:
        text += f" and {minor} {_words(cents)}"
    return text + " Only"


def render_import_po(o: dict, lines: list[dict]) -> bytes:
    base = getSampleStyleSheet()["Normal"]
    st = {
        "title": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=17, textColor=BLUE,
                                alignment=TA_CENTER, leading=21),
        "body": ParagraphStyle("b", parent=base, fontName="Helvetica", fontSize=8.5, textColor=INK, leading=10.5),
        "h": ParagraphStyle("h", parent=base, fontName="Helvetica-Bold", fontSize=10.5, textColor=BLUE, leading=13,
                            spaceBefore=6, spaceAfter=3),
        "th": ParagraphStyle("th", parent=base, fontName="Helvetica-Bold", fontSize=8, textColor=INK, leading=9.5),
        "cell": ParagraphStyle("c", parent=base, fontName="Helvetica", fontSize=8, textColor=INK, leading=9.5),
        "cellb": ParagraphStyle("cb", parent=base, fontName="Helvetica-Bold", fontSize=8.5, textColor=INK, leading=10),
        "bullet": ParagraphStyle("bl", parent=base, fontName="Helvetica", fontSize=8.5, textColor=INK, leading=10.5,
                                 leftIndent=12, bulletIndent=2),
    }
    width = A4[0] - 30 * mm
    currency = o["currency"] or "USD"
    sym = lambda v: f"{cur.symbol(currency)} {Decimal(str(v or 0)):,.2f}"   # noqa: E731
    val = lambda v: _text(v) if v not in (None, "") else "—"                # noqa: E731

    def table(rows, widths, header=True):
        data = [[Paragraph(c if isinstance(c, M) else val(c),
                           st["th"] if (header and r == 0) else st["cell"]) for c in row]
                for r, row in enumerate(rows)]
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        style = [("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                 ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), HEAD))
        t.setStyle(TableStyle(style))
        return t

    two = [width * 0.5, width * 0.5]
    story = [Paragraph("IMPORT PURCHASE ORDER", st["title"]), Spacer(1, 4),
             Paragraph(f"BUYER LEGAL NAME: {LEGAL_NAME}", st["body"]), Spacer(1, 3)]

    rev = f"{o['doc_date'] or '—'} / {int(o.get('revision') or 0):02d}"
    story.append(table([
        ["PO CONTROL FIELD", "DETAILS"],
        ["Purchase Order No.", o["doc_number"]],
        ["PO Date / Revision", rev],
        ["Currency", currency],
        ["Supplier Quotation / Proforma Invoice No. & Date", o["quotation"]],
        ["Purchase Category", o.get("purchase_category")],
        ["PO Status", o["status"]],
    ], two))

    s = o["supplier"]
    story += [Paragraph("1. BUYER AND SUPPLIER DETAILS", st["h"]), table([
        ["FIELD", "BUYER / IMPORTER", "SUPPLIER / EXPORTER"],
        ["Legal / Registered Name", LEGAL_NAME, s["name"]],
        ["Business / Registered Address", ADDRESS, s.get("address") if (s.get("address") and s.get("country") and s["country"].lower() in s["address"].lower()) else ", ".join(x for x in (s.get("address"), s.get("country")) if x)],
        ["Tax / Registration No.", f"NTN {NTN}", " / ".join(x for x in (s.get("ntn"), s.get("stn")) if x)],
        ["Contact Person / Designation", " / ".join(x for x in (o.get("purchaser"), o.get("buyer_designation")) if x),
         " / ".join(x for x in (o.get("supplier_contact"), o.get("supplier_contact_designation")) if x)],
        ["Email / Telephone", " / ".join(x for x in (o.get("purchaser_email"), o.get("contact_number")) if x),
         " / ".join(x for x in (s.get("email"), s.get("phone")) if x)],
        ["Ship-to Address", o.get("ship_to_address") or o.get("warehouse"), None],
        ["Bill-to Address", o.get("bill_to_address") or "Same as buyer address", None],
    ], [width * 0.28, width * 0.36, width * 0.36])]

    incoterm = " — ".join(x for x in (o.get("incoterm"), o.get("incoterm_edition") or ("Incoterms® 2020" if o.get("incoterm") else None)) if x)
    story += [Paragraph("2. ORDER, DELIVERY AND SHIPPING DETAILS", st["h"]), table([
        ["FIELD", "DETAILS"],
        ["Required Shipment Date", o.get("shipment_date")],
        ["Required Delivery Date", o.get("delivery_date")],
        ["Incoterm and Edition", incoterm or None],
        ["Named Place / Port", o.get("named_place")],
        ["Loading Port / Airport", o.get("port_of_loading")],
        ["Destination Port / Airport", o.get("port_of_discharge")],
        ["Mode of Transport", o.get("shipping_mode")],
        ["Partial Shipment / Transshipment", " / ".join(x or "—" for x in (o.get("partial_shipment"), o.get("transshipment")))
         if (o.get("partial_shipment") or o.get("transshipment")) else None],
        ["Packing / Shipping Marks", o.get("packing_marks")],
        ["Country of Origin / Country of Export",
         " / ".join(x or "—" for x in (o.get("country_of_origin"), o.get("country_of_export") or o.get("supplier_country")))],
    ], two)]

    items = [["Line", "Item / Part No.", "Complete Description, Brand, Model & Specifications", "HS / PCT Code",
              "Origin", "Qty", "UOM", "Unit Price", "Line Total"]]
    goods = Decimal("0")
    for n, l in enumerate(lines, start=1):
        goods += Decimal(str(l["net_amount"] or 0))
        items.append([str(n), l.get("item_code"), l["description"], l.get("hs_code"),
                      l.get("origin_country") or o.get("country_of_origin"), _qty(l["quantity"]), l.get("uom"),
                      sym(l["unit_price"]), sym(l["net_amount"])])
    w = [11 * mm, 23 * mm, 0, 18 * mm, 16 * mm, 11 * mm, 12 * mm, 21 * mm, 23 * mm]
    w[2] = width - sum(w)
    story += [Paragraph("3. ITEMS AND PRICING", st["h"]), table(items, w),
              Spacer(1, 3),
              Paragraph("UOM examples: PCS, SET, BOX, CARTON, KG, M, LTR. Use the appropriate unit for the goods and keep "
                        "it consistent with the supplier invoice and applicable import documents.", st["body"])]

    charges = [("Packing / Handling", o["packing_amount"]), ("Freight", o["freight_amount"]),
               ("Insurance", o["insurance_amount"]), ("Other Agreed Charges", o["other_charges"])]
    total = Decimal(str(o["net_payable"] or 0))
    discount = goods + sum((Decimal(str(v or 0)) for _, v in charges), Decimal("0")) - total
    summary = [["DESCRIPTION", "AMOUNT"], ["Goods Subtotal", sym(goods)], ["Discount", sym(discount)]]
    summary += [[k, sym(v)] for k, v in charges]
    summary.append([M("<b>TOTAL PO VALUE</b>"), M(f"<b>{_text(sym(total))}</b>")])
    story += [Paragraph("4. COMMERCIAL VALUE SUMMARY", st["h"]), table(summary, two), Spacer(1, 3),
              Paragraph(f"Amount in words: <b>{_text(amount_in_words(total, currency))}</b>. Clearly identify which "
                        "charges are included in the goods price to avoid double-counting.", st["body"])]
    if currency != "PKR":
        story.append(Paragraph(f"PKR equivalent at 1 {currency} = {Decimal(str(o['exchange_rate'])):,.4f}: "
                               f"<b>PKR {Decimal(str(o['net_payable_base'] or 0)):,.2f}</b>", st["body"]))

    adv = []
    if Decimal(str(o.get("advance_amount") or 0)):
        adv.append(sym(o["advance_amount"]))
    if Decimal(str(o.get("advance_percent") or 0)):
        adv.append(f"{_qty(o['advance_percent'])}%")
    story += [Paragraph("5. PAYMENT TERMS AND BANK DETAILS", st["h"]), table([
        ["FIELD", "DETAILS"],
        ["Payment Method", o.get("payment_method") or o.get("payment_terms")],
        ["Advance Amount / Percentage", " / ".join(adv) or None],
        ["Balance Payment Trigger / Due Date", o.get("balance_trigger")],
        ["Beneficiary Account Title", s["name"]],
        ["Beneficiary Bank / Address", ", ".join(x for x in (s.get("bank_name") or o.get("bank_name"), s.get("bank_address")) if x)],
        ["SWIFT / BIC", s.get("bank_swift")],
        ["IBAN / Account Number", " / ".join(x for x in (s.get("bank_iban"), s.get("bank_account")) if x)],
        ["Bank Charges", o.get("bank_charges")],
        ["Payment Reference", o.get("payment_reference") or o["doc_number"]],
    ], two)]

    def bullets(items_):
        return [Paragraph(t, st["bullet"], bulletText="•") for t in items_]

    story += [Paragraph("6. SHIPPING AND IMPORT DOCUMENTS", st["h"])] + bullets([
        "Commercial invoice with accurate item descriptions, quantities, currency, prices and agreed Incoterm.",
        "Packing list showing package count, contents, net weight and gross weight.",
        "Bill of Lading (B/L) or Air Waybill (AWB), as applicable.",
        "Certificate of origin, where required or agreed.",
        "Insurance certificate, where applicable under the agreed terms.",
        "Technical datasheets, catalogue, model / serial details or compatibility information, where relevant.",
        "Inspection, conformity, permit or other certificates required for the particular goods and import procedure.",
    ]) + [Paragraph("Supplier shall provide documents applicable to the shipment, payment method and destination "
                    "requirements. Buyer / clearing agent to verify any additional Pakistan import requirements before "
                    "dispatch.", st["body"])]

    fill = lambda v, blank: f"<b>{_text(v)}</b>" if v else blank   # noqa: E731
    story += [Paragraph("7. QUALITY, WARRANTY AND PACKING", st["h"])] + bullets([
        "Goods shall conform to the approved specifications, quotation / proforma invoice and part numbers stated in this PO.",
        f"Condition of goods: {fill(o.get('goods_condition'), '[New / Used / Refurbished]')}. State explicitly before acceptance.",
        "No substitutions or changes without prior written approval from the buyer.",
        f"Warranty period and commencement: {fill(o.get('warranty_terms'), '[Specify, if applicable]')}.",
        f"Procedure for defective, damaged, incorrect or short-shipped goods: {fill(o.get('defect_remedy'), '[Agreed replacement / credit / remedy]')}.",
        f"Packaging shall be suitable for international transport and handling; special packing requirements: {fill(o.get('special_packing'), '[Details]')}.",
        f"Pre-shipment inspection or testing: {fill(o.get('pre_shipment_inspection'), '[Required / Not required / Details]')}.",
    ])

    story += [Paragraph("8. SPECIAL INSTRUCTIONS AND PURCHASE TERMS", st["h"])] + bullets([
        "Supplier shall acknowledge this PO in writing and identify any deviations before acceptance.",
        "Any change to price, quantity, specification, shipment date or delivery terms requires written approval by both parties.",
        "Supplier shall provide dispatch details and available shipping documents promptly after shipment.",
        "Partial shipment, excess shipment or short shipment is subject to the terms stated in this PO and any written approval.",
        "Cancellation, force majeure, governing law, dispute resolution and order-of-precedence provisions shall be as agreed "
        "in the contract or written terms accepted by both parties.",
        "If this PO conflicts with the supplier quotation or proforma invoice, the applicable precedence must be expressly "
        "agreed in writing; do not assume unilateral precedence.",
    ]) + [Paragraph(f"Additional special instructions: {fill(o.get('special_instructions') or o.get('remarks'), '—')}.", st["body"])]

    stamp = _image(SIGNATURE_FILE, 38 * mm, 20 * mm)
    approval = table([
        ["PREPARED BY", "APPROVED BY"],
        [M(f"Name: {_text(o.get('prepared_by') or '__________________________')}"),
         M(f"Name: {_text(o.get('approved_by') or '__________________________')}")],
        ["Designation: _____________________", "Designation: _____________________"],
        ["Signature: _______________________", "Signature / Company Stamp:"],
        [M(f"Date: {_text(o['doc_date'] or '')}"), M(f"Date: {_text(o.get('approved_at') or '')}")],
    ], two)
    blocks = [Paragraph("9. APPROVAL AND SUPPLIER ACKNOWLEDGMENT", st["h"]), approval]
    if stamp is not None:
        stamp.hAlign = "RIGHT"
        blocks += [Spacer(1, 10 * mm), stamp]
    blocks += [Spacer(1, 8), Paragraph("<b>SUPPLIER ACKNOWLEDGMENT</b>", st["body"]), Spacer(1, 2),
               Paragraph("Supplier acknowledges receipt and acceptance of this Purchase Order subject to its stated terms "
                         "and any deviations mutually agreed in writing.", st["body"]), Spacer(1, 3),
               table([["SUPPLIER DETAILS", "SIGNATURE"],
                      [M(f"Company: {_text(s['name'])}"), "Authorized Signatory: __________________"],
                      ["Name / Designation: ____________________", "Date: __________________________"],
                      ["Acknowledged deviations (if any): ______________", "Company Stamp: _______________________"]], two)]
    story.append(KeepTogether(blocks))

    def page(canvas, doc):
        w, h = A4
        canvas.saveState()
        canvas.setFillColor(BLUE)
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawCentredString(w / 2, h - 14 * mm, COMPANY)
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(w / 2, h - 18.5 * mm, ADDRESS)
        canvas.drawCentredString(w / 2, h - 22 * mm, f"Website: {WEBSITE}")
        canvas.setFont("Helvetica", 9)
        canvas.drawCentredString(w / 2, 9 * mm, f"{COMPANY}  |  IMPORT PURCHASE ORDER  |  Page {doc.page}")
        canvas.restoreState()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=26 * mm,
                            bottomMargin=16 * mm, title=f"Import Purchase Order {o['doc_number']}", author=COMPANY)
    doc.build(story, onFirstPage=page, onLaterPages=page)
    return buffer.getvalue()
