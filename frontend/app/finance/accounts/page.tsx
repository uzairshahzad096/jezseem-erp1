"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, Pencil, Plus, Search } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Field, Modal, Select, TextArea, TextInput, Toggle } from "@/components/ui/Modal";
import { Button, Card, EmptyState, ErrorNote, PageHeader, Spinner, filterClass } from "@/components/finance/ui";
import { api } from "@/lib/api";
import { drcr, errorText, useFinance, type Account } from "@/lib/finance";
import { PartnerModal } from "@/components/partners/PartnerModal";

interface AccountType { id: string; code: string; name: string; normal_balance: string }
/** A customer or supplier standing behind a control account. */
interface Party { id: string; code: string; name: string; city: string | null; is_active: boolean; balance: number }
interface Parties { kind: "customer" | "supplier" | null; items: Party[]; total: number; unassigned: number }
interface Group { id: string; code: string; name: string; account_type_id: string }

const CONTROL_TYPES = ["RECEIVABLE", "PAYABLE", "INVENTORY", "BANK", "CASH", "TAX", "GRNI"];

export default function ChartOfAccountsPage() {
  const accounts = useFinance<Account[]>("/finance/accounts?with_balances=true");
  const { data: types } = useFinance<AccountType[]>("/finance/account-types");
  const { data: groups } = useFinance<Group[]>("/finance/account-groups");
  const [search, setSearch] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  // Customer / supplier lists start folded: there are over a thousand customers.
  const [partiesOpen, setPartiesOpen] = useState<Set<string>>(new Set());
  const [withBalanceOnly, setWithBalanceOnly] = useState(false);
  const [editing, setEditing] = useState<Account | "new" | null>(null);
  const [parentForNew, setParentForNew] = useState<string>("");
  const [installing, setInstalling] = useState(false);
  const [newCustomer, setNewCustomer] = useState(false);
  const [added, setAdded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const list = accounts.data ?? [];
  // The customers behind the receivable account and the suppliers behind the
  // payable one. They are not accounts of their own: each is listed under its
  // control account with the balance its postings add up to.
  const [partyLists, setPartyLists] = useState<Record<string, Party[]>>({});
  const withParties = list.filter((a) => a.subledger).map((a) => a.id).join(",");
  useEffect(() => {
    let current = true;
    for (const id of withParties.split(",").filter(Boolean)) {
      api.get<Parties>(`/finance/accounts/${id}/parties`)
        .then((data) => { if (current) setPartyLists((all) => ({ ...all, [id]: data.items })); })
        .catch(() => { /* the account row still shows; its list stays empty */ });
    }
    return () => { current = false; };
  }, [withParties, accounts.data]);
  const partiesOf = (a: Account): Party[] => partyLists[a.id] ?? [];
  const receivable = list.find((a) => a.control_type === "RECEIVABLE" && a.subledger);
  const payable = list.find((a) => a.control_type === "PAYABLE" && a.subledger);
  const children = useMemo(() => {
    const map = new Map<string | null, Account[]>();
    for (const a of list) {
      const key = a.parent_id && list.some((p) => p.id === a.parent_id) ? a.parent_id : null;
      map.set(key, [...(map.get(key) ?? []), a]);
    }
    return map;
  }, [list]);

  // A header's balance is the sum of the accounts beneath it.
  const rolled = useMemo(() => {
    const totals = new Map<string, number>();
    const walk = (a: Account): number => {
      const own = a.balance ?? 0;
      const sum = (children.get(a.id) ?? []).reduce((s, c) => s + walk(c), own);
      totals.set(a.id, sum);
      return sum;
    };
    (children.get(null) ?? []).forEach(walk);
    return totals;
  }, [children]);

  const needle = search.trim().toLowerCase();
  const matches = (a: Account) =>
    (showInactive || a.is_active) &&
    (!needle || a.code.toLowerCase().includes(needle) || a.name.toLowerCase().includes(needle));
  // Every customer belongs under Accounts Receivable. Under Advances from
  // Customers only those actually holding an advance are listed, so the same
  // thousand names are not repeated there.
  const advancesOnly = (a: Account) => a.control_type === "CUSTOMER_ADVANCE";
  const matchesParty = (p: Party, a: Account) =>
    (showInactive || p.is_active) && (!(withBalanceOnly || advancesOnly(a)) || p.balance !== 0) &&
    (!needle || p.code.toLowerCase().includes(needle) || p.name.toLowerCase().includes(needle));
  const visibleIds = useMemo(() => {
    const ids = new Set<string>();
    const walk = (a: Account): boolean => {
      const kids = (children.get(a.id) ?? []).map(walk).some(Boolean);
      // Searching for a customer's name or code brings up their control account.
      const show = matches(a) || kids || (Boolean(needle) && partiesOf(a).some((p) => matchesParty(p, a)));
      if (show) ids.add(a.id);
      return show;
    };
    (children.get(null) ?? []).forEach(walk);
    return ids;
  }, [children, needle, showInactive, withBalanceOnly, partyLists]); // eslint-disable-line react-hooks/exhaustive-deps

  const install = async () => {
    setInstalling(true);
    setError(null);
    try {
      await api.post("/finance/setup/install-defaults", {});
      await accounts.reload();
    } catch (err) {
      setError(errorText(err, "Could not install the standard chart."));
    } finally {
      setInstalling(false);
    }
  };

  const toggle = (id: string) => setCollapsed((c) => {
    const next = new Set(c);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const renderRow = (a: Account, depth: number): React.ReactNode => {
    if (!visibleIds.has(a.id)) return null;
    const kids = children.get(a.id) ?? [];
    const open = !collapsed.has(a.id) || Boolean(needle);
    const balance = rolled.get(a.id) ?? 0;
    const sub = a.subledger ?? null;
    const parties = sub ? partiesOf(a).filter((p) => matchesParty(p, a)) : [];
    const partiesShown = Boolean(sub) && (partiesOpen.has(a.id) || (Boolean(needle) && parties.length > 0));
    const noun = sub?.kind === "supplier" ? "supplier" : "customer";
    const toggleParties = () => setPartiesOpen((s) => {
      const next = new Set(s);
      if (next.has(a.id)) next.delete(a.id); else next.add(a.id);
      return next;
    });
    return (
      <div key={a.id}>
        <div className={`group flex items-center gap-2 border-b border-line px-5 py-2 text-[12.8px]
                         hover:bg-primary/5 ${!a.is_active ? "opacity-50" : ""}`}>
          {/* Edit first, as on every list (owner, 19-Oct-2026). */}
          <span className="flex w-16 flex-shrink-0 gap-1">
            <button title="Edit" onClick={() => setEditing(a)}
              className="rounded p-1 text-muted hover:bg-primary/10 hover:text-primary"><Pencil size={13} /></button>
            {!a.is_postable && (
              <button title="Add child account" onClick={() => { setParentForNew(a.id); setEditing("new"); }}
                className="rounded p-1 text-muted hover:bg-primary/10 hover:text-primary"><Plus size={13} /></button>
            )}
          </span>
          <div style={{ paddingLeft: depth * 20 }} className="flex min-w-0 flex-1 items-center gap-1.5">
            {kids.length ? (
              <button onClick={() => toggle(a.id)} className="rounded p-0.5 text-faint hover:text-text" aria-label="Toggle">
                {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
            ) : sub ? (
              <button onClick={toggleParties} className="rounded p-0.5 text-faint hover:text-text"
                aria-label={`Show ${noun}s`} title={`Show the ${noun}s under this account`}>
                {partiesShown ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
            ) : <span className="w-[18px]" />}
            <span className={`w-14 flex-shrink-0 tabular-nums ${a.is_postable ? "" : "font-semibold"}`}>{a.code}</span>
            <span className={`truncate ${a.is_postable ? "" : "font-semibold"}`} title={a.description ?? ""}>{a.name}</span>
            {a.control_type && (
              <span className="ml-1 rounded bg-sky/10 px-1.5 py-[1px] text-[10.5px] font-medium text-sky">
                {a.control_type}{a.is_control_account ? " · control" : ""}
              </span>
            )}
            {sub && (
              <button onClick={toggleParties}
                className="ml-1 whitespace-nowrap rounded bg-primary/10 px-1.5 py-[1px] text-[10.5px] font-medium text-primary hover:bg-primary/20">
                {advancesOnly(a)
                  ? `${partiesOf(a).filter((p) => p.balance !== 0).length.toLocaleString()} with an advance`
                  : `${sub.count.toLocaleString()} ${noun}${sub.count === 1 ? "" : "s"}`}
              </button>
            )}
          </div>
          <span className="hidden w-36 text-[12px] text-muted md:block">{a.account_type_name}</span>
          <span className="hidden w-24 text-[12px] text-muted md:block">{a.is_postable ? "Posting" : "Header"}</span>
          <span className="w-20 text-[12px]">
            {a.is_active ? <span className="text-primary">Active</span> : <span className="text-faint">Inactive</span>}
          </span>
          <span className="w-36 text-right tabular-nums">
            {a.is_postable ? (
              <Link href={`/finance/ledger?account=${a.id}`} className="hover:text-primary hover:underline">{drcr(balance)}</Link>
            ) : <span className="font-semibold">{drcr(balance)}</span>}
          </span>
        </div>
        {open && kids.map((k) => renderRow(k, depth + 1))}
        {partiesShown && (
          <div>
            {parties.length === 0 && (
              <p className="m-0 border-b border-line py-2.5 text-[12.3px] text-faint" style={{ paddingLeft: 20 + (depth + 1) * 20 + 24 }}>
                {advancesOnly(a) ? "No customer is holding an advance."
                  : withBalanceOnly ? `No ${noun} has a balance on this account yet.` : `No ${noun} matches.`}
              </p>
            )}
            {parties.map((p) => (
              <div key={p.id} className={`flex items-center gap-2 border-b border-line px-5 py-1.5 text-[12.5px] hover:bg-primary/5 ${!p.is_active ? "opacity-50" : ""}`}>
                <span className="w-16 flex-shrink-0" />
                <div style={{ paddingLeft: (depth + 1) * 20 }} className="flex min-w-0 flex-1 items-center gap-1.5">
                  <span className="w-[18px]" />
                  <span className="w-[104px] flex-shrink-0 tabular-nums text-muted">{p.code}</span>
                  <span className="truncate">{p.name}</span>
                  {p.city && <span className="truncate text-[11.5px] text-faint">{p.city}</span>}
                </div>
                <span className="hidden w-36 text-[12px] text-muted md:block">{noun === "customer" ? "Customer" : "Supplier"}</span>
                <span className="hidden w-24 text-[12px] text-muted md:block">Subledger</span>
                <span className="w-20 text-[12px]">
                  {p.is_active ? <span className="text-primary">Active</span> : <span className="text-faint">Inactive</span>}
                </span>
                <span className={`w-36 text-right tabular-nums ${p.balance === 0 ? "text-faint" : ""}`}>
                  {noun === "customer"
                    ? <Link href={`/finance/statement?customer=${p.id}`} title="Open the customer statement" className="hover:text-primary hover:underline">{drcr(p.balance)}</Link>
                    : drcr(p.balance)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <AppShell title="Chart of Accounts">
      <PageHeader title="Chart of Accounts"
        subtitle="Codes and names are the company's own. Balances come from posted journals only.">
        <div className="flex gap-2">
          {/* A customer is not an account of its own: it is added to the customer
              file once and is then listed under Accounts Receivable and usable everywhere. */}
          <Button onClick={() => { setAdded(null); setNewCustomer(true); }}>
            <Plus size={14} /> New customer
          </Button>
          <Button tone="primary" onClick={() => { setParentForNew(""); setEditing("new"); }}>
            <Plus size={14} /> New account
          </Button>
        </div>
      </PageHeader>
      {added && (
        <div className="mb-4 rounded-[12px] border border-primary/30 bg-primary/10 px-4 py-2.5 text-[12.8px]">
          {added} has been added. It is listed under Accounts Receivable and can now be picked on quotations,
          sales orders, invoices, receipts and the General Ledger.
        </div>
      )}
      <ErrorNote message={error ?? accounts.error} />

      <Card>
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-3.5">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Code or name…"
              className="w-48 border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint" />
          </div>
          <label className="flex items-center gap-2 text-[12.5px] text-muted">
            <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
            Show inactive
          </label>
          <label className="flex items-center gap-2 text-[12.5px] text-muted" title="In the customer and supplier lists, hide those with a zero balance">
            <input type="checkbox" checked={withBalanceOnly} onChange={(e) => setWithBalanceOnly(e.target.checked)} />
            Customers / suppliers with a balance only
          </label>
          <span className="ml-auto text-[12px] text-faint">
            {list.length} accounts{receivable?.subledger ? ` · ${receivable.subledger.count.toLocaleString()} customers` : ""}
            {payable?.subledger ? ` · ${payable.subledger.count.toLocaleString()} suppliers` : ""}
          </span>
        </div>
        <div className="flex items-center gap-2 border-b border-line bg-bg/60 px-5 py-2 text-[11.5px] font-semibold text-primary">
          <span className="w-16 flex-shrink-0">Edit</span>
          <span className="flex-1 pl-6">Account</span>
          <span className="hidden w-36 md:block">Type</span>
          <span className="hidden w-24 md:block">Kind</span>
          <span className="w-20">Status</span>
          <span className="w-36 text-right">Balance</span>
        </div>
        {accounts.loading && <Spinner />}
        {!accounts.loading && list.length === 0 && (
          <EmptyState>
            <p className="mb-3">No chart of accounts yet.</p>
            <Button tone="primary" busy={installing} onClick={install}>Install the standard chart</Button>
            <p className="mt-3 text-[11.5px]">A structure only (1000–8999), with no balances. Edit it freely afterwards.</p>
          </EmptyState>
        )}
        {(children.get(null) ?? []).map((a) => renderRow(a, 0))}
        {list.length > 0 && (
          <p className="m-0 px-5 py-3 text-[11.5px] leading-relaxed text-faint">
            Customers are listed under <b>Accounts Receivable</b> (Current Assets) and suppliers under <b>Accounts Payable</b>;
            receipts not yet matched to an invoice show against the customer under <b>Advances from Customers</b>:
            click the arrow or the count to open the list, or search a customer&apos;s name or code. A customer added in the
            customer file appears here automatically. Each customer&apos;s balance is what posted invoices, receipts and notes add
            up to, and the account&apos;s own balance is the total of them all.
          </p>
        )}
      </Card>

      {editing && (
        <AccountForm account={editing === "new" ? null : editing} parentId={parentForNew}
          accounts={list} types={types ?? []} groups={groups ?? []}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); accounts.reload(); }} />
      )}
      <PartnerModal open={newCustomer} partner={null} onClose={() => setNewCustomer(false)}
        onSaved={(p) => {
          setNewCustomer(false);
          setAdded(`${p.code} ${p.name}`);
          setSearch(p.code);
          accounts.reload();
        }} />
    </AppShell>
  );
}

function AccountForm({
  account, parentId, accounts, types, groups, onClose, onSaved,
}: {
  account: Account | null; parentId: string; accounts: Account[]; types: AccountType[]; groups: Group[];
  onClose: () => void; onSaved: () => void;
}) {
  const parent = accounts.find((a) => a.id === (account?.parent_id ?? parentId));
  const [form, setForm] = useState({
    code: account?.code ?? "",
    name: account?.name ?? "",
    parent_id: account?.parent_id ?? parentId ?? "",
    account_type_id: account?.account_type_id ?? parent?.account_type_id ?? "",
    account_group_id: account?.account_group_id ?? parent?.account_group_id ?? "",
    normal_balance: account?.normal_balance ?? "",
    control_type: account?.control_type ?? "",
    description: account?.description ?? "",
  });
  const [postable, setPostable] = useState(account?.is_postable ?? true);
  const [control, setControl] = useState(account?.is_control_account ?? false);
  const [manual, setManual] = useState(account?.allow_manual_posting ?? true);
  const [active, setActive] = useState(account?.is_active ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));
  const headers = accounts.filter((a) => !a.is_postable && a.id !== account?.id);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const body = {
        ...form, parent_id: form.parent_id || null, account_group_id: form.account_group_id || null,
        normal_balance: form.normal_balance || null, control_type: form.control_type || null,
        description: form.description || null, is_postable: postable, is_control_account: control,
        allow_manual_posting: manual, is_active: active,
      };
      if (account) await api.put(`/finance/accounts/${account.id}`, body);
      else await api.post("/finance/accounts", body);
      onSaved();
    } catch (err) {
      setError(errorText(err, "Could not save the account."));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!deleting) { setDeleting(true); setError("Press Delete again to confirm. Accounts with postings cannot be deleted — deactivate them."); return; }
    setSaving(true);
    try {
      await api.del(`/finance/accounts/${account!.id}`);
      onSaved();
    } catch (err) {
      setError(errorText(err, "Could not delete the account."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={account ? `Account ${account.code}` : "New account"} open width="md" saving={saving}
           error={error} onClose={onClose} onSave={save} saveLabel={account ? "Save" : "Create"}
           onDelete={account ? remove : undefined}>
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        <Field label="Code" required>
          <TextInput value={form.code} onChange={(e) => set("code", e.target.value)} placeholder="6195" />
        </Field>
        <Field label="Name" required>
          <TextInput value={form.name} onChange={(e) => set("name", e.target.value)} />
        </Field>
        <Field label="Parent (header account)">
          <Select value={form.parent_id} placeholder="Top level"
            onChange={(e) => {
              const p = accounts.find((a) => a.id === e.target.value);
              setForm((f) => ({ ...f, parent_id: e.target.value,
                account_type_id: p?.account_type_id ?? f.account_type_id,
                account_group_id: p?.account_group_id ?? f.account_group_id }));
            }}
            options={headers.map((a) => ({ value: a.id, label: `${a.code} ${a.name}` }))} />
        </Field>
        <Field label="Account type" required>
          <Select value={form.account_type_id} placeholder="Choose…" onChange={(e) => set("account_type_id", e.target.value)}
            options={types.map((t) => ({ value: t.id, label: t.name }))} />
        </Field>
        <Field label="Report group">
          <Select value={form.account_group_id} placeholder="None"
            onChange={(e) => set("account_group_id", e.target.value)}
            options={groups.filter((g) => !form.account_type_id || g.account_type_id === form.account_type_id)
              .map((g) => ({ value: g.id, label: g.name }))} />
        </Field>
        <Field label="Normal balance">
          <Select value={form.normal_balance} placeholder="From the account type"
            onChange={(e) => set("normal_balance", e.target.value)}
            options={[{ value: "DEBIT", label: "Debit" }, { value: "CREDIT", label: "Credit (contra / liability)" }]} />
        </Field>
        <Field label="Control type">
          <Select value={form.control_type} placeholder="None"
            onChange={(e) => set("control_type", e.target.value)}
            options={CONTROL_TYPES.map((c) => ({ value: c, label: c }))} />
          {!account && (form.control_type === "RECEIVABLE" || form.control_type === "PAYABLE") && (
            <p className="mb-0 mt-1.5 text-[11.5px] leading-snug text-amber">
              To add a customer or supplier, close this and use <b>New customer</b>. A new account here would be a second
              receivable / payable account, not a customer.
            </p>
          )}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Toggle label="Posting account" checked={postable} onChange={setPostable} />
          <Toggle label="Active" checked={active} onChange={setActive} />
          <Toggle label="Control account" checked={control}
            onChange={(v) => { setControl(v); if (v) setManual(false); }} />
          <Toggle label="Manual journals allowed" checked={manual} onChange={setManual} />
        </div>
        <div className="col-span-2 max-sm:col-span-1">
          <Field label="Description">
            <TextArea rows={2} value={form.description} onChange={(e) => set("description", e.target.value)} />
          </Field>
        </div>
      </div>
      <p className="mb-0 mt-3 text-[11px] leading-snug text-faint">
        Header accounts group others and cannot be posted to. A control account is fed by its subledger
        (customers, suppliers, stock) and normally refuses manual journals.
      </p>
    </Modal>
  );
}
