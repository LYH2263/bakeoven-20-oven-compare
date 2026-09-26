export class ApiError extends Error {
  status: number;
  data: unknown;
  constructor(status: number, data: unknown, fallback: string) {
    super(
      data && typeof data === "object" && "detail" in data
        ? String((data as Record<string, unknown>).detail)
        : fallback
    );
    this.status = status;
    this.data = data;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const isJson = (res.headers.get("content-type") || "").includes("application/json");
    const data = isJson ? await res.json().catch(() => undefined) : await res.text();
    const fallback = typeof data === "string" && data ? data : res.statusText;
    throw new ApiError(res.status, data, fallback);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}
