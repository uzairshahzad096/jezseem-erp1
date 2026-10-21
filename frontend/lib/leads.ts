"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

export interface Stage { name: string; probability: number; open: boolean }
export interface LeadLookups {
  stages: Stage[];
  ratings: string[];
  activity_types: string[];
  lost_reasons: string[];
  sources: { id: string; name: string }[];
  users: { id: string; name: string }[];
}

export interface Lead {
  id: string;
  lead_number: string;
  lead_date: string;
  title: string;
  customer_id: string | null;
  customer_name: string | null;
  is_customer: boolean;
  company_name: string;
  contact_person: string | null;
  designation: string | null;
  phone: string | null;
  email: string | null;
  city: string | null;
  address: string | null;
  source_id: string | null;
  source: string | null;
  interest: string | null;
  estimated_value: number;
  currency: string;
  weighted_value: number;
  probability: number;
  expected_close_date: string | null;
  stage: string;
  rating: string;
  owner_id: string | null;
  owner: string | null;
  quotation_id: string | null;
  lost_reason: string | null;
  closed_at: string | null;
  remarks: string | null;
  next_follow_up: string | null;
  overdue: boolean;
  last_activity_at: string | null;
  updated_at: string;
  activities?: Activity[];
  quotation?: { id: string; doc_number: string; doc_date: string; status: string; net_receivable: number } | null;
}

export interface Activity {
  id: string;
  activity_type: string;
  activity_at: string;
  summary: string;
  outcome: string | null;
  due_date: string | null;
  done_at: string | null;
  is_follow_up: boolean;
  open: boolean;
  owner: string | null;
  created_by: string | null;
}

export const API = "/leads";

/** Each stage's colour, used on the board, the chips and the bars. */
export const STAGE_TONE: Record<string, { bar: string; chip: string; dot: string }> = {
  New: { bar: "bg-sky", chip: "bg-sky/10 text-sky", dot: "bg-sky" },
  Contacted: { bar: "bg-violet", chip: "bg-violet/10 text-violet", dot: "bg-violet" },
  Qualified: { bar: "bg-amber", chip: "bg-amber/10 text-amber", dot: "bg-amber" },
  Quoted: { bar: "bg-primary/70", chip: "bg-primary/10 text-primary", dot: "bg-primary/70" },
  Negotiation: { bar: "bg-primary", chip: "bg-primary/15 text-primary", dot: "bg-primary" },
  Won: { bar: "bg-primary-dark", chip: "bg-primary text-on-primary", dot: "bg-primary-dark" },
  Lost: { bar: "bg-rose", chip: "bg-rose/10 text-rose", dot: "bg-rose" },
};
export const RATING_TONE: Record<string, string> = {
  Hot: "bg-rose/10 text-rose", Warm: "bg-amber/10 text-amber", Cold: "bg-sky/10 text-sky",
};

export function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export const todayIso = () => new Date().toISOString().slice(0, 10);
export const addDays = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const fmtDate = (iso: string | null | undefined) => {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${Number(d)} ${MONTHS[Number(m) - 1]} ${y}`;
};
/** "today", "tomorrow", "in 3 days", "2 days late". */
export const relDay = (iso: string | null | undefined) => {
  if (!iso) return "";
  const a = new Date(`${iso.slice(0, 10)}T00:00:00`).getTime();
  const b = new Date(`${todayIso()}T00:00:00`).getTime();
  const n = Math.round((a - b) / 86400000);
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n === -1) return "yesterday";
  return n > 0 ? `in ${n} days` : `${-n} days late`;
};
export const timeAgo = (iso: string | null | undefined) => {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(mins, 1)} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  const days = Math.round(hrs / 24);
  return days < 30 ? `${days} days ago` : fmtDate(iso);
};

/** 5,000,000 -> 50 lakh style is how the business talks; show both compact and full. */
export const compact = (n: number) => {
  if (n >= 10000000) return `${(n / 10000000).toFixed(n >= 100000000 ? 0 : 1)} Cr`;
  if (n >= 100000) return `${(n / 100000).toFixed(n >= 1000000 ? 0 : 1)} Lac`;
  if (n >= 1000) return `${Math.round(n / 1000)}K`;
  return String(Math.round(n));
};
export const money = (n: number | null | undefined) =>
  (n ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
export const initials = (name: string | null | undefined) =>
  (name ?? "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("") || "?";

export function useLeadLookups() {
  const [data, setData] = useState<LeadLookups | null>(null);
  useEffect(() => { api.get<LeadLookups>(`${API}/lookups`).then(setData).catch(() => setData(null)); }, []);
  return data;
}

export function useFetch<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) { setData(null); setLoading(false); return; }
    let live = true;
    setLoading(true);
    api.get<T>(path).then((d) => { if (live) { setData(d); setError(null); } })
      .catch((e) => { if (live) setError(errorText(e, "Could not load.")); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [path, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, loading, error, reload };
}
