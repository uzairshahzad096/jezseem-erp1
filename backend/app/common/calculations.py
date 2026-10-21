"""
Document calculation engine.

Spec section 8: "Calculations should not depend on manually entered totals."
Spec section 21 rule 8: "Backend is the source of truth."

So the API never trusts a total sent by the browser. The frontend computes
the same figures purely to give the user live feedback while typing; on save,
the server recalculates from quantity, rate, discount and tax and stores its
own result. If the two ever disagree, the server's answer wins.

Money is Decimal throughout, never float — floats lose cents on large
invoices, and this feeds the ledger.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

TWO_DP = Decimal("0.01")


def money(value) -> Decimal:
    """Round to 2 decimal places, half-up — the convention used on invoices."""
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(TWO_DP, rounding=ROUND_HALF_UP)


@dataclass
class LineInput:
    quantity: Decimal
    unit_price: Decimal
    discount_percent: Decimal = Decimal("0")
    discount_amount: Decimal | None = None
    tax_percent: Decimal = Decimal("0")


@dataclass
class LineResult:
    gross_amount: Decimal       # quantity x unit price
    discount_amount: Decimal
    taxable_amount: Decimal     # gross - discount  (the "XTAX Amount" column)
    tax_amount: Decimal         # the "STAX Amount" column
    net_amount: Decimal         # taxable + tax     (the "Amount" column)


@dataclass
class DocumentTotals:
    lines: list[LineResult] = field(default_factory=list)
    excluding_tax_value: Decimal = Decimal("0.00")
    discount_total: Decimal = Decimal("0.00")
    sales_tax_value: Decimal = Decimal("0.00")
    freight_amount: Decimal = Decimal("0.00")
    gross_amount: Decimal = Decimal("0.00")
    net_receivable: Decimal = Decimal("0.00")


def calculate_line(line: LineInput, tax_inclusive: bool = False) -> LineResult:
    """One document line, matching the Service Invoice column layout.

    With `tax_inclusive` the unit price already contains the tax (retail
    pricing): the tax is extracted from the price rather than added to it, so
    the line total is exactly quantity × price − discount.
    """
    quantity = Decimal(str(line.quantity or 0))
    unit_price = Decimal(str(line.unit_price or 0))
    gross = money(quantity * unit_price)

    # An explicit discount amount overrides the percentage, so a user who
    # types "500 off" gets exactly 500 rather than a re-derived percentage.
    if line.discount_amount is not None:
        discount = money(line.discount_amount)
    else:
        discount = money(gross * Decimal(str(line.discount_percent or 0)) / Decimal("100"))
    discount = min(discount, gross)

    rate = Decimal(str(line.tax_percent or 0))
    if tax_inclusive:
        total = money(gross - discount)
        taxable = money(total * Decimal("100") / (Decimal("100") + rate))
        return LineResult(gross_amount=gross, discount_amount=discount, taxable_amount=taxable,
                          tax_amount=money(total - taxable), net_amount=total)

    taxable = money(gross - discount)
    tax = money(taxable * rate / Decimal("100"))

    return LineResult(
        gross_amount=gross,
        discount_amount=discount,
        taxable_amount=taxable,
        tax_amount=tax,
        net_amount=money(taxable + tax),
    )


def calculate_document(
    lines: list[LineInput],
    freight_amount: Decimal | None = None,
    document_discount: Decimal | None = None,
    tax_inclusive: bool = False,
) -> DocumentTotals:
    """Roll up every line, then apply document-level freight and discount.

    The field names match the legacy export columns (Excluding Stax Value,
    Sale Tax Value, Gross Amount, Discount, Freight, Net Receivable) so the
    new figures can be reconciled against the old system directly.
    """
    results = [calculate_line(line, tax_inclusive) for line in lines]

    excluding_tax = money(sum((r.taxable_amount for r in results), Decimal("0")))
    tax_total = money(sum((r.tax_amount for r in results), Decimal("0")))
    line_discounts = money(sum((r.discount_amount for r in results), Decimal("0")))

    freight = money(freight_amount)
    doc_discount = money(document_discount)

    gross = money(excluding_tax + tax_total)
    net = money(gross + freight - doc_discount)

    return DocumentTotals(
        lines=results,
        excluding_tax_value=excluding_tax,
        discount_total=money(line_discounts + doc_discount),
        sales_tax_value=tax_total,
        freight_amount=freight,
        gross_amount=gross,
        net_receivable=net,
    )
