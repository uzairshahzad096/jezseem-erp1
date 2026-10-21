/** CRM: shared colours and the Customer 360 shape. */

export const SEGMENT_TONE: Record<string, string> = {
  Active: "bg-primary/10 text-primary", Slowing: "bg-amber/10 text-amber",
  Dormant: "bg-rose/10 text-rose", "Never ordered": "bg-hover text-muted",
};

export interface Contact {
  id: string; partner_id: string; customer_name: string | null; contact_name: string; title: string | null;
  department: string | null; phone: string | null; cell: string | null; whatsapp: string | null; email: string | null;
  description: string | null; is_primary: boolean; is_active: boolean; updated_at: string;
}

export interface CrmActivity {
  id: string; activity_type: string; activity_at: string; summary: string; outcome: string | null;
  due_date: string | null; done_at: string | null; open: boolean; overdue?: boolean;
  customer_id?: string | null; customer_name?: string | null; lead_id: string | null; lead_number: string | null;
  lead_title?: string | null; contact: string | null; owner: string | null; created_by: string | null;
}

export interface Doc {
  id: string; doc_number: string; doc_date: string; status: string; net_receivable: number;
  customer_po_number: string | null; converted: boolean;
}

export interface Customer360 {
  customer: {
    id: string; code: string; name: string; address: string | null; city: string | null; territory: string | null;
    phone: string | null; cell: string | null; email: string | null; ntn: string | null; stn: string | null;
    payment_terms: string | null; credit_days: number | null; credit_limit: number | null; is_active: boolean;
    is_supplier: boolean;
  };
  kpis: {
    balance: number; sales_total: number; sales_12m: number; orders: number; average_order: number;
    last_order_date: string | null; days_since_order: number | null; segment: string; first_order_date: string | null;
    quotations: number; quotation_conversion: number | null; last_receipt_date: string | null;
    last_receipt_amount: number | null; open_leads: number; pipeline_value: number; machines: number;
    active_contracts: number;
  };
  sales_by_month: { month: string; value: number }[];
  top_products: { description: string; quantity: number; value: number; last: string }[];
  quotations: Doc[];
  orders: Doc[];
  receipts: { id: string; receipt_number: string; receipt_date: string; amount: number; reference: string | null }[];
  leads: { id: string; lead_number: string; title: string; stage: string; rating: string; estimated_value: number;
           currency: string; probability: number; owner: string | null; updated_at: string }[];
  contacts: Contact[];
  activities: CrmActivity[];
  machines: { id: string; machine_code: string | null; serial_number: string | null; category: string; vendor: string;
              model: string; status: string; location: string | null; certificate_expiry: string | null;
              next_calibration: string | null }[];
  contracts: { id: string; contract_number: string; contract_type: string; start_date: string; end_date: string | null;
               billing_frequency: string; charge_amount: number; status: string }[];
  service_invoices: { id: string; invoice_number: string; invoice_date: string; service_type: string;
                      net_receivable: number; status: string }[];
}
