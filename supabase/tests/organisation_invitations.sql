-- =============================================================================
-- Checks for the organisation invitations migration: who can create, see and
-- revoke invitations, what a signed-out person can learn from a link, and what
-- the sign-up trigger does with an invite code.
--
-- Run against a database that has the migrations applied:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/tests/organisation_invitations.sql
--
-- Everything runs inside one transaction that is rolled back, so no data is
-- left behind. A failed check raises an error and stops the script. Success
-- ends with the notice "organisation_invitations: all checks passed".
-- =============================================================================
begin;

set local plpgsql.check_asserts = on;

-- sha256 of a code, as the API computes it before storing.
create function pg_temp.hash(p_code text) returns text
language sql immutable as $$ select encode(sha256(convert_to(p_code, 'UTF8')), 'hex') $$;

-- ---------------------------------------------------------------------------
-- Fixtures: owner A and owner B, each with their own organisation.
-- ---------------------------------------------------------------------------
insert into auth.users (id, email, raw_user_meta_data) values
  ('a0000000-0000-4000-8000-000000000001', 'owner.a@subpay.test',
     '{"full_name": "Alex Owner", "organisation_name": "Org A Formwork"}'),
  ('b0000000-0000-4000-8000-000000000001', 'owner.b@subpay.test',
     '{"full_name": "Blake Owner", "organisation_name": "Org B Scaffolding"}');

do $$
begin
  perform set_config('test.org_a', (select organisation_id::text from public.profiles where id = 'a0000000-0000-4000-8000-000000000001'), true);
  perform set_config('test.org_b', (select organisation_id::text from public.profiles where id = 'b0000000-0000-4000-8000-000000000001'), true);
end $$;

-- ---------------------------------------------------------------------------
-- Owner A creates invitations
-- ---------------------------------------------------------------------------
set local role authenticated;
set local request.jwt.claims = '{"sub": "a0000000-0000-4000-8000-000000000001", "role": "authenticated"}';
do $$
declare
  v_org_a uuid := current_setting('test.org_a')::uuid;
  v_org_b uuid := current_setting('test.org_b')::uuid;
  v_inv   record;
begin
  insert into public.organisation_invitations (email, token_hash)
  values ('morgan@subpay.test', pg_temp.hash('code-for-morgan'));
  insert into public.organisation_invitations (email, token_hash)
  values ('riley@subpay.test', pg_temp.hash('code-for-riley'));
  insert into public.organisation_invitations (email, token_hash)
  values ('casey@subpay.test', pg_temp.hash('code-for-casey'));

  select id, organisation_id, role, invited_by, expires_at, accepted_at into v_inv
  from public.organisation_invitations where email = 'morgan@subpay.test';
  assert v_inv.organisation_id = v_org_a, 'the organisation comes from the caller';
  assert v_inv.invited_by = 'a0000000-0000-4000-8000-000000000001', 'invited_by is the caller';
  assert v_inv.role = 'member', 'invited people join as members';
  assert v_inv.expires_at between now() + interval '6 days' and now() + interval '8 days', 'an invitation lasts a week';
  assert v_inv.accepted_at is null, 'a new invitation is open';
  perform set_config('test.inv_morgan', v_inv.id::text, true);

  -- the token hash cannot be read back
  begin
    perform token_hash from public.organisation_invitations;
    raise exception 'the token hash should not be readable';
  exception when insufficient_privilege then null;
  end;

  -- one open invitation per address
  begin
    insert into public.organisation_invitations (email, token_hash)
    values ('morgan@subpay.test', pg_temp.hash('second-code-for-morgan'));
    raise exception 'a second open invitation for the same address should be refused';
  exception when unique_violation then null;
  end;

  -- the address must be lower case and look like an address
  begin
    insert into public.organisation_invitations (email, token_hash)
    values ('Morgan@SubPay.test', pg_temp.hash('x1'));
    raise exception 'an upper-case address should be refused';
  exception when check_violation then null;
  end;
  begin
    insert into public.organisation_invitations (email, token_hash)
    values ('not-an-address', pg_temp.hash('x2'));
    raise exception 'a malformed address should be refused';
  exception when check_violation then null;
  end;

  -- only the email and the hash can be chosen
  begin
    insert into public.organisation_invitations (email, token_hash, organisation_id)
    values ('x@subpay.test', pg_temp.hash('x3'), v_org_b);
    raise exception 'choosing the organisation should be refused';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into public.organisation_invitations (email, token_hash, role)
    values ('x@subpay.test', pg_temp.hash('x4'), 'owner');
    raise exception 'choosing the role should be refused';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into public.organisation_invitations (email, token_hash, expires_at)
    values ('x@subpay.test', pg_temp.hash('x5'), now() + interval '10 years');
    raise exception 'choosing the expiry should be refused';
  exception when insufficient_privilege then null;
  end;

  -- nothing can be updated by a client
  begin
    update public.organisation_invitations set accepted_at = now() where email = 'morgan@subpay.test';
    raise exception 'updating an invitation should be refused';
  exception when insufficient_privilege then null;
  end;
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- Owner B: sees none of A's invitations and cannot revoke them
-- ---------------------------------------------------------------------------
set local role authenticated;
set local request.jwt.claims = '{"sub": "b0000000-0000-4000-8000-000000000001", "role": "authenticated"}';
do $$
declare
  v_rows integer;
begin
  assert (select count(*) from public.organisation_invitations) = 0, 'another organisation sees no invitations';
  delete from public.organisation_invitations where email = 'morgan@subpay.test';
  get diagnostics v_rows = row_count;
  assert v_rows = 0, 'another organisation cannot revoke an invitation';
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- Signed out: the table is closed, the preview answers only for a real code
-- ---------------------------------------------------------------------------
set local role anon;
set local request.jwt.claims = '{"role": "anon"}';
do $$
declare
  v_preview record;
begin
  begin
    perform count(*) from public.organisation_invitations;
    raise exception 'anon should not be able to read invitations';
  exception when insufficient_privilege then null;
  end;

  select * into v_preview from public.invitation_preview('code-for-morgan');
  assert found, 'a real code has a preview';
  assert v_preview.organisation_name = 'Org A Formwork', 'the preview names the organisation';
  assert v_preview.email = 'morgan@subpay.test', 'the preview gives the invited address';

  assert (select count(*) from public.invitation_preview('wrong-code')) = 0, 'a wrong code has no preview';
  assert (select count(*) from public.invitation_preview(null)) = 0, 'no code has no preview';
  assert (select count(*) from public.invitation_preview('')) = 0, 'an empty code has no preview';
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- Sign-up with an invite code
-- ---------------------------------------------------------------------------
do $$
declare
  v_org_a   uuid := current_setting('test.org_a')::uuid;
  v_orgs    integer := (select count(*) from public.organisations);
  v_profile public.profiles;
  v_inv     public.organisation_invitations;
  v_refused boolean;
begin
  -- wrong code
  v_refused := false;
  begin
    insert into auth.users (id, email, raw_user_meta_data) values
      ('d0000000-0000-4000-8000-000000000001', 'morgan@subpay.test', '{"full_name": "Morgan", "invite_code": "not-the-code"}');
  exception when raise_exception then v_refused := true;
  end;
  assert v_refused, 'a wrong code should stop the sign-up';
  -- right code, different address
  v_refused := false;
  begin
    insert into auth.users (id, email, raw_user_meta_data) values
      ('d0000000-0000-4000-8000-000000000002', 'someone.else@subpay.test', '{"full_name": "Someone", "invite_code": "code-for-morgan"}');
  exception when raise_exception then v_refused := true;
  end;
  assert v_refused, 'a code used with another address should stop the sign-up';
  assert (select count(*) from public.organisations) = v_orgs, 'a refused invite sign-up creates no organisation';
  assert not exists (select 1 from public.profiles where email in ('morgan@subpay.test', 'someone.else@subpay.test')), 'and no profile';

  -- right code, right address (the address is matched without regard to case)
  insert into auth.users (id, email, raw_user_meta_data) values
    ('a0000000-0000-4000-8000-000000000002', 'Morgan@SubPay.test',
     '{"full_name": "Morgan Member", "invite_code": "code-for-morgan", "organisation_name": "Ignored Pty Ltd"}');

  select * into v_profile from public.profiles where id = 'a0000000-0000-4000-8000-000000000002';
  assert found, 'an invited sign-up creates a profile';
  assert v_profile.organisation_id = v_org_a, 'in the inviting organisation';
  assert v_profile.role = 'member', 'as a member';
  assert v_profile.full_name = 'Morgan Member', 'with the name they gave';
  assert (select count(*) from public.organisations) = v_orgs, 'and no new organisation';

  select * into v_inv from public.organisation_invitations where id = current_setting('test.inv_morgan')::uuid;
  assert v_inv.accepted_at is not null and v_inv.accepted_by = v_profile.id, 'the invitation is marked accepted';

  -- the link works once
  v_refused := false;
  begin
    insert into auth.users (id, email, raw_user_meta_data) values
      ('d0000000-0000-4000-8000-000000000003', 'morgan@subpay.test', '{"full_name": "Again", "invite_code": "code-for-morgan"}');
  exception when raise_exception then v_refused := true;
  end;
  assert v_refused, 'a used code should stop the sign-up';
  assert (select count(*) from public.invitation_preview('code-for-morgan')) = 0, 'a used code has no preview';

  -- an expired invitation
  update public.organisation_invitations set expires_at = now() - interval '1 minute' where email = 'riley@subpay.test';
  v_refused := false;
  begin
    insert into auth.users (id, email, raw_user_meta_data) values
      ('d0000000-0000-4000-8000-000000000004', 'riley@subpay.test', '{"full_name": "Riley", "invite_code": "code-for-riley"}');
  exception when raise_exception then v_refused := true;
  end;
  assert v_refused, 'an expired code should stop the sign-up';
  assert (select count(*) from public.invitation_preview('code-for-riley')) = 0, 'an expired code has no preview';

  -- a sign-up with no code is unchanged: a new organisation, as its owner
  insert into auth.users (id, email, raw_user_meta_data) values
    ('c0000000-0000-4000-8000-000000000001', 'new.owner@subpay.test', '{"full_name": "New Owner", "organisation_name": "Org C"}');
  select * into v_profile from public.profiles where id = 'c0000000-0000-4000-8000-000000000001';
  assert v_profile.role = 'owner' and v_profile.organisation_id <> v_org_a, 'a normal sign-up still gets its own organisation';
  -- a blank code counts as no code
  insert into auth.users (id, email, raw_user_meta_data) values
    ('c0000000-0000-4000-8000-000000000002', 'blank.code@subpay.test', '{"full_name": "Blank", "organisation_name": "Org D", "invite_code": "  "}');
  assert (select role from public.profiles where id = 'c0000000-0000-4000-8000-000000000002') = 'owner', 'a blank code is ignored';
end $$;

-- ---------------------------------------------------------------------------
-- The new member: part of the organisation, but cannot manage invitations
-- ---------------------------------------------------------------------------
set local role authenticated;
set local request.jwt.claims = '{"sub": "a0000000-0000-4000-8000-000000000002", "role": "authenticated"}';
do $$
declare
  v_rows integer;
begin
  assert (select count(*) from public.profiles) = 2, 'a member sees the organisation''s members';
  assert (select count(*) from public.organisation_invitations) = 0, 'a member sees no invitations';
  begin
    insert into public.organisation_invitations (email, token_hash)
    values ('friend@subpay.test', pg_temp.hash('member-made-this'));
    raise exception 'a member should not be able to invite';
  exception when insufficient_privilege then null;
  end;
  delete from public.organisation_invitations where email = 'casey@subpay.test';
  get diagnostics v_rows = row_count;
  assert v_rows = 0, 'a member cannot revoke an invitation';
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- Owner A: sees all three, can revoke an open one, cannot remove an accepted one
-- ---------------------------------------------------------------------------
set local role authenticated;
set local request.jwt.claims = '{"sub": "a0000000-0000-4000-8000-000000000001", "role": "authenticated"}';
do $$
declare
  v_rows integer;
begin
  assert (select count(*) from public.organisation_invitations) = 3, 'the owner sees every invitation';

  delete from public.organisation_invitations where email = 'morgan@subpay.test';
  get diagnostics v_rows = row_count;
  assert v_rows = 0, 'an accepted invitation is kept';

  delete from public.organisation_invitations where email = 'casey@subpay.test';
  get diagnostics v_rows = row_count;
  assert v_rows = 1, 'the owner can revoke an open invitation';

  -- after a revoke (or once accepted), the address can be invited again
  insert into public.organisation_invitations (email, token_hash)
  values ('casey@subpay.test', pg_temp.hash('new-code-for-casey'));
end $$;
reset role;

do $$
begin
  assert (select count(*) from public.invitation_preview('code-for-casey')) = 0, 'a revoked code has no preview';
  assert (select count(*) from public.invitation_preview('new-code-for-casey')) = 1, 'the replacement code works';
end $$;

do $$ begin raise notice 'organisation_invitations: all checks passed'; end $$;

rollback;
