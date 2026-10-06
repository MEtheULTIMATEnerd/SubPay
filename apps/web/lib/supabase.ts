// The browser's Supabase client. Used for authentication only: sign up, sign in,
// sign out and keeping the session fresh. Application data goes through the
// FastAPI service (lib/http.ts), not through this client.
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { LIVE, SUPABASE_ANON_KEY, SUPABASE_URL } from "./env";

let client: SupabaseClient | null = null;

export function supabase(): SupabaseClient {
  if (!LIVE) throw new Error("Supabase is not configured (demo mode).");
  // The anon key is public by design. The service-role key must never be used here.
  client ??= createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
  });
  return client;
}
