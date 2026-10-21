"use client";

import { useEffect, useState } from "react";
import { Download, Pencil, Plus, Search, UserCheck, UserMinus, UserX, Users, Wallet } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Field, Modal, Select, TextArea, TextInput } from "@/components/ui/Modal";
import { GridHeader, GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Button, EmptyState, ErrorNote, PageHeader, ReasonDialog, Spinner } from "@/components/finance/ui";
import { EmployeeForm } from "@/components/hrms/EmployeeForm";
import { SalaryForm } from "@/components/hrms/SalaryForm";
import { Fact, HrBadge, Tile, selectClass } from "@/components/hrms/ui";
import { api } from "@/lib/api";
import {
  days, download, errorText, fmtDate, label, mediaUrl, money, todayIso, useHr,
  type Employee, type EmployeeDetail, type Lookups,
} from "@/lib/hrms";

interface Listing { items: Employee[]; total: number; page: number; page_size: number; status_counts: Record<string, number> }

const PAGE_SIZE = 25;
type StatusFilter = "" | "ACTIVE" | "INACTIVE" | "LEFT";

export default function EmployeesPage() {
  const lookups = useHr<Lookups>("/hrms/lookups");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [department, setDepartment] = useState("");
  const [status, setStatus] = useState<StatusFilter>("ACTIVE");
  const [sort, setSort] = useState("employee_code");
  const [direction, setDirection] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { const t = setTimeout(() => { setQuery(search); setPage(1); }, 300); return () => clearTimeout(t); }, [search]);
  // Opening /hrms/employees?open=<id> shows that profile, for links from other HR screens.
  useEffect(() => { const id = new URLSearchParams(window.location.search).get("open"); if (id) setOpenId(id); }, []);

  const qs = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE), sort, direction });
  if (query) qs.set("search", query);
  if (department) qs.set("department_id", department);
  if (status === "LEFT") { qs.append("status", "RESIGNED"); qs.append("status", "TERMINATED"); }
  else if (status) qs.set("status", status);
  const list = useHr<Listing>(`/hrms/employees?${qs}`);
  const counts = list.data?.status_counts ?? {};
  const leftCount = (counts.RESIGNED ?? 0) + (counts.TERMINATED ?? 0);
  const everyone = Object.values(counts).reduce((a, b) => a + b, 0);

  const onSort = (key: string) => {
    if (sort === key) setDirection((d) => (d === "asc" ? "desc" : "asc")); else { setSort(key); setDirection("asc"); }
  };
  const pickStatus = (next: StatusFilter) => { setStatus((s) => (s === next ? "" : next)); setPage(1); };
  const reset = () => { setSearch(""); setDepartment(""); setStatus("ACTIVE"); setSort("employee_code"); setDirection("asc"); setPage(1); };
  const changed = Boolean(search || department || status !== "ACTIVE");
  const pages = Math.max(1, Math.ceil((list.data?.total ?? 0) / PAGE_SIZE));

  const exportAll = async () => {
    setExporting(true); setError(null);
    try { await download("/hrms/employees/export", "employees.xlsx"); }
    catch (err) { setError(errorText(err, "Could not build the file.")); } finally { setExporting(false); }
  };

  return (
    <AppShell title="Employees">
      <PageHeader title="Employees" subtitle="Everyone on file: who they are, where they work and how they are paid.">
        <Button busy={exporting} onClick={exportAll}><Download size={14} /> Export to Excel</Button>
        <Button tone="primary" onClick={() => setCreating(true)}><Plus size={14} /> New employee</Button>
      </PageHeader>
      <ErrorNote message={error ?? list.error} />

      <div className="mb-5 grid grid-cols-4 gap-[18px] max-xl:grid-cols-2 max-sm:grid-cols-1">
        <Tile icon={UserCheck} label="Active" value={counts.ACTIVE ?? 0} tone="green" active={status === "ACTIVE"} onClick={() => pickStatus("ACTIVE")} />
        <Tile icon={UserMinus} label="Inactive" value={counts.INACTIVE ?? 0} note="not on attendance or payroll" tone="amber"
          active={status === "INACTIVE"} onClick={() => pickStatus("INACTIVE")} />
        <Tile icon={UserX} label="Left the company" value={leftCount} note="resigned or terminated" tone="rose"
          active={status === "LEFT"} onClick={() => pickStatus("LEFT")} />
        <Tile icon={Users} label="Everyone on file" value={everyone} tone="sky" active={status === ""} onClick={() => { setStatus(""); setPage(1); }} />
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={list.data?.total ?? 0} noun="Employee" onReset={reset} resettable={changed} />
        <div className="flex flex-wrap items-center gap-2.5 px-5 pb-4 pt-2">
          <label className="relative">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, code, CNIC or phone…"
              className={`${selectClass} w-[260px] pl-9`} />
          </label>
          <select className={selectClass} value={department} onChange={(e) => { setDepartment(e.target.value); setPage(1); }}>
            <option value="">All departments</option>
            {(lookups.data?.departments ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>

        {list.loading && !list.data ? <Spinner /> : (list.data?.items ?? []).length === 0 ? (
          <EmptyState>
            {everyone === 0 ? "No employees yet. Add the first one with “New employee”." : "No employee matches these filters."}
          </EmptyState>
        ) : (
          <div className="overflow-x-auto border-t border-line">
            <table className="w-full min-w-[980px] border-collapse text-left">
              <thead><tr className="border-b border-line">
                <GridTh sortKey="employee_code" sort={sort} direction={direction} onSort={onSort}>Code</GridTh>
                <GridTh sortKey="full_name" sort={sort} direction={direction} onSort={onSort}>Name</GridTh>
                <GridTh>Department</GridTh><GridTh>Designation</GridTh>
                <GridTh sortKey="employment_type" sort={sort} direction={direction} onSort={onSort}>Type</GridTh>
                <GridTh sortKey="joining_date" sort={sort} direction={direction} onSort={onSort}>Joined</GridTh>
                <GridTh>Mobile</GridTh>
                <GridTh sortKey="status" sort={sort} direction={direction} onSort={onSort}>Status</GridTh>
              </tr></thead>
              <tbody>
                {(list.data?.items ?? []).map((e, i) => (
                  <tr key={e.id} onClick={() => setOpenId(e.id)} className={`${gridRowClass(i)} cursor-pointer`}>
                    <td className={gridCellClass(false, "font-medium text-primary")}>{e.employee_code}</td>
                    <td className={gridCellClass(false, "font-medium")}>{e.full_name}</td>
                    <td className={gridCellClass(false, "text-muted")}>{e.department ?? "—"}</td>
                    <td className={gridCellClass(false, "text-muted")}>{e.designation ?? "—"}</td>
                    <td className={gridCellClass()}>{label(e.employment_type)}</td>
                    <td className={gridCellClass(false, "whitespace-nowrap")}>{fmtDate(e.joining_date)}</td>
                    <td className={gridCellClass(false, "text-muted")}>{e.phone ?? "—"}</td>
                    <td className={gridCellClass()}><HrBadge status={e.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {pages > 1 && (
          <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-3 text-[12.5px] text-muted">
            <Button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <span>Page {page} of {pages}</span>
            <Button disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        )}
      </section>

      {creating && <EmployeeForm employee={null} lookups={lookups.data} onClose={() => setCreating(false)}
        onSaved={(saved) => { setCreating(false); list.reload(); lookups.reload(); setOpenId(saved.id); }} />}
      {openId && <Profile id={openId} lookups={lookups.data} onClose={() => setOpenId(null)}
        onChanged={() => { list.reload(); lookups.reload(); }} />}
    </AppShell>
  );
}

/* ---------------------------------------------------------------- profile */

function Profile({ id, lookups, onClose, onChanged }: {
  id: string; lookups: Lookups | null; onClose: () => void; onChanged: () => void;
}) {
  const detail = useHr<EmployeeDetail>(`/hrms/employees/${id}`);
  const [mode, setMode] = useState<"edit" | "salary" | "leave" | "reinstate" | null>(null);
  const e = detail.data;
  const left = e ? ["RESIGNED", "TERMINATED"].includes(e.status) : false;
  const refresh = () => { detail.reload(); onChanged(); };

  return (
    <>
      <Modal title={e ? `${e.employee_code}  ${e.full_name}` : "Employee"} open={mode === null} width="lg" onClose={onClose}>
        <ErrorNote message={detail.error} />
        {!e ? <Spinner /> : (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2.5">
              <HrBadge status={e.status} />
              <span className="text-[12.8px] text-muted">
                {[e.designation, e.department, e.branch].filter(Boolean).join(" · ") || "No department or designation yet"}
              </span>
              <div className="ml-auto flex flex-wrap gap-2">
                <Button onClick={() => setMode("edit")}><Pencil size={13} /> Edit</Button>
                {e.can_see_pay && !left && <Button tone="soft" onClick={() => setMode("salary")}><Wallet size={13} /> Salary structure</Button>}
                {left ? <Button onClick={() => setMode("reinstate")}>Reinstate</Button>
                  : <Button tone="danger" onClick={() => setMode("leave")}>Record leaving</Button>}
              </div>
            </div>
            {left && (
              <p className="m-0 rounded-lg bg-amber/10 px-4 py-3 text-[12.5px]">
                {label(e.status)} on <b>{fmtDate(e.separation_date)}</b>{e.separation_reason ? ` — ${e.separation_reason}` : ""}
              </p>
            )}

            <div className="flex gap-4 max-sm:flex-col">
              {mediaUrl(e.photo_path) && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={mediaUrl(e.photo_path) ?? ""} alt={e.full_name}
                  className="h-[150px] w-[130px] flex-shrink-0 rounded-xl border border-line object-cover" />
              )}
              <div className="min-w-0 flex-1">
                <Panel title="Basic information">
                  <Fact label="Father name">{e.father_name}</Fact>
                  <Fact label="Father occupation">{e.father_occupation}</Fact>
                  <Fact label="Mother name">{e.mother_name}</Fact>
                  <Fact label="Department">{[e.department, e.sub_department].filter(Boolean).join(" › ")}</Fact>
                  <Fact label="Shift / weekly rest">{[e.shift, e.weekly_rest ? label(e.weekly_rest) : null].filter(Boolean).join(" · ")}</Fact>
                  <Fact label="Reporting to">{e.manager}</Fact>
                  <Fact label="Replaces">{e.replacement}</Fact>
                  <Fact label="EOBI #">{e.eobi_registered || e.eobi_number ? e.eobi_number || "Registered" : null}</Fact>
                  <Fact label="Social security #">{e.social_security_registered || e.social_security_number ? e.social_security_number || "Registered" : null}</Fact>
                  <Fact label="Orientation">{e.orientation_done ? `Done ${fmtDate(e.orientation_date)}${e.orientation_remarks ? ` · ${e.orientation_remarks}` : ""}` : null}</Fact>
                  <Fact label="Permanent address">{[e.address, e.city].filter(Boolean).join(", ")}</Fact>
                  <Fact label="Also">{[e.attendance_exempt && "Exempt for attendance", e.group_insurance && "Group insurance",
                    e.temporary_block && "Temporarily blocked"].filter(Boolean).join(" · ")}</Fact>
                </Panel>
              </div>
            </div>
            <Panel title="Official information">
              <Fact label="Joining date">{fmtDate(e.joining_date)}</Fact>
              <Fact label="Employee type">{label(e.employment_type)}</Fact>
              <Fact label="Grade">{e.grade}</Fact>
              <Fact label="Confirmation">{e.is_confirmed ? `Yes${e.confirmation_date ? ` · ${fmtDate(e.confirmation_date)}` : ""}` : "No"}</Fact>
              <Fact label="Probation">{e.probation_months ? `${e.probation_months} month(s)${e.probation_extend_months ? ` + ${e.probation_extend_months} extended` : ""}` : null}
                {e.probation_end_date ? <span className="text-faint"> · ends {fmtDate(e.probation_end_date)}</span> : null}</Fact>
              <Fact label="Vacancy date">{fmtDate(e.vacancy_date)}</Fact>
              <Fact label="Official email">{e.official_email}</Fact>
              <Fact label="Mobile allow / late allow">{e.mobile_allowed ? "Yes" : "No"} / {e.late_allowed ? "Yes" : "No"}</Fact>
            </Panel>
            <Panel title="Personal information">
              <Fact label="CNIC">{e.cnic}{e.cnic_expiry ? <span className="text-faint"> · expires {fmtDate(e.cnic_expiry)}</span> : null}</Fact>
              <Fact label="Father CNIC">{e.father_cnic}</Fact>
              <Fact label="National tax no">{e.ntn}</Fact>
              <Fact label="Date of birth">{fmtDate(e.date_of_birth)}{e.birth_place ? <span className="text-faint"> · {e.birth_place}</span> : null}</Fact>
              <Fact label="Gender / marital status">{[e.gender, e.marital_status].filter(Boolean).map((x) => label(x)).join(" · ")}</Fact>
              <Fact label="Nationality / religion">{[e.nationality, e.religion ? label(e.religion) : null].filter(Boolean).join(" · ")}</Fact>
              <Fact label="Mobile / phone">{[e.phone, e.phone_landline].filter(Boolean).join(" · ")}</Fact>
              <Fact label="Personal email">{e.email}</Fact>
              <Fact label="Emergency">{[e.emergency_contact_name, e.emergency_contact_phone].filter(Boolean).join(" · ")}</Fact>
              <Fact label="Blood group / hepatitis">{[e.blood_group, e.hepatitis_status].filter(Boolean).join(" · ")}</Fact>
              <Fact label="Cast">{e.caste}</Fact>
              <Fact label="Children">{e.children_count}</Fact>
            </Panel>
            {e.can_see_pay && (
              <Panel title="Confidential information">
                <Fact label="Salary mode">{label(e.payment_mode)}</Fact>
                <Fact label="Bank">{[e.bank_name, e.bank_account_title].filter(Boolean).join(" · ")}</Fact>
                <Fact label="Account / IBAN">{e.iban || e.bank_account_number}</Fact>
                <Fact label="Provident fund / overtime allow">{e.provident_fund_allowed ? "Yes" : "No"} / {e.overtime_allowed ? "Yes" : "No"}</Fact>
                <Fact label="Shift premium / fuel">{[e.shift_premium, e.fixed_fuel_amount].map((n) => (n ? money(n) : "—")).join(" / ")}</Fact>
                <Fact label="Taxable / overtime salary">{[e.taxable_salary, e.overtime_salary].map((n) => (n ? money(n) : "—")).join(" / ")}</Fact>
              </Panel>
            )}

            {e.can_see_pay && (
              <div className="rounded-xl border border-line">
                <div className="flex items-center border-b border-line px-4 py-2.5">
                  <h4 className="m-0 text-[13px] font-semibold">Salary structure</h4>
                  {e.salary && <span className="ml-2 text-[11.5px] text-faint">from {fmtDate(e.salary.effective_from)}</span>}
                </div>
                {!e.salary ? (
                  <p className="m-0 px-4 py-4 text-[12.5px] text-amber">
                    No salary has been entered. Payroll pays nothing for this employee until it is.
                  </p>
                ) : (
                  <div className="grid grid-cols-2 gap-x-8 px-4 py-3 text-[12.8px] max-sm:grid-cols-1">
                    <div>
                      <Line name="Basic salary" amount={e.salary.basic} />
                      {e.salary.lines.filter((l) => l.kind === "EARNING").map((l) => (
                        <Line key={l.component_id} name={l.name ?? ""} amount={l.amount} note={l.calc_type === "PERCENT_BASIC" ? `${l.value}% of basic` : undefined} />
                      ))}
                      <Line name="Gross" amount={e.salary.gross} bold />
                    </div>
                    <div>
                      {e.salary.lines.filter((l) => l.kind === "DEDUCTION").map((l) => (
                        <Line key={l.component_id} name={l.name ?? ""} amount={l.amount} note={l.calc_type === "PERCENT_BASIC" ? `${l.value}% of basic` : undefined} />
                      ))}
                      <Line name="Deductions" amount={e.salary.deductions} bold />
                      <Line name="Net for a full month" amount={e.salary.net} bold tone="text-primary" />
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="rounded-xl border border-line">
              <h4 className="m-0 border-b border-line px-4 py-2.5 text-[13px] font-semibold">Leave balance — {new Date().getFullYear()}</h4>
              {e.leave_balances.length === 0 ? (
                <p className="m-0 px-4 py-4 text-[12.5px] text-faint">No leave types are set up yet.</p>
              ) : (
                <div className="grid grid-cols-4 gap-3 px-4 py-3 max-md:grid-cols-2">
                  {e.leave_balances.map((b) => (
                    <div key={b.id} className="rounded-lg bg-hover/60 px-3 py-2">
                      <div className="text-[11.5px] text-muted">{b.leave_type}</div>
                      {b.is_paid ? (
                        <>
                          <div className="text-[17px] font-bold">{days(b.available)} <span className="text-[11px] font-normal text-faint">left</span></div>
                          <div className="text-[11px] text-faint">{days(b.used)} used of {days(b.entitled + b.carried_forward + b.adjustment)}</div>
                        </>
                      ) : (
                        <>
                          <div className="text-[17px] font-bold">{days(b.used)} <span className="text-[11px] font-normal text-faint">taken</span></div>
                          <div className="text-[11px] text-faint">unpaid, no limit</div>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {e.can_see_pay && (e.loans ?? []).length > 0 && (
              <div className="rounded-xl border border-line">
                <h4 className="m-0 border-b border-line px-4 py-2.5 text-[13px] font-semibold">Loans and advances</h4>
                <table className="w-full border-collapse text-[12.5px]">
                  <tbody>
                    {(e.loans ?? []).map((loan) => (
                      <tr key={loan.id} className="border-b border-line last:border-0">
                        <td className="px-4 py-2 font-medium">{loan.loan_number}</td>
                        <td className="px-2 py-2">{label(loan.kind)} · {fmtDate(loan.loan_date)}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{money(loan.amount)}</td>
                        <td className="px-2 py-2 text-right tabular-nums text-muted">owes {money(loan.outstanding)}</td>
                        <td className="px-4 py-2 text-right"><HrBadge status={loan.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {e.notes && <p className="m-0 whitespace-pre-wrap text-[12.5px] text-muted">{e.notes}</p>}
          </div>
        )}
      </Modal>

      {e && mode === "edit" && <EmployeeForm employee={e} lookups={lookups} onClose={() => setMode(null)}
        onSaved={() => { setMode(null); refresh(); }} />}
      {e && mode === "salary" && <SalaryForm employee={e} lookups={lookups} current={e.salary ?? null}
        onClose={() => setMode(null)} onSaved={() => { setMode(null); refresh(); }} />}
      {e && mode === "leave" && <Leaving employee={e} onClose={() => setMode(null)} onSaved={() => { setMode(null); refresh(); }} />}
      {e && mode === "reinstate" && (
        <ReasonDialog open title={`Reinstate ${e.full_name}`} confirmLabel="Reinstate" label="Why is the leaving being undone?"
          onClose={() => setMode(null)}
          onConfirm={async (reason) => { await api.post(`/hrms/employees/${e.id}/reinstate`, { reason }); refresh(); }}>
          <p className="m-0 text-[12.5px] text-muted">
            This clears the leaving date and makes the employee active again. Use it when the leaving was recorded by mistake;
            for someone who comes back later, add them as a new employee so both periods of service stay on record.
          </p>
        </ReasonDialog>
      )}
    </>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line">
      <h4 className="m-0 border-b border-line px-4 py-2.5 text-[13px] font-semibold">{title}</h4>
      <div className="grid grid-cols-3 gap-x-5 gap-y-3 px-4 py-3 max-md:grid-cols-2 max-sm:grid-cols-1">{children}</div>
    </div>
  );
}

function Line({ name, amount, note, bold, tone = "" }: { name: string; amount: number; note?: string; bold?: boolean; tone?: string }) {
  return (
    <div className={`flex items-baseline gap-2 border-b border-line py-1.5 last:border-0 ${bold ? "font-semibold" : ""} ${tone}`}>
      <span className="flex-1">{name}{note && <span className="ml-1.5 text-[11px] font-normal text-faint">{note}</span>}</span>
      <span className="tabular-nums">{money(amount)}</span>
    </div>
  );
}

function Leaving({ employee, onClose, onSaved }: { employee: EmployeeDetail; onClose: () => void; onSaved: () => void }) {
  const [status, setStatus] = useState("RESIGNED");
  const [on, setOn] = useState(todayIso());
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [owed, setOwed] = useState<number | null>(null);

  const save = async () => {
    if (reason.trim().length < 3) { setError("Give the reason; it is kept on the employee's record."); return; }
    setSaving(true); setError(null);
    try {
      const result = await api.post<{ outstanding_loans: number }>(`/hrms/employees/${employee.id}/separate`,
        { status, separation_date: on, reason: reason.trim() });
      if (result.outstanding_loans > 0) setOwed(result.outstanding_loans); else onSaved();
    } catch (err) { setError(errorText(err, "Could not record the leaving.")); } finally { setSaving(false); }
  };

  if (owed !== null) {
    return (
      <Modal title="Recorded — loans still outstanding" open width="sm" onClose={onSaved}>
        <p className="m-0 text-[12.8px]">
          {employee.full_name} still owes <b>PKR {money(owed)}</b> on loans or advances. The final payroll recovers one instalment
          as usual; settle the rest from Loans &amp; Advances with “Repayment”.
        </p>
      </Modal>
    );
  }
  return (
    <Modal title={`Record leaving — ${employee.full_name}`} open width="sm" saving={saving} error={error}
      onClose={onClose} onSave={save} saveLabel="Record leaving">
      <div className="space-y-4">
        <Field label="How" required>
          <Select value={status} placeholder="Choose…" onChange={(e) => setStatus(e.target.value || "RESIGNED")}
            options={[{ value: "RESIGNED", label: "Resigned" }, { value: "TERMINATED", label: "Terminated" }]} />
        </Field>
        <Field label="Last working day" required><TextInput type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Reason" required><TextArea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <p className="m-0 text-[11.5px] leading-relaxed text-faint">
          The employee stays on file. That month&apos;s payroll pays them up to the last working day; later months leave them out.
        </p>
      </div>
    </Modal>
  );
}
