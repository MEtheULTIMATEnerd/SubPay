-- =============================================================================
-- Contracts and contract items can be deleted (owner: Kinori)
--
-- A person can remove a contract uploaded by mistake (its items go with it,
-- on delete cascade) and any line item the AI got wrong. The stored contract
-- file can be removed too. Evidence is unchanged: archived, never deleted.
--
-- Depends on: 20261004120000_contracts_and_evidence.sql,
--             20261004130000_storage_buckets.sql
-- =============================================================================

grant delete on public.contracts to authenticated;

create policy contracts_delete_own_organisation
  on public.contracts for delete to authenticated
  using ((select public.can_access_project(project_id)));

-- Previously only untouched AI drafts could be removed.
drop policy contract_items_delete_untouched_drafts on public.contract_items;

create policy contract_items_delete_own_organisation
  on public.contract_items for delete to authenticated
  using ((select public.can_access_contract(contract_id)));

create policy subpay_contract_files_delete
  on storage.objects for delete to authenticated
  using (
    bucket_id = 'contracts'
    and public.can_access_project(public.storage_object_project_id(name))
  );
