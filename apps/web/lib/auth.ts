// Authentication for the whole app. Components call these functions and never
// talk to Supabase or the mock directly.
//
// live mode: Supabase Auth holds the credentials and the session. After sign-in
//            the profile and organisation are fetched from GET /api/v1/me and
//            mirrored into the local store, so the rest of the app (including
//            the features that still run on mock data) knows who is signed in.
// demo mode: the original prototype behaviour, simulated in lib/api.ts.
import { useSyncExternalStore } from "react";
import type { AuthError, Session } from "@supabase/supabase-js";
import * as mock from "./api";
import { LIVE } from "./env";
import { ApiError, isApiError } from "./errors";
import { apiFetch, setUnauthorizedHandler } from "./http";
import { resetProjectData } from "./project-data";
import { clearCachedProjects, refreshProjects } from "./projects";
import { commit, getDb } from "./store";
import { supabase } from "./supabase";
import type { Organisation, Profile } from "./types";

export interface Me {
  profile: Profile;
  organisation: Organisation;
}

export interface AuthState {
  /** false until the saved session (if any) has been checked. */
  ready: boolean;
  /** A problem the user should see on the sign-in screen. */
  error: string | null;
}

export interface SignUpInput {
  full_name: string;
  email: string;
  password: string;
  organisation: string;
}

// ---------- observable state ----------
const SERVER_STATE: AuthState = { ready: false, error: null };
let state: AuthState = { ready: !LIVE, error: null };
const listeners = new Set<() => void>();

function setState(patch: Partial<AuthState>) {
  state = { ...state, ...patch };
  listeners.forEach((listener) => listener());
}
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export const getAuthState = () => state;
export const useAuth = () => useSyncExternalStore(subscribe, getAuthState, () => SERVER_STATE);

// ---------- mirroring the signed-in user into the local store ----------
let lastMe: Me | null = null;
let syncedUserId: string | null = null;
let syncing: { userId: string; promise: Promise<void> } | null = null;

function upsert<T extends { id: string }>(rows: T[], row: T) {
  const index = rows.findIndex((r) => r.id === row.id);
  if (index === -1) rows.push(row);
  else rows[index] = row;
}

function mirror(me: Me) {
  lastMe = me;
  commit((d) => {
    upsert(d.organisations, me.organisation);
    upsert(d.profiles, me.profile);
    d.session = { profile_id: me.profile.id };
  });
}

function clearLocalSession() {
  lastMe = null;
  syncedUserId = null;
  resetProjectData();
  if (getDb().session)
    commit((d) => {
      clearCachedProjects(d);
      d.session = null;
    });
}

async function loadProfile(userId: string) {
  try {
    mirror(await apiFetch<Me>("/me"));
    await refreshProjects(); // pages can render straight away once the user is let in
    syncedUserId = userId;
    setState({ ready: true, error: null });
  } catch (err) {
    const error = isApiError(err) ? err : new ApiError(500, "Something went wrong. Please try again.");
    clearLocalSession();
    // The session cannot be used with SubPay (rejected, or no profile): drop it.
    if (error.status === 401 || error.status === 403) await supabase().auth.signOut();
    setState({ ready: true, error: error.message });
  }
}

/** Make sure the store holds the profile for this user. Concurrent calls share one request. */
async function ensureProfile(userId: string) {
  if (syncedUserId === userId) return;
  if (syncing?.userId !== userId) {
    const promise = loadProfile(userId).finally(() => { syncing = null; });
    syncing = { userId, promise };
  }
  await syncing!.promise;
}

async function onSessionChange(session: Session | null) {
  if (!session) {
    clearLocalSession();
    setState({ ready: true });
    return;
  }
  await ensureProfile(session.user.id);
}

let started = false;

/** Start listening for session changes. Safe to call more than once. */
export function initAuth() {
  if (!LIVE || started) return;
  started = true;
  setUnauthorizedHandler(() => {
    clearLocalSession();
    setState({ error: "Your session has expired. Sign in again." });
    void supabase().auth.signOut();
  });
  supabase().auth.onAuthStateChange((_event, session) => {
    // Supabase must not be called from inside this callback, so hand off first.
    setTimeout(() => void onSessionChange(session), 0);
  });
}

// ---------- actions ----------
function fromSupabase(error: AuthError): ApiError {
  // Prefer Supabase's error code; fall back to its message when no code is sent.
  const code =
    error.code ??
    (/invalid login credentials/i.test(error.message) ? "invalid_credentials"
      : /email not confirmed/i.test(error.message) ? "email_not_confirmed"
      : /already registered/i.test(error.message) ? "user_already_exists"
      : undefined);
  switch (code) {
    case "invalid_credentials":
      return new ApiError(401, "Email or password is incorrect", code);
    case "email_not_confirmed":
      return new ApiError(401, "Confirm your email address first. Check your inbox for the link.", code);
    case "user_already_exists":
    case "email_exists":
      return new ApiError(409, "An account with this email already exists", code);
    case "signup_disabled":
      return new ApiError(403, "New sign-ups are currently closed", code);
    case "over_request_rate_limit":
    case "over_email_send_rate_limit":
      return new ApiError(429, "Too many attempts. Wait a minute and try again.", code);
  }
  if (!error.status) {
    return new ApiError(503, "Can't reach the sign-in service. Check your connection and try again.", "service_unavailable");
  }
  return new ApiError(error.status, error.message, error.code);
}

/** Resolves once the user is fully signed in. Throws an ApiError with a message to show otherwise. */
export async function signIn(email: string, password: string): Promise<void> {
  if (!LIVE) return mock.signIn(email, password);
  setState({ error: null });
  const { data, error } = await supabase().auth.signInWithPassword({ email: email.trim(), password });
  if (error) throw fromSupabase(error);
  await ensureProfile(data.user.id);
  if (state.error) throw new ApiError(503, state.error);
}

/** `needsEmailConfirmation` is true when Supabase has emailed a confirmation link instead of signing the user in. */
export async function signUp(input: SignUpInput): Promise<{ needsEmailConfirmation: boolean }> {
  if (!LIVE) {
    mock.signUp(input);
    return { needsEmailConfirmation: false };
  }
  setState({ error: null });
  if (input.password.length < 8) throw new ApiError(422, "Password must be at least 8 characters");
  const { data, error } = await supabase().auth.signUp({
    email: input.email.trim(),
    password: input.password,
    options: {
      // Read by the database sign-up trigger to create the profile and organisation.
      data: { full_name: input.full_name.trim(), organisation_name: input.organisation.trim() },
      emailRedirectTo: typeof window === "undefined" ? undefined : `${window.location.origin}/dashboard`,
    },
  });
  if (error) throw fromSupabase(error);
  // With email confirmation on, Supabase hides "already registered" behind an empty identity list.
  if (data.user?.identities && data.user.identities.length === 0) {
    throw new ApiError(409, "An account with this email already exists", "user_already_exists");
  }
  if (!data.session) return { needsEmailConfirmation: true };
  await ensureProfile(data.session.user.id);
  if (state.error) throw new ApiError(503, state.error);
  return { needsEmailConfirmation: false };
}

export async function signOut(): Promise<void> {
  if (!LIVE) return mock.signOut();
  setState({ error: null });
  clearLocalSession(); // leave the app straight away, even if the network is slow
  await supabase().auth.signOut();
}

export async function updateProfileName(fullName: string): Promise<void> {
  if (!LIVE) return mock.updateProfile(fullName);
  mirror(await apiFetch<Me>("/me", { method: "PATCH", body: { full_name: fullName } }));
}

/** Restore the seeded demo data without signing the current user out or losing their real projects. */
export function resetDemoData() {
  const me = lastMe;
  const mine = LIVE && me ? getDb().projects.filter((p) => p.organisation_id === me.organisation.id) : [];
  mock.resetDemo();
  if (LIVE && me) {
    mirror(me);
    commit((d) => { d.projects.push(...mine); });
  }
}
