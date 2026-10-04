// Organisation members and invitations (F01). Components call these functions
// and never talk to the API or the mock directly.
//
// live mode: the FastAPI service is the source of truth. Members are copied
//            into the local store so every screen can show who did what.
// demo mode: simulated in lib/api.ts.
import * as mock from "./api";
import { LIVE } from "./env";
import { ApiError, isApiError } from "./errors";
import { apiFetch } from "./http";
import { commit, getDb } from "./store";
import type { Invitation, InvitationPreview, Profile, Role } from "./types";

interface Member {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  created_at: string;
}

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const CODE = /^[A-Za-z0-9_-]{20,128}$/;

/** Replace the local copy of this organisation's members with what the API returns. */
export async function refreshMembers(): Promise<void> {
  if (!LIVE) return;
  const { items } = await apiFetch<{ items: Member[] }>("/organisation/members");
  commit((d) => {
    const me = d.session && d.profiles.find((p) => p.id === d.session!.profile_id);
    if (!me) return;
    const members: Profile[] = items.map((m) => ({ ...m, organisation_id: me.organisation_id, updated_at: m.created_at }));
    // Keep the signed-in user's own row as it is: it came from /me and has every field.
    d.profiles = [...d.profiles.filter((p) => p.organisation_id !== me.organisation_id || p.id === me.id), ...members.filter((m) => m.id !== me.id)];
  });
}

/** Owners only. */
export async function listInvitations(): Promise<Invitation[]> {
  if (!LIVE) return mock.listInvitations();
  return (await apiFetch<{ items: Invitation[] }>("/organisation/invitations")).items;
}

/** The address to pass on to the invited person. */
export function inviteLink(code: string): string {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return `${origin}/signup?invite=${encodeURIComponent(code)}`;
}

/**
 * Owners only. Returns the invite link, which is shown once: only a hash of its
 * code is kept, so it cannot be looked up again later.
 */
export async function createInvitation(email: string): Promise<{ id: string; link: string }> {
  const address = email.trim().toLowerCase();
  if (!EMAIL.test(address) || address.length > 320) throw new ApiError(422, "Enter a valid email address", "validation_error");
  if (!LIVE) {
    const { id, code } = mock.createInvitation(address);
    return { id, link: inviteLink(code) };
  }
  const created = await apiFetch<Invitation & { invite_code: string }>("/organisation/invitations", { method: "POST", body: { email: address } });
  return { id: created.id, link: inviteLink(created.invite_code) };
}

/** Owners only. Only an invitation that has not been accepted can be revoked. */
export async function revokeInvitation(id: string): Promise<void> {
  if (!LIVE) return mock.revokeInvitation(id);
  await apiFetch<void>(`/organisation/invitations/${id}`, { method: "DELETE" });
}

/** What an invite link is for, or null when it is wrong, used, revoked or expired. Needs no sign-in. */
export async function previewInvitation(code: string): Promise<InvitationPreview | null> {
  if (!CODE.test(code)) return null;
  if (!LIVE) return mock.previewInvitation(code);
  try {
    return await apiFetch<InvitationPreview>(`/invitations/${code}`, { auth: false });
  } catch (err) {
    if (isApiError(err) && (err.status === 404 || err.status === 422)) return null;
    throw err;
  }
}

/** True when the signed-in user is an owner. */
export const isOwner = () => {
  const d = getDb();
  return d.profiles.find((p) => p.id === d.session?.profile_id)?.role === "owner";
};
