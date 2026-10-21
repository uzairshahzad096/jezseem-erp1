"use client";

import Link from "next/link";
import {
  Banknote, CalendarClock, ChevronRight, ClipboardCheck, HandCoins, UserCheck, UserX, Users,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { StatCard } from "@/components/dashboard/StatCard";
import { Card, ErrorNote, PageHeader, Spinner } from "@/components/finance/ui";
import { HrBadge } from "@/components/hrms/ui";
import { MONTH_NAMES, fmtDate, label, money, useHr } from "@/lib/hrms";

interface Person { id: string; code: string; name: string; department: string | null; date?: string; day?: number; leave_type?: string; until?: string }
interface Dashboard {
  as_of: string; headcount: number; total_on_file: number;
  by_department: { name: string; count: number }[];
  by_employment_type: { name: string; count: number }[];
  today: { marked: number; unmarked: number; present: number; late: number; absent: number; half_day: number; on_leave: number };
  on_leave_today: Person[]; pending_leave_requests: number;
  joined_this_month: Person[]; left_this_month: Person[]; probation_ending: Person[]; cnic_expiring: Person[];
  birthdays_this_month: Person[]; can_see_pay: boolean;
  last_payroll: { id: string; run_number: string; status: string; period: string; total_net: number; employees: number } | null;
  loans_outstanding: number; active_loans: number; employees_without_salary: number; setup_needed: boolean;
}

const LINKS = [
  ["Employees", "/hrms/employees", "Profiles, job details and salary structures"],
  ["Attendance", "/hrms/attendance", "Mark the day, review the month"],
  ["Leave", "/hrms/leave", "Requests, approvals and balances"],
  ["Loans & Advances", "/hrms/loans", "What employees owe and how it is recovered"],
  ["Payroll", "/hrms/payroll", "Calculate, approve and pay the month"],
  ["HR Setup", "/hrms/setup", "Departments, shifts, holidays, leave and pay rules"],
];

export default function HrDashboardPage() {
  const { data, loading, error } = useHr<Dashboard>("/hrms/dashboard");
  const month = MONTH_NAMES[new Date().getMonth()];

  return (
    <AppShell title="HRMS">
      <PageHeader title="Human Resources" subtitle={data ? `As of ${fmtDate(data.as_of)}` : undefined} />
      <ErrorNote message={error} />
      {loading && <Spinner />}

      {data?.setup_needed && (
        <div className="mb-5 rounded-[14px] border border-amber/40 bg-amber/10 px-5 py-4 text-[12.8px]">
          <b>HR is not set up yet.</b> Start with the departments, designations, shifts and leave types — the standard lists can be
          added in one click and edited afterwards.{" "}
          <Link href="/hrms/setup" className="font-medium text-primary hover:underline">Open HR Setup →</Link>
        </div>
      )}
      {data && !data.setup_needed && data.headcount === 0 && (
        <div className="mb-5 rounded-[14px] border border-amber/40 bg-amber/10 px-5 py-4 text-[12.8px]">
          <b>No employees yet.</b>{" "}
          <Link href="/hrms/employees" className="font-medium text-primary hover:underline">Add the first employee →</Link>
        </div>
      )}

      {data && (
        <>
          <div className="mb-5 grid grid-cols-4 gap-[18px] max-xl:grid-cols-2 max-sm:grid-cols-1">
            <StatCard label="Employees" tone="green" icon={Users} value={String(data.headcount)}
              delta={data.total_on_file > data.headcount ? `${data.total_on_file} on file including former staff` : null} />
            <StatCard label="Present today" tone="sky" icon={UserCheck} value={String(data.today.present)}
              delta={data.today.unmarked ? `${data.today.unmarked} not marked yet` : data.today.late ? `${data.today.late} late` : "everyone marked"} />
            <StatCard label="Absent / on leave today" tone="rose" icon={UserX} value={`${data.today.absent} / ${data.today.on_leave}`}
              delta={data.today.half_day ? `${data.today.half_day} half day` : null} />
            <StatCard label="Leave requests waiting" tone="violet" icon={CalendarClock} value={String(data.pending_leave_requests)} />
          </div>

          <div className="grid grid-cols-3 gap-[18px] max-xl:grid-cols-1">
            <Card title="Needs attention">
              <ul className="m-0 list-none p-0 text-[12.8px]">
                {([
                  ["Leave requests waiting for a decision", data.pending_leave_requests, "/hrms/leave"],
                  ["Employees not marked today", data.today.unmarked, "/hrms/attendance"],
                  ["Probation ending within 30 days", data.probation_ending.length, "/hrms/employees"],
                  ["CNIC expired or expiring within 60 days", data.cnic_expiring.length, "/hrms/employees"],
                  ...(data.can_see_pay ? [["Employees without a salary structure", data.employees_without_salary, "/hrms/employees"]] : []),
                ] as [string, number, string][]).map(([text, count, href]) => (
                  <li key={text}>
                    <Link href={href} className="flex items-center gap-2 border-b border-line px-5 py-2.5 last:border-0 hover:bg-hover">
                      <span className="flex-1">{text}</span>
                      <span className={`min-w-[28px] rounded-full px-2 py-[1px] text-center text-[11.5px] font-semibold
                                        ${count ? "bg-amber/15 text-amber" : "bg-hover text-faint"}`}>{count}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>

            <Card title="Headcount by department">
              {data.by_department.length === 0 ? <p className="m-0 px-5 py-5 text-[12.5px] text-faint">No employees yet.</p> : (
                <ul className="m-0 list-none space-y-2.5 px-5 py-4">
                  {data.by_department.map((d) => (
                    <li key={d.name} className="text-[12.5px]">
                      <div className="mb-1 flex"><span className="flex-1">{d.name}</span><span className="font-semibold">{d.count}</span></div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-hover">
                        <div className="h-full rounded-full bg-primary" style={{ width: `${(d.count / data.headcount) * 100}%` }} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              {data.by_employment_type.length > 0 && (
                <div className="flex flex-wrap gap-1.5 border-t border-line px-5 py-3">
                  {data.by_employment_type.map((t) => (
                    <span key={t.name} className="rounded-full bg-hover px-2.5 py-[3px] text-[11px] text-muted">{label(t.name)} {t.count}</span>
                  ))}
                </div>
              )}
            </Card>

            <Card title="HR screens">
              <ul className="m-0 list-none p-0">
                {LINKS.map(([text, href, hint]) => (
                  <li key={href}>
                    <Link href={href} className="flex items-center gap-2 border-b border-line px-5 py-2.5 text-[12.8px] last:border-0 hover:bg-hover hover:text-primary">
                      <span className="flex-1"><span className="font-medium">{text}</span>
                        <span className="block text-[11.5px] text-faint">{hint}</span></span>
                      <ChevronRight size={14} className="text-faint" />
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>

            {data.can_see_pay && (
              <Card title="Payroll and loans">
                <div className="space-y-3 px-5 py-4 text-[12.8px]">
                  {data.last_payroll ? (
                    <Link href={`/hrms/payroll?run=${data.last_payroll.id}`} className="block rounded-lg bg-hover/60 px-3.5 py-3 hover:bg-hover">
                      <div className="flex items-center gap-2">
                        <Banknote size={15} className="text-primary" />
                        <span className="font-semibold">{data.last_payroll.period}</span>
                        <HrBadge status={data.last_payroll.status} />
                      </div>
                      <div className="mt-1 text-[18px] font-bold">PKR {money(data.last_payroll.total_net)}</div>
                      <div className="text-[11.5px] text-faint">net pay to {data.last_payroll.employees} employee(s) · {data.last_payroll.run_number}</div>
                    </Link>
                  ) : (
                    <p className="m-0 text-faint">No payroll has been run yet.</p>
                  )}
                  <Link href="/hrms/loans" className="flex items-center gap-2 rounded-lg bg-hover/60 px-3.5 py-3 hover:bg-hover">
                    <HandCoins size={15} className="text-amber" />
                    <span className="flex-1">{data.active_loans} active loan(s) and advance(s)</span>
                    <span className="font-semibold">PKR {money(data.loans_outstanding)}</span>
                  </Link>
                </div>
              </Card>
            )}

            <Card title="On leave today">
              <People rows={data.on_leave_today} empty="Nobody is on leave today."
                detail={(p) => `${p.leave_type}${p.until ? ` · back after ${fmtDate(p.until)}` : ""}`} />
            </Card>

            <Card title={`${month}: joiners, leavers and birthdays`}>
              <People rows={[
                ...data.joined_this_month.map((p) => ({ ...p, note: `Joined ${fmtDate(p.date)}` })),
                ...data.left_this_month.map((p) => ({ ...p, note: `Left ${fmtDate(p.date)}` })),
                ...data.birthdays_this_month.map((p) => ({ ...p, note: `Birthday on the ${p.day}${ordinal(p.day ?? 0)}` })),
              ]} empty="Nothing this month." detail={(p) => (p as Person & { note: string }).note} />
            </Card>

            {(data.probation_ending.length > 0 || data.cnic_expiring.length > 0) && (
              <Card title="Dates coming up">
                <People rows={[
                  ...data.probation_ending.map((p) => ({ ...p, note: `Probation ends ${fmtDate(p.date)}` })),
                  ...data.cnic_expiring.map((p) => ({ ...p, note: `CNIC expires ${fmtDate(p.date)}` })),
                ]} empty="" detail={(p) => (p as Person & { note: string }).note} />
              </Card>
            )}
          </div>

          <p className="mt-4 flex items-center gap-1.5 text-[11.5px] text-faint">
            <ClipboardCheck size={13} /> Attendance figures are today&apos;s marks; anyone not marked is listed under “Needs attention”.
          </p>
        </>
      )}
    </AppShell>
  );
}

const ordinal = (n: number) => (n % 10 === 1 && n !== 11 ? "st" : n % 10 === 2 && n !== 12 ? "nd" : n % 10 === 3 && n !== 13 ? "rd" : "th");

function People({ rows, empty, detail }: { rows: Person[]; empty: string; detail: (p: Person) => string }) {
  if (rows.length === 0) return <p className="m-0 px-5 py-5 text-[12.5px] text-faint">{empty}</p>;
  return (
    <ul className="m-0 max-h-[260px] list-none overflow-y-auto p-0">
      {rows.map((p, i) => (
        <li key={`${p.id}-${i}`}>
          <Link href={`/hrms/employees?open=${p.id}`} className="flex items-center gap-3 border-b border-line px-5 py-2.5 text-[12.8px] last:border-0 hover:bg-hover">
            <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary">
              {p.name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase()}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{p.name}</span>
              <span className="block truncate text-[11.5px] text-faint">{detail(p)}</span>
            </span>
            <span className="text-[11px] text-faint">{p.department}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
