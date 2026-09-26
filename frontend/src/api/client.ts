export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = text || res.statusText;
    try {
      const data = JSON.parse(text);
      if (typeof data?.detail === "string") detail = data.detail;
    } catch { /* 非 JSON 错误体，按原文展示 */ }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}
