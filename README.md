# SubPay — MVP prototype

> Verified progress claims, from site photo to payment.

A clickable, fully working **frontend prototype** of the SubPay MVP (F01–F20), styled from the Assessment 2b deck. It runs entirely in the browser: a mock service layer and a deterministic mock AI stand in for FastAPI, Supabase and Arya's AI services, using the same data shapes the team prompts agreed on.

## Repository

```
apps/web/            Next.js frontend (the working prototype described below)
services/api/        FastAPI application, /api/v1     (auth check, profile and project endpoints)
services/ai/         AI service, /ai/v1               (not built yet)
supabase/            Migrations, seed data and database checks
packages/contracts/  Shared API / type contracts
tests/integration/   Cross-service end-to-end tests
docs/                Architecture, API contracts, database schema, development guide
```

Start with [docs/development-guide.md](docs/development-guide.md). The shared
contracts every workstream builds against are in
[docs/api-contracts.md](docs/api-contracts.md) and
[docs/database-schema.md](docs/database-schema.md). What is built and what is
still mock is tracked in [docs/architecture.md](docs/architecture.md#7-current-state).

## Run it

```bash
cd apps/web
npm install
npm run dev        # http://localhost:3000
```

Click **Continue as demo user** (Ollie Reid, Kearney Formwork Pty Ltd). Any password works for seeded accounts. Data is saved in your browser's localStorage. To start over, go to **Profile & settings → Reset demo data**.

That is **demo mode**, the default. To use real Supabase sign-in and the API instead (**live mode**), copy `apps/web/.env.example` to `apps/web/.env.local`, fill it in, and follow [docs/development-guide.md](docs/development-guide.md).

Checks: `npm test` (Vitest), `npm run test:e2e` (Playwright), `npm run typecheck`, `npm run lint`, `npm run build`.

## Demo script (Hume St Tower, Claim #7)

1. **Dashboard**: shows the project, evidence support coverage and a "do these things first" list.
2. **Contract**: `Subcontract_HumeSt_Formwork.pdf` has been turned into a 12-line claim schedule. Two lines are AI drafts that need a human check. Upload any PDF/DOCX to watch the mock extraction run.
3. **Evidence**: library with search and type/date filters, plus two potential-variation flags. **Capture on site** is the phone flow: photo → "Which item is this?" → Add to claim.
4. **Review**: approve, reject or move the AI-suggested evidence for each line. Human decisions are styled differently from AI suggestions everywhere.
5. **Claims → Claim #7**: the readiness dashboard (coverage, strong/partial/weak/missing, variations, notice deadlines), the claim evidence summary and the evidence graph.
6. **Evidence package**: export to PDF (print view) or structured JSON.
7. **Audit trail**: every upload, AI action and human decision, newest first.
8. **Profile → Simulate AI outage**: extraction and matching fail gracefully, and manual review still works.

## Structure

```
apps/web/
  app/                      Next.js App Router pages (routes match the team prompts)
    login, signup, dashboard, profile
    projects/[projectId]/   overview · contracts · contracts/[id]/items · evidence · evidence/capture
                            review · claims · claims/[claimId] · claims/[claimId]/export · audit
  components/               shell (layout, nav, notifications), ui (shared primitives), projects, auth
  lib/
    types.ts                Entity shapes: organisations, profiles, projects, contracts, contract_items,
                            evidence, evidence_matches, claims, claim_items, variations, notifications, audit_events
    api.ts                  Mock service layer, one function per /api/v1 endpoint, with org-scoped access checks
    ai.ts                   Deterministic mock AI provider (extraction, matching, variation detection)
    seed.ts                 Hume St Tower demo data (fictional)
    store.ts                localStorage-backed store + React hook
```

## Swapping in the real backend

| Prototype | Replace with | Owner |
|---|---|---|
| `lib/store.ts` (localStorage) | Supabase Postgres + RLS | Jaden |
| `signIn` / `signUp` in `lib/api.ts` | Supabase Auth (JWT forwarded to FastAPI). **Done** in live mode: see `lib/auth.ts`. | Platform |
| project functions in `lib/api.ts` | `/api/v1/projects`. **Done** in live mode: see `lib/projects.ts`. | Platform |
| other `lib/api.ts` functions | `fetch` calls to the matching `/api/v1/...` endpoints, following `lib/projects.ts` | Kinori / Rehan |
| `lib/ai.ts` | `POST /ai/v1/...` calls (same input/output shapes) | Arya |
| `thumbnail` previews / file metadata | Supabase Storage with signed URLs | Kinori |

Pages read from the local store through `lib/api.ts`, and write through a small module per feature (`lib/auth.ts`, `lib/projects.ts`), so the swap is made one feature at a time.

## Prototype limits (deliberate)

- Uploaded files are not stored. Only their metadata is kept, plus a small preview for images.
- The mock AI uses keyword overlap. Its confidence values are placeholders, not calibrated scores.
- In demo mode auth is simulated, so no passwords are stored. "Organisation isolation" for mock data is enforced in `lib/api.ts`. In live mode Supabase Auth and database RLS do this for real.
- "Evidence support coverage" is the share of claimed value backed by strong, human-confirmed evidence. It is not a measure of claim validity or legal entitlement.
