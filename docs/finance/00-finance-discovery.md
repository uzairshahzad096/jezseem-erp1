# Finance & Accounting — Discovery and Design

Status: **awaiting approval.** Implementation will start once this is signed off.

This document answers §54 of the Finance specification ("before writing large
amounts of code, first inspect the existing ERP database and historical finance
data"). It covers items A–H in that order. Every statement about current data
was checked against the live `jezseem_erp` database on 29-Sep-2026 (Alembic
revision `0007`).

---

## Summary

1. **There is no historical finance data in this system to migrate.** No chart
   of accounts, vouchers, journals, receipts, payments, bank or tax records
   exist in the repository or the database. The old ERP's finance exports
   have never been supplied. Only inventory, contacts, quotations and sales
   orders were imported.
2. **The only finance-relevant history is 277 legacy sales orders.** Each
   carries a `PAID` / `PENDING` flag but no payment amount, date or method.
   151 of them are Posted and PENDING, worth PKR 31,797,055.15 across 34
   customers. That is a *candidate* receivables list. It is not a ledger.
3. **Procurement data is demo data.** All six suppliers, seven purchase
   orders, four shipments and three landed-cost vouchers come from
   `app/procurement/demo_data.py`. None of it should be migrated.
4. **Opening stock has no value.** All 402 opening-balance stock entries have
   `unit_cost = 0`, so the inventory account cannot be opened from system data.
5. **There is no audit-log table.** `app/audit/` is an empty package, although
   the README and `mixins.py` both refer to an `audit_logs` table.

My recommendation follows from point 1. Build the finance module on a **cut-over
date**. Open the ledger from a trial balance your accountant approves, plus open
customer and supplier item lists. Treat the legacy sales orders as reference
history, not ledger postings. The alternative is to obtain the old ERP's voucher
data and run the full §32 migration. That can still be done later through the
staging design in section H, without redesigning anything.

---

## A. Current database structure

Stack: FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 16. Every business table
uses a UUID primary key and `AuditMixin` (`created_at/by`, `updated_at/by`).
Company and branch scoping is available through `CompanyScopedMixin`.

| Area | Tables | Rows |
|---|---|---|
| Organisation | `companies`, `branches`, `financial_years` | 1 / 1 / 1 |
| Security | `users`, `roles`, `permissions`, `role_permissions`, `user_roles`, `user_company_access`, `user_branch_access` | 1 / 1 / 617 / … |
| Partners | `business_partners`, `partner_contacts` | 1,116 / 0 |
| Inventory | `inventory_items`, `main_products`, `inventory_sub_categories`, `inventory_sub_detail_categories`, `item_racks`, `item_locations`, `unit_of_measures`, `item_uom_conversions` | 4,981 items |
| Stock | `stock_ledger_entries` (immutable movement log) | 428 |
| Sales | `sales_documents` (quotations + sales orders), `sales_document_lines` | 1,959 / 2,084 |
| Gate passes | `gate_passes`, `gate_pass_lines` | 66 / 80 |
| Procurement | `in_house_orders`, `purchase_orders`, `import_shipments`, `landed_costs` (+ charges, items, allocations, charge types), `material_receiving_notes`, `mrn_lines` | demo |
| Numbering | `document_sequences` | 11 |
| Import staging | `inventory_item_import`, `quotation_import_source`, `quotation_import_mapping`, `product_stock_location_import/_mapping` | — |

## B. Existing finance-related structures

There are no accounting tables. The following existing structures are what the
finance module must build on or post from:

| Structure | What it holds | What Finance does with it |
|---|---|---|
| `companies.default_currency` | `PKR` | Becomes the base currency |
| `financial_years` | `2026-27`, 01-Jul-2026 → 30-Jun-2027. Dates are stored as **strings** | Convert to `DATE`, then add accounting periods |
| `business_partners` | Customers and suppliers in one table, with `is_customer` / `is_supplier`, `ntn`, `stn`, `credit_days`, `currency`, bank details | Becomes the AR/AP subledger party. No separate customer or supplier tables |
| `sales_documents` (sales_order) | Totals: `excluding_tax_value`, `sales_tax_value`, `freight_amount`, `net_receivable`, plus `payment_status` | Source document for sales/AR postings |
| `purchase_orders` | Currency, `exchange_rate`, `net_payable`, `net_payable_base` | Commitments only. No GL effect |
| `material_receiving_notes` + `mrn_lines.unit_cost_base` | Goods received, costed in PKR | Source for the *Dr Inventory / Cr GRNI* posting |
| `landed_costs` + charges/allocations | Freight, insurance, customs, tax, port, clearing, bank and other costs, allocated to items | Source for capitalising import costs into inventory |
| `landed_cost_charge_types.account_code`, `.is_inventoriable` | Already reserved "for when there is a chart of accounts" | Becomes a foreign key to `accounts` |
| `stock_ledger_entries` | `direction`, `quantity`, `unit_cost`, `source_type/id/number` | Source for COGS and adjustment postings. Its `source_*` drill-down pattern is reused for journals |
| `document_sequences` + `next_number()` | Per company, fiscal year and doc type, with a `FOR UPDATE` lock | Reused for JV/CPV/CRV/BPV/BRV numbering |
| `common/calculations.py` | Server-side line and tax maths (reproduces the Service Invoice at 18%) | Unchanged. Tax *codes* will feed it the rate instead of a free `tax_percent` |
| `permissions` (seed `MODULES["finance"]`) | `accounts, journals, invoices, payments, reports` × 9 actions | Replaced by the full finance permission set (section G.9) |
| Frontend `navigation.ts` Finance menu | 5 links, all 404 | Replaced by the §42 menu |

## C. Sample historical records

**Sales orders by fiscal year and payment flag.** These are the only legacy
records with a financial meaning.

| FY | Status | Payment | Tax invoice | Docs | Excl. tax | Sales tax | Net receivable |
|---|---|---|---|---|---|---|---|
| 2023-24 | Posted | PENDING | No | 11 | 2,185,085.00 | 0.00 | 2,185,085.00 |
| 2023-24 | Posted | PENDING | Yes | 2 | 295,000.00 | 12,600.00 | 307,600.00 |
| 2024-25 | Posted | PAID | Yes | 15 | 7,058,487.00 | 1,270,527.66 | 8,329,014.66 |
| 2024-25 | Posted | PENDING | No | 29 | 6,176,713.00 | 0.00 | 6,176,713.00 |
| 2024-25 | Posted | PENDING | Yes | 18 | 3,097,210.00 | 557,497.80 | 3,654,707.80 |
| 2025-26 | Posted | PAID | No | 36 | 3,839,206.00 | 0.00 | 3,839,206.00 |
| 2025-26 | Posted | PENDING | No | 70 | 15,248,505.01 | 0.00 | 15,248,505.01 |
| 2025-26 | Posted | PENDING | Yes | 20 | 3,537,665.00 | 636,779.34 | 4,174,444.34 |
| *(plus Draft rows and smaller groups; 277 sales orders in total, dated 08-Aug-2023 → 2026)* |

**Stock ledger by source.**

| Source | Direction | Entries | Value (qty × unit_cost) |
|---|---|---|---|
| opening_balance | in | 402 | **0.00** (every unit_cost is 0) |
| goods_receipt | in | 16 | 11,602,434.28 (demo) |
| goods_receipt_reversal | out | 3 | 10,451,784.28 (demo) |
| sales_order | out | 2 | 482,840.00 |

**Anomalies that affect accounting.**

| # | Finding | Count |
|---|---|---|
| 1 | Sales order marked "without sales tax" but carrying tax | 2 docs, PKR 9,090 |
| 2 | Sales order marked "with sales tax" but carrying zero tax | 4 docs |
| 3 | Tax rate other than 18% | 1 doc at 31% |
| 4 | Sales orders with no `fiscal_year` value | all 277 (quotations have it) |
| 5 | `PAID` / `PENDING` with no amount, date or reference (`payment_reference` is null on every order) | 277 |
| 6 | Quotations dated in the future (1537 → 01-Oct-2026, 1538 → 01-Nov-2026) | 2 |
| 7 | Opening stock with zero cost | 402 entries |

## D. Proposed accounting interpretation

| Legacy record | Interpretation | Confidence |
|---|---|---|
| Sales order, status **Posted** | A delivered and invoiced sale: stock has left (it writes outward stock entries) | High for stock. **UNKNOWN — REQUIRES BUSINESS CONFIRMATION** whether it is also the tax invoice, or whether a separate invoice exists in the old ERP |
| Sales order, status **Draft** | Not invoiced, so no accounting effect | Medium |
| `payment_status = PAID` | Customer has settled in full, on an unknown date and by an unknown method | **UNKNOWN — REQUIRES BUSINESS CONFIRMATION** (could be a manual flag that was never kept up to date) |
| `payment_status = PENDING` | Amount still owed | Same as above |
| `with_sales_tax = false` | Non-tax ("simple") invoice; no output tax | Medium. Contradicted by anomaly 1 |
| `net_receivable` | Amount the customer owes: excl. tax − discount + tax + freight | High (matches `calculations.py`) |
| `freight_amount` on sales | Recharged to the customer. **UNKNOWN — REQUIRES BUSINESS CONFIRMATION** whether it is revenue or a recovery credited against freight expense |
| Business partner flags | `is_customer` → receivable party; `is_supplier` → payable party. One party can be both | High |
| Landed-cost charge with `is_inventoriable = true` | Capitalised into inventory value | High (by design) |

**Proposed standard postings** (all configurable through posting rules, G.4):

| Event | Debit | Credit |
|---|---|---|
| Sales invoice (posted SO) | Accounts Receivable (party) | Sales Revenue; Output Sales Tax; Freight Recovered |
| Sale — cost | Cost of Goods Sold | Inventory |
| Goods receipt (MRN) | Inventory | Goods Received Not Invoiced (GRNI) |
| Supplier invoice | GRNI; Input Sales Tax | Accounts Payable (party) |
| Landed cost, inventoriable charge | Inventory | AP (the charge's own vendor) / Accrued Import Costs |
| Landed cost, non-inventoriable | Import Expense | AP / Accrued |
| Customer receipt | Cash / Bank | AR (allocated to invoices) |
| Supplier payment with WHT | AP | Bank; WHT Payable |
| Stock adjustment | Inventory Adjustment (P&L) | Inventory, or the reverse |
| Depreciation | Depreciation Expense | Accumulated Depreciation |
| Realised FX difference | AP / AR | Exchange Gain, or Dr Exchange Loss |

## E. Old-to-new mapping

### What exists today

| Source | Target | Rule |
|---|---|---|
| `business_partners` (is_customer) | AR party on `journal_entry_lines.partner_id` + `open_items` | Direct. No copy is made. Code and name stay on the partner |
| `business_partners` (is_supplier) | AP party | Direct. **Exclude the six `SUP-*` demo suppliers** |
| Sales order, Posted + PENDING | `open_items` (type `opening_invoice`), `legacy_ref = doc_number`, due date = doc_date + `credit_days` | Only after business confirms the PENDING list (F.3). The total goes into the opening journal as Dr AR / Cr Opening Balance Equity |
| Sales order, Posted + PAID | No GL entry. Kept as sales history | Nothing to settle at cut-over |
| Sales order before cut-over | Remains in `sales_documents`. Sales reports keep working | Never re-posted to the GL |
| Stock `opening_balance` entries | Inventory opening value | **Blocked until item costs are supplied** (F.6) |
| `landed_cost_charge_types.account_code` (text) | `landed_cost_charge_types.account_id` (FK) | Mapped once the chart of accounts is approved |
| `financial_years.start_date/end_date` (text) | Same columns as `DATE` | Lossless Alembic type change |
| Procurement demo rows | — | Excluded. Recommend deleting them before go-live |

### What the old ERP will need to provide, if a full migration is wanted

The §32 mapping table (old account code → new account, old voucher type →
journal type, and so on) cannot be filled in without these exports. When they
arrive, each goes into a staging table unchanged (section H).

| Export needed from the old ERP | Used for |
|---|---|
| Chart of accounts (code, name, parent, type) | `legacy_account_map` |
| Voucher list with lines: JV / CPV / CRV / BPV / BRV and any others, with date, number, account, party, Dr, Cr, narration | Historical journals |
| Trial balance at the cut-over date, signed by the accountant | **Opening journal (minimum requirement)** |
| Customer ledger / ageing at cut-over | AR open items |
| Supplier ledger / ageing at cut-over | AP open items |
| Bank statements and bank book balance at cut-over, per account | Bank opening + first reconciliation |
| Cash-in-hand at cut-over | Cash opening |
| Item-wise stock valuation at cut-over | Inventory opening value, and the fix for the zero unit costs |
| Fixed-asset register (cost, date, accumulated depreciation) | Asset opening |
| Last sales tax and WHT returns | Tax payable/receivable opening |

## F. Items requiring business confirmation

Each of these is marked **UNKNOWN — REQUIRES BUSINESS CONFIRMATION** in the design.

1. **Cut-over approach.** Opening balances at a cut-over date (recommended),
   or full historical voucher migration? If the latter, can the old ERP's
   finance data be exported, and in what form (SQL backup, Excel, CSV)?
2. **Cut-over date.** Suggested 01-Jul-2026, the start of FY 2026-27, so the
   whole current year sits in one system. This means re-entering Jul–Sep 2026
   transactions. The alternative is 01-Oct-2026.
3. **Is the PENDING list accurate?** Do the 151 posted PENDING orders (PKR 31.8M,
   34 customers) match the accountant's customer ledger? Are partial payments
   recorded anywhere?
4. **Is a posted sales order the invoice?** Or does the old ERP issue a
   separate sales invoice document?
5. **Existing chart of accounts.** Should the old account codes be kept, or
   should the §5 structure (1000 Assets, 1100 Current Assets, …) be adopted?
6. **Opening stock costs.** Where do item unit costs at cut-over come from?
7. **Inventory costing method.** Weighted average (recommended, and what
   `mrn_lines.unit_cost_base` supports) or FIFO?
8. **Perpetual inventory accounting.** Should every stock movement post COGS
   and inventory in real time (recommended), or should inventory be adjusted
   periodically?
9. **Sales freight.** Revenue, or a recovery of freight expense?
10. **Tax registrations.** Which apply: federal sales tax (FBR), provincial
    sales tax on services (PRA / SRB / KPRA / BRA), WHT agent status? Which
    WHT sections are used on supplier payments and on receipts?
11. **Document number format.** The spec shows `JV-000001`. Existing
    documents use per-type formats (`202609221`, `10-26`). Confirm the finance
    format, and whether it resets each fiscal year.
12. **Approval limits.** Who approves journals and payments, and above which
    amounts?
13. **Branches and cost centres.** One branch today (Head Office). Which cost
    centres, departments and profit centres are actually used?
14. **Bank accounts.** List of bank accounts (bank, branch, title, IBAN,
    currency).
15. **Payroll.** HRMS is not built. Should payroll post a monthly summary
    journal for now?
16. **The 7 data anomalies in C.** Correct them at source, or carry them
    as-is with a note?

## G. Proposed new database schema

All tables are company-scoped, UUID-keyed and carry `AuditMixin`. Money is
`NUMERIC(18,2)` in base currency. Foreign amounts are `NUMERIC(18,2)` with a
`NUMERIC(18,6)` rate, following the existing procurement convention. Code lives
in a new `backend/app/finance/` package with one sub-module per area, matching
`procurement/` (models, schemas, service, router).

### G.1 Organisation and periods (Phase 1)

- `financial_years`: *existing*. Dates change to `DATE`. Add
  `status (open|closing|closed)`, `retained_earnings_account_id`.
- `accounting_periods`: `financial_year_id`, `period_number` (0 = opening,
  1–12 monthly, 13 = adjustment), `name`, `start_date`, `end_date`,
  `status (open|closed|locked)`, `closed_by/at`. Unique `(financial_year_id, period_number)`.
- `period_status_log`: every close and reopen, with user, reason and timestamp.
- `currencies`: `code` (PK), `name`, `symbol`, `decimals`. Replaces the dict
  in `common/currency.py`, which becomes a lookup.
- `exchange_rates`: `currency`, `rate_date`, `rate_type (buying|selling|average|customs)`, `rate`.
- `dimensions`: `cost_centers`, `profit_centers`, `departments`, `projects`.
  Each has code, name, `parent_id` and active. Separate tables, so foreign keys
  stay real.

### G.2 Chart of accounts (Phase 1)

- `account_groups`: `code`, `name`, `nature (asset|liability|equity|revenue|expense)`,
  `statement (BS|PL)`, `report_section` (for statement layout, e.g.
  "current_assets", "cost_of_sales"), `cash_flow_category`, `sort_order`, `parent_id`.
- `accounts`: `code`, `name`, `parent_id`, `group_id`, `normal_balance (Dr|Cr)`,
  `is_postable` (headers are false), `control_type`
  (`none|receivable|payable|bank|cash|tax|inventory|grni`), `currency` (null =
  any), `default_cost_center_id`, `requires_cost_center`, `is_active`,
  `description`. Unique `(company_id, code)`.
  A control account accepts postings **only from its subledger service**. A
  manual JV cannot hit AR or AP directly, which is what keeps AR/AP equal to the GL.
- Opening balances are not stored on the account. They are an `opening`
  journal in period 0, so there is one source of truth.

### G.3 Journals and General Ledger (Phase 1)

- `journal_entries`: `number`, `journal_type`
  (`manual|adjustment|accrual|reversal|opening|closing|transfer|fx_revaluation|depreciation|tax_adjustment|system`),
  `entry_date`, `posting_date`, `financial_year_id`, `period_id`, `branch_id`,
  `currency`, `exchange_rate`, `reference`, `narration`,
  `status (draft|submitted|approved|posted|reversed|cancelled)`,
  `source_type`, `source_id`, `source_number` (drill-down, the same pattern as
  `stock_ledger_entries`), `reversal_of_id`, `reversed_by_id`,
  `submitted_by/at`, `approved_by/at`, `posted_by/at`, `total_debit`,
  `total_credit`, plus the legacy fields (G.8).
- `journal_entry_lines`: `line_number`, `account_id`, `debit`, `credit`,
  `currency`, `amount_fc`, `exchange_rate`, `partner_id`, `cost_center_id`,
  `profit_center_id`, `department_id`, `project_id`, `tax_code_id`,
  `open_item_id`, `description`.
  `CHECK (debit >= 0 AND credit >= 0 AND (debit = 0) <> (credit = 0))`.
- **General Ledger = posted `journal_entry_lines`.** No mutable balance column
  anywhere. At current volumes (~2,000 documents in 3 years) balances are
  computed on read. An `account_period_balances` summary can be added later,
  refreshed only by the posting service, if reports slow down.
- **Database-level guarantees** (not just service code):
  - a constraint trigger raises if a journal moves to `posted` with Σdebit ≠
    Σcredit or fewer than 2 lines;
  - a trigger blocks `UPDATE`/`DELETE` on lines of posted journals and on
    posted headers, except the `status → reversed` transition;
  - a trigger rejects posting into a closed period, or to a non-postable or
    inactive account.

### G.4 Posting engine (Phase 1 core, used by every phase)

- `posting_rules`: `event` (e.g. `sales_invoice.revenue`,
  `sales_invoice.output_tax`, `mrn.inventory`, `mrn.grni`, `sale.cogs`,
  `receipt.bank`, `payment.wht`), with optional match keys (`main_product_id`,
  `partner_id`, `branch_id`, `tax_code_id`, `charge_type_id`) → `account_id`.
  The most specific match wins.
- `finance/posting.py`: the **only** code that writes journal entries. Other
  modules call `post_document(db, source_type, source_id)`. It builds the
  lines from the rules, validates them and posts in the caller's transaction.
  Sales, procurement and inventory never touch accounts directly (§45).

### G.5 Subledgers — AR and AP (Phase 2)

- `open_items`: one row per receivable or payable: `partner_id`,
  `side (AR|AP)`, `document_type`, `document_id`, `document_number`,
  `document_date`, `due_date`, `currency`, `amount`, `amount_base`,
  `open_amount`, `open_amount_base`, `status (open|partial|settled)`,
  `journal_entry_id`.
- `receipts` / `payments`: header with party, method
  (`cash|cheque|online|pay_order`), cash/bank account, cheque no/date,
  amount, WHT, currency, status and journal link.
- `allocations`: `from_item_id` → `to_item_id`, amount, amount_base, FX
  difference, date. `CHECK`, plus a service rule that an allocation never
  exceeds either side's open amount.
- `credit_notes` / `debit_notes`, and a `supplier_invoices` document (header +
  lines, matched to MRN lines for 3-way match: PO ↔ MRN ↔ invoice).
- Customer credit limit: add `credit_limit` to `business_partners`.
- `sales_documents.payment_status` becomes **derived** from open items rather
  than hand-set.

### G.6 Cash, bank and reconciliation (Phase 3)

- `bank_accounts`: bank, branch, title, account no, IBAN, currency,
  `account_id` (GL, `control_type = bank`).
- `cash_accounts`: name, custodian, branch, `account_id`.
- `cheques`: number, date, bank account, party, amount,
  `status (issued|presented|cleared|bounced|cancelled)`, direction.
- `bank_statements` + `bank_statement_lines` (imported CSV/Excel or entered).
- `bank_reconciliations` + `reconciliation_matches` (statement line ↔ GL
  line, many-to-many for partial matches).

### G.7 Tax (Phase 4)

- `tax_authorities`: FBR, PRA, SRB, KPRA, BRA (configurable).
- `tax_codes`: code, name, `tax_type (sales_tax|further_tax|extra_tax|wht|income_tax)`,
  authority, `applies_to (sale|purchase|payment|receipt)`,
  `payable_account_id`, `recoverable_account_id`, `is_inclusive`, `is_exempt`,
  `is_zero_rated`, `wht_section`.
- `tax_rates`: `tax_code_id`, `rate`, `effective_from`, `effective_to`. Rates
  are never hard-coded (§14).
- `tax_code_rules`: which codes apply by partner (filer/non-filer, NTN/STN
  present), item category or transaction type.
- `tax_transactions`: written by the posting engine for every taxed line
  (base, rate, tax, code, document), so tax reports read posted data only.
- `wht_certificates`: number, party, period, section, amount.

### G.8 Assets, expenses, budgets and migration (Phases 5–8)

- `asset_categories` (default life, method, the 3 GL accounts),
  `fixed_assets`, `depreciation_runs`, `depreciation_lines`,
  `asset_transactions` (transfer, disposal, revaluation).
- `expense_categories`, `expense_claims`, `expense_claim_lines`,
  `employee_advances`.
- `budgets`, `budget_lines` (account × period × dimension).
- Legacy columns on `journal_entries`, `open_items`, `receipts`, `payments`:
  `legacy_system`, `legacy_table`, `legacy_record_id`, `legacy_voucher_no`,
  `import_batch_id`.
- `migration_batches`: source, file, record/success/failure/duplicate counts,
  imported by/at, status.
- `legacy_staging_*`: one per source file, raw columns kept as text plus
  `row_no`, `batch_id`, `validation_status`, `errors (jsonb)`,
  `mapped_target_id`.
- `legacy_account_map`, `legacy_voucher_type_map`, `legacy_party_map`.

### G.9 Cross-cutting

- `audit_logs` (**missing today**): table, record_id, action, before (jsonb),
  after (jsonb), user, IP, session, timestamp. Written by a SQLAlchemy session
  event for finance tables, so no code path can skip it.
- `document_sequences`: *existing*. Add `branch_id` (nullable) and a
  `format` pattern column (e.g. `JV-{seq:06}`), so the format is configuration.
- `approval_rules`: doc_type, role, branch, department, `min_amount`,
  `max_amount`, `level`. `approval_actions`: document, level, user, decision,
  comment, timestamp.
- Permissions: replace `finance: [accounts, journals, invoices, payments, reports]`
  with `accounts, journals, ledger, ar, ap, cash, bank, reconciliation, tax,
  assets, expenses, dimensions, budgets, statements, closing, opening, migration,
  settings`. Add the actions `reverse`, `close_period`, `reopen_period`,
  `view_sensitive` to the finance modules.

## H. Migration strategy

```
Old ERP export ─► legacy_staging_* (raw, never modified)
                        │ validate (duplicates, missing refs, Dr≠Cr, dates, FY, tax codes)
                        ▼
                  mapping tables (account, voucher type, party) — resolved on
                  Finance → Legacy Data Migration screen
                        │ import only rows with status = valid
                        ▼
                  journal_entries / open_items (legacy_* fields filled, batch id)
                        │
                        ▼
                  Reconciliation report: legacy TB vs new TB per account,
                  customer, supplier, bank, cash, inventory, tax
```

Rules:

- Source files are copied into `data/finance/legacy/` and never edited. Staging
  rows are never deleted. A re-run creates a new batch.
- Failed rows are corrected in staging (with audit) and re-processed. Rows
  already imported match on `legacy_record_id` and are skipped, the same
  idempotent pattern as `inventory/import_legacy.py`.
- The migration is complete only when the reconciliation report shows zero
  difference against the accountant-approved legacy trial balance (§48).

**Recommended cut-over sequence** (based on F.1–F.2):

1. Approve the chart of accounts and posting rules.
2. Load the accountant's trial balance at cut-over → one `opening` journal in
   period 0. The system refuses it unless Dr = Cr.
3. Load customer and supplier open items. Their totals must equal the AR and AP
   control-account lines in the opening journal. The Opening Balance
   Verification Report shows both figures side by side.
4. Load bank, cash, inventory (item-wise, which also fixes the zero unit costs)
   and fixed-asset openings. Each must tie to its control account.
5. Turn on automatic posting from sales, procurement and inventory from the
   cut-over date forward.

---

## Implementation plan after approval

The spec's §51 phases, each delivered and tested before the next starts:

| Phase | Delivers | Depends on answers |
|---|---|---|
| 1 Foundation | Periods, currencies, dimensions, CoA, journals (full status workflow and reversal), posting engine, GL with drill-down, trial balance, audit log, finance permissions and menu | F.5, F.11, F.12 |
| 2 Subledgers | Open items, receipts, payments, allocations, credit/debit notes, supplier invoice with 3-way match, sales/MRN/landed-cost auto-posting, ageing, statements | F.3, F.4, F.7, F.8, F.9 |
| 3 Cash & bank | Cash book, bank accounts, cheques, transfers, statement import, reconciliation | F.14 |
| 4 Tax | Tax codes and rates, sales tax, WHT, certificates, tax reports | F.10 |
| 5 Assets & expenses | Asset register, depreciation run, expense claims | — |
| 6 Dimensions & budgets | Cost/profit centre reports, budget vs actual | F.13 |
| 7 Advanced | FX revaluation, balance sheet, P&L, cash flow, equity statement, dashboard, period and year-end close | — |
| 8 Migration | Staging, mapping screen, validation, import, reconciliation | F.1, legacy exports |

Tests for every phase include the invariant **Σ trial-balance debits = Σ credits,
and the balance sheet balances,** asserted after every posting test (§52).
