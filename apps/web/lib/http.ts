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
  /** For a `form` upload: called with how much has been sent, from 0 to 1. */
  onUploadProgress?: (fraction: number) => void;
}

type ErrorPayload = { error?: { code?: string; message?: string; details?: ErrorDetail[] } } | null;
const UNREACHABLE = "Can't reach the SubPay server. Check your connection and try again.";

function toError(status: number, payload: ErrorPayload): ApiError {
  return new ApiError(status, payload?.error?.message ?? "Something went wrong. Please try again.", payload?.error?.code, payload?.error?.details);
}

/** fetch() cannot report how much of an upload has been sent, so uploads that show progress use XMLHttpRequest. */
function upload(url: URL, method: string, token: string, form: FormData, onProgress: (fraction: number) => void): Promise<{ status: number; payload: unknown }> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open(method, url.toString());
    request.setRequestHeader("Authorization", `Bearer ${token}`);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress(Math.min(1, event.loaded / event.total));
    };
    request.onload = () => {
      let payload: unknown = null;
      try {
        payload = request.responseText ? JSON.parse(request.responseText) : null;
      } catch {
        // not JSON: handled by the caller as an error with the default message
      }
      resolve({ status: request.status, payload });
    };
    request.onerror = () => reject(new ApiError(503, UNREACHABLE, "service_unavailable"));
    request.onabort = request.onerror;
    request.send(form);
  });
}

let onUnauthorized: (() => void) | null = null;

/** Called when the API rejects the session, so the app can sign the user out. */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

export async function apiFetch<T>(path: string, { method = "GET", body, form, query, onUploadProgress }: RequestOptions = {}): Promise<T> {
  const { data } = await supabase().auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new ApiError(401, "Sign in to continue", "unauthenticated");

  const url = new URL(`${API_URL}/api/v1${path}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }

  if (form && onUploadProgress && typeof XMLHttpRequest !== "undefined") {
    const { status, payload } = await upload(url, method, token, form, onUploadProgress);
    if (status >= 200 && status < 300) {
      onUploadProgress(1);
      return payload as T;
    }
    if (status === 401) onUnauthorized?.();
    throw toError(status, payload as ErrorPayload);
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
    throw new ApiError(503, UNREACHABLE, "service_unavailable");
  }

  if (response.ok) {
    return (response.status === 204 ? undefined : await response.json()) as T;
  }

  const error = toError(response.status, (await response.json().catch(() => null)) as ErrorPayload);
  if (response.status === 401) onUnauthorized?.();
  throw error;
}
