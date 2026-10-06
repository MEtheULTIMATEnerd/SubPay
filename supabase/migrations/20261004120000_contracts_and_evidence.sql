-- =============================================================================
-- SubPay contract and evidence data (owner: Kinori)
--
-- Creates:
--   contracts        uploaded contract documents and their processing state
--   contract_items   structured claim line items extracted from a contract
--   evidence         photos, documents, dockets, messages and notes
--   can_access_contract()   RLS helper for tables that hang off a contract
--
-- Files themselves live in Supabase Storage; these tables hold the path and
-- metadata. Storage buckets and their policies are in a later migration.
--
-- Depends on: 20261004090000_platform_foundation.sql
-- Conventions: docs/database-schema.md
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. contracts
-- -----------------------------------------------------------------------------
create table public.contracts (
  id                 uuid primary key default gen_random_uuid(),
  project_id         uuid not null references public.projects (id) on delete restrict,
  original_filename  text not null,
  -- '<bucket>/<object path>': contracts/{project_id}/{contract_id}/original.<ext>
  storage_path       text not null,
  mime_type          text not null,
  size_bytes         bigint not null,
  page_count         integer,
  processing_status  text not null default 'uploaded',
  -- User-safe message when processing_status = 'failed'.
  error              text,
  uploaded_by        uuid default auth.uid() references public.profiles (id) on delete set null,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  processed_at       timestamptz,
  constraint contracts_processing_status_check
    check (processing_status in ('uploaded', 'processing', 'ready', 'failed')),
  constraint contracts_filename_length check (char_length(btrim(original_filename)) between 1 and 255),
  constraint contracts_mime_type_check check (mime_type in (
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  )),
  -- 25 MB, the MVP upload limit for contracts.
  constraint contracts_size_check check (size_bytes > 0 and size_bytes <= 26214400),
  constraint contracts_page_count_check check (page_count is null or page_count > 0),
  -- A row can only point at a file inside its own project and contract folder.
  constraint contracts_storage_path_check
    check (storage_path like 'contracts/' || project_id::text || '/' || id::text || '/%')
);

create index contracts_project_id_idx on public.contracts (project_id, created_at desc);
create index contracts_uploaded_by_idx on public.contracts (uploaded_by);

create trigger contracts_set_updated_at
  before update on public.contracts
  for each row execute function public.set_updated_at();

-- True when the contract belongs to a project in the signed-in user's organisation.
-- Use in policies for any table that hangs off a contract:
--   using (public.can_access_contract(contract_id))
create or replace function public.can_access_contract(p_contract_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.contracts c
    where c.id = p_contract_id
      and public.can_access_project(c.project_id)
  )
$$;

revoke execute on function public.can_access_contract(uuid) from public, anon;
grant execute on function public.can_access_contract(uuid) to authenticated, service_role;


-- -----------------------------------------------------------------------------
-- 2. contract_items
--
-- AI output is never silently overwritten:
--   * extracted_values keeps the values exactly as the AI returned them
--   * a trigger sets edited_by_human when a person changes any extracted field
--   * a trigger records who confirmed or rejected the item
-- Not every contract has every field, so most columns are nullable.
-- -----------------------------------------------------------------------------
create table public.contract_items (
  id                     uuid primary key default gen_random_uuid(),
  contract_id            uuid not null references public.contracts (id) on delete cascade,
  item_code              text not null,
  description            text not null,
  quantity               numeric,
  unit                   text,
  rate                   numeric,
  amount                 numeric,
  conditions             text,
  notice_requirement     text,
  due_date               date,
  -- AI confidence from 0 to 1. Null for an item a person added by hand.
  extraction_confidence  numeric,
  review_status          text not null default 'draft',
  edited_by_human        boolean not null default false,
  reviewed_by            uuid references public.profiles (id) on delete set null,
  -- Where in the contract the item came from, e.g. 'Schedule 2, p. 14'.
  source_reference       text,
  -- Snapshot of the AI-extracted values. Written once at insert, never updated.
  extracted_values       jsonb,
  -- Order of the item within the contract's schedule.
  sort_order             integer not null default 0,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  constraint contract_items_review_status_check
    check (review_status in ('draft', 'confirmed', 'rejected')),
  constraint contract_items_item_code_length check (char_length(btrim(item_code)) between 1 and 50),
  constraint contract_items_description_length check (char_length(btrim(description)) between 1 and 2000),
  constraint contract_items_confidence_check
    check (extraction_confidence is null or (extraction_confidence >= 0 and extraction_confidence <= 1)),
  constraint contract_items_quantity_check check (quantity is null or quantity >= 0),
  constraint contract_items_rate_check check (rate is null or rate >= 0),
  constraint contract_items_amount_check check (amount is null or amount >= 0),
  constraint contract_items_extracted_values_check
    check (extracted_values is null or jsonb_typeof(extracted_values) = 'object')
);

create index contract_items_contract_id_idx on public.contract_items (contract_id, sort_order);
create index contract_items_reviewed_by_idx on public.contract_items (reviewed_by);

-- Keeps the review bookkeeping honest regardless of what the client sends.
create or replace function public.contract_items_track_review()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if (new.item_code, new.description, new.quantity, new.unit, new.rate, new.amount,
      new.conditions, new.notice_requirement, new.due_date)
     is distinct from
     (old.item_code, old.description, old.quantity, old.unit, old.rate, old.amount,
      old.conditions, old.notice_requirement, old.due_date)
  then
    new.edited_by_human := true;
  end if;

  if new.review_status is distinct from old.review_status then
    if new.review_status = 'draft' then
      new.reviewed_by := null;
    else
      new.reviewed_by := auth.uid();
    end if;
  end if;

  new.updated_at := now();
  return new;
end;
$$;

create trigger contract_items_track_review
  before update on public.contract_items
  for each row execute function public.contract_items_track_review();


-- -----------------------------------------------------------------------------
-- 3. evidence
--
-- A record is a file, a written note, or both. Source files and metadata are
-- preserved: evidence is archived, never deleted.
-- -----------------------------------------------------------------------------
create table public.evidence (
  id                 uuid primary key default gen_random_uuid(),
  project_id         uuid not null references public.projects (id) on delete restrict,
  -- Human-friendly reference, unique within a project: EV-001, EV-002, ...
  -- Both columns are assigned by a trigger; clients never send them.
  sequence_number    integer not null,
  code               text not null,
  uploaded_by        uuid default auth.uid() references public.profiles (id) on delete set null,
  -- '<bucket>/<object path>': evidence/{project_id}/{evidence_id}/original.<ext>
  -- Null for a written note with no file.
  storage_path       text,
  original_filename  text,
  mime_type          text,
  size_bytes         bigint,
  evidence_type      text not null default 'other',
  -- When the evidence was created on site, not when it was uploaded.
  captured_at        timestamptz not null default now(),
  title              text not null,
  description        text not null default '',
  -- Free-form, e.g. { "location": null, "source": "mobile_upload", "tags": [] }
  metadata           jsonb not null default '{}'::jsonb,
  processing_status  text not null default 'uploaded',
  archived           boolean not null default false,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint evidence_type_check
    check (evidence_type in ('photo', 'document', 'docket', 'message', 'other')),
  constraint evidence_processing_status_check
    check (processing_status in ('uploaded', 'processing', 'ready', 'failed')),
  constraint evidence_title_length check (char_length(btrim(title)) between 1 and 200),
  constraint evidence_description_length check (char_length(description) <= 5000),
  constraint evidence_metadata_is_object check (jsonb_typeof(metadata) = 'object'),
  -- A record needs a file or a written note.
  constraint evidence_file_or_note_check
    check (storage_path is not null or char_length(btrim(description)) > 0),
  -- File details come together: all present with a file, all absent without one.
  constraint evidence_file_fields_check check (
    (storage_path is null and original_filename is null and mime_type is null and size_bytes is null)
    or
    (storage_path is not null and original_filename is not null and mime_type is not null and size_bytes is not null)
  ),
  -- 50 MB, the MVP upload limit for evidence.
  constraint evidence_size_check check (size_bytes is null or (size_bytes > 0 and size_bytes <= 52428800)),
  -- A row can only point at a file inside its own project and evidence folder.
  constraint evidence_storage_path_check check (
    storage_path is null
    or storage_path like 'evidence/' || project_id::text || '/' || id::text || '/%'
  ),
  constraint evidence_sequence_unique unique (project_id, sequence_number),
  constraint evidence_code_unique unique (project_id, code)
);

create index evidence_project_captured_idx on public.evidence (project_id, captured_at desc);
create index evidence_project_type_idx on public.evidence (project_id, evidence_type);
create index evidence_uploaded_by_idx on public.evidence (uploaded_by);

create trigger evidence_set_updated_at
  before update on public.evidence
  for each row execute function public.set_updated_at();

-- Assigns the next EV-nnn code within the project. The advisory lock makes two
-- uploads to the same project at the same moment take turns.
create or replace function public.evidence_assign_code()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform pg_advisory_xact_lock(hashtextextended('evidence_code:' || new.project_id::text, 0));

  select coalesce(max(e.sequence_number), 0) + 1
  into new.sequence_number
  from public.evidence e
  where e.project_id = new.project_id;

  new.code := 'EV-' || lpad(new.sequence_number::text, 3, '0');
  return new;
end;
$$;

create trigger evidence_assign_code
  before insert on public.evidence
  for each row execute function public.evidence_assign_code();

revoke execute on function public.evidence_assign_code() from public, anon, authenticated;
revoke execute on function public.contract_items_track_review() from public, anon, authenticated;


-- -----------------------------------------------------------------------------
-- 4. Privileges
--
-- Signed-out callers get nothing. Signed-in callers get only the operations
-- and columns listed here; Row Level Security then limits them to rows in
-- their own organisation's projects. Server-set columns (uploaded_by, codes,
-- review bookkeeping, timestamps) are deliberately left out.
-- -----------------------------------------------------------------------------
revoke all on public.contracts      from anon, authenticated;
revoke all on public.contract_items from anon, authenticated;
revoke all on public.evidence       from anon, authenticated;

grant select on public.contracts to authenticated;
grant insert (id, project_id, original_filename, storage_path, mime_type, size_bytes)
  on public.contracts to authenticated;
grant update (processing_status, error, page_count, processed_at)
  on public.contracts to authenticated;

grant select on public.contract_items to authenticated;
grant insert (contract_id, item_code, description, quantity, unit, rate, amount, conditions,
              notice_requirement, due_date, extraction_confidence, source_reference,
              extracted_values, sort_order)
  on public.contract_items to authenticated;
grant update (item_code, description, quantity, unit, rate, amount, conditions,
              notice_requirement, due_date, review_status)
  on public.contract_items to authenticated;
grant delete on public.contract_items to authenticated;

grant select on public.evidence to authenticated;
grant insert (id, project_id, storage_path, original_filename, mime_type, size_bytes,
              evidence_type, captured_at, title, description, metadata)
  on public.evidence to authenticated;
grant update (evidence_type, captured_at, title, description, metadata, archived, processing_status)
  on public.evidence to authenticated;

grant all on public.contracts, public.contract_items, public.evidence to service_role;


-- -----------------------------------------------------------------------------
-- 5. Row Level Security
-- -----------------------------------------------------------------------------
alter table public.contracts      enable row level security;
alter table public.contract_items enable row level security;
alter table public.evidence       enable row level security;

-- contracts: members of the project's organisation read, upload and update.
-- No delete policy: an uploaded contract and its history are kept.
create policy contracts_select_own_organisation
  on public.contracts for select to authenticated
  using ((select public.can_access_project(project_id)));

create policy contracts_insert_own_organisation
  on public.contracts for insert to authenticated
  with check (
    (select public.can_access_project(project_id))
    and uploaded_by = (select auth.uid())
  );

create policy contracts_update_own_organisation
  on public.contracts for update to authenticated
  using ((select public.can_access_project(project_id)))
  with check ((select public.can_access_project(project_id)));

-- contract_items: follow their contract.
create policy contract_items_select_own_organisation
  on public.contract_items for select to authenticated
  using ((select public.can_access_contract(contract_id)));

create policy contract_items_insert_own_organisation
  on public.contract_items for insert to authenticated
  with check ((select public.can_access_contract(contract_id)));

create policy contract_items_update_own_organisation
  on public.contract_items for update to authenticated
  using ((select public.can_access_contract(contract_id)))
  with check ((select public.can_access_contract(contract_id)));

-- Only untouched AI drafts can be removed (so a failed extraction can be
-- re-run cleanly). Anything a person has edited, confirmed or rejected stays.
create policy contract_items_delete_untouched_drafts
  on public.contract_items for delete to authenticated
  using (
    (select public.can_access_contract(contract_id))
    and review_status = 'draft'
    and not edited_by_human
  );

-- evidence: members of the project's organisation read, add and edit.
-- No delete policy: evidence is archived, never deleted.
create policy evidence_select_own_organisation
  on public.evidence for select to authenticated
  using ((select public.can_access_project(project_id)));

create policy evidence_insert_own_organisation
  on public.evidence for insert to authenticated
  with check (
    (select public.can_access_project(project_id))
    and uploaded_by = (select auth.uid())
  );

create policy evidence_update_own_organisation
  on public.evidence for update to authenticated
  using ((select public.can_access_project(project_id)))
  with check ((select public.can_access_project(project_id)));
