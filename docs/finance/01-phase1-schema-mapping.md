# Finance Phase 1 — Schema Mapping

What Phase 1 reuses, what it adds, and what it deliberately leaves alone.
Migration: `backend/migrations/versions/0008_finance_foundation.py`.

## Reused — referenced by foreign key, never duplicated

| Existing table | Used by Finance as |
|---|---|
| `companies` | `company_id` on every finance table |
| `branches` | `branch_id` on journals, journal lines, opening batches and lines |
| `financial_years` | `financial_year_id` on periods, journals and opening batches. New years are created in this same table. Its string date columns are read as ISO dates and are **not altered** |
| `users` | `created_by`, `posted_by`, `approved_by`, … and `audit_logs.user_id` |
| `permissions`, `roles`, `role_permissions` | The 11 finance permission codes are rows in `permissions`, granted to Administrator. There is no second authorisation system |
| `user_company_access`, `user_branch_access` | Enforce the finance company and branch context for non-superusers |
| `business_partners` | `customer_id` / `supplier_id` on journal lines and opening lines (role flags checked) |
| `inventory_items` | `inventory_item_id` on journal lines and opening lines |
| `item_locations` | Warehouse on inventory opening lines |
| `document_sequences` | Counters for finance numbering. Gains a nullable `branch_id`; existing rows and callers are unaffected |

Not touched: `sales_documents` and their lines, quotations, `stock_ledger_entries`,
procurement and gate-pass tables. No existing row is updated or deleted by
the migration.

## New tables

| Table | Purpose |
|---|---|
| `account_types` | Global reference: ASSET, LIABILITY, EQUITY, REVENUE, COST_OF_SALES, EXPENSE, OTHER_INCOME, OTHER_EXPENSE, with normal balance and statement |
| `account_groups` | Company-scoped report groupings (Current Assets, Current Liabilities, …) |
| `accounts` | Chart of accounts. Hierarchical, with header/posting flag, control type, manual-posting flag |
| `cost_centers` | Minimal dimension so `journal_entry_lines.cost_center_id` is a real FK |
| `accounting_periods` | Monthly periods per financial year: OPEN / CLOSED / LOCKED |
| `document_series` | Numbering configuration per document type: prefix, padding, reset per FY, per branch |
| `journal_entries` | Journal header with status workflow and source-document reference |
| `journal_entry_lines` | Debit/credit lines, transaction and base amounts, partner/item/branch/cost-centre dimensions |
| `posting_rules` | Event + line key → account. The configurable half of the posting engine |
| `opening_balance_batches` | One accountant-prepared opening position |
| `opening_balance_lines` | GL / AR / AP / INVENTORY / BANK schedule rows, with raw values kept |
| `opening_balance_imports` | Each uploaded file, with a SHA-256 hash for duplicate detection |
| `opening_balance_reconciliations` | Legacy vs ERP balance per category, with difference and explanation |
| `audit_logs` | Append-only audit trail (UPDATE/DELETE blocked by trigger) |

## Database-enforced accounting rules

These hold even if a future module, script or SQL session bypasses the service layer:

- line amounts are ≥ 0, and exactly one of debit/credit is positive (CHECK);
- a journal cannot be inserted as POSTED. It must go DRAFT → lines → POSTED;
- moving to POSTED requires ≥ 2 lines, Σ base debit = Σ base credit, an OPEN
  period covering the date, and active posting accounts of the same company;
- a POSTED journal can change only to REVERSED; REVERSED and CANCELLED are final;
- lines can be inserted, updated or deleted only while their journal is DRAFT;
- non-draft journals cannot be deleted;
- journal numbers are unique per company and financial year;
- one POSTED system journal per (source document, event), so a document cannot post twice;
- opening lines are frozen once their batch is APPROVED;
- `audit_logs` rows cannot be updated or deleted.

## Not in Phase 1

No journal is created from existing sales orders, stock movements or demo
procurement data. The sales-invoice, receipt, purchase-invoice and payment
events exist in the posting engine and are covered by tests. They are not
wired into the sales or procurement screens; that is Phase 2.
