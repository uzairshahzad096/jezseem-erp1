"use client";

import { Suspense } from "react";
import { DocumentScreen } from "@/components/receivables/DocumentScreen";

export default function InvoicesPage() {
  return <Suspense><DocumentScreen docType="sales_invoice" /></Suspense>;
}