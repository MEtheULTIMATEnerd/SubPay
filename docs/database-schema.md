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
| `organisations` | Subcontractor business. The tenant boundary. | Platform | Planned |
| `profiles` | Application profile for an auth user, with organisation and role | Platform | Planned |
| `projects` | Construction project workspace | Platform | Planned |
| `contracts` | Uploaded contract and processing metadata | Kinori | Planned |
| `contract_items` | Structured contractual / claim line item | Kinori | Planned |
| `evidence` | Photo, document, docket, message or other supporting record | Kinori | Planned |
| `evidence_matches` | AI-suggested or human-confirmed link between evidence and a contract item | Arya writes suggestions, Rehan owns confirmation | Planned |
| `claims` | Progress claim workspace | Rehan | Planned |
| `claim_items` | Claim-level view of a contract item and its evidence state | Rehan | Planned |
| `variations` | Potential additional or changed work flagged for review | Arya | Planned |
| `notifications` | User-facing reminder or action item | Rehan | Planned |
| `audit_events` | Record of important workflow actions | Rehan | Planned |

"Planned" means the shape is agreed here but the migration has not been written.
The web prototype keeps the same shapes in `apps/web/lib/types.ts`.

## 3. Row Level Security

Every table has RLS enabled. Nothing is publicly readable.

Shared helper functions, created by the platform migration, for everyone's policies:

| Function | Returns | Use |
|---|---|---|
| `public.current_organisation_id()` | `uuid` | The organisation of the signed-in user (`auth.uid()`), or `null` |
| `public.can_access_project(project_id uuid)` | `boolean` | True when the project belongs to the signed-in user's organisation |

Policy patterns:

```sql
-- Table with its own organisation_id
using (organisation_id = public.current_organisation_id())

-- Table that hangs off a project
using (public.can_access_project(project_id))

-- Table one step further down (e.g. contract_items -> contracts -> projects)
using (exists (
  select 1 from public.contracts c
  where c.id = contract_items.contract_id
    and public.can_access_project(c.project_id)
))
```

Write policies (`insert`, `update`) need a matching `with check` so a row
cannot be moved into another organisation.

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
| `email` | text | Copy of the auth email, for display |
| `full_name` | text | Not null |
| `role` | text | `owner` or `member` |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

Because `profiles.id` is the auth user id, every `created_by`, `uploaded_by`,
`confirmed_by` and `actor_id` column in other tables references `profiles(id)`.

Access: a user can read profiles in their own organisation and update their own
`full_name`. `role` and `organisation_id` cannot be changed by the client.

**Sign-up.** A trigger on `auth.users` creates the organisation and the profile
in one transaction. The web app passes two values as sign-up metadata:
`full_name` and `organisation_name`. The person who signs up becomes the
`owner` of a new organisation.

### `projects`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `organisation_id` | uuid | FK to `organisations`. Not null. Indexed. |
| `name` | text | Not null |
| `client_name` | text | Not null. Head contractor / client. |
| `site_address` | text | Not null, default `''` |
| `status` | text | `active` or `archived`. Default `active`. |
| `start_date` | date | Nullable |
| `end_date` | date | Nullable. Check: not before `start_date`. |
| `created_by` | uuid | FK to `profiles` |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

Access: organisation members can read, create and edit their organisation's
projects. There is no delete policy. Projects are archived.

## 5. Contract and evidence tables (owner: Kinori)

### `contracts`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `project_id` | uuid | FK to `projects` |
| `original_filename` | text | |
| `storage_path` | text | `contracts/{project_id}/{contract_id}/original.<ext>` |
| `mime_type` | text | PDF or DOCX |
| `size_bytes` | bigint | |
| `page_count` | integer | Nullable |
| `processing_status` | text | `uploaded`, `processing`, `ready`, `failed` |
| `error` | text | Nullable. User-safe message when `failed`. |
| `uploaded_by` | uuid | FK to `profiles` |
| `created_at`, `updated_at` | timestamptz | |
| `processed_at` | timestamptz | Nullable |

### `contract_items`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `contract_id` | uuid | FK to `contracts` |
| `item_code` | text | e.g. `4.2` |
| `description` | text | |
| `quantity` | numeric | Nullable |
| `unit` | text | Nullable |
| `rate` | numeric | Nullable |
| `amount` | numeric | Nullable |
| `conditions` | text | Nullable |
| `notice_requirement` | text | Nullable |
| `due_date` | date | Nullable |
| `extraction_confidence` | numeric | 0 to 1. Nullable for items a person added. |
| `review_status` | text | `draft`, `confirmed`, `rejected` |
| `edited_by_human` | boolean | True once a person has changed any extracted field |
| `reviewed_by` | uuid | FK to `profiles`. Nullable. |
| `source_reference` | text | Nullable. Where in the contract it came from. |
| `created_at`, `updated_at` | timestamptz | |

AI output is never silently overwritten: an edit sets `edited_by_human` and the
previous values go to `audit_events`.

### `evidence`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `project_id` | uuid | FK to `projects` |
| `code` | text | Human-friendly reference, e.g. `EV-001`, unique within a project |
| `uploaded_by` | uuid | FK to `profiles` |
| `storage_path` | text | `evidence/{project_id}/{evidence_id}/original.<ext>`. Nullable for a written note with no file. |
| `original_filename` | text | |
| `mime_type` | text | |
| `evidence_type` | text | `photo`, `document`, `docket`, `message`, `other` |
| `captured_at` | timestamptz | When the evidence was created on site, not when it was uploaded |
| `title` | text | |
| `description` | text | |
| `metadata` | jsonb | e.g. `{ "location": null, "source": "mobile_upload", "tags": [] }` |
| `processing_status` | text | `uploaded`, `processing`, `ready`, `failed` |
| `archived` | boolean | Default false |
| `created_at`, `updated_at` | timestamptz | |

Source files and their metadata are preserved. Evidence is archived, not deleted.

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
