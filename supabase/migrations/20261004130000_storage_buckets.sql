-- =============================================================================
-- SubPay file storage (owner: Kinori)
--
-- Creates two PRIVATE Supabase Storage buckets and the policies that decide
-- who can read and upload files in them:
--   contracts   {project_id}/{contract_id}/original.<ext>
--   evidence    {project_id}/{evidence_id}/original.<ext>
--
-- The first folder of every object is the project id. A signed-in user can
-- read or upload an object only when that project belongs to their
-- organisation. There are no update or delete policies: once uploaded, a
-- source file cannot be replaced or removed by a user.
--
-- Files are never public. The API hands out short-lived signed URLs.
--
-- Depends on: 20261004090000_platform_foundation.sql
-- =============================================================================

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  (
    'contracts', 'contracts', false,
    26214400,  -- 25 MB
    array[
      'application/pdf',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ]
  ),
  (
    'evidence', 'evidence', false,
    52428800,  -- 50 MB
    array[
      'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif',
      'application/pdf',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'text/plain', 'text/csv'
    ]
  )
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

-- The project id an object belongs to: the first folder of its name.
-- Returns null when the first folder is not a uuid, which then fails every policy.
create or replace function public.storage_object_project_id(p_object_name text)
returns uuid
language sql
immutable
set search_path = ''
as $$
  select case
    when split_part(p_object_name, '/', 1)
         ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    then split_part(p_object_name, '/', 1)::uuid
  end
$$;

revoke execute on function public.storage_object_project_id(text) from public, anon;
grant execute on function public.storage_object_project_id(text) to authenticated, service_role;

-- Read (also needed to create a signed URL).
create policy subpay_project_files_select
  on storage.objects for select to authenticated
  using (
    bucket_id in ('contracts', 'evidence')
    and public.can_access_project(public.storage_object_project_id(name))
  );

-- Upload. The name must be exactly {project_id}/{record_id}/{file}.
create policy subpay_project_files_insert
  on storage.objects for insert to authenticated
  with check (
    bucket_id in ('contracts', 'evidence')
    and array_length(string_to_array(name, '/'), 1) = 3
    and public.can_access_project(public.storage_object_project_id(name))
  );
