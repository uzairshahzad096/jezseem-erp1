import { redirect } from "next/navigation";

export default function CalibrationIndex() {
  redirect("/calibration/machine-definitions");
}
