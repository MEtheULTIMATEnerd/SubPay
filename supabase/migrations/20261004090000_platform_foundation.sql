-- =============================================================================
-- SubPay platform foundation
--
-- Creates the shared foundational entities and the security helpers every
-- other workstream builds on:
--   organisations, profiles, projects
--   set_updated_at(), current_organisation_id(), current_profile_role(),
--   can_access_project()
--   sign-up trigger that creates an organisation + owner profile
--   Row Level Security so users only see their own organisation's records
--
-- Conventions: docs/database-schema.md
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. Shared trigger function: keep updated_at current
--    Attach to every table that has an updated_at column.
-- -----------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;


-- -----------------------------------------------------------------------------
-- 2. Tables
-- -----------------------------------------------------------------------------

-- The subcontractor business. This is the tenant boundary.
create table public.organisations (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint organisations_name_length check (char_length(btrim(name)) between 1 and 200)
);

-- Application profile for a Supabase Auth user. profiles.id IS the auth user id.
create table public.profiles (
  id               uuid primary key references auth.users (id) on delete cascade,
  organisation_id  uuid not null references public.organisations (id) on delete restrict,
  email            text not null default '',
  full_name        text not null,
  role             text not null default 'member',
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint profiles_role_check check (role in ('owner', 'member')),
  constraint profiles_full_name_length check (char_length(btrim(full_name)) between 1 and 200)
);

create index profiles_organisation_id_idx on public.profiles (organisation_id);


-- -----------------------------------------------------------------------------
-- 3. Security helper functions
--
-- SECURITY DEFINER so they can read profiles/projects without tripping the
-- policies that call them. They only ever answer questions about the caller.
-- Reuse these in every other table's policies.
-- -----------------------------------------------------------------------------

-- Organisation of the signed-in user, or null when not signed in.
create or replace function public.current_organisation_id()
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
  select p.organisation_id
  from public.profiles p
  where p.id = (select auth.uid())
$$;

-- Role ('owner' | 'member') of the signed-in user, or null when not signed in.
create or replace function public.current_profile_role()
returns text
language sql
stable
security definer
set search_path = ''
as $$
  select p.role
  from public.profiles p
  where p.id = (select auth.uid())
$$;


-- Construction project workspace. Belongs to one organisation.
-- organisation_id and created_by default to the caller, so clients never send them.
create table public.projects (
  id               uuid primary key default gen_random_uuid(),
  organisation_id  uuid not null default public.current_organisation_id()
                     references public.organisations (id) on delete restrict,
  name             text not null,
  client_name      text not null,
  site_address     text not null default '',
  status           text not null default 'active',
  start_date       date,
  end_date         date,
  created_by       uuid default auth.uid() references public.profiles (id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint projects_status_check check (status in ('active', 'archived')),
  constraint projects_name_length check (char_length(btrim(name)) between 1 and 200),
  constraint projects_client_name_length check (char_length(btrim(client_name)) between 1 and 200),
  constraint projects_dates_check check (start_date is null or end_date is null or end_date >= start_date)
);

create index projects_organisation_id_status_idx on public.projects (organisation_id, status);
create index projects_created_by_idx on public.projects (created_by);

-- True when the project belongs to the signed-in user's organisation.
-- Use in policies for any table that hangs off a project:
--   using (public.can_access_project(project_id))
create or replace function public.can_access_project(p_project_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.projects pr
    where pr.id = p_project_id
      and pr.organisation_id = public.current_organisation_id()
  )
$$;

revoke execute on function public.current_organisation_id() from public, anon;
revoke execute on function public.current_profile_role() from public, anon;
revoke execute on function public.can_access_project(uuid) from public, anon;
grant execute on function public.current_organisation_id() to authenticated, service_role;
grant execute on function public.current_profile_role() to authenticated, service_role;
grant execute on function public.can_access_project(uuid) to authenticated, service_role;


-- -----------------------------------------------------------------------------
-- 4. updated_at triggers
-- -----------------------------------------------------------------------------
create trigger organisations_set_updated_at
  before update on public.organisations
  for each row execute function public.set_updated_at();

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function public.set_updated_at();

create trigger projects_set_updated_at
  before update on public.projects
  for each row execute function public.set_updated_at();


-- -----------------------------------------------------------------------------
-- 5. Sign-up: create an organisation and an owner profile for every new user
--
-- The web app passes two values as sign-up metadata: full_name and
-- organisation_name. Metadata is supplied by the client, so nothing here lets
-- a new user join an EXISTING organisation. They always get a new one.
-- -----------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_full_name  text;
  v_org_name   text;
  v_org_id     uuid;
begin
  v_full_name := nullif(btrim(coalesce(new.raw_user_meta_data ->> 'full_name', '')), '');
  v_org_name  := nullif(btrim(coalesce(new.raw_user_meta_data ->> 'organisation_name', '')), '');

  if v_full_name is null then
    v_full_name := coalesce(nullif(split_part(coalesce(new.email, ''), '@', 1), ''), 'New user');
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

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Keep the display copy of the email in step with Supabase Auth.
create or replace function public.handle_user_email_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  update public.profiles
  set email = coalesce(new.email, '')
  where id = new.id;
  return new;
end;
$$;

create trigger on_auth_user_email_changed
  after update of email on auth.users
  for each row
  when (old.email is distinct from new.email)
  execute function public.handle_user_email_change();

revoke execute on function public.handle_new_user() from public, anon, authenticated;
revoke execute on function public.handle_user_email_change() from public, anon, authenticated;


-- -----------------------------------------------------------------------------
-- 6. Privileges
--
-- Nothing is available to signed-out (anon) callers. Signed-in callers get
-- only the operations and columns the MVP needs; Row Level Security below
-- then limits them to their own organisation's rows.
-- -----------------------------------------------------------------------------
revoke all on public.organisations from anon, authenticated;
revoke all on public.profiles      from anon, authenticated;
revoke all on public.projects      from anon, authenticated;

grant select                on public.organisations to authenticated;
grant update (name)         on public.organisations to authenticated;

grant select                on public.profiles to authenticated;
grant update (full_name)    on public.profiles to authenticated;

grant select                on public.projects to authenticated;
grant insert (name, client_name, site_address, start_date, end_date)
                            on public.projects to authenticated;
grant update (name, client_name, site_address, status, start_date, end_date)
                            on public.projects to authenticated;

grant all on public.organisations, public.profiles, public.projects to service_role;


-- -----------------------------------------------------------------------------
-- 7. Row Level Security
-- -----------------------------------------------------------------------------
alter table public.organisations enable row level security;
alter table public.profiles      enable row level security;
alter table public.projects      enable row level security;

-- organisations: members read their own; owners can rename it.
-- Rows are created by the sign-up trigger only, and never deleted by clients.
create policy organisations_select_own
  on public.organisations for select to authenticated
  using (id = (select public.current_organisation_id()));

create policy organisations_update_owner
  on public.organisations for update to authenticated
  using (
    id = (select public.current_organisation_id())
    and (select public.current_profile_role()) = 'owner'
  )
  with check (
    id = (select public.current_organisation_id())
    and (select public.current_profile_role()) = 'owner'
  );

-- profiles: members read profiles in their own organisation (includes their own);
-- a user can update only their own row, and only full_name (column grant above).
create policy profiles_select_same_organisation
  on public.profiles for select to authenticated
  using (organisation_id = (select public.current_organisation_id()));

create policy profiles_update_self
  on public.profiles for update to authenticated
  using (id = (select auth.uid()))
  with check (id = (select auth.uid()));

-- projects: organisation members read, create and edit their organisation's
-- projects. No delete policy: projects are archived, not deleted.
create policy projects_select_own_organisation
  on public.projects for select to authenticated
  using (organisation_id = (select public.current_organisation_id()));

create policy projects_insert_own_organisation
  on public.projects for insert to authenticated
  with check (
    organisation_id = (select public.current_organisation_id())
    and created_by = (select auth.uid())
  );

create policy projects_update_own_organisation
  on public.projects for update to authenticated
  using (organisation_id = (select public.current_organisation_id()))
  with check (organisation_id = (select public.current_organisation_id()));
