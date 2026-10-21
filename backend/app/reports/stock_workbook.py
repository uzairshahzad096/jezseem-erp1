"""
The stock movement analysis as one Excel workbook.

    Summary         headline counts, thresholds used, top repeat sellers, definitions
    Restock list    what to reorder now, by priority, with a suggested quantity
    Repeat sellers  products sold on several separate orders in the period
    Dead stock      stock that has not sold for a long time (or never)
    All products    every product with its figures, filterable

Every sheet has a frozen, filterable header and prints landscape on one
page width, so it can go straight to the store or purchasing.
"""

from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.reports.movement import MOVEMENT_LABELS, MOVEMENTS, Settings

GREEN = "2BC155"
DARK = "2A3547"
MUTED = "7E8A99"
BAND = "F3F7F5"
THIN = Side(style="thin", color="E3E8E6")

MOVEMENT_FILL = {
    "REPEAT": "D8F5E0", "OCCASIONAL": "DCEBFD", "SLOW": "FFF1D6", "DEAD": "FDE0E0", "INACTIVE": "EEF1F3",
}
MOVEMENT_FONT = {
    "REPEAT": "1E8A3C", "OCCASIONAL": "2F6FC4", "SLOW": "B57600", "DEAD": "C43C3C", "INACTIVE": "7E8A99",
}
PRIORITY_FILL = {"HIGH": "FDE0E0", "MEDIUM": "FFF1D6", "LOW": "EEF1F3"}
PRIORITY_FONT = {"HIGH": "C43C3C", "MEDIUM": "B57600", "LOW": "5E6A78"}
PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

QTY = "#,##0.##"
MONEY = "#,##0"
DATE = "DD-MMM-YYYY"
PCT = '0.#"%"'


def _title(ws: Worksheet, title: str, subtitle: str, width: int) -> int:
    """A title band over the table; returns the header row number."""
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=15, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=GREEN)
    ws["A1"].alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[1].height = 30
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=width)
    ws["A2"] = subtitle
    ws["A2"].font = Font(italic=True, size=9.5, color=MUTED)
    ws["A2"].alignment = Alignment(indent=1)
    return 4


def _table(ws: Worksheet, header_row: int, columns: list[tuple], rows: list[dict]) -> None:
    """columns: (key, label, width, number format or None)."""
    for c, (_key, label, width, _fmt) in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=c, value=label)
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.fill = PatternFill("solid", fgColor=DARK)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = Border(bottom=THIN)
        ws.column_dimensions[get_column_letter(c)].width = width
    ws.row_dimensions[header_row].height = 30

    for r, row in enumerate(rows, start=header_row + 1):
        band = PatternFill("solid", fgColor=BAND) if (r - header_row) % 2 == 0 else None
        for c, (key, _label, _width, fmt) in enumerate(columns, start=1):
            value = row.get(key)
            cell = ws.cell(row=r, column=c, value=value)
            cell.border = Border(bottom=THIN)
            cell.font = Font(size=10, color=DARK)
            if fmt:
                cell.number_format = fmt
            if band:
                cell.fill = band
            if key == "movement_label":
                m = row.get("movement")
                cell.fill = PatternFill("solid", fgColor=MOVEMENT_FILL.get(m, BAND))
                cell.font = Font(size=10, bold=True, color=MOVEMENT_FONT.get(m, DARK))
            if key == "restock_priority" and value:
                cell.fill = PatternFill("solid", fgColor=PRIORITY_FILL[value])
                cell.font = Font(size=10, bold=True, color=PRIORITY_FONT[value])
            if key == "description":
                cell.alignment = Alignment(wrap_text=False)

    last_col = get_column_letter(len(columns))
    last_row = max(header_row + len(rows), header_row + 1)
    ws.auto_filter.ref = f"A{header_row}:{last_col}{last_row}"
    ws.freeze_panes = ws.cell(row=header_row + 1, column=3)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{header_row}:{header_row}"
    if not rows:
        ws.cell(row=header_row + 1, column=1, value="Nothing in this list.").font = Font(italic=True, color=MUTED)


BASE = [("item_code", "Item Code", 15, None), ("description", "Description", 48, None),
        ("main_product", "Category", 18, None), ("uom", "UOM", 7, None)]


def build_workbook(company: str, cfg: Settings, rows: list[dict], totals: dict) -> bytes:
    wb = Workbook()
    stamp = f"{company} · {cfg.period_label} · generated {datetime.now():%d-%b-%Y %H:%M}"

    # ---------------- Summary
    ws = wb.active
    ws.title = "Summary"
    _title(ws, "Stock Movement Analysis", stamp, 6)
    ws.column_dimensions["A"].width = 30
    for col in "BCDEF":
        ws.column_dimensions[col].width = 16

    def heading(row: int, text: str) -> None:
        ws.cell(row=row, column=1, value=text).font = Font(bold=True, size=12, color=DARK)

    heading(4, "Movement")
    r = 5
    for m in MOVEMENTS:
        label = ws.cell(row=r, column=1, value=MOVEMENT_LABELS[m])
        label.fill = PatternFill("solid", fgColor=MOVEMENT_FILL[m])
        label.font = Font(bold=True, color=MOVEMENT_FONT[m])
        ws.cell(row=r, column=2, value=totals["counts"][m]).number_format = "#,##0"
        r += 1
    ws.cell(row=r, column=1, value="Dead stock quantity")
    ws.cell(row=r, column=2, value=totals["dead_quantity"]).number_format = QTY
    ws.cell(row=r + 1, column=1, value="Dead stock at list price (PKR)")
    ws.cell(row=r + 1, column=2, value=totals["dead_list_value"]).number_format = MONEY

    heading(r + 3, "Restock needed")
    rr = r + 4
    for label, key, prio in (("High — repeat sellers", "restock_high", "HIGH"),
                             ("Medium — occasional", "restock_medium", "MEDIUM"),
                             ("Low — slow or not selling", "restock_low", "LOW")):
        cell = ws.cell(row=rr, column=1, value=label)
        cell.fill = PatternFill("solid", fgColor=PRIORITY_FILL[prio])
        cell.font = Font(bold=True, color=PRIORITY_FONT[prio])
        ws.cell(row=rr, column=2, value=totals[key])
        rr += 1
    ws.cell(row=rr, column=1, value="Total").font = Font(bold=True)
    ws.cell(row=rr, column=2, value=totals["restock_total"]).font = Font(bold=True)

    heading(rr + 2, "Settings used")
    settings = [("Period", cfg.period_label),
                ("Repeat seller", f"sold on {cfg.repeat_min}+ separate orders in the period"),
                ("Dead stock", f"in stock, not sold for {cfg.dead_days}+ days (or never)"),
                ("Restock when left", f"{cfg.restock_percent:g}% or less of the stock last added"),
                ("Suggested quantity covers", f"{cfg.cover_months:g} months of average sales")]
    sr = rr + 3
    for label, value in settings:
        ws.cell(row=sr, column=1, value=label).font = Font(color=MUTED)
        ws.cell(row=sr, column=2, value=value)
        sr += 1

    heading(sr + 1, "Top repeat sellers")
    top_header = sr + 2
    for c, label in enumerate(["Item Code", "Description", "Orders", "Qty sold", "Customers", "Stock"], start=1):
        cell = ws.cell(row=top_header, column=c, value=label)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=DARK)
    for i, row in enumerate(totals["top_repeat"], start=top_header + 1):
        for c, key in enumerate(["item_code", "description", "orders_in_period", "qty_sold_in_period",
                                 "customers_in_period", "quantity"], start=1):
            cell = ws.cell(row=i, column=c, value=row[key])
            if c >= 3:
                cell.number_format = QTY
    ws.column_dimensions["B"].width = 50

    notes = top_header + len(totals["top_repeat"]) + 2
    heading(notes, "How to read this")
    for i, text in enumerate([
        "A sale is a line on a posted sales order; quotations and un-posted orders do not count.",
        "Stock is the stock ledger balance. Products with no stock and no recent sales are 'Inactive' "
        "and are not flagged for restocking.",
        "Stock added = the quantity on hand right after the latest opening balance or goods receipt "
        "(had 5, received 95 = 100). % left = stock now against that level.",
        "A product with no stock added on record is flagged only when it is out of stock and selling.",
        "Dead stock value uses the item master selling price; there is no cost price on record yet.",
    ], start=notes + 1):
        ws.cell(row=i, column=1, value=text).font = Font(size=9.5, color=MUTED)

    # ---------------- Restock list
    ws = wb.create_sheet("Restock list")
    restock = sorted((r for r in rows if r["restock"]),
                     key=lambda r: (PRIORITY_ORDER[r["restock_priority"]], -r["orders_in_period"],
                                    -r["qty_sold_in_period"]))
    cols = BASE + [("added_level", "Stock Added (level)", 12, QTY), ("added_on", "Added On", 13, DATE),
                   ("quantity", "In Stock", 10, QTY), ("remaining_pct", "% Left", 9, PCT),
                   ("suggested_restock_qty", "Suggested Order Qty", 12, QTY),
                   ("restock_priority", "Priority", 10, None), ("restock_reason", "Why", 30, None),
                   ("movement_label", "Movement", 14, None),
                   ("orders_in_period", "Orders (period)", 11, "#,##0"),
                   ("qty_sold_in_period", "Qty Sold (period)", 12, QTY),
                   ("avg_monthly_qty", "Avg / Month (12m)", 12, QTY), ("last_sold", "Last Sold", 13, DATE),
                   ("location", "Location", 16, None)]
    header = _title(ws, f"Restock List — {cfg.restock_percent:g}% or less of stock added left", stamp, len(cols))
    _table(ws, header, cols, restock)

    # ---------------- Repeat sellers
    ws = wb.create_sheet("Repeat sellers")
    repeat = sorted((r for r in rows if r["movement"] == "REPEAT"),
                    key=lambda r: (-r["orders_in_period"], -r["qty_sold_in_period"]))
    cols = BASE + [("orders_in_period", "Orders (period)", 11, "#,##0"),
                   ("qty_sold_in_period", "Qty Sold (period)", 12, QTY),
                   ("customers_in_period", "Customers", 10, "#,##0"),
                   ("sales_value_in_period", "Sales Value excl. Tax", 15, MONEY),
                   ("quantity", "In Stock", 10, QTY), ("restock_priority", "Restock", 10, None),
                   ("last_sold", "Last Sold", 13, DATE)]
    header = _title(ws, f"Repeat Sellers — {cfg.repeat_min}+ orders", stamp, len(cols))
    _table(ws, header, cols, repeat)

    # ---------------- Dead stock
    ws = wb.create_sheet("Dead stock")
    dead = sorted((dict(r, list_value=round(r["quantity"] * r["stock_value_basis"], 2))
                   for r in rows if r["movement"] == "DEAD"),
                  key=lambda r: (-r["list_value"], -r["quantity"]))
    cols = BASE + [("location", "Location", 16, None), ("quantity", "In Stock", 10, QTY),
                   ("last_sold", "Last Sold", 13, DATE), ("days_since_sale", "Days Since Sale", 11, "#,##0"),
                   ("lifetime_orders", "Orders Ever", 10, "#,##0"),
                   ("stock_value_basis", "List Price", 12, MONEY), ("list_value", "Value at List Price", 14, MONEY)]
    header = _title(ws, f"Dead Stock — not sold for {cfg.dead_days}+ days", stamp, len(cols))
    _table(ws, header, cols, dead)

    # ---------------- All products
    ws = wb.create_sheet("All products")
    everything = sorted(rows, key=lambda r: (MOVEMENTS.index(r["movement"]), r["item_code"]))
    cols = BASE + [("sub_category", "Sub Category", 18, None), ("location", "Location", 16, None),
                   ("added_level", "Stock Added (level)", 12, QTY),
                   ("quantity", "In Stock", 10, QTY), ("remaining_pct", "% Left", 9, PCT),
                   ("movement_label", "Movement", 14, None),
                   ("orders_in_period", "Orders (period)", 11, "#,##0"),
                   ("qty_sold_in_period", "Qty Sold (period)", 12, QTY),
                   ("last_sold", "Last Sold", 13, DATE), ("days_since_sale", "Days Since Sale", 11, "#,##0"),
                   ("restock_priority", "Restock", 10, None),
                   ("suggested_restock_qty", "Suggested Order Qty", 12, QTY),
                   ("item_status", "Status", 10, None)]
    header = _title(ws, "All Products", stamp, len(cols))
    _table(ws, header, cols, everything)

    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()
