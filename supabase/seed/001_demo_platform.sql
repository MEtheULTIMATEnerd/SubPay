-- =============================================================================
-- Demo data for the platform tables. Fictional. Safe to run more than once.
--
-- Demo ACCOUNTS are created through Supabase Auth, not here, so no password
-- ever lives in this repository:
--
--   1. In Supabase: Authentication > Users > Add user (or sign up in the app)
--        ollie@kearneyformwork.test     main demo user
--        sam@othersubbie.test           optional second organisation, used to
--                                       demonstrate organisation isolation
--   2. Run this file (SQL editor, or `supabase db reset` locally).
--
-- An account that does not exist yet is skipped with a notice.
-- Project ids are fixed so later seed files can refer to them.
-- Contracts and evidence need stored files, so the demo project that has them
-- ("Riverside Commercial Fitout") is created through the API instead:
-- services/api/scripts/seed_demo.py.
-- =============================================================================

do $$
declare
  v_profile public.profiles;
begin
  -- ---- Kearney Formwork Pty Ltd -------------------------------------------
  select * into v_profile from public.profiles where email = 'ollie@kearneyformwork.test';

  if not found then
    raise notice 'Demo user ollie@kearneyformwork.test not found. Create the account first, then run this seed again.';
  else
    update public.profiles set full_name = 'Ollie Reid' where id = v_profile.id;
    update public.organisations set name = 'Kearney Formwork Pty Ltd' where id = v_profile.organisation_id;

    insert into public.projects
      (id, organisation_id, name, client_name, site_address, status, start_date, end_date, created_by)
    values
      ('5eed0000-0000-4000-8000-000000000001', v_profile.organisation_id,
       'Hume St Tower', 'Bellrock Construction', '118 Hume St, Melbourne VIC',
       'active', current_date - 120, current_date + 240, v_profile.id),
      ('5eed0000-0000-4000-8000-000000000002', v_profile.organisation_id,
       'Docklands Car Park L2', 'Harbourline Builders', '9 Wharf Rd, Docklands VIC',
       'archived', current_date - 400, current_date - 60, v_profile.id)
    on conflict (id) do nothing;

    raise notice 'Seeded demo projects for Kearney Formwork Pty Ltd.';
  end if;

  -- ---- Other Subbie Pty Ltd (a different organisation) ---------------------
  select * into v_profile from public.profiles where email = 'sam@othersubbie.test';

  if not found then
    raise notice 'Optional demo user sam@othersubbie.test not found. Skipping the second organisation.';
  else
    update public.profiles set full_name = 'Sam Other' where id = v_profile.id;
    update public.organisations set name = 'Other Subbie Pty Ltd' where id = v_profile.organisation_id;

    insert into public.projects
      (id, organisation_id, name, client_name, site_address, status, created_by)
    values
      ('5eed0000-0000-4000-8000-0000000000ff', v_profile.organisation_id,
       'Other Org Secret Job', 'Someone', '', 'active', v_profile.id)
    on conflict (id) do nothing;

    raise notice 'Seeded demo project for Other Subbie Pty Ltd.';
  end if;
end $$;
