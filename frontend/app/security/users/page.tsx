"use client";

import { useState } from "react";
import { BarChart3, ShieldCheck, UserRound } from "lucide-react";
import { ListScreen, type ListColumn } from "@/components/calibration/ListScreen";
import { Field, Modal, TextInput, Toggle } from "@/components/ui/Modal";
import { api } from "@/lib/api";

interface UserRow {
  id: string; username: string; full_name: string; email: string; is_active: boolean; is_superuser: boolean;
  role: string | null; other_roles: string[]; business_dashboard: boolean;
}

const COLUMNS: ListColumn<UserRow>[] = [
  { key: "full_name", label: "Name", render: (r) => <span className="font-medium">{r.full_name}</span> },
  { key: "username", label: "Login" },
  { key: "email", label: "Email" },
  { key: "role", label: "Role", value: (r) => (r.is_superuser ? "Administrator" : r.role ?? ""),
    render: (r) => <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${
      r.is_superuser || r.role === "Administrator" ? "bg-violet/10 text-violet" : "bg-sky/10 text-sky"}`}>
      {r.is_superuser ? "Administrator" : r.role ?? "No role"}</span> },
  { key: "business_dashboard", label: "Sees business figures", value: (r) => (r.business_dashboard ? "Yes" : "No"),
    render: (r) => (r.business_dashboard
      ? <span className="inline-flex items-center gap-1 font-medium text-primary"><BarChart3 size={12} /> Yes</span>
      : <span className="text-faint">No — simple dashboard</span>) },
  { key: "is_active", label: "Active", value: (r) => (r.is_active ? "Yes" : "No"),
    render: (r) => (r.is_active ? <span className="text-primary">Yes</span> : <span className="text-rose">Switched off</span>) },
];

export default function UsersPage() {
  const [editing, setEditing] = useState<UserRow | "new" | null>(null);
  const [reload, setReload] = useState(0);
  return (
    <ListScreen<UserRow> title="Users" subtitle="Logins for employees: their role, and whether the home dashboard shows them sales and money figures."
      endpoint="/security/users" storageKey="security.users" columns={COLUMNS} onCreate={() => setEditing("new")}
      onEdit={(r) => setEditing(r)} reloadKey={reload} noun="User" createLabel="New user"
      footnote={<>
        <b>Administrator</b> — everything, including these Security screens. <b>Staff</b> — every module, with the simple home dashboard
        (their own follow-ups, leads and the day&apos;s work, no sales or money figures). Tick <b>Sees business figures</b> on a Staff
        user to show them the full dashboard as well.
      </>}>
      {editing && <UserForm user={editing === "new" ? null : editing} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); setReload((n) => n + 1); }} />}
    </ListScreen>
  );
}

function UserForm({ user, onClose, onSaved }: { user: UserRow | null; onClose: () => void; onSaved: () => void }) {
  const [username, setUsername] = useState(user?.username ?? "");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(user?.is_superuser ? "Administrator" : user?.role ?? "Staff");
  const [business, setBusiness] = useState(user?.business_dashboard ?? false);
  const [active, setActive] = useState(user?.is_active ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    if (!user && password.length < 8) { setError("Give them a password of at least 8 characters."); return; }
    if (user && password && password.length < 8) { setError("The new password must be at least 8 characters."); return; }
    setSaving(true); setError(null);
    const body = { username, full_name: fullName, email, password: password || null, role,
                   business_dashboard: role === "Administrator" || business, is_active: active };
    try {
      if (user) await api.put(`/security/users/${user.id}`, body); else await api.post("/security/users", body);
      onSaved();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save."); } finally { setSaving(false); }
  };

  const roleCard = (value: string, icon: React.ReactNode, title: string, text: string) => (
    <button type="button" onClick={() => setRole(value)} disabled={user?.is_superuser}
      className={`flex flex-1 items-start gap-3 rounded-xl border px-4 py-3 text-left ${role === value ? "border-primary bg-primary/5" : "border-line hover:bg-hover"}`}>
      <span className={`mt-0.5 rounded-lg p-1.5 ${role === value ? "bg-primary text-on-primary" : "bg-hover text-muted"}`}>{icon}</span>
      <span><b className="block text-[13px]">{title}</b><span className="text-[11.5px] text-muted">{text}</span></span>
    </button>
  );

  return (
    <Modal title={user ? `User — ${user.full_name}` : "New user"} open width="lg" saving={saving} error={error}
      onClose={onClose} onSave={save} saveLabel={user ? "Apply Changes" : "Create user"}>
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        <Field label="Full name" required><TextInput value={fullName} onChange={(e) => setFullName(e.target.value)} /></Field>
        <Field label="Login (username)" required>
          <TextInput value={username} disabled={Boolean(user)} placeholder="e.g. wasim" onChange={(e) => setUsername(e.target.value.toLowerCase().replace(/\s/g, ""))} />
        </Field>
        <Field label="Email" required><TextInput value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label={user ? "New password (leave empty to keep)" : "Password"} required={!user}>
          <TextInput type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
      </div>
      <div className="mt-4 flex gap-3 max-sm:flex-col">
        {roleCard("Staff", <UserRound size={15} />, "Staff", "Every module; simple home dashboard")}
        {roleCard("Administrator", <ShieldCheck size={15} />, "Administrator", "Everything, including users and the business figures")}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-6 rounded-xl bg-hover/50 px-4 py-3">
        <Toggle label="Sees business figures on the dashboard (sales, receivables, best customers)"
          checked={role === "Administrator" || business} onChange={(v) => setBusiness(v)} />
        <Toggle label="Active" checked={active} onChange={setActive} />
      </div>
      {role === "Administrator" && <p className="mb-0 mt-2 text-[11.5px] text-faint">An Administrator always sees the business figures.</p>}
    </Modal>
  );
}
