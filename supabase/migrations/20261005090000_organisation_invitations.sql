-- =============================================================================
-- SubPay organisation invitations
--
-- Lets an owner bring a second person into their organisation:
--   organisation_invitations   one row per invite link an owner has created
--   invitation_preview(code)   what a signed-out person may see about a link
--   handle_new_user()          replaced: a sign-up that carries a valid invite
--                              code joins that organisation as a member instead
--                              of getting a new organisation
--
-- The invite code is a long random secret made by the API. Only its SHA-256
-- hash is stored, so reading this table never reveals a working link.
--
-- Conventions: docs/database-schema.md
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. Table
-- -----------------------------------------------------------------------------
create table public.organisation_invitations (
  id               uuid primary key default gen_random_uuid(),
  organisation_id  uuid not null default public.current_organisation_id()
                     references public.organisations (id) on delete cascade,
  -- The address the invited person must sign up with. Always lower case.
  email            text not null,
  -- Invited people always join as a member. Kept as a column so the role an
  -- invitation grants is recorded with it.
  role             text not null default 'member',
  token_hash       text not null,
  invited_by       uuid default auth.uid() references public.profiles (id) on delete set null,
  expires_at       timestamptz not null default (now() + interval '7 days'),
  accepted_at      timestamptz,
  accepted_by      uuid references public.profiles (id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint organisation_invitations_email_check
    check (email = lower(btrim(email)) and char_length(email) between 3 and 320
           and email ~ '^[^@[:space:]]+@[^@[:space:]]+$'),
  constraint organisation_invitations_role_check check (role = 'member'),
  constraint organisation_invitations_token_hash_check check (token_hash ~ '^[0-9a-f]{64}$')
);

create unique index organisation_invitations_token_hash_key
  on public.organisation_invitations (token_hash);
-- One open invitation per address in an organisation.
create unique index organisation_invitations_open_email_key
  on public.organisation_invitations (organisation_id, email)
  where accepted_at is null;
create index organisation_invitations_organisation_id_idx
  on public.organisation_invitations (organisation_id, created_at desc);

create trigger organisation_invitations_set_updated_at
  before update on public.organisation_invitations
  for each row execute function public.set_updated_at();


-- -----------------------------------------------------------------------------
-- 2. What a signed-out person may learn from an invite link
--
-- Returns one row for a code that is still open, and nothing otherwise. A
-- wrong, used, revoked or expired code all look the same.
-- -----------------------------------------------------------------------------
create or replace function public.invitation_preview(p_code text)
returns table (organisation_name text, email text, expires_at timestamptz)
language sql
stable
security definer
set search_path = ''
as $$
  select o.name, i.email, i.expires_at
  from public.organisation_invitations i
  join public.organisations o on o.id = i.organisation_id
  where i.token_hash = encode(sha256(convert_to(coalesce(p_code, ''), 'UTF8')), 'hex')
    and i.accepted_at is null
    and i.expires_at > now()
$$;

revoke execute on function public.invitation_preview(text) from public;
grant execute on function public.invitation_preview(text) to anon, authenticated, service_role;


-- -----------------------------------------------------------------------------
-- 3. Sign-up
--
-- Without an invite code: unchanged. The new user gets a new organisation and
-- is its owner.
--
-- With an invite code (sign-up metadata `invite_code`): the code must match an
-- open invitation for the same email address. The new user then joins that
-- organisation as a member and the invitation is marked accepted, so the link
-- works once. Anything else stops the sign-up: a person who was invited to an
-- organisation is never quietly given a new one instead.
--
-- Metadata is supplied by the client. The code is the only thing in it that
-- can place a user in an existing organisation, and it cannot be guessed.
-- -----------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_full_name   text;
  v_org_name    text;
  v_org_id      uuid;
  v_code        text;
  v_invitation  public.organisation_invitations;
begin
  v_full_name := nullif(btrim(coalesce(new.raw_user_meta_data ->> 'full_name', '')), '');
  v_org_name  := nullif(btrim(coalesce(new.raw_user_meta_data ->> 'organisation_name', '')), '');
  v_code      := nullif(btrim(coalesce(new.raw_user_meta_data ->> 'invite_code', '')), '');

  if v_full_name is null then
    v_full_name := coalesce(nullif(split_part(coalesce(new.email, ''), '@', 1), ''), 'New user');
  end if;

  if v_code is not null then
    select * into v_invitation
    from public.organisation_invitations i
    where i.token_hash = encode(sha256(convert_to(v_code, 'UTF8')), 'hex')
      and i.accepted_at is null
      and i.expires_at > now()
      and i.email = lower(btrim(coalesce(new.email, '')))
    for update;

    if not found then
      raise exception 'This invitation is not valid for this email address, or has expired'
        using errcode = 'P0001';
    end if;

    insert into public.profiles (id, organisation_id, email, full_name, role)
    values (new.id, v_invitation.organisation_id, coalesce(new.email, ''),
            left(v_full_name, 200), v_invitation.role);

    update public.organisation_invitations
    set accepted_at = now(), accepted_by = new.id
    where id = v_invitation.id;

    return new;
  end if;

  if v_org_name is null then
    v_org_name := v_full_name || '''s organisation';
  end if;

  insert into public.organisations (name)
  values (left(v_org_name, 200))
  returning id into v_org_id;

  insert into public.profiles (id, organisation_id, email, full_name, role)
  values (new.id, v_org_id, coalesce(new.email, ''), left(v_full_name, 200), 'owner');

  return new;
end;
$$;

revoke execute on function public.handle_new_user() from public, anon, authenticated;


-- -----------------------------------------------------------------------------
-- 4. Privileges
--
-- Signed-in callers may read everything except the token hash, create an
-- invitation by giving only the email and the hash, and delete. Row Level
-- Security below limits all of it to owners and to their own organisation.
-- Nothing can be updated: accepting is done by the sign-up trigger only.
-- -----------------------------------------------------------------------------
revoke all on public.organisation_invitations from anon, authenticated;

grant select (id, organisation_id, email, role, invited_by, expires_at,
              accepted_at, accepted_by, created_at, updated_at)
                                  on public.organisation_invitations to authenticated;
grant insert (email, token_hash)  on public.organisation_invitations to authenticated;
grant delete                      on public.organisation_invitations to authenticated;

grant all on public.organisation_invitations to service_role;


-- -----------------------------------------------------------------------------
-- 5. Row Level Security: owners only, own organisation only
-- -----------------------------------------------------------------------------
alter table public.organisation_invitations enable row level security;

create policy organisation_invitations_select_owner
  on public.organisation_invitations for select to authenticated
  using (
    organisation_id = (select public.current_organisation_id())
    and (select public.current_profile_role()) = 'owner'
  );

create policy organisation_invitations_insert_owner
  on public.organisation_invitations for insert to authenticated
  with check (
    organisation_id = (select public.current_organisation_id())
    and (select public.current_profile_role()) = 'owner'
    and invited_by = (select auth.uid())
    and accepted_at is null
  );

-- An invitation that has been accepted is a record of how a member joined and
-- is kept. Only an open one can be revoked.
create policy organisation_invitations_delete_owner
  on public.organisation_invitations for delete to authenticated
  using (
    organisation_id = (select public.current_organisation_id())
    and (select public.current_profile_role()) = 'owner'
    and accepted_at is null
  );
