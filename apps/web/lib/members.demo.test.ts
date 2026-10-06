// Demo mode: members and invitations are simulated in the browser.
import { beforeEach, expect, test, vi } from "vitest";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("./env", () => ({ LIVE: false, API_URL: "", SUPABASE_URL: "", SUPABASE_ANON_KEY: "" }));
vi.mock("./http", () => ({ apiFetch, setUnauthorizedHandler: vi.fn() }));
vi.mock("./supabase", () => ({ supabase: () => { throw new Error("Supabase must not be used in demo mode"); } }));

import { read } from "./api";
import { signIn, signOut, signUp } from "./auth";
import { createInvitation, listInvitations, previewInvitation, refreshMembers, revokeInvitation } from "./members";
import { commit, getDb, resetDb } from "./store";

beforeEach(() => resetDb({ profile_id: "usr-ollie" }));

const codeOf = (link: string) => new URL(link, "http://demo.test").searchParams.get("invite")!;
const newcomer = { full_name: "Riley New", email: "riley@subpay.test", password: "long-enough", organisation: "" };

test("an owner invites someone, who signs up through the link and joins as a member", async () => {
  const { id, link } = await createInvitation(" Riley@SubPay.test ");
  const code = codeOf(link);
  await refreshMembers();

  expect(await listInvitations()).toMatchObject([{ id, email: "riley@subpay.test", role: "member", status: "pending" }]);
  expect(await previewInvitation(code)).toMatchObject({ organisation_name: "Kearney Formwork Pty Ltd", email: "riley@subpay.test" });

  await signOut();
  await signUp({ ...newcomer, invite_code: code });

  const me = read.me(getDb())!;
  expect(me).toMatchObject({ full_name: "Riley New", role: "member", email: "riley@subpay.test" });
  expect(read.org(getDb()).name).toBe("Kearney Formwork Pty Ltd");
  expect(read.projects(getDb()).some((p) => p.name === "Hume St Tower")).toBe(true); // sees the organisation's projects

  // the link works once
  expect(await previewInvitation(code)).toBeNull();
  // a member cannot manage invitations
  await expect(listInvitations()).rejects.toThrow("Only an owner");
  await expect(createInvitation("friend@subpay.test")).rejects.toThrow("Only an owner");
  expect(apiFetch).not.toHaveBeenCalled();
});

test("the code only works for the invited address, and not after it is revoked or expired", async () => {
  const first = await createInvitation("riley@subpay.test");
  const code = codeOf(first.link);
  const organisations = getDb().organisations.length;
  await signOut();

  await expect(signUp({ ...newcomer, email: "someone.else@subpay.test", invite_code: code })).rejects.toThrow("no longer valid");
  await expect(signUp({ ...newcomer, invite_code: "not-a-real-code-at-all-0000" })).rejects.toThrow("no longer valid");
  expect(read.me(getDb())).toBeNull();
  expect(getDb().organisations).toHaveLength(organisations); // nobody was quietly given a new organisation

  await signIn("ollie@kearneyformwork.test", "pw");
  await revokeInvitation(first.id);
  expect(await previewInvitation(code)).toBeNull();
  expect(await listInvitations()).toEqual([]);

  const second = await createInvitation("riley@subpay.test");
  commit((d) => { d.invitations!.find((i) => i.id === second.id)!.expires_at = "2020-01-01T00:00:00Z"; });
  expect(await previewInvitation(codeOf(second.link))).toBeNull();
  expect(await listInvitations()).toMatchObject([{ status: "expired" }]);
});

test("existing members and open invitations cannot be invited again", async () => {
  await expect(createInvitation("jas@kearneyformwork.test")).rejects.toThrow("already a member");
  await createInvitation("riley@subpay.test");
  await expect(createInvitation("RILEY@subpay.test")).rejects.toThrow("already been invited");
  await expect(createInvitation("not-an-address")).rejects.toThrow("Enter a valid email address");
});
