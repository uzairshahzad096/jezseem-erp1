"""Customer receipt voucher (RV / BRV) as a one-page PDF, from stored columns only."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.documents.pdf import INK, LINE, _text


def render_receipt(company: str, receipt: dict, allocations: list[dict]) -> bytes:
    base = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=15, textColor=INK)
    label = ParagraphStyle("l", parent=base["Normal"], fontName="Helvetica", fontSize=8.5, textColor=colors.grey)
    value = ParagraphStyle("v", parent=base["Normal"], fontName="Helvetica", fontSize=10, textColor=INK)
    bold = ParagraphStyle("b", parent=value, fontName="Helvetica-Bold")

    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title=receipt["receipt_number"])
    kind = "CASH RECEIPT VOUCHER" if receipt["method_kind"] == "CASH" else "BANK RECEIPT VOUCHER"
    story = [Paragraph(_text(company), bold), Spacer(1, 4), Paragraph(kind, title), Spacer(1, 10)]

    def cell(caption, text, style=value):
        return [Paragraph(caption, label), Paragraph(_text(text or "—"), style)]

    facts = [
        cell("Receipt #", receipt["receipt_number"], bold) + cell("Date", receipt["receipt_date"]),
        cell("Received from", f"{receipt['customer_code']} {receipt['customer_name']}")
        + cell("Status", receipt["status"]),
        cell("Payment method", receipt["payment_method"]) + cell("Deposited to", receipt["deposit_account"]),
        cell("Cheque / reference", receipt.get("cheque_number") or receipt.get("reference"))
        + cell("Bank", receipt.get("bank_name")),
        cell("Amount", f"{receipt['currency']} {receipt['amount']:,.2f}", bold)
        + cell("Journal", (receipt.get("journal") or {}).get("journal_number")),
    ]
    table = Table(facts, colWidths=[32 * mm, 55 * mm, 32 * mm, 55 * mm])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [table, Spacer(1, 12)]

    if allocations:
        rows = [["Applied to", "Date", "Amount"]] + [
            [a["document_number"], str(a["date"]), f"{a['amount']:,.2f}"] for a in allocations if a["status"] == "ACTIVE"]
        rows.append(["Unallocated (held as advance)", "", f"{receipt['unallocated']:,.2f}"])
        alloc = Table(rows, colWidths=[90 * mm, 40 * mm, 44 * mm])
        alloc.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, LINE), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF4EF")),
        ]))
        story += [alloc, Spacer(1, 12)]
    if receipt.get("notes"):
        story += [Paragraph("Notes", label), Paragraph(_text(receipt["notes"]), value), Spacer(1, 12)]
    story += [Spacer(1, 30), Table([["Received by", "Checked by", "Approved by"]], colWidths=[58 * mm] * 3,
                                   style=TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.5, INK),
                                                     ("FONTSIZE", (0, 0), (-1, -1), 9)]))]
    doc.build(story)
    return stream.getvalue()
