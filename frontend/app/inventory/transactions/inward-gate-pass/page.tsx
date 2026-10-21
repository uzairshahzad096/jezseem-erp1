"use client";

import { GatePassScreen } from "@/components/gatepass/GatePassScreen";

/** Goods arriving, usually back against an outward pass. Approving one puts
 *  the stock back at the location. */
export default function InwardGatePassPage() {
  return <GatePassScreen passType="inward" />;
}
