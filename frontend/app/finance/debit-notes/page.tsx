"use client";

import { Suspense } from "react";
import { DocumentScreen } from "@/components/receivables/DocumentScreen";

export default function DebitNotesPage() {
  return <Suspense><DocumentScreen docType="debit_note" /></Suspense>;
}