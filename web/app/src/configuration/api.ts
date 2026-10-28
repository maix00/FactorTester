export async function request(url: string, options: RequestInit = {}): Promise<any> {
  const response = await fetch(url, { ...options, credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...options.headers } });
  const value = await response.json().catch(() => ({}));
  if (!response.ok || value.success === false) throw Object.assign(new Error(value.error || `HTTP ${response.status}`), { status: response.status });
  return value;
}

