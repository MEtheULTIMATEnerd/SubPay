# SubPay architecture

Living document. Last updated: 2026-10-04.

SubPay is a subcontractor-first claim protection platform. It answers one question:

> "Before I submit my progress claim, do I have sufficient evidence supporting what I'm claiming?"

AI recommends and explains. A human confirms. SubPay never decides legal
entitlement, specification compliance or adjudication outcomes, and never
submits a claim on its own.

## 1. System overview

```
Browser: Next.js app (apps/web)
  |
  |  1. sign up / sign in / sign out
  +----------------------------------------> Supabase Auth
  |  <--- session (JWT access token) -------
  |
  |  2. /api/v1/*   Authorization: Bearer <JWT>
  +----------------------------------------> FastAPI (services/api)
                                               |
                                               |  verifies the JWT, derives user + organisation
                                               |
                                               |  3. reads/writes as that user (RLS applies)
                                               +-------> Supabase Postgres (+ pgvector)
                                               +-------> Supabase Storage (private buckets, signed URLs)
                                               |
                                               |  4. server to server
                                               +-------> AI service (services/ai, /ai/v1/*)
```

| Component | Tech | Responsibility | Owner |
|---|---|---|---|
| Web app | Next.js (App Router), React, TypeScript, Tailwind CSS | All screens. Talks to Supabase Auth for sign-in and to FastAPI for data. | Platform shell: Jaden. Feature screens: each feature owner. |
| API | Python, FastAPI | `/api/v1`. Validates identity, applies business rules, owns workflow state. | Foundation: platform. Routers: each feature owner. |
| AI service | Python, FastAPI | `/ai/v1`. Extraction, evidence understanding, matching, completeness, variation detection. | Arya |
| Database | Supabase PostgreSQL, pgvector | System of record. Row Level Security on every table. | Foundation: platform. Tables: each feature owner. |
| Auth | Supabase Auth | Credentials, sessions, JWTs. SubPay never stores passwords. | Platform |
| Storage | Supabase Storage | Contract and evidence files in private buckets. | Kinori |

## 2. Repository structure

```
apps/
  web/                 Next.js frontend
services/
  api/                 FastAPI application (/api/v1)
  ai/                  AI / ML service (/ai/v1)
supabase/
  migrations/          SQL migrations, run in filename order
  seed/                Fictional demo data
packages/
  contracts/           Shared API / type contracts
tests/
  integration/         Cross-service end-to-end tests
docs/                  This folder
```

The repository is organised by application and feature, not by person. Do not
reorganise it without team agreement.

## 3. Authentication and identity

1. The browser signs in with Supabase Auth using the public (anon / publishable) key. Supabase returns a session containing a JWT access token.
2. Every request to FastAPI sends `Authorization: Bearer <access token>`.
3. FastAPI verifies the token signature and expiry, then reads the user id from the token's `sub` claim.
4. The user's `profiles` row gives their `organisation_id` and `role`.

Rules that every endpoint follows:

- Identity comes from the verified token only. A `user_id` or `organisation_id` in a request body or query string is never trusted, and clients are never asked to send one.
- A record in another organisation is reported as `404 Not Found`, the same as a record that does not exist.
- The Supabase service-role key exists only on the server. It never appears in `apps/web` or in any `NEXT_PUBLIC_*` variable.

Roles for the MVP: `owner` and `member`. No finer-grained permissions.

## 4. Data access and isolation

Tenant boundary: the **organisation** (the subcontractor business).

```
organisation 1---* profiles
organisation 1---* projects 1---* contracts 1---* contract_items
                            1---* evidence
                            1---* claims    1---* claim_items
                            1---* variations
              evidence *---* contract_items   (through evidence_matches)
```

Two layers enforce isolation, and both must hold:

1. **Row Level Security in Postgres.** Every table has RLS enabled. Policies allow access only to rows belonging to the caller's organisation, directly (`organisation_id`) or through the parent project.
2. **FastAPI acts as the caller.** For user requests the API queries Supabase with the caller's own JWT, so RLS applies to everything it does. The service-role key (which bypasses RLS) is used only for deliberate server-side work, such as a background AI job writing results, and each use must re-check project ownership in code.

## 5. AI boundary

```
Contract  -> document extraction        -> structured contract schedule
Evidence  -> vision / OCR / text        -> structured evidence signals
Evidence + schedule -> semantic matching -> LLM reasoning -> evidence assessment
AI suggestions -> human confirmation -> claim readiness -> evidence package
```

- The browser never calls the AI service directly. FastAPI calls it and stores the result.
- AI output is always stored as a suggestion (`review_status = draft`, `status = suggested`). Only a human action changes it to confirmed or rejected.
- AI results carry a confidence and a reason so a person can review them.
- If the AI service is down, uploads and manual linking still work. Processing is marked `failed` and can be retried.
- No confidential customer or project data goes to an external AI provider without permission and appropriate controls. Demo data is fictional.

## 6. File storage

- Private buckets: `contracts` and `evidence`.
- Project-scoped paths: `contracts/{project_id}/{contract_id}/original.<ext>` and `evidence/{project_id}/{evidence_id}/original.<ext>`.
- Files are opened through short-lived signed URLs issued after an access check. No public URLs.
- The database stores the path and metadata. The file bytes live in Storage, not in Postgres.

## 7. Current state

Updated as each piece lands.

| Piece | State |
|---|---|
| Web UI for F01 to F20 | Prototype. Runs on a mock service layer (`apps/web/lib/api.ts`) with `localStorage` data and a mock AI (`apps/web/lib/ai.ts`). |
| Repository structure and shared docs | Done |
| Database migrations: organisations, profiles, projects, RLS | Done. Not yet applied to a shared Supabase project. |
| FastAPI foundation and `/api/v1/health` | Done: config, CORS, error format, Supabase token verification, health endpoint |
| Profile and project endpoints | Done in the API. The web app still uses its mock for them. |
| Supabase Auth in the web app | Not started. Login is simulated. |
| Contracts, contract items, evidence, storage | Not started. Mock only. |
| Matches, claims, readiness, export, audit, notifications | Not started. Mock only. |
| AI service | Not started. Mock only. |

### Moving from the prototype to the real backend

Pages only call `apps/web/lib/api.ts`. Each function in that file maps to one
endpoint in [api-contracts.md](api-contracts.md). Replacing a mock function
with a `fetch` call to its endpoint moves that feature onto the real backend
without changing the screens. Entity shapes are in `apps/web/lib/types.ts` and
match [database-schema.md](database-schema.md).

## 8. Decisions

| # | Decision | Why |
|---|---|---|
| 1 | Supabase Auth issues identity. FastAPI only verifies tokens. | One authentication system, no password handling in our code. |
| 2 | FastAPI queries Supabase with the caller's JWT. | RLS stays the last line of defence even if an endpoint has a bug. |
| 3 | The organisation is the tenant boundary. Projects, and everything under them, inherit it. | Matches how subcontractors work: one business, many projects. |
| 4 | Cross-organisation access returns 404, not 403. | Does not reveal that a record exists. |
| 5 | Status values are `text` with `check` constraints, not Postgres enums. | Easier to extend in a later migration. |
| 6 | Human confirmation is workflow state in the application, never set by the AI service. | Keeps "AI suggested" and "human confirmed" clearly separate. |
| 7 | Responsive web app / PWA, no native mobile app. | In MVP scope. |

## 9. Open questions

- How a second person joins an existing organisation. The schema supports `member`, but there is no invite screen in the MVP. For now members are added through seed data.
- Which model provider the AI service uses, and what data controls apply. Owner: Arya.
- Whether shared TypeScript types are generated from the API's OpenAPI schema into `packages/contracts`.
