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

### In the web app

All authentication code is in `apps/web/lib/auth.ts`. Components call
`signIn`, `signUp`, `signOut` and `useAuth` from there and never talk to
Supabase directly.

- The Supabase browser client (`lib/supabase.ts`) is used for authentication only. It keeps the session in the browser and refreshes the token.
- After sign-in the app loads the profile and organisation from `GET /api/v1/me` (`lib/http.ts` adds the bearer token). If the API cannot be reached, the user is not let into the app.
- `components/shell.tsx` protects routes: until the saved session has been checked nobody counts as signed in, and signed-out visitors are sent to `/login`. This is a convenience for the user. The real protection is that the API and the database refuse requests without a valid token.
- A `401` from the API signs the user out.

Contracts follow it too, in `apps/web/lib/contracts.ts`. A project's contracts
and items are loaded when the project is opened (`lib/project-data.ts`), and
the screens wait for that first load. After an upload the app checks the
contract every 1.5 seconds until extraction is ready or has failed.

Evidence follows it in `apps/web/lib/evidence.ts`, loaded with the contracts
when a project is opened. Photo previews are signed links that expire after an
hour, so they are kept in memory only and never written to the browser's
storage; if one fails to load the app fetches fresh links. Matching evidence
to contract items is still mock data: in live mode it runs in the browser once
the API reports the evidence `ready`.

Projects follow the same shape in `apps/web/lib/projects.ts`: `createProject`,
`updateProject`, `setProjectStatus` and `refreshProjects`. In live mode the API
is the source of truth and the local store holds a copy of the organisation's
projects, loaded at sign-in and refreshed when the dashboard or project list
opens. Pages keep reading from the store, so they render without waiting, and
the features that still run on mock data can attach to real project ids. The
copy is removed from the browser at sign-out.

The web app has two modes, chosen by environment variables at build time:

| Mode | When | Behaviour |
|---|---|---|
| Live | `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` are set | Real Supabase Auth and the FastAPI service |
| Demo | They are empty | The original prototype: runs entirely in the browser with a simulated sign-in and seeded demo data. No network calls. |

Demo mode keeps the clickable prototype available for demos and for teammates
whose features still run on mock data.

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
- The API reaches the AI service through one interface per capability (`services/api/app/ai/`). Each has a deterministic mock, so every other workstream can build without the real model. Switching to the real service is a configuration change.
- Extraction runs in the API process after the upload response is sent, using the uploader's own access. That is enough for the MVP. A long-running model call belongs in a separate worker later.
- No confidential customer or project data goes to an external AI provider without permission and appropriate controls. Demo data is fictional.

## 6. File storage

- Private buckets: `contracts` and `evidence`.
- Project-scoped paths: `contracts/{project_id}/{contract_id}/original.<ext>` and `evidence/{project_id}/{evidence_id}/original.<ext>`.
- Files are opened through short-lived signed URLs issued after an access check. No public URLs.
- The database stores the path and metadata. The file bytes live in Storage, not in Postgres.
- The browser uploads to FastAPI, which checks the file and then stores it in Supabase Storage **as the signed-in user**, so the storage policies apply as well as the API's own checks.
- A file's type is decided from its contents, not from what the browser claims. The uploaded filename is kept for display and never used in a storage path.
- Uploaded files are immutable for users: no overwrite, rename or delete.
- Requests larger than 60 MB are refused before they are read.

## 7. Current state

Updated as each piece lands.

| Piece | State |
|---|---|
| Web UI for F01 to F20 | Prototype. Runs on a mock service layer (`apps/web/lib/api.ts`) with `localStorage` data and a mock AI (`apps/web/lib/ai.ts`). |
| Repository structure and shared docs | Done |
| Database migrations: organisations, profiles, projects, RLS | Done. Not yet applied to a shared Supabase project. |
| FastAPI foundation and `/api/v1/health` | Done: config, CORS, error format, Supabase token verification, health endpoint |
| Profile and project endpoints | Done. The web app uses them in live mode. |
| Supabase Auth in the web app | Done: sign up, sign in, sign out, session persistence, protected routes, profile from `/api/v1/me`. Demo mode keeps the simulated login. |
| Contracts and contract items | Done. Upload, list, download link, extraction (mock provider), retry, and human review (edit, confirm, reject, reopen). The contract and item review screens use the API in live mode. |
| Evidence | Done. Upload (file or written note), library with search and filters, signed previews and downloads, edit, archive and restore, AI processing status and retry. The evidence library and site capture screens use the API in live mode. |
| Matches, claims, readiness, export, audit, notifications | Not started. Mock only. |
| AI service | Not started. Mock only. |

### Moving from the prototype to the real backend

Each function in `apps/web/lib/api.ts` (the mock) maps to one endpoint in
[api-contracts.md](api-contracts.md). To move a feature onto the real backend,
follow what `lib/auth.ts` and `lib/projects.ts` do:

1. Create `lib/<feature>.ts` that exports the same operations as async functions.
2. In live mode (`LIVE` from `lib/env.ts`) call the API with `apiFetch` from `lib/http.ts` and write the result into the store. In demo mode call the existing mock function.
3. Change the screens to import from `lib/<feature>.ts` and to `await` the calls.
4. Add Vitest tests for both modes, as `lib/projects.test.ts` and `lib/projects.demo.test.ts` do.

Reads (`read.*` in `lib/api.ts`) do not change, because they read the store.
Entity shapes are in `apps/web/lib/types.ts` and match
[database-schema.md](database-schema.md).

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
| 8 | The web app keeps a demo mode with no backend. | Demos and mock-based features keep working while the real backend is built feature by feature. |
| 9 | The browser holds the Supabase session; routes are guarded in the client. | Every page is a client component that loads data with the user's token, so the API and RLS are the enforcement point. |

## 9. Open questions

- How a second person joins an existing organisation. The schema supports `member`, but there is no invite screen in the MVP. For now members are added through seed data. In live mode the profile page lists only the signed-in user, because there is no members endpoint yet.
- Which model provider the AI service uses, and what data controls apply. Owner: Arya.
- Whether shared TypeScript types are generated from the API's OpenAPI schema into `packages/contracts`.
