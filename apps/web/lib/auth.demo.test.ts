// Demo mode: no Supabase values configured. Sign-in is simulated in the browser.
import { beforeEach, expect, test, vi } from "vitest";

const supabase = vi.hoisted(() => vi.fn(() => { throw new Error("Supabase must not be used in demo mode"); }));
vi.mock("./env", () => ({ LIVE: false, API_URL: "", SUPABASE_URL: "", SUPABASE_ANON_KEY: "" }));
vi.mock("./supabase", () => ({ supabase }));

import * as auth from "./auth";
import { read } from "./api";
import { getDb, resetDb } from "./store";

beforeEach(() => resetDb(null));

test("demo mode is ready immediately and never touches Supabase", async () => {
  expect(auth.getAuthState()).toEqual({ ready: true, error: null });
  auth.initAuth();

  await auth.signIn("ollie@kearneyformwork.test", "anything");
  expect(read.me(getDb())?.full_name).toBe("Ollie Reid");

  await auth.updateProfileName("Ollie R.");
  expect(read.me(getDb())?.full_name).toBe("Ollie R.");

  await auth.signOut();
  expect(read.me(getDb())).toBeNull();
  expect(supabase).not.toHaveBeenCalled();
});

test("demo sign-up creates a local organisation with the user as owner", async () => {
  await expect(auth.signUp({ full_name: "New Person", email: "new@subpay.test", password: "long-enough", organisation: "New Co" })).resolves.toEqual({ needsEmailConfirmation: false });
  const me = read.me(getDb())!;
  expect(me.role).toBe("owner");
  expect(read.org(getDb()).name).toBe("New Co");
});

test("demo sign-in still rejects an unknown email", async () => {
  await expect(auth.signIn("nobody@subpay.test", "pw")).rejects.toThrow("Email or password is incorrect");
});
