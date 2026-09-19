const BASE = "/api/v1";

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      /* ignore non-JSON errors */
    }
    throw new Error(
      res.status === 404
        ? `Not found: ${detail}`
        : `Request failed (${res.status}): ${detail}`
    );
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}