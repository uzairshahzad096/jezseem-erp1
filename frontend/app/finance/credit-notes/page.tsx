"use client";

import { Suspense } from "react";
import { DocumentScreen } from "@/components/receivables/DocumentScreen";

export default function CreditNotesPage() {
  return <Suspense><DocumentScreen docType="credit_note" /></Suspense>;
}