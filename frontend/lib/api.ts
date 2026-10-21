/**
 * Thin API client for the FastAPI backend.
 *
 * The access token is kept in memory + sessionStorage for now. Moving it to
 * an httpOnly cookie is tracked for the security hardening pass (spec §15)
 * and will change only this file.
 */

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

console.log("[Jezseem API] BASE =", BASE);

const TOKEN_KEY = "jezseem-access-token";

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage unavailable — session will not survive a reload */
  }
}

export function clearToken(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* nothing to clear */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  // A multipart body must not carry an explicit Content-Type: the browser
  // sets it along with the boundary, and overriding it makes the upload
  // unparseable server-side.
  const isMultipart = init.body instanceof FormData;

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        ...(isMultipart ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    });
  } catch {
    // fetch() only rejects on network-level failure: the API is unreachable,
    // or the browser blocked the response (usually a CORS-less 500). Say so,
    // rather than leaving the user with a bare "Failed to fetch".
    throw new ApiError(
      0,
      `Cannot reach the ERP server at ${BASE}. Check that the backend is running ` +
        `(docker compose ps) and look at its logs (docker compose logs backend).`,
    );
  }

  if (!res.ok) {
    // Surface the backend's human-readable detail rather than a bare status.
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      // A form value the server could not read: say which field, e.g.
      // "Freight amount: Input should be a valid decimal (line 2)".
      else if (Array.isArray(body.detail) && body.detail.length) {
        detail = body.detail.slice(0, 3).map((e: { loc?: (string | number)[]; msg?: string }) => {
          const loc = (e.loc ?? []).filter((p) => p !== "body");
          const line = loc.find((p) => typeof p === "number");
          const field = String([...loc].reverse().find((p) => typeof p === "string") ?? "value").replace(/_/g, " ");
          return `${field[0].toUpperCase()}${field.slice(1)}: ${e.msg ?? "not valid"}`
            + (typeof line === "number" ? ` (line ${line + 1})` : "");
        }).join("; ");
      }
    } catch {
      /* response had no JSON body */
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  // Generic verbs used by the module screens.
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  put: <T,>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  del: (path: string) => request<void>(path, { method: "DELETE" }),

  /** Single-file multipart upload, e.g. a product image. */
  upload: <T,>(path: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<T>(path, { method: "POST", body });
  },

  login: (username: string, password: string) =>
    request<{ access_token: string; refresh_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  authStatus: () => request<{ auth_required: boolean }>("/auth/status"),

  me: () =>
    request<{ id: string; username: string; full_name: string; roles: string[] }>("/auth/me"),

  dashboardSummary: () => request<DashboardSummary>("/dashboard/summary"),
};

export interface StatValue {
  value: number | null;
  formatted: string | null;
  delta_percent: number | null;
}

export interface ChartData {
  categories: string[];
  series: { name: string; data: number[] }[];
}

export interface ActivityItem {
  id: string;
  title: string;
  subtitle: string;
  status: "pending" | "progress" | "rejected" | "done";
}

export interface DashboardSummary {
  company_name: string;
  branch_name: string | null;
  financial_year: string | null;
  user_full_name: string;
  stats: Record<string, StatValue>;
  revenue: ChartData | null;
  sales_statistics: Record<string, ChartData>;
  recent_activity: ActivityItem[];
  top_products: { name: string; category: string; meta: string; tag: string }[];
}
