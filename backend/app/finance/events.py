"""
The accounting events the posting engine understands.

An event says what shape of entry a business transaction produces: which
lines, on which side, carrying which party. It never names an account. The
account for each line comes from `posting_rules`, which the company sets on
the Finance Settings screen. So "Dr Accounts Receivable / Cr Sales" is code,
and "Accounts Receivable is 1130" is data.

A caller supplies one amount per line key. A negative amount posts on the
opposite side, which is how an adjustment in either direction uses a single
event. The engine refuses the entry unless the lines balance, so a caller
that sends a revenue figure without the matching receivable is stopped
rather than half-posted.
"""

from dataclasses import dataclass, field

DEBIT = "debit"
CREDIT = "credit"


@dataclass(frozen=True)
class LineSpec:
    key: str
    side: str
    label: str
    #: "customer" / "supplier": the line carries that party from the request,
    #: so subledgers can be built from the ledger itself.
    party: str | None = None
    #: A required line must have an account configured whenever it carries
    #: an amount. An optional line with no amount is simply left out.
    required: bool = True


@dataclass(frozen=True)
class EventSpec:
    code: str
    label: str
    source_module: str
    lines: tuple[LineSpec, ...] = field(default_factory=tuple)
    #: Events whose lines come ready-made from the caller (manual journals,
    #: opening balances, bank transactions) rather than from rules.
    explicit_lines: bool = False
    description: str = ""


EVENTS: dict[str, EventSpec] = {e.code: e for e in [
    EventSpec(
        "SALES_INVOICE_POSTED", "Sales invoice posted", "sales",
        lines=(
            # A cash sale overrides this line's account with the till or bank.
            LineSpec("receivable", DEBIT, "Accounts receivable", party="customer"),
            LineSpec("revenue", CREDIT, "Sales revenue"),
            LineSpec("output_tax", CREDIT, "Output sales tax", required=False),
            LineSpec("freight", CREDIT, "Freight recovered", required=False),
            LineSpec("discount", DEBIT, "Sales discount (document level)", required=False),
            # Unused in Phase 2: COGS is posted at stock issue once inventory
            # valuation exists (Phase 4), never here as well.
            LineSpec("cogs", DEBIT, "Cost of goods sold", required=False),
            LineSpec("inventory", CREDIT, "Inventory", required=False),
        ),
        description="Dr Receivable / Cr Revenue, Output tax, Freight; Dr Discount.",
    ),
    EventSpec(
        "CUSTOMER_RECEIPT_POSTED", "Customer receipt posted", "ar",
        lines=(
            LineSpec("bank_cash", DEBIT, "Bank / cash"),
            LineSpec("wht", DEBIT, "Tax withheld by customer", required=False),
            LineSpec("receivable", CREDIT, "Accounts receivable (allocated part)",
                     party="customer", required=False),
            LineSpec("advance", CREDIT, "Customer advances (unallocated part)",
                     party="customer", required=False),
        ),
        description="Dr Bank/Cash / Cr Receivable for what is allocated, Cr Customer advances for the rest.",
    ),
    EventSpec(
        "CUSTOMER_ADVANCE_ALLOCATED", "Customer advance allocated", "ar",
        lines=(
            LineSpec("advance", DEBIT, "Customer advances", party="customer"),
            LineSpec("receivable", CREDIT, "Accounts receivable", party="customer"),
        ),
        description="Dr Customer advances / Cr Receivable. A negative amount unallocates.",
    ),
    EventSpec(
        "CUSTOMER_RECEIPT_REVERSED", "Customer receipt reversed", "ar",
        lines=(
            LineSpec("advance", DEBIT, "Customer advances", party="customer"),
            LineSpec("bank_cash", CREDIT, "Bank / cash"),
        ),
        description="Dr Customer advances / Cr Bank/Cash, after every allocation is undone.",
    ),
    EventSpec(
        "SALES_CREDIT_NOTE_POSTED", "Sales credit note posted", "ar",
        lines=(
            LineSpec("returns", DEBIT, "Sales returns / revenue adjustment"),
            LineSpec("output_tax", DEBIT, "Output sales tax", required=False),
            LineSpec("freight", DEBIT, "Freight recovered", required=False),
            LineSpec("receivable", CREDIT, "Accounts receivable", party="customer"),
        ),
        description="Dr Sales returns, Output tax / Cr Receivable.",
    ),
    EventSpec(
        "SALES_DEBIT_NOTE_POSTED", "Sales debit note posted", "ar",
        lines=(
            LineSpec("receivable", DEBIT, "Accounts receivable", party="customer"),
            LineSpec("revenue", CREDIT, "Revenue / other charges"),
            LineSpec("output_tax", CREDIT, "Output sales tax", required=False),
        ),
        description="Dr Receivable / Cr Revenue, Output tax.",
    ),
    EventSpec(
        "PURCHASE_INVOICE_POSTED", "Purchase invoice posted", "purchases",
        lines=(
            LineSpec("purchase", DEBIT, "Inventory / expense / GRNI clearing"),
            LineSpec("input_tax", DEBIT, "Input sales tax", required=False),
            LineSpec("payable", CREDIT, "Accounts payable", party="supplier"),
        ),
        description="Dr Inventory or Expense, Input tax / Cr Payable.",
    ),
    EventSpec(
        "SUPPLIER_PAYMENT_POSTED", "Supplier payment posted", "ap",
        lines=(
            LineSpec("payable", DEBIT, "Accounts payable", party="supplier"),
            LineSpec("bank_cash", CREDIT, "Bank / cash"),
            LineSpec("wht", CREDIT, "Withholding tax payable", required=False),
        ),
        description="Dr Payable / Cr Bank/Cash (and WHT payable).",
    ),
    EventSpec(
        "STOCK_RECEIPT_POSTED", "Stock received", "inventory",
        lines=(
            LineSpec("inventory", DEBIT, "Inventory"),
            LineSpec("grni", CREDIT, "Goods received not invoiced"),
        ),
        description="Dr Inventory / Cr GRNI.",
    ),
    EventSpec(
        "STOCK_ISSUE_POSTED", "Stock issued", "inventory",
        lines=(
            LineSpec("cogs", DEBIT, "Cost of goods sold / consumption"),
            LineSpec("inventory", CREDIT, "Inventory"),
        ),
        description="Dr COGS / Cr Inventory.",
    ),
    EventSpec(
        "EXPENSE_POSTED", "Expense posted", "expenses",
        lines=(
            LineSpec("expense", DEBIT, "Expense"),
            LineSpec("input_tax", DEBIT, "Input tax", required=False),
            LineSpec("bank_cash", CREDIT, "Bank / cash / payable"),
        ),
        description="Dr Expense / Cr Bank/Cash.",
    ),
    EventSpec(
        "BANK_TRANSACTION_POSTED", "Bank transaction posted", "bank",
        explicit_lines=True,
        description="Lines supplied by the bank module.",
    ),
    EventSpec(
        "DEPRECIATION_POSTED", "Depreciation posted", "assets",
        lines=(
            LineSpec("depreciation_expense", DEBIT, "Depreciation expense"),
            LineSpec("accumulated_depreciation", CREDIT, "Accumulated depreciation"),
        ),
        description="Dr Depreciation expense / Cr Accumulated depreciation.",
    ),
    EventSpec(
        "JOURNAL_ENTRY_POSTED", "Manual journal posted", "finance",
        explicit_lines=True,
        description="Lines entered by the user.",
    ),
    EventSpec(
        "OPENING_BALANCE_POSTED", "Opening balances posted", "finance",
        explicit_lines=True,
        description="Lines composed from an approved opening-balance batch.",
    ),
]}


def rule_keys() -> list[tuple[str, LineSpec]]:
    """Every (event, line) pair that needs an account configured."""
    return [(e.code, line) for e in EVENTS.values() for line in e.lines]
