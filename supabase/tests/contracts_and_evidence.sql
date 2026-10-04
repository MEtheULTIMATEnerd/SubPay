-- =============================================================================
-- Checks for the contracts and evidence migration: organisation isolation,
-- column privileges, storage-path rules, review bookkeeping and evidence codes.
--
-- Run against a database that has the migrations applied:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/tests/contracts_and_evidence.sql
--
-- Everything runs inside one transaction that is rolled back, so no data is
-- left behind. A failed check raises an error and stops the script. Success
-- ends with the notice "contracts_and_evidence: all checks passed".
-- =============================================================================
begin;

set local plpgsql.check_asserts = on;

-- Fixtures: A owns organisation A, B owns organisation B. Each has a project.
insert into auth.users (id, email, raw_user_meta_data) values
  ('a0000000-0000-4000-8000-0000000000a1', 'owner.a@subpay.test',
     '{"full_name": "Alex Owner", "organisation_name": "Org A Formwork"}'),
  ('b0000000-0000-4000-8000-0000000000b1', 'owner.b@subpay.test',
     '{"full_name": "Blake Owner", "organisation_name": "Org B Scaffolding"}');

insert into public.projects (id, organisation_id, name, client_name, created_by)
select 'aaaaaaaa-0000-4000-8000-000000000001', organisation_id, 'A Tower', 'Builder', id
from public.profiles where id = 'a0000000-0000-4000-8000-0000000000a1';

insert into public.projects (id, organisation_id, name, client_name, created_by)
select 'aaaaaaaa-0000-4000-8000-000000000002', organisation_id, 'A Car Park', 'Builder', id
from public.profiles where id = 'a0000000-0000-4000-8000-0000000000a1';

insert into public.projects (id, organisation_id, name, client_name, created_by)
select 'bbbbbbbb-0000-4000-8000-000000000001', organisation_id, 'B Warehouse', 'Builder', id
from public.profiles where id = 'b0000000-0000-4000-8000-0000000000b1';

-- ---------------------------------------------------------------------------
-- Signed out (anon): no access at all
-- ---------------------------------------------------------------------------
set local role anon;
set local request.jwt.claims = '{"role": "anon"}';
do $$
declare
  v_table text;
begin
  foreach v_table in array array['contracts', 'contract_items', 'evidence'] loop
    begin
      execute format('select count(*) from public.%I', v_table);
      raise exception 'anon should not be able to read %', v_table;
    exception when insufficient_privilege then null;
    end;
  end loop;
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- Owner A: contracts
-- ---------------------------------------------------------------------------
set local role authenticated;
set local request.jwt.claims = '{"sub": "a0000000-0000-4000-8000-0000000000a1", "role": "authenticated"}';
do $$
declare
  v_project  constant uuid := 'aaaaaaaa-0000-4000-8000-000000000001';
  v_other    constant uuid := 'aaaaaaaa-0000-4000-8000-000000000002';
  v_b        constant uuid := 'bbbbbbbb-0000-4000-8000-000000000001';
  v_id       constant uuid := 'cccccccc-0000-4000-8000-000000000001';
  v_contract public.contracts;
  v_rows     integer;
begin
  insert into public.contracts (id, project_id, original_filename, storage_path, mime_type, size_bytes)
  values (v_id, v_project, 'Subcontract.pdf',
          'contracts/' || v_project || '/' || v_id || '/original.pdf', 'application/pdf', 120000)
  returning * into v_contract;
  assert v_contract.uploaded_by = 'a0000000-0000-4000-8000-0000000000a1', 'uploaded_by is derived from the caller';
  assert v_contract.processing_status = 'uploaded', 'new contracts start as uploaded';
  assert public.can_access_contract(v_id), 'can_access_contract() is true for an own contract';

  -- the file must sit in this contract's own folder
  begin
    insert into public.contracts (id, project_id, original_filename, storage_path, mime_type, size_bytes)
    values (gen_random_uuid(), v_project, 'x.pdf',
            'contracts/' || v_b || '/' || v_id || '/original.pdf', 'application/pdf', 10);
    raise exception 'a storage path in another project should be rejected';
  exception when check_violation then null;
  end;
  begin
    insert into public.contracts (id, project_id, original_filename, storage_path, mime_type, size_bytes)
    values (gen_random_uuid(), v_project, 'x.pdf',
            'contracts/' || v_project || '/' || v_id || '/original.pdf', 'application/pdf', 10);
    raise exception 'a storage path in another contract''s folder should be rejected';
  exception when check_violation then null;
  end;

  -- only PDF and DOCX, up to 25 MB
  begin
    insert into public.contracts (id, project_id, original_filename, storage_path, mime_type, size_bytes)
    values ('cccccccc-0000-4000-8000-000000000009', v_project, 'x.exe',
            'contracts/' || v_project || '/cccccccc-0000-4000-8000-000000000009/original.exe',
            'application/x-msdownload', 10);
    raise exception 'an unsupported file type should be rejected';
  exception when check_violation then null;
  end;
  begin
    insert into public.contracts (id, project_id, original_filename, storage_path, mime_type, size_bytes)
    values ('cccccccc-0000-4000-8000-000000000009', v_project, 'big.pdf',
            'contracts/' || v_project || '/cccccccc-0000-4000-8000-000000000009/original.pdf',
            'application/pdf', 26214401);
    raise exception 'a contract over 25 MB should be rejected';
  exception when check_violation then null;
  end;

  -- cannot upload into another organisation's project
  begin
    insert into public.contracts (id, project_id, original_filename, storage_path, mime_type, size_bytes)
    values ('cccccccc-0000-4000-8000-000000000008', v_b, 'x.pdf',
            'contracts/' || v_b || '/cccccccc-0000-4000-8000-000000000008/original.pdf', 'application/pdf', 10);
    raise exception 'inserting a contract into another organisation''s project should be denied';
  exception when insufficient_privilege then null;
  end;

  -- cannot pretend someone else uploaded it
  begin
    insert into public.contracts (id, project_id, original_filename, storage_path, mime_type, size_bytes, uploaded_by)
    values ('cccccccc-0000-4000-8000-000000000007', v_project, 'x.pdf',
            'contracts/' || v_project || '/cccccccc-0000-4000-8000-000000000007/original.pdf',
            'application/pdf', 10, 'b0000000-0000-4000-8000-0000000000b1');
    raise exception 'setting uploaded_by should be denied';
  exception when insufficient_privilege then null;
  end;

  -- processing state can move; the document itself cannot be repointed or moved
  update public.contracts set processing_status = 'processing' where id = v_id;
  update public.contracts set processing_status = 'failed', error = 'AI analysis unavailable.' where id = v_id;
  update public.contracts set processing_status = 'ready', error = null, processed_at = now(), page_count = 42 where id = v_id;
  get diagnostics v_rows = row_count;
  assert v_rows = 1, 'A can update processing state';
  begin
    update public.contracts set processing_status = 'done' where id = v_id;
    raise exception 'an unknown processing status should be rejected';
  exception when check_violation then null;
  end;
  begin
    update public.contracts set storage_path = 'contracts/elsewhere' where id = v_id;
    raise exception 'changing storage_path should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    update public.contracts set project_id = v_other where id = v_id;
    raise exception 'moving a contract to another project should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    delete from public.contracts where id = v_id;
    raise exception 'deleting a contract should be denied';
  exception when insufficient_privilege then null;
  end;
end $$;

-- ---------------------------------------------------------------------------
-- Owner A: contract items and the review bookkeeping
-- ---------------------------------------------------------------------------
do $$
declare
  v_contract constant uuid := 'cccccccc-0000-4000-8000-000000000001';
  v_item     public.contract_items;
  v_untouched uuid;
  v_rows     integer;
begin
  insert into public.contract_items
    (contract_id, item_code, description, quantity, unit, rate, amount, extraction_confidence,
     source_reference, extracted_values, sort_order)
  values
    (v_contract, '4.2', 'Electrical conduit installation', 120, 'm', 45, 5400, 0.91, 'Schedule 2, p. 14',
     '{"item_code": "4.2", "description": "Electrical conduit installation", "quantity": 120}', 1)
  returning * into v_item;
  assert v_item.review_status = 'draft', 'extracted items start as drafts';
  assert not v_item.edited_by_human and v_item.reviewed_by is null, 'and are untouched';

  insert into public.contract_items (contract_id, item_code, description, sort_order)
  values (v_contract, '4.3', 'Cable tray installation', 2)
  returning id into v_untouched;

  -- nullable fields really are optional
  assert (select quantity is null and rate is null and amount is null and due_date is null
          from public.contract_items where id = v_untouched), 'missing contract fields stay null';

  -- a client cannot pre-approve an item or forge the bookkeeping
  begin
    insert into public.contract_items (contract_id, item_code, description, review_status)
    values (v_contract, '9.9', 'Sneaky', 'confirmed');
    raise exception 'inserting with review_status should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    update public.contract_items set edited_by_human = false where id = v_item.id;
    raise exception 'setting edited_by_human directly should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    update public.contract_items set reviewed_by = 'b0000000-0000-4000-8000-0000000000b1' where id = v_item.id;
    raise exception 'setting reviewed_by directly should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    update public.contract_items set extracted_values = '{}' where id = v_item.id;
    raise exception 'changing the AI snapshot should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    update public.contract_items set extraction_confidence = 1 where id = v_item.id;
    raise exception 'changing the AI confidence should be denied';
  exception when insufficient_privilege then null;
  end;

  -- confirming records who did it, and is not an edit
  update public.contract_items set review_status = 'confirmed' where id = v_item.id returning * into v_item;
  assert v_item.reviewed_by = 'a0000000-0000-4000-8000-0000000000a1', 'confirming records the reviewer';
  assert not v_item.edited_by_human, 'confirming alone does not count as an edit';

  -- editing an extracted field flags the item and keeps the AI snapshot
  update public.contract_items set quantity = 150, amount = 6750 where id = v_item.id returning * into v_item;
  assert v_item.edited_by_human, 'changing an extracted field sets edited_by_human';
  assert (v_item.extracted_values ->> 'quantity')::numeric = 120, 'the AI''s original value is kept';
  assert v_item.review_status = 'confirmed', 'editing does not change the review status';

  -- rejecting, then reopening, clears the reviewer
  update public.contract_items set review_status = 'rejected' where id = v_item.id returning * into v_item;
  assert v_item.reviewed_by = 'a0000000-0000-4000-8000-0000000000a1', 'rejecting records the reviewer';
  update public.contract_items set review_status = 'draft' where id = v_item.id returning * into v_item;
  assert v_item.reviewed_by is null, 'reopening clears the reviewer';
  assert v_item.edited_by_human, 'but the item still counts as edited';

  begin
    update public.contract_items set review_status = 'approved' where id = v_item.id;
    raise exception 'an unknown review status should be rejected';
  exception when check_violation then null;
  end;
  begin
    update public.contract_items set quantity = -1 where id = v_item.id;
    raise exception 'a negative quantity should be rejected';
  exception when check_violation then null;
  end;

  -- only untouched drafts can be removed (to re-run a failed extraction)
  delete from public.contract_items where contract_id = v_contract;
  get diagnostics v_rows = row_count;
  assert v_rows = 1, 'only the untouched draft is deleted';
  assert exists (select 1 from public.contract_items where id = v_item.id), 'the edited item is kept';
  assert not exists (select 1 from public.contract_items where id = v_untouched), 'the untouched draft is gone';

  perform set_config('test.item_a', v_item.id::text, true);
end $$;

-- ---------------------------------------------------------------------------
-- Owner A: evidence
-- ---------------------------------------------------------------------------
do $$
declare
  v_project constant uuid := 'aaaaaaaa-0000-4000-8000-000000000001';
  v_other   constant uuid := 'aaaaaaaa-0000-4000-8000-000000000002';
  v_b       constant uuid := 'bbbbbbbb-0000-4000-8000-000000000001';
  v_id      constant uuid := 'eeeeeeee-0000-4000-8000-000000000001';
  v_ev      public.evidence;
  v_note    public.evidence;
begin
  -- a photo with a file
  insert into public.evidence
    (id, project_id, storage_path, original_filename, mime_type, size_bytes, evidence_type, captured_at, title, metadata)
  values
    (v_id, v_project, 'evidence/' || v_project || '/' || v_id || '/original.jpg', 'IMG_0412.jpg',
     'image/jpeg', 2400000, 'photo', '2026-10-01T03:15:00Z', 'Edge beam formwork L3',
     '{"location": "Level 3, grid C5", "source": "mobile_upload", "tags": ["formwork"]}')
  returning * into v_ev;
  assert v_ev.code = 'EV-001' and v_ev.sequence_number = 1, 'the first record in a project is EV-001';
  assert v_ev.uploaded_by = 'a0000000-0000-4000-8000-0000000000a1', 'uploaded_by is derived from the caller';
  assert v_ev.processing_status = 'uploaded' and not v_ev.archived, 'new evidence is uploaded and not archived';
  assert v_ev.metadata ->> 'location' = 'Level 3, grid C5', 'metadata is stored as sent';

  -- a written note with no file
  insert into public.evidence (project_id, evidence_type, title, description)
  values (v_project, 'message', 'Site instruction', 'Builder asked for extra penetrations on L3.')
  returning * into v_note;
  assert v_note.code = 'EV-002', 'codes count up within the project';
  assert v_note.storage_path is null and v_note.metadata = '{}'::jsonb, 'a note has no file and empty metadata';

  -- numbering is per project
  insert into public.evidence (project_id, title, description) values (v_other, 'Other project note', 'x')
  returning * into v_note;
  assert v_note.code = 'EV-001', 'each project has its own numbering';
  assert v_note.evidence_type = 'other', 'evidence_type defaults to other';

  -- a record needs a file or a note
  begin
    insert into public.evidence (project_id, title, description) values (v_project, 'Empty', '   ');
    raise exception 'evidence with no file and no note should be rejected';
  exception when check_violation then null;
  end;
  -- file details come together
  begin
    insert into public.evidence (id, project_id, storage_path, title)
    values ('eeeeeeee-0000-4000-8000-000000000002', v_project,
            'evidence/' || v_project || '/eeeeeeee-0000-4000-8000-000000000002/original.jpg', 'Half a file');
    raise exception 'a file without its filename, type and size should be rejected';
  exception when check_violation then null;
  end;
  -- the file must sit in this record's own folder
  begin
    insert into public.evidence (id, project_id, storage_path, original_filename, mime_type, size_bytes, title)
    values ('eeeeeeee-0000-4000-8000-000000000003', v_project,
            'evidence/' || v_b || '/eeeeeeee-0000-4000-8000-000000000003/original.jpg', 'x.jpg', 'image/jpeg', 10, 'Wrong folder');
    raise exception 'a storage path in another project should be rejected';
  exception when check_violation then null;
  end;
  begin
    insert into public.evidence (project_id, title, description, evidence_type) values (v_project, 'Bad type', 'x', 'video');
    raise exception 'an unknown evidence type should be rejected';
  exception when check_violation then null;
  end;
  begin
    insert into public.evidence (project_id, title, description, metadata) values (v_project, 'Bad metadata', 'x', '[1, 2]');
    raise exception 'metadata that is not an object should be rejected';
  exception when check_violation then null;
  end;

  -- clients cannot choose the code or the uploader, or upload into another organisation
  begin
    insert into public.evidence (project_id, title, description, code) values (v_project, 'Sneaky', 'x', 'EV-999');
    raise exception 'setting the code should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into public.evidence (project_id, title, description, uploaded_by)
    values (v_project, 'Sneaky', 'x', 'b0000000-0000-4000-8000-0000000000b1');
    raise exception 'setting uploaded_by should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into public.evidence (project_id, title, description) values (v_b, 'Sneaky', 'x');
    raise exception 'adding evidence to another organisation''s project should be denied';
  exception when insufficient_privilege then null;
  end;

  -- edit metadata and archive; the source file reference cannot be changed
  update public.evidence
  set title = 'Edge beam formwork, level 3', evidence_type = 'photo', archived = true,
      metadata = metadata || '{"tags": ["formwork", "level-3"]}'
  where id = v_id returning * into v_ev;
  assert v_ev.archived and v_ev.metadata -> 'tags' ->> 1 = 'level-3', 'A can edit metadata and archive';
  update public.evidence set archived = false, processing_status = 'ready' where id = v_id;
  begin
    update public.evidence set storage_path = null where id = v_id;
    raise exception 'changing storage_path should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    update public.evidence set project_id = v_other where id = v_id;
    raise exception 'moving evidence to another project should be denied';
  exception when insufficient_privilege then null;
  end;
  begin
    delete from public.evidence where id = v_id;
    raise exception 'deleting evidence should be denied';
  exception when insufficient_privilege then null;
  end;

  assert (select count(*) from public.evidence where project_id = v_project) = 2, 'failed inserts left nothing behind';
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- Owner B: organisation A's contracts, items and evidence are invisible and unwritable
-- ---------------------------------------------------------------------------
set local role authenticated;
set local request.jwt.claims = '{"sub": "b0000000-0000-4000-8000-0000000000b1", "role": "authenticated"}';
do $$
declare
  v_contract_a constant uuid := 'cccccccc-0000-4000-8000-000000000001';
  v_evidence_a constant uuid := 'eeeeeeee-0000-4000-8000-000000000001';
  v_item_a     constant uuid := current_setting('test.item_a')::uuid;
  v_b          constant uuid := 'bbbbbbbb-0000-4000-8000-000000000001';
  v_rows       integer;
  v_ev         public.evidence;
begin
  assert (select count(*) from public.contracts) = 0, 'B sees none of A''s contracts';
  assert (select count(*) from public.contract_items) = 0, 'B sees none of A''s contract items';
  assert (select count(*) from public.evidence) = 0, 'B sees none of A''s evidence';
  assert not public.can_access_contract(v_contract_a), 'can_access_contract() is false across organisations';

  update public.contracts set processing_status = 'failed' where id = v_contract_a;
  get diagnostics v_rows = row_count;
  assert v_rows = 0, 'B cannot update A''s contract';

  update public.contract_items set review_status = 'rejected' where id = v_item_a;
  get diagnostics v_rows = row_count;
  assert v_rows = 0, 'B cannot review A''s contract item';

  delete from public.contract_items where id = v_item_a;
  get diagnostics v_rows = row_count;
  assert v_rows = 0, 'B cannot delete A''s contract item';

  update public.evidence set archived = true, title = 'Hijacked' where id = v_evidence_a;
  get diagnostics v_rows = row_count;
  assert v_rows = 0, 'B cannot edit or archive A''s evidence';

  begin
    insert into public.contract_items (contract_id, item_code, description) values (v_contract_a, '1', 'Injected');
    raise exception 'adding an item to another organisation''s contract should be denied';
  exception when insufficient_privilege then null;
  end;

  -- B's own project numbers its evidence independently
  insert into public.evidence (project_id, title, description) values (v_b, 'B note', 'x') returning * into v_ev;
  assert v_ev.code = 'EV-001', 'B''s project starts its own numbering';
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- Back as the database owner: nothing B tried changed A's data
-- ---------------------------------------------------------------------------
do $$
begin
  assert (select processing_status from public.contracts where id = 'cccccccc-0000-4000-8000-000000000001') = 'ready',
         'A''s contract is unchanged';
  assert (select review_status from public.contract_items where id = current_setting('test.item_a')::uuid) = 'draft',
         'A''s contract item is unchanged';
  assert (select title from public.evidence where id = 'eeeeeeee-0000-4000-8000-000000000001') = 'Edge beam formwork, level 3',
         'A''s evidence is unchanged';

  -- updated_at is maintained by triggers
  update public.contracts set updated_at = '2000-01-01T00:00:00Z' where id = 'cccccccc-0000-4000-8000-000000000001';
  update public.evidence set updated_at = '2000-01-01T00:00:00Z' where id = 'eeeeeeee-0000-4000-8000-000000000001';
  update public.contract_items set updated_at = '2000-01-01T00:00:00Z' where id = current_setting('test.item_a')::uuid;
  assert (select updated_at from public.contracts where id = 'cccccccc-0000-4000-8000-000000000001') > '2001-01-01T00:00:00Z',
         'contracts.updated_at is set by the trigger';
  assert (select updated_at from public.evidence where id = 'eeeeeeee-0000-4000-8000-000000000001') > '2001-01-01T00:00:00Z',
         'evidence.updated_at is set by the trigger';
  assert (select updated_at from public.contract_items where id = current_setting('test.item_a')::uuid) > '2001-01-01T00:00:00Z',
         'contract_items.updated_at is set by the trigger';
end $$;

do $$ begin raise notice 'contracts_and_evidence: all checks passed'; end $$;

rollback;
