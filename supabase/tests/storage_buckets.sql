-- =============================================================================
-- Checks for the storage migration: private buckets, and upload / read rules
-- for contract and evidence files.
--
-- Run against a database that has the migrations applied:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/tests/storage_buckets.sql
--
-- Rows are inserted straight into storage.objects to exercise the policies.
-- No file bytes are involved, and the transaction is rolled back. Success ends
-- with the notice "storage_buckets: all checks passed".
-- =============================================================================
begin;

set local plpgsql.check_asserts = on;

insert into auth.users (id, email, raw_user_meta_data) values
  ('a0000000-0000-4000-8000-0000000000a1', 'owner.a@subpay.test',
     '{"full_name": "Alex Owner", "organisation_name": "Org A Formwork"}'),
  ('b0000000-0000-4000-8000-0000000000b1', 'owner.b@subpay.test',
     '{"full_name": "Blake Owner", "organisation_name": "Org B Scaffolding"}');

insert into public.projects (id, organisation_id, name, client_name, created_by)
select 'aaaaaaaa-0000-4000-8000-000000000001', organisation_id, 'A Tower', 'Builder', id
from public.profiles where id = 'a0000000-0000-4000-8000-0000000000a1';

insert into public.projects (id, organisation_id, name, client_name, created_by)
select 'bbbbbbbb-0000-4000-8000-000000000001', organisation_id, 'B Warehouse', 'Builder', id
from public.profiles where id = 'b0000000-0000-4000-8000-0000000000b1';

-- Buckets exist, are private, and carry the MVP limits.
do $$
declare
  v_bucket storage.buckets;
begin
  select * into v_bucket from storage.buckets where id = 'contracts';
  assert found and not v_bucket.public, 'the contracts bucket exists and is private';
  assert v_bucket.file_size_limit = 26214400, 'contracts are limited to 25 MB';
  assert v_bucket.allowed_mime_types @> array['application/pdf'], 'contracts accept PDF';
  assert not (v_bucket.allowed_mime_types @> array['image/jpeg']), 'contracts do not accept images';

  select * into v_bucket from storage.buckets where id = 'evidence';
  assert found and not v_bucket.public, 'the evidence bucket exists and is private';
  assert v_bucket.file_size_limit = 52428800, 'evidence is limited to 50 MB';
  assert v_bucket.allowed_mime_types @> array['image/jpeg', 'application/pdf'], 'evidence accepts photos and PDFs';
  assert not (v_bucket.allowed_mime_types @> array['text/html']), 'evidence does not accept HTML';
end $$;

-- The path helper never throws on odd names.
do $$
begin
  assert public.storage_object_project_id('aaaaaaaa-0000-4000-8000-000000000001/x/original.pdf')
         = 'aaaaaaaa-0000-4000-8000-000000000001', 'the first folder is the project id';
  assert public.storage_object_project_id('not-a-uuid/x/original.pdf') is null, 'a non-uuid folder gives null';
  assert public.storage_object_project_id('original.pdf') is null, 'a bare filename gives null';
  assert public.storage_object_project_id('') is null, 'an empty name gives null';
end $$;

-- ---------------------------------------------------------------------------
-- Signed out (anon): cannot read or upload
-- ---------------------------------------------------------------------------
set local role anon;
set local request.jwt.claims = '{"role": "anon"}';
do $$
begin
  assert (select count(*) from storage.objects where bucket_id in ('contracts', 'evidence')) = 0,
         'anon sees no project files';
  begin
    insert into storage.objects (bucket_id, name)
    values ('evidence', 'aaaaaaaa-0000-4000-8000-000000000001/eeeeeeee-0000-4000-8000-000000000009/original.jpg');
    raise exception 'anon upload should be denied';
  exception when insufficient_privilege then null;
  end;
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- Owner A
-- ---------------------------------------------------------------------------
set local role authenticated;
set local request.jwt.claims = '{"sub": "a0000000-0000-4000-8000-0000000000a1", "role": "authenticated"}';
do $$
declare
  v_a constant text := 'aaaaaaaa-0000-4000-8000-000000000001';
  v_b constant text := 'bbbbbbbb-0000-4000-8000-000000000001';
  v_rows integer;
begin
  -- upload into own project, both buckets
  insert into storage.objects (bucket_id, name)
  values ('contracts', v_a || '/cccccccc-0000-4000-8000-000000000001/original.pdf');
  insert into storage.objects (bucket_id, name)
  values ('evidence', v_a || '/eeeeeeee-0000-4000-8000-000000000001/original.jpg');
  assert (select count(*) from storage.objects where bucket_id in ('contracts', 'evidence')) = 2,
         'A can read the files in their own project';

  -- another organisation's project
  begin
    insert into storage.objects (bucket_id, name)
    values ('contracts', v_b || '/cccccccc-0000-4000-8000-000000000002/original.pdf');
    raise exception 'uploading into another organisation''s project should be denied';
  exception when insufficient_privilege then null;
  end;

  -- names that are not {project_id}/{record_id}/{file}
  begin
    insert into storage.objects (bucket_id, name) values ('evidence', 'original.jpg');
    raise exception 'a file at the bucket root should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into storage.objects (bucket_id, name) values ('evidence', v_a || '/original.jpg');
    raise exception 'a file directly under the project folder should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into storage.objects (bucket_id, name) values ('evidence', v_a || '/x/y/original.jpg');
    raise exception 'a file nested too deep should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into storage.objects (bucket_id, name) values ('evidence', 'not-a-uuid/x/original.jpg');
    raise exception 'a file under a non-project folder should be denied';
  exception when insufficient_privilege then null;
  end;

  -- source files cannot be replaced, renamed or removed
  update storage.objects set name = v_a || '/eeeeeeee-0000-4000-8000-000000000001/replaced.jpg'
  where bucket_id = 'evidence';
  get diagnostics v_rows = row_count;
  assert v_rows = 0, 'A cannot rename or replace an uploaded file';
  delete from storage.objects where bucket_id = 'evidence';
  get diagnostics v_rows = row_count;
  assert v_rows = 0, 'A cannot delete an evidence file';
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- Owner B: organisation A's files are invisible
-- ---------------------------------------------------------------------------
set local role authenticated;
set local request.jwt.claims = '{"sub": "b0000000-0000-4000-8000-0000000000b1", "role": "authenticated"}';
do $$
begin
  assert (select count(*) from storage.objects where bucket_id in ('contracts', 'evidence')) = 0,
         'B cannot read (or sign URLs for) A''s files';
  begin
    insert into storage.objects (bucket_id, name)
    values ('evidence', 'aaaaaaaa-0000-4000-8000-000000000001/eeeeeeee-0000-4000-8000-000000000002/original.jpg');
    raise exception 'B uploading into A''s project should be denied';
  exception when insufficient_privilege then null;
  end;

  insert into storage.objects (bucket_id, name)
  values ('evidence', 'bbbbbbbb-0000-4000-8000-000000000001/eeeeeeee-0000-4000-8000-000000000003/original.jpg');
  assert (select count(*) from storage.objects where bucket_id in ('contracts', 'evidence')) = 1,
         'B sees only their own file';
end $$;
reset role;

do $$
begin
  assert (select count(*) from storage.objects where bucket_id in ('contracts', 'evidence')
          and name like 'aaaaaaaa-0000-4000-8000-000000000001/%') = 2, 'A''s two files are still there';
  raise notice 'storage_buckets: all checks passed';
end $$;

rollback;
