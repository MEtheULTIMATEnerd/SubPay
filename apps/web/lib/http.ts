// Calls to the FastAPI service. Every request carries the signed-in user's
// Supabase access token; the API derives the user and organisation from it.
// Never send a user id or an organisation id from here.
import { API_URL } from "./env";
import { ApiError, type ErrorDetail } from "./errors";
import { supabase } from "./supabase";

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  /** Sent as JSON. */
  body?: unknown;
  /** Sent as multipart/form-data, for file uploads. Use instead of `body`. */
  form?: FormData;
  query?: Record<string, string | number | undefined>;
}

let onUnauthorized: (() => void) | null = null;

/** Called when the API rejects the session, so the app can sign the user out. */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

export async function apiFetch<T>(path: string, { method = "GET", body, form, query }: RequestOptions = {}): Promise<T> {
  const { data } = await supabase().auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new ApiError(401, "Sign in to continue", "unauthenticated");

  const url = new URL(`${API_URL}/api/v1${path}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        // For a form the browser sets Content-Type itself, including the boundary.
        ...(body === undefined || form ? {} : { "Content-Type": "application/json" }),
      },
      body: form ?? (body === undefined ? undefined : JSON.stringify(body)),
    });
  } catch {
    throw new ApiError(503, "Can't reach the SubPay server. Check your connection and try again.", "service_unavailable");
  }

  if (response.ok) {
    return (response.status === 204 ? undefined : await response.json()) as T;
  }

  const payload = (await response.json().catch(() => null)) as {
    error?: { code?: string; message?: string; details?: ErrorDetail[] };
  } | null;
  const error = new ApiError(
    response.status,
    payload?.error?.message ?? "Something went wrong. Please try again.",
    payload?.error?.code,
    payload?.error?.details,
  );
  if (response.status === 401) onUnauthorized?.();
  throw error;
}
