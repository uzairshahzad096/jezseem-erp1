import { redirect } from "next/navigation";

export default function ReportsIndex() {
  redirect("/inventory/reports/product-stock");
}
