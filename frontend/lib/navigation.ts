import type { LucideIcon } from "lucide-react";
import {
  LayoutGrid, ShieldCheck, Wallet, Filter, Users,
  Boxes, KanbanSquare, MessagesSquare, IdCard, Gauge,
} from "lucide-react";

export interface NavChild {
  label: string;
  href: string;
  permission: string;
  /** Third navigation level — e.g. Inventory > Setup Forms > Item Racks. */
  children?: NavChild[];
}

export interface NavModule {
  key: string;
  label: string;
  href: string;
  icon: LucideIcon;
  /** Permission required for this module to appear in the sidebar at all.
   *  Rendering only — the backend independently enforces access. */
  permission: string;
  children: NavChild[];
}

/**
 * Sidebar navigation: the nine top-level ERP modules with their submodules.
 *
 * REQUIRES BUSINESS CONFIRMATION: the submodule lists below are a first pass
 * based on standard ERP structure. They must be reconciled against the
 * existing ERP's actual screens during discovery before any of these routes
 * are built.
 */
export const NAV_MODULES: NavModule[] = [
  {
    key: "dashboard", label: "Dashboard", href: "/", icon: LayoutGrid,
    permission: "dashboard.view",
    // No submodules: clicking Dashboard opens it (owner, 20-Oct-2026).
    children: [],
  },
  {
    key: "security", label: "Security", href: "/security", icon: ShieldCheck,
    permission: "security.module.view",
    children: [
      { label: "Users", href: "/security/users", permission: "security.users.view" },
      { label: "Audit Log", href: "/finance/audit", permission: "finance.audit" },
    ],
  },
  {
    // Finance Phase 1: the accounting foundation. Receivables, payables,
    // banking and tax arrive in later phases on top of the same ledger.
    key: "finance", label: "Finance", href: "/finance", icon: Wallet,
    permission: "finance.view",
    children: [
      { label: "Dashboard", href: "/finance", permission: "finance.view" },
      { label: "Chart of Accounts", href: "/finance/accounts", permission: "finance.view" },
      { label: "Journal Entries", href: "/finance/journals", permission: "finance.view" },
      { label: "Payment Receipts", href: "/finance/receipts", permission: "ar.view" },
      { label: "General Ledger", href: "/finance/ledger", permission: "finance.reports" },
      { label: "Trial Balance", href: "/finance/trial-balance", permission: "finance.reports" },
      {
        // Finance Phase 2: accounts receivable. The owner removed the sales &
        // AR dashboard, invoices, credit / debit notes, statement and registers
        // from the menu (14-Oct-2026); the screens remain for links that open them.
        label: "Receivables", href: "/finance/aging", permission: "ar.reports",
        children: [
          { label: "AR Aging", href: "/finance/aging", permission: "ar.reports" },
          { label: "AR Reconciliation", href: "/finance/ar-reconciliation", permission: "ar.reports" },
        ],
      },
      { label: "Accounting Periods", href: "/finance/periods", permission: "finance.view" },
      { label: "Finance Settings", href: "/finance/settings", permission: "finance.chart_of_accounts" },
      { label: "Audit Log", href: "/finance/audit", permission: "finance.audit" },
    ],
  },
  {
    key: "leads", label: "Leads", href: "/leads", icon: Filter,
    permission: "leads.module.view",
    children: [
      { label: "All Leads", href: "/leads", permission: "leads.view.view" },
      { label: "Follow-ups", href: "/leads/followups", permission: "leads.followups.view" },
      { label: "Assignments", href: "/leads/assignments", permission: "leads.assignments.view" },
      { label: "Sources", href: "/leads/sources", permission: "leads.sources.view" },
    ],
  },
  {
    key: "crm", label: "CRM", href: "/crm", icon: Users,
    permission: "crm.module.view",
    children: [
      { label: "Customers", href: "/crm/customers", permission: "partners.customers.view" },
      { label: "Contacts", href: "/crm/contacts", permission: "crm.contacts.view" },
      { label: "Opportunities", href: "/crm/opportunities", permission: "crm.opportunities.view" },
      { label: "Activities", href: "/crm/activities", permission: "crm.activities.view" },
    ],
  },
  {
    key: "inventory", label: "Inventory", href: "/inventory", icon: Boxes,
    permission: "inventory.module.view",
    children: [
      {
        label: "Setup Forms", href: "/inventory/setup", permission: "inventory.module.view",
        children: [
          { label: "Item Racks", href: "/inventory/setup/racks", permission: "inventory.racks.view" },
          { label: "Item Locations", href: "/inventory/setup/locations", permission: "inventory.locations.view" },
          { label: "Main Products", href: "/inventory/setup/main-products", permission: "inventory.main_products.view" },
          { label: "Inventory Sub Category", href: "/inventory/setup/sub-categories", permission: "inventory.sub_categories.view" },
          { label: "Inventory Sub Detail Category", href: "/inventory/setup/sub-detail-categories", permission: "inventory.sub_detail_categories.view" },
          { label: "Units of Measure", href: "/inventory/setup/uoms", permission: "inventory.items.view" },
          { label: "Product Details", href: "/inventory/setup/products", permission: "inventory.items.view" },
        ],
      },
      {
        label: "Transactions", href: "/inventory/transactions", permission: "inventory.transactions.view",
        children: [
          { label: "Product Quotation", href: "/inventory/transactions/quotations", permission: "sales.quotations.view" },
          { label: "Product Sale Order", href: "/inventory/transactions/sales-orders", permission: "sales.orders.view" },
          { label: "Outward Gate Pass", href: "/inventory/transactions/outward-gate-pass", permission: "inventory.gate_passes.view" },
          { label: "Inward Gate Pass", href: "/inventory/transactions/inward-gate-pass", permission: "inventory.gate_passes.view" },
        ],
      },
      {
        // The procurement chain, in the order the work happens: what we need,
        // what we ordered, what shipped, what it cost, what arrived.
        label: "In House Order", href: "/inventory/inhouse-orders/purchase-orders", permission: "inventory.inhouse_orders.view",
        children: [
          { label: "Purchase Orders", href: "/inventory/inhouse-orders/purchase-orders", permission: "procurement.purchase_orders.view" },
          { label: "Import Shipments", href: "/inventory/inhouse-orders/shipments", permission: "procurement.shipments.view" },
          { label: "Import Landed Costing", href: "/inventory/inhouse-orders/landed-costs", permission: "procurement.landed_costs.view" },
          { label: "Goods Receipts", href: "/inventory/inhouse-orders/goods-receipts", permission: "procurement.goods_receipts.view" },
        ],
      },
      {
        label: "Reports", href: "/inventory/reports", permission: "inventory.reports.view",
        children: [
          { label: "Product Stock", href: "/inventory/reports/product-stock", permission: "inventory.reports.view" },
          { label: "Product Sales Report", href: "/inventory/reports/product-sales", permission: "inventory.reports.view" },
          { label: "Inventory Valuation", href: "/inventory/reports/inventory-valuation", permission: "inventory.reports.view" },
          { label: "Import Landed Costing", href: "/inventory/reports/import-landed-costing", permission: "inventory.reports.view" },
        ],
      },
    ],
  },
  {
    key: "projects", label: "Project Management", href: "/projects", icon: KanbanSquare,
    permission: "projects.module.view",
    children: [
      { label: "Projects", href: "/projects", permission: "projects.view" },
      { label: "Tasks", href: "/projects/tasks", permission: "projects.tasks.view" },
      { label: "Members", href: "/projects/members", permission: "projects.members.view" },
      { label: "Documents", href: "/projects/documents", permission: "projects.documents.view" },
    ],
  },
  {
    key: "communication", label: "Communication Channel", href: "/communication", icon: MessagesSquare,
    permission: "communication.module.view",
    children: [
      { label: "Messages", href: "/communication/messages", permission: "communication.messages.view" },
      { label: "Notices", href: "/communication/notices", permission: "communication.notices.view" },
      { label: "Announcements", href: "/communication/announcements", permission: "communication.announcements.view" },
    ],
  },
  {
    key: "hrms", label: "HRMS", href: "/hrms", icon: IdCard,
    permission: "hrms.module.view",
    children: [
      { label: "Dashboard", href: "/hrms", permission: "hrms.module.view" },
      { label: "Employees", href: "/hrms/employees", permission: "hrms.employees.view" },
      { label: "Attendance", href: "/hrms/attendance", permission: "hrms.attendance.view" },
      { label: "Leave", href: "/hrms/leave", permission: "hrms.leave.view" },
      { label: "Loans & Advances", href: "/hrms/loans", permission: "hrms.loans.view" },
      { label: "Payroll", href: "/hrms/payroll", permission: "hrms.payroll.view" },
      { label: "HR Setup", href: "/hrms/setup", permission: "hrms.setup.view" },
    ],
  },
  {
    key: "calibration", label: "Calibration / Services", href: "/calibration", icon: Gauge,
    permission: "calibration.module.view",
    children: [
      // The previous ERP's six screens.
      { label: "Machine Definitions", href: "/calibration/machine-definitions", permission: "calibration.machines.view" },
      { label: "Customer Machines", href: "/calibration/customer-machines", permission: "calibration.customer_machines.view" },
      { label: "Contract", href: "/calibration/contracts", permission: "calibration.contracts.view" },
      { label: "Invoices", href: "/calibration/invoices", permission: "calibration.invoices.view" },
      { label: "Calibration Definitions", href: "/calibration/definitions", permission: "calibration.definitions.view" },
      { label: "Calibration Reports", href: "/calibration/reports", permission: "calibration.reports.view" },
    ],
  },
];
