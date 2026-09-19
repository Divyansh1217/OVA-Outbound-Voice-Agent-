export function formatDate(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDuration(seconds: number): string {
  if (!seconds) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function statusClass(status: string): string {
  return `status-${status.replace("_", "-")}`;
}

export function inferStatus(value: string, ref: string): string | null {
  const num = parseFloat(value);
  if (Number.isNaN(num)) return null;
  const upper = ref.match(/<\s*([\d.]+)/)?.[1];
  const lower = ref.match(/>\s*([\d.]+)/)?.[1];
  const range = ref.match(/([\d.]+)\s*[-–to]+\s*([\d.]+)/);
  if (range) {
    const lo = parseFloat(range[1]);
    const hi = parseFloat(range[2]);
    if (num > hi) return "HIGH";
    if (num < lo) return "LOW";
    return "NORMAL";
  }
  if (upper && num > parseFloat(upper)) return "HIGH";
  if (lower && num < parseFloat(lower)) return "LOW";
  return null;
}

export function statusBadgeClass(status: string): string {
  const map: Record<string, string> = {
    HIGH: "badge-danger",
    LOW: "badge-warn",
    "BORDERLINE HIGH": "badge-warn",
    CRITICAL: "badge-danger",
    NORMAL: "badge-ok",
  };
  return map[status] ?? "badge-neutral";
}