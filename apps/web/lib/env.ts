// Public configuration. NEXT_PUBLIC_* values are inlined at build time, so each
// one must be read as a literal `process.env.NEXT_PUBLIC_...` expression.
// Never put a secret here: everything in this file is shipped to the browser.

const trimSlash = (value: string | undefined) => (value ?? "").trim().replace(/\/+$/, "");

export const SUPABASE_URL = trimSlash(process.env.NEXT_PUBLIC_SUPABASE_URL);
export const SUPABASE_ANON_KEY = (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "").trim();
export const API_URL = trimSlash(process.env.NEXT_PUBLIC_API_URL) || "http://localhost:8000";

/**
 * live: real Supabase Auth and the FastAPI service.
 * demo: no Supabase values set. The app runs entirely in the browser with
 *       simulated sign-in and seeded demo data, as the original prototype did.
 */
export const LIVE = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);
