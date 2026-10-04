# Database schema

Living document. Last updated: 2026-10-04.

Database: Supabase PostgreSQL, with pgvector for embeddings. Migrations live in
`supabase/migrations/`.

## 1. Conventions

| Topic | Rule |
|---|---|
| Table names | Plural `snake_case`: `contract_items`, `audit_events` |
| Column names | `snake_case` |
| Primary key | `id uuid primary key default gen_random_uuid()` |
| Timestamps | `created_at timestamptz not null default now()` and `updated_at timestamptz not null default now()` |
| `updated_at` | Maintained by the shared trigger function `set_updated_at()`. Attach it to every table that has the column. |
| Foreign keys | Always declared, named `<thing>_id`. Index every foreign key column. |
| Status columns | `text` with a `check` constraint listing the allowed values. No Postgres enums. |
| Money and quantities | `numeric`, never `float` |
| Optional values | `null`. Do not use `''` or `0` to mean "unknown". |
| Flexible metadata | `jsonb`, only where the shape really varies (e.g. `evidence.metadata`) |
| Deletes | Prefer archiving (`status` or `archived`) to deleting. Evidence and audit history must survive. |
| Security | `alter table ... enable row level security` in the same migration that creates the table |

### Migration rules

1. File name: `<YYYYMMDDHHMMSS>_<short_name>.sql`, e.g. `20261004090000_platform_foundation.sql`. Files run in name order.
2. Never edit a migration after it is merged. Fix it with a new migration.
3. One owner per table (see section 2). Ask the owner before altering their table.
4. Do not create a second version of a table that already exists here.
5. Explain every migration in the merge request description.

## 2. Table ownership

| Table | Purpose | Owner | State |
|---|---|---|---|
| `organisations` | Subcontractor business. The tenant boundary. | Platform | Live |
| `profiles` | Application profile for an auth user, with organisation and role | Platform | Live |
| `projects` | Construction project workspace | Platform | Live |
| `contracts` | Uploaded contract and processing metadata | Kinori | Live |
| `contract_items` | Structured contractual / claim line item | Kinori | Live |
| `evidence` | Photo, document, docket, message or other supporting record | Kinori | Live |
| `evidence_matches` | AI-suggested or human-confirmed link between evidence and a contract item | Arya writes suggestions, Rehan owns confirmation | Planned |
| `claims` | Progress claim workspace | Rehan | Planned |
| `claim_items` | Claim-level view of a contract item and its evidence state | Rehan | Planned |
| `variations` | Potential additional or changed work flagged for review | Arya | Planned |
| `notifications` | User-facing reminder or action item | Rehan | Planned |
| `audit_events` | Record of important workflow actions | Rehan | Planned |

"Live" means a migration in `supabase/migrations/` creates it. "Planned" means
the shape is agreed here but the migration has not been written. The web
prototype keeps the same shapes in `apps/web/lib/types.ts`.

Migrations so far:

| File | Creates |
|---|---|
| `20261004090000_platform_foundation.sql` | `organisations`, `profiles`, `projects`, the helper functions in section 3, the sign-up trigger, privileges and RLS policies |
| `20261004120000_contracts_and_evidence.sql` | `contracts`, `contract_items`, `evidence`, `can_access_contract()`, the review-tracking and evidence-code triggers, privileges and RLS policies |

pgvector is not enabled yet. The first migration that needs it (Arya's
embedding tables) should start with
`create extension if not exists vector with schema extensions;`.

## 3. Row Level Security

Every table has RLS enabled. Nothing is publicly readable.

Shared helper functions, created by the platform migration, for everyone's policies:

| Function | Returns | Use |
|---|---|---|
| `public.current_organisation_id()` | `uuid` | The organisation of the signed-in user (`auth.uid()`), or `null` |
| `public.current_profile_role()` | `text` | `owner` or `member` for the signed-in user, or `null` |
| `public.can_access_project(project_id uuid)` | `boolean` | True when the project belongs to the signed-in user's organisation |
| `public.can_access_contract(contract_id uuid)` | `boolean` | True when the contract's project belongs to the signed-in user's organisation |
| `public.set_updated_at()` | trigger | Attach as a `before update` trigger to keep `updated_at` current |

Policy patterns:

```sql
-- Table with its own organisation_id
using (organisation_id = public.current_organisation_id())

-- Table that hangs off a project
using (public.can_access_project(project_id))

-- Table that hangs off a contract (e.g. contract_items)
using (public.can_access_contract(contract_id))

-- Table further down still (e.g. a table that references evidence or contract_items)
using (exists (
  select 1 from public.evidence e
  where e.id = evidence_matches.evidence_id
    and public.can_access_project(e.project_id)
))
```

Write policies (`insert`, `update`) need a matching `with check` so a row
cannot be moved into another organisation. Wrap helper calls in `(select ...)`
inside policies, e.g. `(select public.current_organisation_id())`, so Postgres
evaluates them once per query instead of once per row.

### Privileges

RLS decides which rows. Grants decide which operations and columns. Every
migration sets both, explicitly, and does not rely on Supabase's default grants:

```sql
revoke all on public.<table> from anon, authenticated;
grant select on public.<table> to authenticated;
grant insert (<client-writable columns>) on public.<table> to authenticated;
grant update (<client-writable columns>) on public.<table> to authenticated;
grant all on public.<table> to service_role;
```

Leave server-set columns (`id`, `organisation_id`, `created_by`, `uploaded_by`,
timestamps) out of the insert and update grants and give them a default, so a
client cannot choose them. Signed-out callers (`anon`) get nothing.

### Checking it works

`supabase/tests/platform_foundation.sql` and
`supabase/tests/contracts_and_evidence.sql` sign up test users in two
organisations and assert the rules above, inside a transaction that is rolled
back. Add a similar file for each new set of tables. See
[development-guide.md](development-guide.md#6-database).

The service-role key bypasses RLS. Server code that uses it must check project
ownership itself and must never be reachable from the browser.

## 4. Platform tables

### `organisations`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `name` | text | Not null |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

Access: members can read their own organisation. Owners can rename it.

### `profiles`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK. Same value as `auth.users.id`. FK, `on delete cascade`. |
| `organisation_id` | uuid | FK to `organisations`. Not null. Indexed. |
| `email` | text | Copy of the auth email, for display. Kept in step by a trigger. |
| `full_name` | text | Not null |
| `role` | text | `owner` or `member` |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

Because `profiles.id` is the auth user id, every `created_by`, `uploaded_by`,
`confirmed_by` and `actor_id` column in other tables references `profiles(id)`.

Access: a user can read profiles in their own organisation and update their own
`full_name`. `role` and `organisation_id` cannot be changed by the client.

**Sign-up.** A trigger on `auth.users` (`handle_new_user()`) creates the
organisation and the profile in one transaction. The web app passes two values
as sign-up metadata: `full_name` and `organisation_name`. The person who signs
up becomes the `owner` of a new organisation. If the metadata is missing, the
name falls back to the part of the email before `@`. Sign-up metadata comes
from the client, so it can never place a user in an existing organisation.

### `projects`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `organisation_id` | uuid | FK to `organisations`. Not null. Indexed. Defaults to the caller's organisation. |
| `name` | text | Not null. 1 to 200 characters. |
| `client_name` | text | Not null. Head contractor / client. 1 to 200 characters. |
| `site_address` | text | Not null, default `''` |
| `status` | text | `active` or `archived`. Default `active`. |
| `start_date` | date | Nullable |
| `end_date` | date | Nullable. Check: not before `start_date`. |
| `created_by` | uuid | FK to `profiles`. Defaults to the caller. |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

Access: organisation members can read, create and edit their organisation's
projects. Clients can write `name`, `client_name`, `site_address`,
`start_date`, `end_date`, and on update `status`. There is no delete privilege
or policy. Projects are archived.

## 5. Contract and evidence tables (owner: Kinori)

Files live in Supabase Storage. These tables hold the path and metadata.

### `contracts`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK. Chosen by the API before upload, because the storage path contains it. |
| `project_id` | uuid | FK to `projects` |
| `original_filename` | text | 1 to 255 characters |
| `storage_path` | text | `contracts/{project_id}/{contract_id}/original.<ext>`. A check constraint enforces that it sits in this contract's own folder. |
| `mime_type` | text | PDF or DOCX only |
| `size_bytes` | bigint | Up to 25 MB |
| `page_count` | integer | Nullable |
| `processing_status` | text | `uploaded`, `processing`, `ready`, `failed`. Default `uploaded`. |
| `error` | text | Nullable. User-safe message when `failed`. |
| `uploaded_by` | uuid | FK to `profiles`. Defaults to the caller. |
| `created_at`, `updated_at` | timestamptz | |
| `processed_at` | timestamptz | Nullable |

Access: members of the project's organisation can read and upload. After
upload only the processing fields (`processing_status`, `error`, `page_count`,
`processed_at`) can change. Contracts are not deleted.

### `contract_items`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `contract_id` | uuid | FK to `contracts` |
| `item_code` | text | e.g. `4.2` |
| `description` | text | |
| `quantity` | numeric | Nullable. Not negative. |
| `unit` | text | Nullable |
| `rate` | numeric | Nullable. Not negative. |
| `amount` | numeric | Nullable. Not negative. |
| `conditions` | text | Nullable |
| `notice_requirement` | text | Nullable |
| `due_date` | date | Nullable |
| `extraction_confidence` | numeric | 0 to 1. Nullable for items a person added. Cannot be changed after insert. |
| `review_status` | text | `draft`, `confirmed`, `rejected`. Always `draft` on insert. |
| `edited_by_human` | boolean | Set by a trigger once a person changes any extracted field |
| `reviewed_by` | uuid | FK to `profiles`. Set by a trigger to whoever confirmed or rejected; cleared when the item returns to `draft`. |
| `source_reference` | text | Nullable. Where in the contract it came from. |
| `extracted_values` | jsonb | Nullable. The values exactly as the AI returned them. Written once, never updated. |
| `sort_order` | integer | Position within the contract's schedule |
| `created_at`, `updated_at` | timestamptz | |

Not every contract contains every field, so most columns are nullable.

AI output is never silently overwritten. A person's edit changes the column,
sets `edited_by_human`, and leaves the AI's original in `extracted_values`.
Clients cannot set `edited_by_human`, `reviewed_by`, `extracted_values` or
`extraction_confidence` on update; the database maintains them.

Access: members of the contract's organisation can read, add, edit and review
items. Only untouched AI drafts (`review_status = 'draft'` and not
`edited_by_human`) can be deleted, so a failed extraction can be re-run. An
item a person has edited, confirmed or rejected is kept.

### `evidence`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK. Chosen by the API before upload when there is a file. |
| `project_id` | uuid | FK to `projects` |
| `sequence_number` | integer | 1, 2, 3 ... within the project. Assigned by a trigger. |
| `code` | text | `EV-001`, `EV-002` ... Unique within a project. Assigned by a trigger; clients never send it. |
| `uploaded_by` | uuid | FK to `profiles`. Defaults to the caller. |
| `storage_path` | text | `evidence/{project_id}/{evidence_id}/original.<ext>`, enforced by a check constraint. Null for a written note with no file. |
| `original_filename` | text | Null when there is no file |
| `mime_type` | text | Null when there is no file |
| `size_bytes` | bigint | Up to 50 MB. Null when there is no file. |
| `evidence_type` | text | `photo`, `document`, `docket`, `message`, `other`. Default `other`. |
| `captured_at` | timestamptz | When the evidence was created on site, not when it was uploaded |
| `title` | text | 1 to 200 characters |
| `description` | text | Default `''` |
| `metadata` | jsonb | A JSON object, e.g. `{ "location": null, "source": "mobile_upload", "tags": [] }` |
| `processing_status` | text | `uploaded`, `processing`, `ready`, `failed`. Default `uploaded`. |
| `archived` | boolean | Default false |
| `created_at`, `updated_at` | timestamptz | |

A record is a file, a written note, or both: it needs a `storage_path` or a
non-empty `description`. The four file columns are all set or all null.

Access: members of the project's organisation can read and add evidence, and
edit `title`, `description`, `evidence_type`, `captured_at`, `metadata`,
`archived` and `processing_status`. The file reference cannot be changed.
Source files and their metadata are preserved: evidence is archived, never
deleted.

## 6. Match and claim tables

### `evidence_matches` (shared model)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `evidence_id` | uuid | FK to `evidence` |
| `contract_item_id` | uuid | FK to `contract_items` |
| `confidence` | numeric | 0 to 1 |
| `assessment` | text | `strong`, `partial`, `weak` |
| `reason` | text | Explanation a person can review |
| `missing_evidence` | text[] | What would strengthen the match |
| `status` | text | `suggested`, `confirmed`, `rejected` |
| `source` | text | `ai` or `human` |
| `confirmed_by` | uuid | FK to `profiles`. Nullable. |
| `confirmed_at` | timestamptz | Nullable |
| `created_at`, `updated_at` | timestamptz | |

One row per (`evidence_id`, `contract_item_id`). Only a human action sets
`confirmed` or `rejected`.

### `claims` (owner: Rehan)

`id`, `project_id`, `name`, `number`, `period_start`, `period_end`, `due_date`,
`status` (`draft`, `ready`, `exported`), `created_by`, `created_at`, `updated_at`.

### `claim_items` (owner: Rehan)

`id`, `claim_id`, `contract_item_id`, `claimed_quantity`, `claimed_amount`,
`readiness_status`, `completeness_score` (if provided by AI), `created_at`,
`updated_at`. Do not create another contract item table.

### `variations` (owner: Arya)

`id`, `project_id`, `code`, `title`, `confidence`, `reason`,
`estimated_amount`, `related_evidence_ids`, `related_contract_item_id`,
`notice_due`, `review_required`, `status` (`flagged`, `acknowledged`,
`dismissed`), `created_at`. A variation row is a flag for review, never an
entitlement decision.

### `notifications` (owner: Rehan)

`id`, `profile_id`, `project_id`, `title`, `body`, `href`, `status` (`unread`,
`read`, `dismissed`), `created_at`. A user sees only their own.

### `audit_events` (owner: Rehan)

`id`, `organisation_id`, `project_id`, `actor_id` (null means SubPay AI),
`action`, `entity`, `entity_id`, `metadata` (jsonb), `created_at`.

Append-only: there are insert and select policies, and no update or delete
policy, so users cannot rewrite history. Action names follow
`<entity>.<verb>`, e.g. `contract_item.edited`, `match.confirmed`,
`package.exported`.

### AI tables (owner: Arya, optional)

`evidence_embeddings`, `contract_item_embeddings`, `ai_runs`. They reference
the core tables and record model / provider metadata. They do not duplicate
`evidence` or `contract_items`.

## 7. Storage buckets (owner: Kinori)

| Bucket | Public | Object path inside the bucket |
|---|---|---|
| `contracts` | No | `{project_id}/{contract_id}/original.<ext>` |
| `evidence` | No | `{project_id}/{evidence_id}/original.<ext>` |

The `storage_path` column stores the bucket name followed by the object path,
e.g. `contracts/{project_id}/{contract_id}/original.pdf`.

Storage policies use `public.can_access_project()` on the first segment of the
object path. Files are served through signed URLs only.
