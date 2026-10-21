"use client";

import { GatePassScreen } from "@/components/gatepass/GatePassScreen";

/** Goods leaving the premises: a delivery, a machine going out for repair,
 *  something sent free of charge. Approving one takes the stock off the
 *  location it left from. */
export default function OutwardGatePassPage() {
  return <GatePassScreen passType="outward" />;
}
