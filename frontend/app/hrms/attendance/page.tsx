"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCheck, ChevronLeft, ChevronRight, Download, Save } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Button, Card, EmptyState, ErrorNote, PageHeader, Spinner } from "@/components/finance/ui";
import { Tabs, selectClass } from "@/components/hrms/ui";
import { api } from "@/lib/api";
import { ATTENDANCE, MONTH_NAMES, days, download, errorText, fmtDate, todayIso, useHr, type Lookups } from "@/lib/hrms";

const TABS = [["daily", "Daily marking"], ["monthly", "Monthly sheet"]] as const;

export default function AttendancePage() {
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("daily");
  const lookups = useHr<Lookups>("/hrms/lookups");
  const [department, setDepartment] = useState("");
  return (
    <AppShell title="Attendance">
      <PageHeader title="Attendance" subtitle="Mark each day once; the monthly sheet and payroll read the same marks.">
        <select className={selectClass} value={department} onChange={(e) => setDepartment(e.target.value)}>
          <option value="">All departments</option>
          {(lookups.data?.departments ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </PageHeader>
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {tab === "daily" ? <Daily department={department} /> : <Monthly department={department} />}
    </AppShell>
  );
}

/* ---------------------------------------------------------------- daily */

interface DayRow {
  employee_id: string; employee_code: string; employee_name: string; shift: string | null; marked: boolean;
  status: string | null; default_status: string | null; check_in: string | null; check_out: string | null;
  worked_minutes: number; late_minutes: number; overtime_minutes: number; from_leave: boolean; remarks: string | null;
}
interface DaySheet { work_date: string; holiday: string | null; rows: DayRow[] }
interface Entry { status: string | null; check_in: string; check_out: string; remarks: string }

const MARKS = ["PRESENT", "LATE", "HALF_DAY", "ABSENT", "HOLIDAY", "WEEKLY_OFF"];
const shift = (iso: string, by: number): string => {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + by);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const weekday = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { weekday: "long" });
const hm = (minutes: number) => (minutes ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}` : "");

function Daily({ department }: { department: string }) {
  const today = todayIso();
  const [date, setDate] = useState(today);
  const sheet = useHr<DaySheet>(`/hrms/attendance/daily?work_date=${date}${department ? `&department_id=${department}` : ""}`);
  const [edits, setEdits] = useState<Record<string, Entry>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setEdits({}); setMessage(null); setError(null); }, [date, department]);

  const rows = sheet.data?.rows ?? [];
  const entryOf = (r: DayRow): Entry => edits[r.employee_id]
    ?? { status: r.status, check_in: r.check_in ?? "", check_out: r.check_out ?? "", remarks: r.remarks ?? "" };
  const change = (r: DayRow, patch: Partial<Entry>) =>
    setEdits((all) => ({ ...all, [r.employee_id]: { ...entryOf(r), ...patch } }));
  const dirty = Object.keys(edits).length;

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    let unmarked = 0;
    for (const r of rows) {
      const status = (edits[r.employee_id]?.status ?? r.status) ?? r.default_status;
      if (status) out[status] = (out[status] ?? 0) + 1; else unmarked += 1;
    }
    return { out, unmarked };
  }, [rows, edits]);

  const markAllPresent = () => {
    const next = { ...edits };
    for (const r of rows) {
      if (r.from_leave || r.default_status) continue;                 // leave, holidays and rest days stay as they are
      if (!(next[r.employee_id]?.status ?? r.status)) next[r.employee_id] = { ...entryOf(r), status: "PRESENT" };
    }
    setEdits(next);
  };

  const save = async () => {
    setSaving(true); setError(null); setMessage(null);
    try {
      const result = await api.put<{ saved: number; cleared: number; skipped_leave: number }>("/hrms/attendance/daily", {
        work_date: date,
        entries: Object.entries(edits).map(([employee_id, e]) => ({
          employee_id, status: e.status, check_in: e.check_in || null, check_out: e.check_out || null, remarks: e.remarks || null })),
      });
      setEdits({});
      setMessage(`Saved ${result.saved} mark(s)${result.cleared ? `, cleared ${result.cleared}` : ""}.`);
      sheet.reload();
    } catch (err) { setError(errorText(err, "Could not save the attendance.")); } finally { setSaving(false); }
  };

  const input = "w-[92px] rounded-md border border-line bg-bg px-2 py-1 text-[12px] outline-none focus:border-primary disabled:opacity-40";

  return (
    <Card
      title={`${weekday(date)}, ${fmtDate(date)}`}
      action={<>
        <Button onClick={() => setDate(shift(date, -1))} title="Previous day"><ChevronLeft size={14} /></Button>
        <input type="date" value={date} max={today} onChange={(e) => e.target.value && setDate(e.target.value)} className={selectClass} />
        <Button disabled={date >= today} onClick={() => setDate(shift(date, 1))} title="Next day"><ChevronRight size={14} /></Button>
        <Button tone="soft" onClick={markAllPresent} title="Marks everyone not yet marked as present. Leave, holidays and rest days are left alone.">
          <CheckCheck size={14} /> Mark the rest present
        </Button>
        <Button tone="primary" busy={saving} disabled={!dirty} onClick={save}><Save size={14} /> Save{dirty ? ` (${dirty})` : ""}</Button>
      </>}>
      <div className="px-5 pt-4"><ErrorNote message={error ?? sheet.error} /></div>
      {message && <p className="mx-5 mb-0 mt-0 rounded-lg bg-primary/10 px-4 py-2.5 text-[12.5px] text-primary">{message}</p>}
      {sheet.data?.holiday && (
        <p className="mx-5 mb-0 mt-3 rounded-lg bg-amber/10 px-4 py-2.5 text-[12.5px]">
          <b>{sheet.data.holiday}</b> — a holiday. Nobody needs marking unless they worked.
        </p>
      )}
      <div className="flex flex-wrap gap-2 px-5 py-3 text-[11.5px]">
        {Object.entries(ATTENDANCE).map(([key, a]) => (
          <span key={key} className={`rounded-full px-2.5 py-[3px] font-semibold ${a.tone}`}>{a.name} {counts.out[key] ?? 0}</span>
        ))}
        {counts.unmarked > 0 && <span className="rounded-full bg-amber/20 px-2.5 py-[3px] font-semibold text-amber">Not marked {counts.unmarked}</span>}
      </div>

      {sheet.loading && !sheet.data ? <Spinner /> : rows.length === 0 ? (
        <EmptyState>No employees were employed on this day{department ? " in this department" : ""}.</EmptyState>
      ) : (
        <div className="overflow-x-auto border-t border-line">
          <table className="w-full min-w-[1040px] border-collapse text-left">
            <thead><tr className="border-b border-line">
              <GridTh>Code</GridTh><GridTh>Name</GridTh><GridTh>Status</GridTh><GridTh>In</GridTh><GridTh>Out</GridTh>
              <GridTh numeric>Worked</GridTh><GridTh numeric>Late</GridTh><GridTh numeric>Overtime</GridTh><GridTh>Remarks</GridTh>
            </tr></thead>
            <tbody>
              {rows.map((r, i) => {
                const e = entryOf(r);
                const edited = Boolean(edits[r.employee_id]);
                const noTimes = !e.status || ["ABSENT", "HOLIDAY", "WEEKLY_OFF"].includes(e.status);
                return (
                  <tr key={r.employee_id} className={`${gridRowClass(i)} ${edited ? "!bg-primary/5" : ""}`}>
                    <td className={gridCellClass(false, "font-medium")}>{r.employee_code}</td>
                    <td className={gridCellClass()}>{r.employee_name}
                      {r.shift && <span className="block text-[10.5px] text-faint">{r.shift}</span>}</td>
                    <td className={gridCellClass()}>
                      {r.from_leave ? (
                        <span className={`rounded-full px-2.5 py-[3px] text-[11px] font-semibold ${ATTENDANCE.LEAVE.tone}`}
                          title="Recorded by an approved leave request. Cancel the request to change it.">On leave</span>
                      ) : (
                        <div className="flex flex-wrap items-center gap-1">
                          {MARKS.map((m) => {
                            const on = e.status === m;
                            const suggested = !e.status && r.default_status === m;
                            return (
                              <button key={m} type="button" title={ATTENDANCE[m].name}
                                onClick={() => change(r, { status: on ? null : m })}
                                className={`min-w-[30px] rounded-md px-1.5 py-1 text-[11px] font-semibold transition-colors
                                  ${on ? ATTENDANCE[m].tone : suggested ? "bg-hover text-muted ring-1 ring-line" : "text-faint hover:bg-hover"}`}>
                                {ATTENDANCE[m].short}
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </td>
                    <td className={gridCellClass()}>
                      <input type="time" className={input} disabled={r.from_leave || noTimes} value={e.check_in}
                        onChange={(ev) => change(r, { check_in: ev.target.value })} />
                    </td>
                    <td className={gridCellClass()}>
                      <input type="time" className={input} disabled={r.from_leave || noTimes} value={e.check_out}
                        onChange={(ev) => change(r, { check_out: ev.target.value })} />
                    </td>
                    <td className={gridCellClass(true, "text-muted")}>{edited ? "" : hm(r.worked_minutes)}</td>
                    <td className={gridCellClass(true, r.late_minutes ? "text-amber" : "")}>{edited ? "" : hm(r.late_minutes)}</td>
                    <td className={gridCellClass(true, "text-muted")}>{edited ? "" : hm(r.overtime_minutes)}</td>
                    <td className={gridCellClass()}>
                      <input className={`${input} w-full min-w-[140px]`} disabled={r.from_leave} value={e.remarks}
                        onChange={(ev) => change(r, { remarks: ev.target.value })} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="m-0 border-t border-line px-5 py-3 text-[11.5px] leading-relaxed text-faint">
        Click a letter to mark, click it again to clear. With clock times entered, arriving after the shift&apos;s grace period
        becomes Late automatically, and time beyond the shift counts as overtime. An outlined letter is what the day already is
        (holiday or rest day) without anyone marking it. Leave is not marked here: it comes from approved leave requests.
      </p>
    </Card>
  );
}

/* ---------------------------------------------------------------- monthly */

interface MonthRow {
  employee_id: string; employee_code: string; employee_name: string; department: string | null;
  days: Record<string, string | null>; present: number; absent: number; half_days: number; late_count: number;
  paid_leave: number; unpaid_leave: number; holidays: number; weekly_offs: number; not_employed: number;
  unmarked: number; overtime_hours: number;
}
interface MonthSheet { year: number; month: number; days: string[]; rows: MonthRow[] }

function Monthly({ department }: { department: string }) {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const qs = `year=${year}&month=${month}${department ? `&department_id=${department}` : ""}`;
  const sheet = useHr<MonthSheet>(`/hrms/attendance/monthly?${qs}`);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const step = (by: number) => {
    const next = new Date(year, month - 1 + by, 1);
    setYear(next.getFullYear()); setMonth(next.getMonth() + 1);
  };
  const exportSheet = async () => {
    setExporting(true); setError(null);
    try { await download(`/hrms/attendance/monthly/export?${qs}`, `attendance-${year}-${month}.xlsx`); }
    catch (err) { setError(errorText(err, "Could not build the file.")); } finally { setExporting(false); }
  };
  const dayCell = (status: string | null | undefined) => {
    if (status === null || status === undefined) return <span className="text-faint" title="Not employed on this day">·</span>;
    if (status === "") return null;                                   // a day that has not happened yet
    const assumed = status.startsWith("~");
    const a = ATTENDANCE[assumed ? status.slice(1) : status];
    if (!a) return null;
    return (
      <span title={assumed ? `Not marked — counted as ${a.name.toLowerCase()}` : a.name}
        className={`inline-block min-w-[21px] rounded px-0 py-[2px] text-[10px] font-semibold ${assumed ? "text-faint ring-1 ring-line" : a.tone}`}>
        {a.short}
      </span>
    );
  };
  const rows = sheet.data?.rows ?? [];

  return (
    <Card title={`${MONTH_NAMES[month - 1]} ${year}`}
      action={<>
        <Button onClick={() => step(-1)} title="Previous month"><ChevronLeft size={14} /></Button>
        <select className={selectClass} value={month} onChange={(e) => setMonth(Number(e.target.value))}>
          {MONTH_NAMES.map((name, i) => <option key={name} value={i + 1}>{name}</option>)}
        </select>
        <input type="number" className={`${selectClass} w-[86px]`} value={year} min={2000} max={2100} onChange={(e) => setYear(Number(e.target.value) || year)} />
        <Button onClick={() => step(1)} title="Next month"><ChevronRight size={14} /></Button>
        <Button busy={exporting} onClick={exportSheet}><Download size={14} /> Excel</Button>
      </>}>
      <div className="px-5 pt-4"><ErrorNote message={error ?? sheet.error} /></div>
      {sheet.loading && !sheet.data ? <Spinner /> : rows.length === 0 ? (
        <EmptyState>No employees were employed in this month{department ? " in this department" : ""}.</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="border-collapse text-left">
            <thead>
              <tr className="border-b border-line">
                <th className="sticky left-0 z-10 min-w-[190px] border-r border-line bg-surface px-3 py-2 text-[11.5px] font-semibold text-primary">Employee</th>
                {(sheet.data?.days ?? []).map((d) => {
                  const date = new Date(`${d}T12:00:00`);
                  const sunday = date.getDay() === 0;
                  return (
                    <th key={d} className={`min-w-[25px] px-0 py-1.5 text-center text-[10.5px] font-medium ${sunday ? "text-rose" : "text-muted"}`}>
                      <div>{date.toLocaleDateString("en-GB", { weekday: "narrow" })}</div><div className="font-semibold">{date.getDate()}</div>
                    </th>
                  );
                })}
                {[["Present", "Days present"], ["Absent", "Days absent"], ["Late", "Late arrivals"], ["Leave", "Paid leave days"],
                  ["Unpaid", "Unpaid leave days"], ["OT h", "Overtime hours"]].map(([h, title]) => (
                  <th key={h} title={title} className="whitespace-nowrap border-l border-line px-2 py-2 text-right text-[11px] font-semibold text-primary">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.employee_id} className={`border-b border-line last:border-0 ${i % 2 ? "bg-hover/50" : ""}`}>
                  <td className={`sticky left-0 z-10 border-r border-line px-3 py-1.5 text-[12.3px] ${i % 2 ? "bg-hover" : "bg-surface"}`}>
                    <span className="font-medium">{r.employee_name}</span>
                    <span className="block text-[10.5px] text-faint">{r.employee_code}{r.department ? ` · ${r.department}` : ""}</span>
                  </td>
                  {(sheet.data?.days ?? []).map((d) => <td key={d} className="px-0 py-1 text-center">{dayCell(r.days[d])}</td>)}
                  <td className="border-l border-line px-2.5 text-right text-[12.3px] tabular-nums">{days(r.present)}</td>
                  <td className={`border-l border-line px-2.5 text-right text-[12.3px] tabular-nums ${r.absent ? "font-semibold text-rose" : "text-faint"}`}>{days(r.absent)}</td>
                  <td className={`border-l border-line px-2.5 text-right text-[12.3px] tabular-nums ${r.late_count ? "text-amber" : "text-faint"}`}>{r.late_count}</td>
                  <td className="border-l border-line px-2.5 text-right text-[12.3px] tabular-nums">{days(r.paid_leave)}</td>
                  <td className={`border-l border-line px-2.5 text-right text-[12.3px] tabular-nums ${r.unpaid_leave ? "text-rose" : "text-faint"}`}>{days(r.unpaid_leave)}</td>
                  <td className="border-l border-line px-2.5 text-right text-[12.3px] tabular-nums">{days(r.overtime_hours)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3 text-[11px] text-faint">
        {Object.values(ATTENDANCE).map((a) => (
          <span key={a.short} className="flex items-center gap-1"><span className={`rounded px-1 py-[1px] font-semibold ${a.tone}`}>{a.short}</span>{a.name}</span>
        ))}
        <span className="flex items-center gap-1"><span className="rounded px-1 py-[1px] font-semibold ring-1 ring-line">P</span>
          not marked, counted by the policy in HR Setup</span>
      </div>
    </Card>
  );
}
