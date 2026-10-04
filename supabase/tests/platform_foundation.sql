-- =============================================================================
-- Checks for the platform foundation migration: sign-up trigger, column
-- privileges and organisation isolation (Row Level Security).
--
-- Run against a database that has the migrations applied:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/tests/platform_foundation.sql
--
-- Everything runs inside one transaction that is rolled back, so no data is
-- left behind. A failed check raises an error and stops the script. Success
-- ends with the notice "platform_foundation: all checks passed".
-- =============================================================================
begin;

set local plpgsql.check_asserts = on;

-- ---------------------------------------------------------------------------
-- Fixtures: three sign-ups. The trigger gives each a new organisation.
--   A = owner of organisation A        M = later moved into A as a member
--   B = owner of organisation B        N = signs up with no metadata
-- ---------------------------------------------------------------------------
insert into auth.users (id, email, raw_user_meta_data) values
  ('a0000000-0000-4000-8000-000000000001', 'owner.a@subpay.test',
     '{"full_name": "Alex Owner", "organisation_name": "Org A Formwork"}'),
  ('b0000000-0000-4000-8000-000000000001', 'owner.b@subpay.test',
     '{"full_name": "Blake Owner", "organisation_name": "Org B Scaffolding"}'),
  ('a0000000-0000-4000-8000-000000000002', 'member.a@subpay.test',
     '{"full_name": "Morgan Member", "organisation_name": "Temporary"}'),
  ('c0000000-0000-4000-8000-000000000001', 'nometa@subpay.test', null);

-- Sign-up trigger
do $$
declare
  v_profile public.profiles;
  v_org     public.organisations;
begin
  select * into v_profile from public.profiles where id = 'a0000000-0000-4000-8000-000000000001';
  assert found, 'sign-up should create a profile';
  assert v_profile.role = 'owner', 'the person who signs up is the owner';
  assert v_profile.full_name = 'Alex Owner', 'full_name comes from sign-up metadata';
  assert v_profile.email = 'owner.a@subpay.test', 'email is copied from auth';

  select * into v_org from public.organisations where id = v_profile.organisation_id;
  assert v_org.name = 'Org A Formwork', 'organisation name comes from sign-up metadata';

  select * into v_profile from public.profiles where id = 'c0000000-0000-4000-8000-000000000001';
  assert found and v_profile.full_name = 'nometa', 'missing metadata falls back to the email name';
  select * into v_org from public.organisations where id = v_profile.organisation_id;
  assert v_org.name = 'nometa''s organisation', 'missing organisation name gets a fallback';

  assert (select count(distinct organisation_id) from public.profiles
          where id in ('a0000000-0000-4000-8000-000000000001',
                       'b0000000-0000-4000-8000-000000000001',
                       'a0000000-0000-4000-8000-000000000002',
                       'c0000000-0000-4000-8000-000000000001')) = 4,
         'every sign-up gets its own organisation';
end $$;

-- Move M into organisation A as a member (how members are added for the MVP).
do $$
declare
  v_org_a   uuid := (select organisation_id from public.profiles where id = 'a0000000-0000-4000-8000-000000000001');
  v_org_b   uuid := (select organisation_id from public.profiles where id = 'b0000000-0000-4000-8000-000000000001');
  v_old_org uuid := (select organisation_id from public.profiles where id = 'a0000000-0000-4000-8000-000000000002');
begin
  update public.profiles set organisation_id = v_org_a, role = 'member'
  where id = 'a0000000-0000-4000-8000-000000000002';
  delete from public.organisations where id = v_old_org;

  perform set_config('test.org_a', v_org_a::text, true);
  perform set_config('test.org_b', v_org_b::text, true);
end $$;

-- Email changes in Supabase Auth are copied to the profile.
update auth.users set email = 'blake@subpay.test' where id = 'b0000000-0000-4000-8000-000000000001';
do $$
begin
  assert (select email from public.profiles where id = 'b0000000-0000-4000-8000-000000000001') = 'blake@subpay.test',
         'profile email follows the auth email';
end $$;

-- ---------------------------------------------------------------------------
-- Signed out (anon): no access at all
-- ---------------------------------------------------------------------------
set local role anon;
set local request.jwt.claims = '{"role": "anon"}';
do $$
declare
  v_table text;
begin
  foreach v_table in array array['organisations', 'profiles', 'projects'] loop
    begin
      execute format('select count(*) from public.%I', v_table);
      raise exception 'anon should not be able to read %', v_table;
    exception when insufficient_privilege then null;
    end;
  end loop;
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- Owner A
-- ---------------------------------------------------------------------------
set local role authenticated;
set local request.jwt.claims = '{"sub": "a0000000-0000-4000-8000-000000000001", "role": "authenticated"}';
do $$
declare
  v_org_a   uuid := current_setting('test.org_a')::uuid;
  v_org_b   uuid := current_setting('test.org_b')::uuid;
  v_project public.projects;
  v_rows    integer;
begin
  assert public.current_organisation_id() = v_org_a, 'current_organisation_id() returns the caller''s organisation';
  assert public.current_profile_role() = 'owner', 'current_profile_role() returns the caller''s role';

  assert (select count(*) from public.organisations) = 1, 'A sees exactly one organisation';
  assert (select id from public.organisations) = v_org_a, 'and it is their own';
  assert (select count(*) from public.profiles) = 2, 'A sees the two profiles in organisation A';
  assert not exists (select 1 from public.profiles where organisation_id <> v_org_a),
         'A sees no profile from another organisation';

  -- create a project without sending organisation_id or created_by
  insert into public.projects (name, client_name, site_address, start_date, end_date)
  values ('Hume St Tower', 'Bellrock Construction', '88 Hume St', '2026-03-02', '2026-12-18')
  returning * into v_project;
  assert v_project.organisation_id = v_org_a, 'organisation_id is derived from the caller';
  assert v_project.created_by = 'a0000000-0000-4000-8000-000000000001', 'created_by is derived from the caller';
  assert v_project.status = 'active', 'new projects are active';
  perform set_config('test.project_a', v_project.id::text, true);
  assert public.can_access_project(v_project.id), 'can_access_project() is true for an own project';

  -- cannot choose the organisation, the creator or the status on insert
  begin
    insert into public.projects (organisation_id, name, client_name) values (v_org_b, 'Sneaky', 'X');
    raise exception 'inserting with an explicit organisation_id should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into public.projects (created_by, name, client_name)
    values ('b0000000-0000-4000-8000-000000000001', 'Sneaky', 'X');
    raise exception 'inserting with an explicit created_by should be denied';
  exception when insufficient_privilege then null;
  end;

  -- edit and archive
  update public.projects set name = 'Hume Street Tower', status = 'archived' where id = v_project.id;
  get diagnostics v_rows = row_count;
  assert v_rows = 1, 'A can edit and archive an own project';
  update public.projects set status = 'active' where id = v_project.id;

  -- cannot move a project to another organisation
  begin
    update public.projects set organisation_id = v_org_b where id = v_project.id;
    raise exception 'changing organisation_id should be denied';
  exception when insufficient_privilege then null;
  end;

  -- validation lives in the database too
  begin
    update public.projects set status = 'deleted' where id = v_project.id;
    raise exception 'an unknown status should be rejected';
  exception when check_violation then null;
  end;
  begin
    update public.projects set start_date = '2026-06-01', end_date = '2026-05-01' where id = v_project.id;
    raise exception 'end_date before start_date should be rejected';
  exception when check_violation then null;
  end;
  begin
    insert into public.projects (name, client_name) values ('   ', 'X');
    raise exception 'a blank project name should be rejected';
  exception when check_violation then null;
  end;

  -- projects are archived, never deleted
  begin
    delete from public.projects where id = v_project.id;
    raise exception 'deleting a project should be denied';
  exception when insufficient_privilege then null;
  end;

  -- profile: own full_name only
  update public.profiles set full_name = 'Alex O. Owner' where id = 'a0000000-0000-4000-8000-000000000001';
  get diagnostics v_rows = row_count;
  assert v_rows = 1, 'A can update their own full_name';
  update public.profiles set full_name = 'Hacked' where id = 'a0000000-0000-4000-8000-000000000002';
  get diagnostics v_rows = row_count;
  assert v_rows = 0, 'A cannot update a colleague''s profile';
  begin
    update public.profiles set role = 'member' where id = 'a0000000-0000-4000-8000-000000000001';
    raise exception 'changing role should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    update public.profiles set organisation_id = v_org_b where id = 'a0000000-0000-4000-8000-000000000001';
    raise exception 'changing organisation_id on a profile should be denied';
  exception when insufficient_privilege then null;
  end;

  -- owner can rename the organisation
  update public.organisations set name = 'Org A Formwork Pty Ltd' where id = v_org_a;
  get diagnostics v_rows = row_count;
  assert v_rows = 1, 'an owner can rename their organisation';
  update public.organisations set name = 'Taken over' where id = v_org_b;
  get diagnostics v_rows = row_count;
  assert v_rows = 0, 'an owner cannot rename another organisation';
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- Owner B: organisation A's data is invisible and unwritable
-- ---------------------------------------------------------------------------
set local role authenticated;
set local request.jwt.claims = '{"sub": "b0000000-0000-4000-8000-000000000001", "role": "authenticated"}';
do $$
declare
  v_org_a     uuid := current_setting('test.org_a')::uuid;
  v_project_a uuid := current_setting('test.project_a')::uuid;
  v_rows      integer;
begin
  assert (select count(*) from public.projects) = 0, 'B sees none of A''s projects';
  assert not exists (select 1 from public.projects where id = v_project_a), 'B cannot read A''s project by id';
  assert not public.can_access_project(v_project_a), 'can_access_project() is false across organisations';
  assert not exists (select 1 from public.organisations where id = v_org_a), 'B cannot read organisation A';
  assert not exists (select 1 from public.profiles where organisation_id = v_org_a), 'B cannot read A''s profiles';

  update public.projects set name = 'Hijacked', status = 'archived' where id = v_project_a;
  get diagnostics v_rows = row_count;
  assert v_rows = 0, 'B cannot edit or archive A''s project';

  insert into public.projects (name, client_name) values ('Dock Rd Warehouse', 'Northside Builders');
  assert (select count(*) from public.projects) = 1, 'B sees only their own project';
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- Member of organisation A: shares projects, is not an owner
-- ---------------------------------------------------------------------------
set local role authenticated;
set local request.jwt.claims = '{"sub": "a0000000-0000-4000-8000-000000000002", "role": "authenticated"}';
do $$
declare
  v_org_a     uuid := current_setting('test.org_a')::uuid;
  v_project_a uuid := current_setting('test.project_a')::uuid;
  v_rows      integer;
begin
  assert public.current_profile_role() = 'member', 'M is a member';
  assert (select count(*) from public.projects) = 1, 'a member sees the organisation''s project';
  assert (select name from public.projects where id = v_project_a) = 'Hume Street Tower',
         'B''s attempted edit did not change A''s project';

  update public.projects set site_address = '90 Hume St' where id = v_project_a;
  get diagnostics v_rows = row_count;
  assert v_rows = 1, 'a member can edit the organisation''s project';

  insert into public.projects (name, client_name) values ('Member Project', 'Client');
  assert (select count(*) from public.projects) = 2, 'a member can create a project';

  update public.organisations set name = 'Renamed by member' where id = v_org_a;
  get diagnostics v_rows = row_count;
  assert v_rows = 0, 'a member cannot rename the organisation';
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- updated_at is maintained by the trigger
-- ---------------------------------------------------------------------------
do $$
declare
  v_project_a uuid := current_setting('test.project_a')::uuid;
begin
  update public.projects set updated_at = '2000-01-01T00:00:00Z' where id = v_project_a;
  assert (select updated_at from public.projects where id = v_project_a) > '2001-01-01T00:00:00Z',
         'updated_at is set by the trigger, not by the caller';
  assert (select name from public.organisations where id = current_setting('test.org_a')::uuid) = 'Org A Formwork Pty Ltd',
         'only the owner''s rename was applied';
end $$;

do $$ begin raise notice 'platform_foundation: all checks passed'; end $$;

rollback;
