// Live mode: Supabase Auth for credentials, GET /api/v1/me for the profile.
// Supabase and the API are replaced by fakes; nothing here touches the network.
import { beforeEach, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  signInWithPassword: vi.fn(),
  signUp: vi.fn(),
  signOut: vi.fn(),
  getSession: vi.fn(),
  onAuthStateChange: vi.fn(),
  apiFetch: vi.fn(),
}));

vi.mock("./env", () => ({ LIVE: true, API_URL: "http://api.test", SUPABASE_URL: "http://supabase.test", SUPABASE_ANON_KEY: "anon" }));
vi.mock("./supabase", () => ({
  supabase: () => ({
    auth: {
      signInWithPassword: mocks.signInWithPassword,
      signUp: mocks.signUp,
      signOut: mocks.signOut,
      getSession: mocks.getSession,
      onAuthStateChange: mocks.onAuthStateChange,
    },
  }),
}));
vi.mock("./http", () => ({ apiFetch: mocks.apiFetch, setUnauthorizedHandler: vi.fn() }));

import { ApiError } from "./errors";

const USER_ID = "a0000000-0000-4000-8000-000000000001";
const ORG_ID = "0b6f3c1e-6d2f-4c0a-9d53-1f0f5a6f7a01";
const at = "2026-10-04T05:00:00Z";
const ME = {
  profile: { id: USER_ID, organisation_id: ORG_ID, email: "alex@subpay.test", full_name: "Alex Owner", role: "owner" as const, created_at: at, updated_at: at },
  organisation: { id: ORG_ID, name: "Org A Formwork", created_at: at, updated_at: at },
};
const session = { access_token: "token", user: { id: USER_ID } };
const PROJECT = {
  id: "5a0d8a0e-2c9b-4a55-8a8e-0a2b9a6c1d22", organisation_id: ORG_ID, name: "Real Tower", client_name: "Builder", site_address: "",
  status: "active" as const, start_date: null, end_date: null, created_by: USER_ID, created_at: at, updated_at: at,
};

const TEAM_MATE = { id: "a0000000-0000-4000-8000-000000000002", email: "morgan@subpay.test", full_name: "Morgan Member", role: "member" as const, created_at: at };
const members = (me = ME) => [{ id: me.profile.id, email: me.profile.email, full_name: me.profile.full_name, role: me.profile.role, created_at: at }, TEAM_MATE];

/** The API answers normally: /me returns the profile, /projects the organisation's projects, /organisation/members its people. */
function apiAnswers(me = ME, projects = [PROJECT]) {
  mocks.apiFetch.mockImplementation(async (path: string) =>
    path === "/projects" ? { items: projects } : path === "/organisation/members" ? { items: members(me) } : me);
}
const callsTo = (path: string) => mocks.apiFetch.mock.calls.filter(([p]) => p === path).length;

// auth.ts keeps module-level state, so every test gets a fresh copy of it and of the store.
async function load() {
  vi.resetModules();
  const auth = await import("./auth");
  const store = await import("./store");
  const api = await import("./api");
  store.resetDb(null);
  return { auth, store, api, me: () => api.read.me(store.getDb()) };
}

beforeEach(() => {
  Object.values(mocks).forEach((m) => m.mockReset());
  mocks.signOut.mockResolvedValue({ error: null });
  mocks.signInWithPassword.mockResolvedValue({ data: { user: session.user, session }, error: null });
  apiAnswers();
});

test("sign-in loads the profile from the API and signs the user into the app", async () => {
  const { auth, store, me } = await load();
  await auth.signIn("  alex@subpay.test ", "correct horse");

  expect(mocks.signInWithPassword).toHaveBeenCalledWith({ email: "alex@subpay.test", password: "correct horse" });
  expect(mocks.apiFetch).toHaveBeenCalledWith("/me");
  expect(me()).toMatchObject({ id: USER_ID, full_name: "Alex Owner", organisation_id: ORG_ID });
  expect(store.getDb().organisations.find((o) => o.id === ORG_ID)?.name).toBe("Org A Formwork");
  expect(auth.getAuthState()).toEqual({ ready: true, error: null });
});

test("sign-in also loads the organisation's projects, so pages can render straight away", async () => {
  const { auth, store, api } = await load();
  await auth.signIn("alex@subpay.test", "pw");

  expect(api.read.projects(store.getDb()).map((p) => p.name)).toEqual(["Real Tower"]);
  // seeded demo projects belong to another organisation and stay invisible
  expect(api.read.project(store.getDb(), "prj-hume")).toBeNull();
});

test("wrong credentials give a friendly error and no session", async () => {
  const { auth, me } = await load();
  mocks.signInWithPassword.mockResolvedValue({ data: { user: null, session: null }, error: { code: "invalid_credentials", status: 400, message: "Invalid login credentials" } });

  await expect(auth.signIn("alex@subpay.test", "nope")).rejects.toMatchObject({ status: 401, message: "Email or password is incorrect" });
  expect(mocks.apiFetch).not.toHaveBeenCalled();
  expect(me()).toBeNull();
});

test("Supabase errors without a code are recognised by their message", async () => {
  const { auth } = await load();
  mocks.signInWithPassword.mockResolvedValue({ data: { user: null, session: null }, error: { status: 400, message: "Invalid login credentials" } });
  await expect(auth.signIn("alex@subpay.test", "nope")).rejects.toThrow("Email or password is incorrect");

  mocks.signUp.mockResolvedValue({ data: { user: null, session: null }, error: { status: 422, message: "User already registered" } });
  await expect(auth.signUp({ full_name: "A", email: "a@subpay.test", password: "long-enough", organisation: "O" })).rejects.toThrow("An account with this email already exists");
});

test("an unconfirmed email address is explained", async () => {
  const { auth } = await load();
  mocks.signInWithPassword.mockResolvedValue({ data: { user: null, session: null }, error: { code: "email_not_confirmed", status: 400, message: "Email not confirmed" } });
  await expect(auth.signIn("alex@subpay.test", "pw")).rejects.toThrow(/Confirm your email/);
});

test("an unreachable sign-in service is reported as such", async () => {
  const { auth } = await load();
  mocks.signInWithPassword.mockResolvedValue({ data: { user: null, session: null }, error: { status: 0, message: "Failed to fetch" } });
  await expect(auth.signIn("alex@subpay.test", "pw")).rejects.toMatchObject({ status: 503 });
});

test("a Supabase account with no SubPay profile is signed back out", async () => {
  const { auth, me } = await load();
  mocks.apiFetch.mockRejectedValue(new ApiError(403, "This account has no SubPay profile. Sign up again or contact support.", "forbidden"));

  await expect(auth.signIn("alex@subpay.test", "pw")).rejects.toThrow(/no SubPay profile/);
  expect(mocks.signOut).toHaveBeenCalledOnce();
  expect(me()).toBeNull();
  expect(auth.getAuthState().error).toMatch(/no SubPay profile/);
});

test("if the API is unreachable the user is not let into the app", async () => {
  const { auth, me } = await load();
  mocks.apiFetch.mockRejectedValue(new ApiError(503, "Can't reach the SubPay server. Check your connection and try again."));

  await expect(auth.signIn("alex@subpay.test", "pw")).rejects.toThrow(/Can't reach the SubPay server/);
  expect(me()).toBeNull();
  expect(mocks.signOut).not.toHaveBeenCalled(); // the Supabase session is fine; a retry can succeed

  apiAnswers();
  await auth.signIn("alex@subpay.test", "pw");
  expect(me()?.id).toBe(USER_ID);
  expect(auth.getAuthState().error).toBeNull();
});

test("sign-up sends the name and business as metadata for the database trigger", async () => {
  const { auth, me } = await load();
  mocks.signUp.mockResolvedValue({ data: { user: { id: USER_ID, identities: [{}] }, session }, error: null });

  const result = await auth.signUp({ full_name: " Alex Owner ", email: " alex@subpay.test", password: "long-enough", organisation: " Org A Formwork " });

  expect(result).toEqual({ needsEmailConfirmation: false });
  const args = mocks.signUp.mock.calls[0][0];
  expect(args.email).toBe("alex@subpay.test");
  expect(args.options.data).toEqual({ full_name: "Alex Owner", organisation_name: "Org A Formwork" });
  expect(me()?.id).toBe(USER_ID);
});

test("sign-up through an invite link sends the code instead of a business name", async () => {
  const { auth, me } = await load();
  mocks.signUp.mockResolvedValue({ data: { user: { id: USER_ID, identities: [{}] }, session }, error: null });

  await auth.signUp({ full_name: "Morgan Member", email: "morgan@subpay.test", password: "long-enough", organisation: "", invite_code: "the-invite-code" });

  expect(mocks.signUp.mock.calls[0][0].options.data).toEqual({ full_name: "Morgan Member", invite_code: "the-invite-code" });
  expect(me()?.id).toBe(USER_ID);
});

test("an invite code the database refuses is explained", async () => {
  const { auth, me } = await load();
  mocks.signUp.mockResolvedValue({ data: { user: null, session: null }, error: { status: 500, code: "unexpected_failure", message: "Database error saving new user" } });

  const input = { full_name: "Morgan", email: "morgan@subpay.test", password: "long-enough", organisation: "" };
  await expect(auth.signUp({ ...input, invite_code: "used-code" })).rejects.toMatchObject({ status: 410, message: expect.stringContaining("no longer valid") });
  expect(me()).toBeNull();
  // Without an invite code the same failure is not blamed on an invitation.
  await expect(auth.signUp({ ...input, organisation: "Org" })).rejects.not.toThrow("no longer valid");
});

test("sign-in loads the team so their names can be shown, and sign-out removes them again", async () => {
  const { auth, store } = await load();
  await auth.signIn("alex@subpay.test", "pw");
  const mates = () => store.getDb().profiles.filter((p) => p.organisation_id === ORG_ID).map((p) => p.full_name);
  expect(mates()).toEqual(["Alex Owner", "Morgan Member"]);

  await auth.signOut();
  expect(mates()).not.toContain("Morgan Member");
  expect(JSON.stringify(store.getDb())).not.toContain("morgan@subpay.test");
});

test("a failure to load the team does not stop the sign-in", async () => {
  const { auth, me } = await load();
  mocks.apiFetch.mockImplementation(async (path: string) => {
    if (path === "/organisation/members") throw new ApiError(503, "Service unavailable");
    return path === "/projects" ? { items: [PROJECT] } : ME;
  });
  await auth.signIn("alex@subpay.test", "pw");
  expect(me()?.id).toBe(USER_ID);
});

test("sign-up that needs email confirmation does not sign the user in", async () => {
  const { auth, me } = await load();
  mocks.signUp.mockResolvedValue({ data: { user: { id: USER_ID, identities: [{}] }, session: null }, error: null });

  await expect(auth.signUp({ full_name: "A", email: "a@subpay.test", password: "long-enough", organisation: "O" })).resolves.toEqual({ needsEmailConfirmation: true });
  expect(mocks.apiFetch).not.toHaveBeenCalled();
  expect(me()).toBeNull();
});

test("sign-up with an email that is already registered is rejected", async () => {
  const { auth } = await load();
  // What Supabase returns when email confirmation is on: a user with no identities.
  mocks.signUp.mockResolvedValue({ data: { user: { id: "x", identities: [] }, session: null }, error: null });
  await expect(auth.signUp({ full_name: "A", email: "a@subpay.test", password: "long-enough", organisation: "O" })).rejects.toMatchObject({ status: 409 });

  mocks.signUp.mockResolvedValue({ data: { user: null, session: null }, error: { code: "user_already_exists", status: 422, message: "User already registered" } });
  await expect(auth.signUp({ full_name: "A", email: "a@subpay.test", password: "long-enough", organisation: "O" })).rejects.toMatchObject({ status: 409 });
});

test("sign-up rejects a short password before calling Supabase", async () => {
  const { auth } = await load();
  await expect(auth.signUp({ full_name: "A", email: "a@subpay.test", password: "short", organisation: "O" })).rejects.toMatchObject({ status: 422 });
  expect(mocks.signUp).not.toHaveBeenCalled();
});

test("sign-out leaves the app and ends the Supabase session", async () => {
  const { auth, me } = await load();
  await auth.signIn("alex@subpay.test", "pw");
  expect(me()).not.toBeNull();

  await auth.signOut();
  expect(me()).toBeNull();
  expect(mocks.signOut).toHaveBeenCalledOnce();
});

test("sign-out removes the organisation's projects from the browser's copy", async () => {
  const { auth, store } = await load();
  await auth.signIn("alex@subpay.test", "pw");
  expect(store.getDb().projects.some((p) => p.id === PROJECT.id)).toBe(true);

  await auth.signOut();
  expect(store.getDb().projects.some((p) => p.organisation_id === ORG_ID)).toBe(false);
});

test("updating the name saves through the API and updates the app", async () => {
  const { auth, me } = await load();
  await auth.signIn("alex@subpay.test", "pw");
  mocks.apiFetch.mockResolvedValue({ ...ME, profile: { ...ME.profile, full_name: "Alex O. Owner" } });

  await auth.updateProfileName("Alex O. Owner");
  expect(mocks.apiFetch).toHaveBeenLastCalledWith("/me", { method: "PATCH", body: { full_name: "Alex O. Owner" } });
  expect(me()?.full_name).toBe("Alex O. Owner");
});

test("resetting the demo data keeps the user signed in", async () => {
  const { auth, store, me } = await load();
  await auth.signIn("alex@subpay.test", "pw");
  auth.resetDemoData();
  expect(me()?.id).toBe(USER_ID);
  expect(store.getDb().projects.some((p) => p.name === "Hume St Tower")).toBe(true);
  expect(store.getDb().projects.some((p) => p.id === PROJECT.id)).toBe(true); // real projects are kept
});

test("a saved session is restored on page load", async () => {
  vi.useFakeTimers();
  try {
    const { auth, me } = await load();
    expect(auth.getAuthState().ready).toBe(false);
    auth.initAuth();
    auth.initAuth(); // a second call must not subscribe twice
    expect(mocks.onAuthStateChange).toHaveBeenCalledOnce();

    const notify = mocks.onAuthStateChange.mock.calls[0][0];
    notify("INITIAL_SESSION", session);
    notify("SIGNED_IN", session); // Supabase often sends both
    await vi.runAllTimersAsync();

    expect(callsTo("/me")).toBe(1);
    expect(callsTo("/projects")).toBe(1);
    expect(me()?.id).toBe(USER_ID);
    expect(auth.getAuthState()).toEqual({ ready: true, error: null });
  } finally {
    vi.useRealTimers();
  }
});

test("with no saved session the app is ready and signed out", async () => {
  vi.useFakeTimers();
  try {
    const { auth, store, me } = await load();
    store.commit((d) => { d.session = { profile_id: "usr-ollie" }; }); // stale value left in the browser
    auth.initAuth();
    mocks.onAuthStateChange.mock.calls[0][0]("INITIAL_SESSION", null);
    await vi.runAllTimersAsync();

    expect(me()).toBeNull();
    expect(auth.getAuthState().ready).toBe(true);
    expect(mocks.apiFetch).not.toHaveBeenCalled();
  } finally {
    vi.useRealTimers();
  }
});
