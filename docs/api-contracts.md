# API contracts

Living document. Last updated: 2026-10-04.

Stable interfaces that every workstream builds against. Change a shared shape
only with agreement from the owner of that resource, and update this file in
the same merge request.

## 1. Conventions

| Topic | Rule |
|---|---|
| Base path | `/api/v1` for the application API, `/ai/v1` for the AI service |
| Format | JSON request and response bodies, `snake_case` field names |
| File uploads | `multipart/form-data` |
| IDs | UUID strings |
| Timestamps | ISO 8601 in UTC, e.g. `2026-10-04T05:12:00Z` |
| Dates | `YYYY-MM-DD`, e.g. `2026-10-31` |
| Money | Numbers in AUD, e.g. `5400` or `5400.50`. No currency symbols. |
| Missing values | `null`, never an empty string or `0` standing in for "unknown" |
| Docs | FastAPI serves OpenAPI at `/api/v1/docs` and `/api/v1/openapi.json` |

### Authentication

Every endpoint except `GET /api/v1/health` requires:

```
Authorization: Bearer <Supabase access token>
```

- The API derives the user and their organisation from the token.
- Clients never send `user_id` or `organisation_id`. If one is sent, it is ignored.
- Fields such as `created_by`, `uploaded_by`, `confirmed_by` and `organisation_id` are set by the server.

### Resource naming

- Plural nouns, kebab-case in paths: `/contract-items`, `/evidence-matches`, `/audit-events`.
- A collection sits under its parent: `GET /projects/{project_id}/contracts`.
- A single record is addressed directly: `GET /contracts/{contract_id}`.
- State changes that are not plain edits are `POST` actions: `/confirm`, `/reject`, `/archive`, `/restore`, `/export`.

### Methods and status codes

| Situation | Status |
|---|---|
| Read OK, update OK, action OK | `200` |
| Created | `201` with the new record in the body |
| Missing or invalid token | `401` |
| Signed in but not allowed (e.g. role) | `403` |
| Record does not exist, or belongs to another organisation | `404` |
| Conflict, e.g. duplicate | `409` |
| File too large | `413` |
| File type not supported | `415` |
| Validation failed | `422` |
| AI service or another dependency unavailable | `503` |

`PATCH` updates only the fields that are sent.

### Lists

List endpoints return an object, so paging can be added without breaking clients:

```json
{ "items": [ ... ] }
```

Optional query parameters where a list can grow: `limit` (default 50, max 200) and `offset` (default 0).

### Errors

Every error has the same shape:

```json
{
  "error": {
    "code": "not_found",
    "message": "Project not found"
  }
}
```

Validation errors add `details`:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": [
      { "field": "name", "message": "Project name is required" }
    ]
  }
}
```

Error codes: `bad_request`, `unauthenticated`, `forbidden`, `not_found`,
`method_not_allowed`, `conflict`, `payload_too_large`,
`unsupported_media_type`, `validation_error`, `ai_unavailable`,
`service_unavailable`, `internal_error`. `message` is safe to show to a user.

A `401` means the token is missing, invalid or expired, and the client should
send the user to sign in. A `503` with `service_unavailable` means the token
could not be checked right now, and the client should retry.

### AI output

Anything produced by AI is returned and stored as a suggestion. Each suggestion
includes a `confidence` between 0 and 1 and a human-readable `reason`.
Confirmation is a separate human action and a separate endpoint.

## 2. Endpoint index

State: **Planned** means agreed but not implemented. **Mock** means the web
prototype implements it in `apps/web/lib/api.ts` only. **Live** means FastAPI
serves it. The web app keeps using its mock function for a Live endpoint until
that screen is wired to the API.

### Platform (F01, F02)

| Method | Path | Purpose | State |
|---|---|---|---|
| GET | `/api/v1/health` | Liveness check, no auth | Live |
| GET | `/api/v1/me` | Signed-in profile and organisation | Live |
| PATCH | `/api/v1/me` | Update own `full_name` | Live |
| GET | `/api/v1/projects` | List the organisation's projects, newest first. Optional `?status=active\|archived`, `limit`, `offset` | Live |
| POST | `/api/v1/projects` | Create a project. Returns `201`. | Live |
| GET | `/api/v1/projects/{project_id}` | Get one project | Live |
| PATCH | `/api/v1/projects/{project_id}` | Edit a project | Live |
| POST | `/api/v1/projects/{project_id}/archive` | Archive. Safe to repeat. | Live |
| POST | `/api/v1/projects/{project_id}/restore` | Restore to active. Safe to repeat. | Live |

Sign up, sign in and sign out go straight from the browser to Supabase Auth, not through this API.

### Contracts and evidence (F03 to F07) — owner: Kinori

| Method | Path | Purpose | State |
|---|---|---|---|
| POST | `/api/v1/projects/{project_id}/contracts` | Upload a contract (PDF or DOCX) and start extraction. Returns `201`. | Live |
| GET | `/api/v1/projects/{project_id}/contracts` | List contracts with processing status, newest first | Live |
| GET | `/api/v1/contracts/{contract_id}` | Get one contract, including a signed download URL | Live |
| POST | `/api/v1/contracts/{contract_id}/extract` | Run extraction again after a failure | Live |
| GET | `/api/v1/contracts/{contract_id}/items` | List extracted contract items in schedule order | Live |
| PATCH | `/api/v1/contract-items/{item_id}` | Human edit of an extracted item | Mock |
| POST | `/api/v1/contract-items/{item_id}/confirm` | Human confirms an item | Mock |
| POST | `/api/v1/contract-items/{item_id}/reject` | Human rejects an item | Mock |
| POST | `/api/v1/projects/{project_id}/evidence` | Upload evidence (file and/or written note) with metadata | Mock |
| GET | `/api/v1/projects/{project_id}/evidence` | List evidence. Filters: `q`, `evidence_type`, `from`, `to`, `archived` | Mock |
| GET | `/api/v1/evidence/{evidence_id}` | Get one evidence record, including a signed URL | Mock |
| PATCH | `/api/v1/evidence/{evidence_id}` | Edit description, type, captured date, metadata, archived | Mock |

### Claim experience (F10 to F15, F17 to F19) — owner: Rehan

| Method | Path | Purpose | State |
|---|---|---|---|
| GET | `/api/v1/projects/{project_id}/claims` | List claims | Mock |
| GET | `/api/v1/claims/{claim_id}` | Get one claim | Mock |
| GET | `/api/v1/claims/{claim_id}/items` | Claim items | Mock |
| GET | `/api/v1/claims/{claim_id}/readiness` | Readiness summary | Mock |
| GET | `/api/v1/claims/{claim_id}/matches` | Evidence matches for the claim | Mock |
| POST | `/api/v1/evidence-matches/{match_id}/confirm` | Human confirms a match | Mock |
| POST | `/api/v1/evidence-matches/{match_id}/reject` | Human rejects a match | Mock |
| PATCH | `/api/v1/evidence-matches/{match_id}` | Human changes a match | Mock |
| POST | `/api/v1/claims/{claim_id}/export` | Generate the evidence package | Mock |
| GET | `/api/v1/projects/{project_id}/audit-events` | Audit trail | Mock |
| GET | `/api/v1/notifications` | Notifications for the signed-in user | Mock |
| PATCH | `/api/v1/notifications/{id}` | Mark read, unread or dismissed | Mock |

### AI service — owner: Arya

| Method | Path | Purpose | State |
|---|---|---|---|
| POST | `/ai/v1/contracts/{contract_id}/extract` | Contract to structured line items | Mock (`apps/web/lib/ai.ts`) |
| POST | `/ai/v1/evidence/{evidence_id}/understand` | OCR / vision / text to structured signals | Planned |
| POST | `/ai/v1/matches` | Evidence to contract item suggestions | Mock |
| POST | `/ai/v1/completeness` | Strong / partial / weak / missing per item | Mock |
| POST | `/ai/v1/variations/detect` | Flag potential variations | Mock |

Exact AI routes may change after team discussion. The input and output shapes in section 6 are what callers depend on.

## 3. Platform objects

### `GET /api/v1/health`

```json
{ "status": "ok", "service": "subpay-api", "version": "0.1.0", "environment": "development" }
```

### Organisation

```json
{
  "id": "0b6f3c1e-6d2f-4c0a-9d53-1f0f5a6f7a01",
  "name": "Kearney Formwork Pty Ltd",
  "created_at": "2026-09-01T02:00:00Z",
  "updated_at": "2026-09-01T02:00:00Z"
}
```

### Profile

```json
{
  "id": "7f1f5c58-2a4e-4b43-8a34-3f8a1f0c9b10",
  "organisation_id": "0b6f3c1e-6d2f-4c0a-9d53-1f0f5a6f7a01",
  "email": "ollie@kearneyformwork.test",
  "full_name": "Ollie Reid",
  "role": "owner",
  "created_at": "2026-09-01T02:00:00Z",
  "updated_at": "2026-09-01T02:00:00Z"
}
```

`id` is the Supabase Auth user id. `role` is `owner` or `member`.

### `GET /api/v1/me`

```json
{
  "profile": { "...": "Profile" },
  "organisation": { "...": "Organisation" }
}
```

`PATCH /api/v1/me` accepts `{ "full_name": "New Name" }` and returns the same shape.

A signed-in user who has no profile gets `403 forbidden` from `/me` and from
creating a project. This should not happen in normal use, because sign-up
creates the profile.

### Project

```json
{
  "id": "5a0d8a0e-2c9b-4a55-8a8e-0a2b9a6c1d22",
  "organisation_id": "0b6f3c1e-6d2f-4c0a-9d53-1f0f5a6f7a01",
  "name": "Hume St Tower",
  "client_name": "Bellrock Construction",
  "site_address": "118 Hume St, Melbourne VIC",
  "status": "active",
  "start_date": "2026-03-02",
  "end_date": null,
  "created_by": "7f1f5c58-2a4e-4b43-8a34-3f8a1f0c9b10",
  "created_at": "2026-09-01T02:05:00Z",
  "updated_at": "2026-09-01T02:05:00Z"
}
```

`status` is `active` or `archived`.

Create (`POST /api/v1/projects`) and edit (`PATCH /api/v1/projects/{project_id}`) accept:

| Field | Type | Rules |
|---|---|---|
| `name` | string | Required on create. 1 to 200 characters. |
| `client_name` | string | Required on create. 1 to 200 characters. |
| `site_address` | string | Optional. Defaults to `""`. |
| `start_date` | date or null | Optional. |
| `end_date` | date or null | Optional. Must not be before `start_date`. |

`id`, `organisation_id`, `created_by` and `status` are not accepted from the
client. If sent, they are ignored. Use `/archive` and `/restore` to change
status. Projects are archived, not deleted, so there is no `DELETE`.

A `PATCH` must include at least one editable field. `name`, `client_name` and
`site_address` cannot be set to `null`. `start_date` and `end_date` can, which
clears them. `site_address` is at most 500 characters.

`GET /api/v1/projects` returns `{ "items": [Project, ...] }`.

## 4. Contract and evidence objects

Field lists are in [database-schema.md](database-schema.md). Responses return
the table columns under the same names.

### Uploading a contract

`POST /api/v1/projects/{project_id}/contracts` takes `multipart/form-data`
with one part named `file`.

- PDF or DOCX, up to 25 MB. The type is judged from the file's contents and its extension, not from the `Content-Type` the browser sends.
- `415 unsupported_media_type` for anything else, `413 payload_too_large` over the limit, `422` for an empty or missing file, `404` when the project is not the caller's.
- The file is stored privately at `contracts/{project_id}/{contract_id}/original.<ext>`. The uploaded filename is kept for display only and is never used in the path.

The response is the new Contract with `processing_status: "processing"`.
Extraction runs after the response is sent. Poll
`GET /api/v1/contracts/{contract_id}` until the status is `ready` or `failed`.

```json
{
  "id": "c1d2e3f4-0000-4000-8000-000000000001",
  "project_id": "5a0d8a0e-2c9b-4a55-8a8e-0a2b9a6c1d22",
  "original_filename": "Subcontract_HumeSt_Formwork.pdf",
  "storage_path": "contracts/5a0d8a0e-.../c1d2e3f4-.../original.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 482113,
  "page_count": null,
  "processing_status": "processing",
  "error": null,
  "uploaded_by": "7f1f5c58-2a4e-4b43-8a34-3f8a1f0c9b10",
  "created_at": "2026-10-04T05:12:00Z",
  "updated_at": "2026-10-04T05:12:00Z",
  "processed_at": null
}
```

`GET /api/v1/contracts/{contract_id}` returns the same fields plus
`download_url`: a signed link to the stored document that expires after five
minutes. Ask for the contract again to get a fresh link.

`POST /api/v1/contracts/{contract_id}/extract` restarts extraction for a
contract that `failed`. It returns `409 conflict` when the contract is already
`ready` or is still `processing`. A contract stuck in `processing` for more
than ten minutes can be retried. Re-running never touches an item a person has
edited, confirmed or rejected.

`GET /api/v1/contracts/{contract_id}/items` returns `{ "items": [ContractItem] }`.
Every extracted item arrives as `review_status: "draft"` with
`extraction_confidence` and an `extracted_values` snapshot of the AI's answer.

- **Contract**: `processing_status` is `uploaded`, `processing`, `ready` or `failed`. A failed contract carries a user-safe `error` message.
- **ContractItem**: `review_status` is `draft`, `confirmed` or `rejected`. `extraction_confidence` is the AI's confidence, or `null` for an item a person added. Quantity, unit, rate, amount, conditions, notice requirement and due date are all nullable, because not every contract contains them.
- **Evidence**: `evidence_type` is `photo`, `document`, `docket`, `message` or `other`. `metadata` is a free-form object, for example `{ "location": null, "source": "mobile_upload", "tags": [] }`.

Upload limits for the MVP: contracts are PDF or DOCX up to 25 MB, evidence files up to 50 MB.

## 5. Match, claim and audit objects

### EvidenceMatch

One shared model. Do not create an alternative.

```json
{
  "id": "uuid",
  "evidence_id": "uuid",
  "contract_item_id": "uuid",
  "confidence": 0.91,
  "assessment": "strong",
  "reason": "Evidence indicates electrical conduit installation",
  "missing_evidence": ["quantity confirmation"],
  "status": "suggested",
  "source": "ai",
  "confirmed_by": null,
  "confirmed_at": null,
  "created_at": "2026-10-04T05:12:00Z",
  "updated_at": "2026-10-04T05:12:00Z"
}
```

- `assessment`: `strong`, `partial` or `weak`.
- `status`: `suggested`, `confirmed` or `rejected`. Only a human action moves it out of `suggested`.
- `source`: `ai` for a suggestion, `human` for a link a person created by hand.

Completeness per claim item is `strong`, `partial`, `weak` or `missing`.

Claim, ClaimItem, Variation, Notification and AuditEvent field lists are in
[database-schema.md](database-schema.md).

## 6. AI service interface (`/ai/v1`)

FastAPI calls these server to server. The browser never does.

### Contract extraction

`POST /ai/v1/contracts/{contract_id}/extract`. The API sends:

```json
{
  "contract_id": "uuid",
  "original_filename": "Subcontract_HumeSt_Formwork.pdf",
  "mime_type": "application/pdf",
  "document_url": "https://<project>.supabase.co/storage/v1/object/sign/contracts/...?token=..."
}
```

`document_url` is a short-lived signed link the AI service uses to fetch the
document. It expires after five minutes, so fetch it straight away. The AI
service answers:

```json
{
  "contract_id": "uuid",
  "items": [
    {
      "item_code": "4.2",
      "description": "Electrical conduit installation",
      "quantity": 120,
      "unit": "m",
      "rate": 45,
      "amount": 5400,
      "conditions": null,
      "notice_requirement": null,
      "due_date": null,
      "confidence": 0.91,
      "source_reference": "Schedule 2, p. 14"
    }
  ]
}
```

Only `item_code`, `description` and `confidence` are guaranteed. Everything
else may be `null` or left out. `confidence` is between 0 and 1, and
`contract_id` must match the request. An answer that breaks these rules is
treated as an AI outage.

The API side of this boundary is `services/api/app/ai/extraction.py`. Until the
AI service exists, a deterministic mock answers instead
(`AI_EXTRACTION_PROVIDER=mock`, the default). Setting
`AI_EXTRACTION_PROVIDER=http` makes the API call `AI_SERVICE_URL`. Nothing
else changes.

### Evidence matching

Input: one evidence record and the project's confirmed contract items.

```json
{
  "evidence_id": "uuid",
  "matches": [
    {
      "contract_item_id": "uuid",
      "confidence": 0.91,
      "assessment": "strong",
      "reason": "Evidence indicates electrical conduit installation",
      "missing_evidence": ["quantity confirmation"]
    }
  ]
}
```

An empty `matches` array is a valid answer.

### Potential variation

```json
{
  "potential_variation": true,
  "confidence": 0.72,
  "reason": "Describes work not found in the contract schedule",
  "related_evidence_ids": ["uuid"],
  "review_required": true
}
```

A flag is a prompt for human review. It is not a decision about entitlement.

### Failure

If the AI service cannot answer, it returns `503` with code `ai_unavailable`.
The caller marks the record `failed`, keeps the upload, and lets the user retry
or continue manually.
