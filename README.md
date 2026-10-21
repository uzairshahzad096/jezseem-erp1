# Jezseem ERP

Production-track ERP for Jezseem Traders. Modular monolith: Next.js/TypeScript
frontend, FastAPI backend, PostgreSQL.

Docker is **optional**. You run the backend and frontend directly on your
machine, which gives fast reload and readable errors. Docker stays available
for deploying to the company server later.

---

## What you need installed

| | |
|---|---|
| Python 3.11+ | python.org — tick "Add Python to PATH" |
| Node.js LTS | nodejs.org |
| PostgreSQL 16 | postgresql.org — *or* use Docker for just the database, below |

## First-time setup

```bat
scripts\setup.bat
```

It creates `.env` and pauses so you can fill it in. Set these four:

| Variable | What to put |
|---|---|
| `POSTGRES_PASSWORD` | anything you choose |
| `DATABASE_URL` | the **same** password inside it |
| `SECRET_KEY` | a long random string |
| `SEED_ADMIN_PASSWORD` | 10+ characters |

Then it builds the Python virtual environment and installs all packages.

### Getting PostgreSQL running

**Either** install it natively and create the database:

```sql
CREATE DATABASE jezseem_erp;
CREATE USER jezseem WITH PASSWORD 'your-password';
GRANT ALL PRIVILEGES ON DATABASE jezseem_erp TO jezseem;
```

**Or** let Docker run just the database — no building, no app containers:

```bat
docker compose up -d
```

## Create the tables and seed data

```bat
scripts\migrate.bat
```

Applies the migration, then creates the permission catalogue (~600 codes),
the Administrator role, Jezseem Traders, Head Office, the financial year and
the `admin` user, plus the finance structure: the standard chart of accounts
(if none exists), numbering series, posting rules and accounting periods. No
balance or journal is ever seeded.

## Import the legacy inventory data

The three Excel exports from the current ERP sit in `data/inventory/`:

```bat
scripts\import-inventory.bat
```

This loads 7 main products, 28 sub-categories, 57 sub-detail categories and
~4,980 items, then prints a migration report (imported / updated / skipped /
failed) and a reconciliation table you can compare against the old system.
It is safe to run repeatedly — records match on their natural keys and are
updated rather than duplicated.

## Import customers

```bat
scripts\import-partners.bat
```

Loads the Contacts Grid export into customers and their contacts.

## Run it

```bat
scripts\dev.bat
```

Two windows open — backend and frontend.

| | |
|---|---|
| Application | http://localhost:3000 |
| API docs | http://localhost:8000/api/docs |
| Health check | http://localhost:8000/api/health |

Close the two windows to stop. On Linux/macOS use the `.sh` equivalents.

---

## Authentication is currently switched off

`AUTH_DISABLED=true` in `.env` means the dashboard opens without signing in.
Every request runs as the seeded `admin` and permission checks pass.

The auth system is fully present: `/login` works, `POST /api/v1/auth/login`
works, and every endpoint still declares its `require_permission(...)`
dependency. To switch it on, set `AUTH_DISABLED=false` and restart the
backend — no code changes.

The backend **refuses to start** with `AUTH_DISABLED=true` and
`ENVIRONMENT=production`.

---

## Structure

```
backend/app/
  core/       config, database, celery, seed
  auth/       password hashing, JWT, dependencies, login router
  users/      User / Role / Permission models
  companies/  Company / Branch / FinancialYear models + router
  dashboard/  summary endpoint
  finance/    chart of accounts, periods, journals, posting engine, ledger,
              trial balance, opening balances
  audit/      append-only audit log
backend/migrations/    Alembic (0001 … 0008 finance foundation)
backend/tests/         pytest suite (finance)

frontend/
  app/         layout, dashboard page, login page
  components/  layout/{Sidebar,Topbar}
               dashboard/{StatCard,Panel,EChart,ActivityList,ProductCarousel}
  lib/         api, navigation, chartOptions, useTheme

scripts/      setup / migrate / dev / reset-password
docker/       full containerised stack, for server deployment
```

## Deploying to the company server (later)

The full Docker stack is still the intended path for the Ubuntu server, so the
deployment is reproducible rather than hand-assembled:

```bash
docker compose -f docker/docker-compose.full.yml up --build
```

That brings up Postgres, Redis, the backend, a Celery worker, the frontend and
Nginx together. The application code is identical either way.

---

## Inventory module

Built from the discovery document and screenshots of the current ERP.

```
Inventory
├── Setup Forms
│   ├── Item Racks                      full CRUD
│   ├── Item Locations                  full CRUD
│   ├── Main Products                   full CRUD
│   ├── Inventory Sub Category          full CRUD
│   ├── Inventory Sub Detail Category   full CRUD
│   └── Product Details                 faceted search, card grid, item form
├── Transactions        not documented yet
├── In House Order      not documented yet
└── Reports             not documented yet
```

The category chain is three levels, as in the old system:
Main Product → Sub Category → Sub Detail Category → Item. Dependent dropdowns
mean an invalid combination cannot be submitted, and deletes are blocked when
child records or items still reference the row.

## Sales & procurement

```
Inventory
├── Transactions
│   ├── Product Quotation    full: listing, filters, form, status, 3 PDFs, convert
│   ├── Product Sale Order   full: listing, filters, form, status, 5 PDFs, stock posting
│   ├── Outward Gate Pass    tables + API; screens next
│   └── Inward Gate Pass     tables + API; screens next
├── In House Order
│   ├── Purchase Order       tables + API; screens next
│   └── Material Receiving   tables + API; screens next
└── Reports
    ├── Product Stock        full, reads the stock ledger
    └── Product Sales        full, with filters and totals
```

**Document flow.** An approved quotation converts into a sales order with one
click, carrying the customer, products, quantities and prices across; the
quotation is then closed and cannot be converted twice. Posting a sales order
writes outward stock ledger entries in the same transaction as the status
change, so the Product Stock report always agrees with the documents.

**Calculations** live in `backend/app/common/calculations.py` and run
server-side only. The browser computes the same figures while you type purely
for feedback; on save the server recalculates from quantity, rate, discount and
tax, and its answer is what gets stored. The engine reproduces the supplied
Service Invoice exactly (124,600.00 + 18% = 22,428.00 tax = 147,028.00 total).

**PDFs** are generated by `backend/app/documents/pdf.py` using reportlab — no
system libraries needed on Windows. One renderer produces the Service Invoice,
Quotation, Sales Tax Invoice, Sales Invoice, Delivery Note and Proforma
Invoice, reading stored columns only, so a printed figure can never disagree
with the record. Documents open in a browser tab where print and download are
both available.

**Stock** is never a mutable number on the item. `stock_ledger_entries` holds
one immutable row per movement; corrections are reversing entries, never edits.

## Finance (Phase 1 — accounting foundation)

```
Finance
├── Dashboard            cash, bank, AR, AP, inventory, revenue, expenses, P/L, pending work
├── Chart of Accounts    tree, header/posting accounts, control accounts, standard 1000–8999 chart
├── Journal Entries      draft → submitted → approved → posted; reversal; cancel
├── General Ledger       per account, running balance, drill-down to journal and source
├── Trial Balance        by year / period / dates / branch; XLSX, PDF, CSV
├── Opening Balances     import → validate → preview → approve → post → reconcile → complete
├── Accounting Periods   financial years, monthly periods, close / reopen / lock
├── Finance Settings     posting rules, document numbering, cost centres
└── Audit Log            append-only
```

Design and mapping: `docs/finance/00-finance-discovery.md`,
`docs/finance/01-phase1-schema-mapping.md`. Code: `backend/app/finance/`.

**The ledger is empty until the accountant's opening balances are posted.**
Nothing is derived from the old ERP's sales orders, zero-cost opening stock or
demo procurement data. Download the template from Opening Balances, fill it
from the legacy closing trial balance and schedules, and import it.

**Every accounting entry goes through one posting engine** (`finance/posting.py`).
Events such as `SALES_INVOICE_POSTED` define the shape of the entry; which
account each line hits is set under Finance Settings → Posting Rules.

### Phase 2 — Sales invoices & receivables (`backend/app/receivables/`)

Sales Order (posted = delivered) or approved outward gate pass → **Sales
Invoice** (Draft → Confirmed → Posted) → AR → **Customer Receipt** (allocated
to invoices; the rest held as a customer advance) → GL. Credit and debit notes
reference their invoice; a posted invoice is cancelled by reversal, never
deleted. Invoices, credit notes and debit notes are doc types on the existing
`sales_documents` table.

- The invoice moves no stock and posts no COGS: stock was issued when the
  order posted, and COGS arrives with inventory valuation (Phase 4).
- Sales orders dated before the AR cut-off (Finance Settings → Receivables,
  default = start of the current year) cannot be invoiced, so historical
  orders never become AR. Pre-go-live balances enter via Opening Balances.
- Reports: customer statement, AR aging, customer balances, AR reconciliation
  (subledger vs control account, per customer), registers, sales summary.
  Design: `docs/finance/02-phase2-plan.md`.

**The database enforces the rules as well as the code:** no unbalanced or
single-line journal can be posted, nothing can be posted into a closed period
or to a header or inactive account, posted journals and their lines cannot be
edited or deleted, and the audit log refuses updates and deletes.

Run the finance tests (they use the local database inside a transaction that
is always rolled back, so nothing is left behind):

```bat
cd backend
.venv\Scripts\python -m pytest
```

## Not built yet

Calibration / Services is built (`app/calibration`, migrations 0019–0020):
machine definitions, customer machines, contracts with the printed
maintenance agreement, service invoices that post to the customer's ledger
(Dr AR, Cr 4200 Sales - Services), calibration definitions and calibration
reports printed as certificates.

Leads, CRM, Projects and Communication have sidebar
entries and permission codes but no routes, tables or endpoints — clicking a
submenu item gives a 404. Finance Phases 2+ (receivables, payables, banking,
tax, fixed assets, budgets, legacy migration) are designed in
`docs/finance/00-finance-discovery.md` but not built. Inventory Transactions, In House Order and Reports are
in the same position: they exist in the old ERP but have not been documented.

Gate pass, purchase order and MRN **screens** — their tables, relationships
and stock behaviour are in place, so those are listing and form work rather
than design work.

The old ERP's sidebar also contains a **Web API** module that was not in the
nine-module list. It is not built here.

Redis and Celery are configured but unused; no module queues a background job
yet. You do not need Redis running.

Search for `REQUIRES BUSINESS CONFIRMATION` — each marks a rule taken from
assumption rather than from your existing ERP. Currently: the financial-year
start month, the submodule lists, and what counts as dashboard "activity".

---

## Troubleshooting

**`setup.bat` fails creating the venv** — Python is not on your PATH.
Reinstall Python with "Add Python to PATH" ticked.

**Migration cannot connect** — PostgreSQL is not running, or the password in
`DATABASE_URL` does not match the database. Test with:
`psql -U jezseem -d jezseem_erp -h localhost`

**"Cannot reach the ERP server"** — the backend window has closed or crashed.
Look at that window; the traceback is printed there.

**Changed `.env` and nothing happened** — restart the backend window.
Environment variables load at startup.

**"Incorrect username or password" after changing `SEED_ADMIN_PASSWORD`** —
the seed never overwrites an existing password. Run
`scripts\reset-password.bat`.
