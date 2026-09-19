import { STATUS_LABELS } from "../types";

export default function StatusBadge({ status }: { status: string }) {
  const label = STATUS_LABELS[status] ?? status;
  return <span className={`badge status-${status.replace("_", "-")}`}>{label}</span>;
}