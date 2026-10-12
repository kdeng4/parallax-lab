export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    cache: 'no-store',
  });
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const data = await response.json();
      message = typeof data.detail === 'string' ? data.detail : data.detail?.map((item: { msg?: string }) => item.msg).join('; ') || message;
    } catch { /* Keep the response status if the server returned HTML. */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const money = (value: number, digits = 0) => new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: digits,
}).format(value);
export const percent = (value: number) => `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
export const time = (value: string) => new Date(value).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
export const date = (value: string) => new Date(value).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
