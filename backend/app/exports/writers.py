"""
Turn a list of rows into a downloadable file.

Three formats, one shape of input, so every listing in the ERP exports the
same way and a new module only has to describe its columns.

CSV is written with a UTF-8 BOM: without it Excel on a Pakistani or European
Windows opens the file in the system codepage and mangles every accented
character — the same class of damage that had to be repaired in the imported
data.
"""

import csv
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO, StringIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.documents.pdf import INK, LINE, _text

HEADER_FILL = "FFEFF4EF"


def _cell(value) -> str:
    """One value as display text. Dates use the ISO form so a spreadsheet
    sorts them correctly whatever the machine's locale."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def to_csv(columns: list[tuple[str, str]], rows: list[dict]) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([label for _, label in columns])
    for row in rows:
        writer.writerow([_cell(row.get(key)) for key, _ in columns])
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def to_xlsx(columns: list[tuple[str, str]], rows: list[dict], title: str) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31] or "Export"

    sheet.append([label for _, label in columns])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(vertical="center")

    for row in rows:
        sheet.append([
            # Numbers stay numbers so the spreadsheet can total them; only
            # text is pre-formatted.
            row.get(key) if isinstance(row.get(key), (int, float, Decimal))
            and not isinstance(row.get(key), bool)
            else _cell(row.get(key))
            for key, _ in columns
        ])

    for index, (key, label) in enumerate(columns, start=1):
        longest = max(
            [len(label)] + [len(_cell(row.get(key))) for row in rows[:500]] or [len(label)]
        )
        sheet.column_dimensions[get_column_letter(index)].width = min(max(longest + 2, 10), 55)

    sheet.freeze_panes = "A2"

    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


# A printed overview truncates: one sales order can list two dozen products,
# and a cell that tall cannot fit on any page — reportlab raises rather than
# splitting it. CSV and XLSX carry the untruncated text.
PDF_CELL_LIMIT = 200


def _pdf_cell(value) -> str:
    text = _cell(value)
    return text if len(text) <= PDF_CELL_LIMIT else text[: PDF_CELL_LIMIT - 1].rstrip() + "…"


def _pdf_widths(columns, rows, usable: float, size: float) -> list[float]:
    """Each column as wide as its longest value on one line (the heading may
    wrap between words). When that is wider than the page, only the widest
    columns are narrowed, to one common width, and their text wraps; spare
    room goes to the widest column, usually the narration or description."""
    padding = 7
    natural = []
    for key, label in columns:
        heading = max((stringWidth(word, "Helvetica-Bold", size) for word in label.split()), default=0)
        values = [stringWidth(_pdf_cell(row.get(key)), "Helvetica", size) for row in rows[:2000]]
        natural.append(max([heading, *values]) + padding)
    total = sum(natural)
    if total <= usable:
        widest = natural.index(max(natural))
        natural[widest] += usable - total
        return natural
    # Narrow the widest columns to the one width at which everything fits.
    ordered = sorted(natural)
    fixed, limit = 0.0, usable / len(natural)
    for n, width in enumerate(ordered):
        limit = (usable - fixed) / (len(ordered) - n)
        if width > limit:
            break
        fixed += width
    return [min(width, limit) for width in natural]


def to_pdf(columns: list[tuple[str, str]], rows: list[dict], title: str, header: dict | None = None) -> bytes:
    """Landscape, because these listings are wide. Long values wrap inside
    their cell, and very long ones are trimmed so a row still fits a page.
    With `header` the page carries a report heading laid out like the previous
    ERP's (see `_draw_header`) on every page, instead of the plain title."""
    base = getSampleStyleSheet()
    head_style = ParagraphStyle("h", parent=base["Normal"], fontName="Helvetica-Bold",
                                fontSize=6.5, textColor=INK, leading=8)
    cell_style = ParagraphStyle("c", parent=base["Normal"], fontName="Helvetica",
                                fontSize=6.5, textColor=INK, leading=8)
    title_style = ParagraphStyle("t", parent=base["Normal"], fontName="Helvetica-Bold",
                                 fontSize=13, textColor=INK)
    note_style = ParagraphStyle("n", parent=base["Normal"], fontName="Helvetica",
                                fontSize=7.5, textColor=colors.HexColor("#666666"))

    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream, pagesize=landscape(A4),
        leftMargin=10 * mm, rightMargin=10 * mm, topMargin=(42 if header else 10) * mm, bottomMargin=10 * mm,
        title=title,
    )

    story = [] if header else [
        Paragraph(_text(title), title_style),
        Spacer(1, 3),
        Paragraph(
            f"{len(rows):,} record(s) &middot; generated "
            f"{datetime.now().strftime('%d %B %Y %H:%M')}",
            note_style,
        ),
        Spacer(1, 8),
    ]

    data = [[Paragraph(_text(label), head_style) for _, label in columns]]
    for row in rows:
        data.append([Paragraph(_text(_pdf_cell(row.get(key))), cell_style) for key, _ in columns])

    usable = landscape(A4)[0] - 20 * mm
    table = Table(data, colWidths=_pdf_widths(columns, rows, usable, cell_style.fontSize),
                  repeatRows=1, splitInRow=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF4EF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)

    if header:
        doc.build(story, canvasmaker=_numbered(header))
    else:
        doc.build(story)
    return stream.getvalue()


MAROON = colors.HexColor("#7A1F1F")
BLUE = colors.HexColor("#1F3FD1")


def _draw_header(canvas, header: dict, page: int, pages: int) -> None:
    """Company name, report name, the date range, the print date with
    "Page n Of m", and the account boxed underneath, as the previous ERP prints
    a ledger. header: company, report, date_from, date_to, code, name."""
    width, height = landscape(A4)
    middle, top = width / 2, height - 10 * mm
    canvas.saveState()
    canvas.setFillColor(MAROON)
    canvas.setFont("Helvetica", 16)
    canvas.drawCentredString(middle, top - 6 * mm, header["company"])
    canvas.setFillColor(INK)
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawCentredString(middle, top - 14 * mm, header["report"])

    y = top - 20.5 * mm
    canvas.setFont("Helvetica", 8.5)
    canvas.setFillColor(BLUE)
    canvas.drawRightString(middle - 33 * mm, y, "From :")
    canvas.drawRightString(middle + 10 * mm, y, "To :")
    canvas.setFillColor(INK)
    canvas.setFont("Helvetica-Bold", 7.5)
    canvas.drawString(middle - 31.5 * mm, y, header["date_from"])
    canvas.drawString(middle + 13 * mm, y, header["date_to"])

    right = width - 10 * mm
    canvas.setFont("Helvetica-Bold", 8.5)
    canvas.drawString(right - 62 * mm, top - 8 * mm, "DATE:")
    canvas.drawString(right - 62 * mm, top - 15 * mm, "PAGE:")
    canvas.drawString(right - 26 * mm, top - 15 * mm, "Of")
    canvas.setFont("Helvetica", 8.5)
    canvas.drawString(right - 45 * mm, top - 8 * mm, header["printed"])
    canvas.drawCentredString(right - 34 * mm, top - 15 * mm, str(page))
    canvas.drawCentredString(right - 14 * mm, top - 15 * mm, str(pages))

    box_top, box_height = top - 23.5 * mm, 6.5 * mm
    left = 10 * mm + 22 * mm
    split = left + 55 * mm
    canvas.setLineWidth(0.9)
    canvas.rect(left, box_top - box_height, right - left, box_height)
    canvas.line(split, box_top, split, box_top - box_height)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawRightString(left - 2 * mm, box_top - 4.6 * mm, f"{header.get('label', 'Account')}:")
    canvas.setFont("Helvetica", 8)
    canvas.drawString(left + 2 * mm, box_top - 4.4 * mm, header["code"])
    canvas.drawString(split + 2 * mm, box_top - 4.4 * mm, header["name"])
    canvas.restoreState()


def _numbered(header: dict):
    """A canvas that holds every page back until the last, so each can say
    how many pages there are."""
    from reportlab.pdfgen.canvas import Canvas

    class NumberedCanvas(Canvas):
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
                _draw_header(self, header, n, total)
                super().showPage()
            super().save()

    return NumberedCanvas


FORMATS = {
    "csv": ("text/csv", "csv", to_csv),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx", to_xlsx),
    "pdf": ("application/pdf", "pdf", to_pdf),
}
