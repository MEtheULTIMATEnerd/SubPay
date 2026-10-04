// Live mode: members and invitations go through the API. The API is replaced by a fake.
import { beforeEach, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("./env", () => ({ LIVE: true, API_URL: "http://api.test", SUPABASE_URL: "http://supabase.test", SUPABASE_ANON_KEY: "anon" }));
vi.mock("./http", () => ({ apiFetch: mocks.apiFetch, setUnauthorizedHandler: vi.fn() }));
vi.mock("./supabase", () => ({ supabase: () => { throw new Error("not used"); } }));

import { ApiError } from "./errors";
import { createInvitation, inviteLink, listInvitations, previewInvitation, refreshMembers, revokeInvitation } from "./members";
import { commit, getDb, resetDb } from "./store";
import type { Invitation } from "./types";

const USER_ID = "a0000000-0000-4000-8000-000000000001";
const ORG_ID = "0b6f3c1e-6d2f-4c0a-9d53-1f0f5a6f7a01";
const at = "2026-10-04T05:00:00Z";
const CODE = "Zk3vT9w2Qm8Lr5Xy7Bn1Hc4Jd6Fg0PsAaUuEeIiOo_-";
const invitation: Invitation = { id: "inv-1", email: "riley@subpay.test", role: "member", invited_by: USER_ID, expires_at: "2026-10-11T05:00:00Z", accepted_at: null, created_at: at, status: "pending" };
const team = () => getDb().profiles.filter((p) => p.organisation_id === ORG_ID);

beforeEach(() => {
  mocks.apiFetch.mockReset();
  resetDb(null);
  commit((d) => {
    d.organisations.push({ id: ORG_ID, name: "Org A Formwork", created_at: at, updated_at: at });
    d.profiles.push({ id: USER_ID, organisation_id: ORG_ID, email: "alex@subpay.test", full_name: "Alex Owner", role: "owner", created_at: at, updated_at: at });
    d.profiles.push({ id: "gone", organisation_id: ORG_ID, email: "gone@subpay.test", full_name: "No Longer Here", role: "member", created_at: at, updated_at: at });
    d.session = { profile_id: USER_ID };
  });
});

test("refresh replaces the local copy of the organisation's members and leaves other organisations alone", async () => {
  const others = getDb().profiles.filter((p) => p.organisation_id !== ORG_ID).length;
  mocks.apiFetch.mockResolvedValue({ items: [
    { id: USER_ID, email: "alex@subpay.test", full_name: "Alex Owner", role: "owner", created_at: at },
    { id: "m2", email: "morgan@subpay.test", full_name: "Morgan Member", role: "member", created_at: at },
  ] });

  await refreshMembers();

  expect(mocks.apiFetch).toHaveBeenCalledWith("/organisation/members");
  expect(team().map((p) => [p.full_name, p.role, p.organisation_id])).toEqual([["Alex Owner", "owner", ORG_ID], ["Morgan Member", "member", ORG_ID]]);
  expect(getDb().profiles.filter((p) => p.organisation_id !== ORG_ID)).toHaveLength(others);
});

test("creating an invitation sends a tidied address and returns the link to pass on", async () => {
  mocks.apiFetch.mockResolvedValue({ ...invitation, invite_code: CODE });
  vi.stubGlobal("window", { location: { origin: "https://app.subpay.test" } });

  const created = await createInvitation("  Riley@SubPay.test ");

  expect(mocks.apiFetch).toHaveBeenCalledWith("/organisation/invitations", { method: "POST", body: { email: "riley@subpay.test" } });
  expect(created).toEqual({ id: "inv-1", link: `https://app.subpay.test/signup?invite=${CODE}` });
  expect(inviteLink("a b")).toBe("https://app.subpay.test/signup?invite=a%20b");
  expect(JSON.stringify(getDb())).not.toContain(CODE); // the code is never kept in the browser's copy
  vi.unstubAllGlobals();
});

test("an address that is clearly wrong is refused before any request", async () => {
  for (const email of ["", "riley", "riley@subpay", "two@at@signs.test", "has space@subpay.test"]) {
    await expect(createInvitation(email)).rejects.toThrow("Enter a valid email address");
  }
  expect(mocks.apiFetch).not.toHaveBeenCalled();
});

test("the API's refusals are passed on", async () => {
  mocks.apiFetch.mockRejectedValue(new ApiError(409, "This person is already a member of your organisation", "conflict"));
  await expect(createInvitation("morgan@subpay.test")).rejects.toThrow("already a member");
  mocks.apiFetch.mockRejectedValue(new ApiError(403, "Only an owner can manage invitations", "forbidden"));
  await expect(listInvitations()).rejects.toThrow("Only an owner");
});

test("listing and revoking use the organisation's invitation endpoints", async () => {
  mocks.apiFetch.mockResolvedValueOnce({ items: [invitation] });
  await expect(listInvitations()).resolves.toEqual([invitation]);
  expect(mocks.apiFetch).toHaveBeenLastCalledWith("/organisation/invitations");

  mocks.apiFetch.mockResolvedValueOnce(undefined);
  await revokeInvitation("inv-1");
  expect(mocks.apiFetch).toHaveBeenLastCalledWith("/organisation/invitations/inv-1", { method: "DELETE" });
});

test("an invite link is looked up without a session", async () => {
  const preview = { organisation_name: "Org A Formwork", email: "riley@subpay.test", expires_at: "2026-10-11T05:00:00Z" };
  mocks.apiFetch.mockResolvedValue(preview);
  await expect(previewInvitation(CODE)).resolves.toEqual(preview);
  expect(mocks.apiFetch).toHaveBeenCalledWith(`/invitations/${CODE}`, { auth: false });
});

test("a link that is wrong, used or expired is simply not valid", async () => {
  mocks.apiFetch.mockRejectedValue(new ApiError(404, "Invitation not found", "not_found"));
  await expect(previewInvitation(CODE)).resolves.toBeNull();
  // something that cannot be a code never reaches the API
  mocks.apiFetch.mockClear();
  await expect(previewInvitation("../../me")).resolves.toBeNull();
  await expect(previewInvitation("short")).resolves.toBeNull();
  expect(mocks.apiFetch).not.toHaveBeenCalled();
});

test("an outage while checking a link is reported, not mistaken for a bad link", async () => {
  mocks.apiFetch.mockRejectedValue(new ApiError(503, "Can't reach the SubPay server.", "service_unavailable"));
  await expect(previewInvitation(CODE)).rejects.toThrow("Can't reach the SubPay server");
});
