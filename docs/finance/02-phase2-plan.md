# Finance Phase 2 — Sales & Accounts Receivable: implementation map

Migration: `0009_sales_ar`. Built on Phase 1 (`0008`). The Phase 1 posting
engine remains the only code that writes journal entries.

## What the inspection found

| Fact | Consequence |
|---|---|
| `sales_documents` already holds quotations and sales orders, told apart by `doc_type`, with `source_document_id` for the chain and one shared lines table | Invoices, credit notes and debit notes become three more `doc_type`s. No separate invoice table |
| **Posting a sales order is the stock issue**: it writes outward `stock_ledger_entries` and sets `delivered_quantity` | "Delivery" = the posted sales order. The invoice never moves stock, so nothing is issued twice |
| Outward gate passes also move stock when approved, and have `sales_document_id`, but none of the 52 existing passes are linked to an order | Invoice-from-delivery is supported for outward gate passes, and references the pass lines |
| Stock movements from sales orders store the **selling price** as `unit_cost`, and there is no cost valuation engine | **No COGS in Phase 2** (see below) |
| 1,110 customers, all active, 114 used on documents. No customer has payment terms or credit days | Payment terms become master data. The customer gains an optional credit limit |
| 1,682 quotations, 277 sales orders (the brief's 1,664 / 190 figures do not match the database) | None are converted, posted or turned into AR |
| `app/common/calculations.py` does tax-exclusive line maths | Extended with an optional tax-inclusive mode. Existing callers are unchanged |
| Existing invoice PDFs print from sales orders | The same renderer prints real invoices, credit notes and debit notes |

## Reuse / extend / new

| Existing component | Decision |
|---|---|
| Customer (`business_partners`) | Reuse. Adds `credit_limit`, `default_payment_term_id` |
| Quotation | Reuse. Direct quotation → invoice only if AR settings allow it (off by default) |
| Sales Order | Reuse. Source of invoices; invoiced/remaining quantities derived |
| Sales Document + Lines | **Extend**: doc types `sales_invoice`, `credit_note`, `debit_note`; new header and line columns |
| Outward Gate Pass | Reuse as delivery reference |
| Inventory items | Reuse. No new item table |
| Accounting engine | Reuse. Gains `splits` (one key → several lines, e.g. revenue per product) and rounding absorption for foreign currency |
| Numbering (`document_series`) | Reuse: SI, CN, DN, RV (cash), BRV (bank) |
| Chart of accounts | Reuse. New control type `CUSTOMER_ADVANCE` (2160 Advances from Customers) |
| AR subledger (`ar_items`, `ar_allocations`) | New |
| Customer Receipt (`customer_receipts`) | New |
| Credit / Debit Note | New doc types on `sales_documents` |
| Tax codes, payment terms, payment methods, AR settings | New master data |
| AR Aging, Customer Statement, AR Reconciliation, registers, dashboard | New reports |

## Key rules

- **Where the figures come from.** Financial figures come from posted journal
  lines. Customer statement and AR balances = ledger lines on RECEIVABLE and
  CUSTOMER_ADVANCE accounts carrying the customer. Sales by customer and by
  product = revenue lines, which carry the customer and the item.
- **Subledger.** An `ar_items` row is written when a receivable document
  posts: invoice, debit note, credit note, receipt, or opening AR line. Its
  amount never changes. Outstanding = amount − active allocations, so there
  is no editable balance.
- **Receipts.** The allocated part credits AR. The unallocated part credits
  Customer Advances. Allocating an advance later posts Dr Advances / Cr AR.
  Unallocating posts the opposite.
- **Credit notes.** They credit AR in full and are auto-allocated to their
  invoice. Credit-to-invoice allocations move no GL.
- **Cancelling a posted invoice.** It reverses the posting journal, provided
  no allocation is active. The invoice stays visible, marked CANCELLED.
- **Journal screen reversals are blocked.** A journal owned by a sales/AR
  document can only be reversed through that document, which keeps the
  subledger and the GL together.
- **COGS.** Not posted in Phase 2. Stock issue happens when a sales order
  posts, and a correct cost needs the inventory valuation engine (Phase 4).
  COGS will post at stock issue through `STOCK_ISSUE_POSTED`. The invoice
  event keeps its `cogs` / `inventory` keys unused, so there can never be two
  COGS entries.
- **Historical sales orders cannot be invoiced.** Orders dated before
  `ar_settings.sales_order_cutoff_date` (default: start of the current
  financial year) are refused, so the old 277 orders can never become AR.
  Pre-go-live balances enter through Opening Balances.
- **Credit limit policy** (AR settings): NONE, WARN, BLOCK or APPROVAL.
- **Invoice numbers** restart each financial year. The single
  `uq_sales_doc_number` constraint is replaced by two partial unique indexes:
  (company, type, number) for quotations and orders, as today; (company,
  type, financial year, number) for the new document types.
- **Database guards**, as in Phase 1:
  - posted/cancelled invoices, credit notes and debit notes cannot be edited
    or deleted, and their lines change only while DRAFT;
  - posted receipts are immutable except for reversal;
  - `ar_items` and `ar_allocations` are append-only except for status.

## New accounting events

| Event | Entry |
|---|---|
| `SALES_INVOICE_POSTED` (extended) | Dr AR (or cash for a cash sale) / Cr Revenue (per line) / Cr Output tax (per tax code) / Cr Freight / Dr Discount |
| `CUSTOMER_RECEIPT_POSTED` (extended) | Dr Bank or Cash / Cr AR (allocated) / Cr Customer Advances (unallocated) |
| `CUSTOMER_ADVANCE_ALLOCATED` | Dr Customer Advances / Cr AR |
| `SALES_CREDIT_NOTE_POSTED` | Dr Sales Returns / Dr Output tax / Dr Freight / Cr AR |
| `SALES_DEBIT_NOTE_POSTED` | Dr AR / Cr Revenue / Cr Output tax |
