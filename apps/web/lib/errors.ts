// The one error type the UI handles. `message` is always safe to show to a user.
// Mirrors the API's error shape: { "error": { "code", "message", "details" } }.

export interface ErrorDetail {
  field: string;
  message: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public details?: ErrorDetail[],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** True for any ApiError, including one created by another copy of this module. */
export function isApiError(value: unknown): value is ApiError {
  return value instanceof Error && typeof (value as ApiError).status === "number";
}
