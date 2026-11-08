"use client";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "/api/backend";
const TOKEN_KEY = "trendscope.token";
const USER_KEY = "trendscope.user";

export class ApiError extends Error {
  status: number;
  code: string;
  details: { field?: string | null; issue: string }[];
  requestId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: { field?: string | null; issue: string }[] = [],
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setSession(token: string, user: unknown): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* storage may be blocked; the in-memory session still works for the page */
  }
}

export function clearSession(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {
    /* ignore */
  }
}

export function readUser<T>(): T | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname !== "/login") {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/login?next=${next}`;
  }
}

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
  /** Skip the redirect-on-401 behaviour (used by the login screen). */
  noRedirect?: boolean;
  /** Do not attempt a refresh on 401 (used by the refresh call itself). */
  skipRefresh?: boolean;
};

let refreshInFlight: Promise<boolean> | null = null;

/**
 * Exchange the HttpOnly refresh cookie for a new access token. Concurrent
 * 401s share one request: the refresh token rotates on every use, so two
 * parallel refreshes would present the same token twice and be treated as
 * reuse, revoking the whole session.
 */
function refreshAccessToken(): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  if (!refreshInFlight) {
    refreshInFlight = request<import("./types").LoginResponse>("/auth/refresh", {
      method: "POST",
      noRedirect: true,
      skipRefresh: true,
    })
      .then((result) => {
        setSession(result.access_token, result.user);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  async function send(): Promise<Response> {
    const headers: Record<string, string> = { Accept: "application/json" };
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;

    let body: BodyInit | undefined;
    if (options.formData) {
      body = options.formData;
    } else if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.body);
    }

    try {
      return await fetch(`${API_BASE}${path}`, {
        method: options.method || (body ? "POST" : "GET"),
        headers,
        body,
        signal: options.signal,
        cache: "no-store",
        credentials: "include",
      });
    } catch (error) {
      if ((error as Error)?.name === "AbortError") throw error;
      throw new ApiError(
        0,
        "NETWORK_ERROR",
        "Cannot reach the TrendScope API. Check that the backend is running.",
      );
    }
  }

  let response = await send();

  if (
    response.status === 401 &&
    !options.noRedirect &&
    !options.skipRefresh &&
    !path.startsWith("/auth/")
  ) {
    if (await refreshAccessToken()) {
      response = await send();
    }
  }

  if (response.status === 401 && !options.noRedirect) {
    clearSession();
    redirectToLogin();
    throw new ApiError(401, "UNAUTHENTICATED", "Your session has expired. Sign in again.");
  }

  if (response.status === 204) return undefined as T;

  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    let message = response.statusText || "Request failed.";
    let details: { field?: string | null; issue: string }[] = [];
    let requestId: string | null = null;
    if (contentType.includes("application/json")) {
      try {
        const payload = await response.json();
        const err = payload?.error ?? payload;
        code = err?.code ?? code;
        message = err?.message ?? message;
        details = Array.isArray(err?.details) ? err.details : [];
        requestId = err?.request_id ?? null;
      } catch {
        /* fall through to generic message */
      }
    }
    throw new ApiError(response.status, code, message, details, requestId);
  }

  if (response.status === 202 || contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.text()) as unknown as T;
}

export const api = {
  get<T>(path: string, signal?: AbortSignal): Promise<T> {
    return request<T>(path, { method: "GET", signal });
  },
  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, { method: "POST", body: body ?? {} });
  },
  patch<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, { method: "PATCH", body: body ?? {} });
  },
  delete<T = void>(path: string): Promise<T> {
    return request<T>(path, { method: "DELETE" });
  },
  upload<T>(path: string, formData: FormData): Promise<T> {
    return request<T>(path, { method: "POST", formData });
  },
  login(body: { email: string; password: string }) {
    return request<import("./types").LoginResponse>("/auth/login", {
      method: "POST",
      body,
      noRedirect: true,
    });
  },
  /** Revoke the refresh token and clear its cookie. Called before sign-out. */
  async logout(): Promise<void> {
    try {
      await request<void>("/auth/logout", {
        method: "POST",
        noRedirect: true,
        skipRefresh: true,
      });
    } catch {
      /* the local session is still cleared even if the API is unreachable */
    }
  },
  /** Fetch a file with auth, then hand it to the browser as a download. */
  async download(path: string, fallbackName: string): Promise<void> {
    const response = await fetchFile(path, "DOWNLOAD_FAILED", "Download failed.");
    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || fallbackName;
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  },
  /** Open an authenticated file (used for the CSV template preview). */
  async text(path: string): Promise<string> {
    const response = await fetchFile(path, "FETCH_FAILED", "Fetch failed.");
    return response.text();
  },
};

/** Authenticated file fetch that retries once after a silent token refresh. */
async function fetchFile(path: string, code: string, message: string): Promise<Response> {
  async function send(): Promise<Response> {
    const token = getToken();
    return fetch(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: "include",
    });
  }

  let response = await send();
  if (response.status === 401 && (await refreshAccessToken())) {
    response = await send();
  }
  if (response.status === 401) {
    clearSession();
    redirectToLogin();
    throw new ApiError(401, "UNAUTHENTICATED", "Your session has expired. Sign in again.");
  }
  if (!response.ok) throw new ApiError(response.status, code, message);
  return response;
}

type QueryValue = string | number | boolean | null | undefined | string[];

export function queryString(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, String(item));
    } else {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}
