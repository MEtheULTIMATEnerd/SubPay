# SubPay — MVP prototype

> Evidence support for progress claims, with human review.

A **deterministic frontend MVP demo** for FIT3195 Assessment 3. The complete
demonstration workflow runs in the browser using fictional seed data,
localStorage and simulated AI behaviour. It is not a verified live deployment.
The protected frontend checkpoint is `707a63ea6bc79999ce6bdb2609f46070ed5b7f3b`
on `feature/claim-experience`; ensure the supplied checkout contains that checkpoint.

## Run the FIT3195 MVP Demo

1. **Prerequisites:** Git to obtain the submitted repository, Node.js 22.12 or
   newer (Node.js 24 also works), npm and a modern browser. Internet access is
   needed to download npm dependencies. Python, Docker, Supabase, FastAPI and
   external AI API keys are **not required for deterministic demo mode**.
2. From the repository root, install the frontend dependencies and start Next.js:

   ```bash
   cd apps/web
   npm install
   npm run dev -- --webpack --port 3101
   ```

3. Open [http://localhost:3101](http://localhost:3101) after the server reports
   ready. Keep the terminal running while using the demo.
4. On the login page, select **Continue as demo user**. This uses the fictional
   Ollie Reid account at Kearney Formwork Pty Ltd; no real account or password
   is needed.
5. To restore the fictional starting state, open **Profile & settings**, select
   **Reset demo data**, and confirm. This discards changes made in this browser's
   demo store. Use the same browser and origin to retain demo progress.
6. To stop the server, press **Ctrl+C** in its terminal.

**Keep demo mode enabled:** a fresh clone needs no environment file. Leave
`NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` unset or empty,
including in the launching shell. The app selects live mode when both are
populated; `NEXT_PUBLIC_API_URL` alone does not enable it. Do not configure
Supabase or run database migrations to follow this demo.

## Repository

```
apps/web/            Next.js frontend (the working prototype described below)
services/api/        FastAPI application, /api/v1     (auth, profile, projects, contract upload and extraction)
services/ai/         FastAPI AI service, /ai/v1; mock services and optional hosted vision adapters
supabase/            Migrations, seed data and database checks
packages/contracts/  Shared API / type contracts
tests/integration/   Cross-service test intent (currently documentation)
docs/                Architecture, API contracts, database schema, development guide
```

Start with [docs/development-guide.md](docs/development-guide.md). The shared
contracts every workstream builds against are in
[docs/api-contracts.md](docs/api-contracts.md) and
[docs/database-schema.md](docs/database-schema.md). What is built and what is
still mock is also discussed in [docs/architecture.md](docs/architecture.md#7-current-state).
Some supporting documents describe earlier phases; the demo instructions and
limitations in this README describe the submitted frontend workflow.

## Frontend Checks

Run from `apps/web`: `npm test` (Vitest), `npm run lint`, `npm run build`,
`npm run typecheck`, and optionally `npm run test:e2e` (Playwright). On a fresh
clone, run the build or development server before typecheck so Next.js generates
its route types. Browser tests need Playwright Chromium installed separately;
see [the development guide](docs/development-guide.md#7-checks). No checks need
to be run merely to explore the demo.

## Demo script (Hume St Tower, Claim #7)

1. **Demo login and project:** select Continue as demo user, then choose
   **Hume St Tower** from the dashboard. Claim #7 and its evidence are fictional.
2. **Simulated contract extraction:** open Contract. The existing 12-line schedule
   is seeded data, not the result of reading a real PDF. Upload a PDF/DOCX to
   demonstrate simulated processing: a filename selects one of two fixed schedules.
3. **Contract item review:** open Review items, inspect a draft, edit if needed,
   and Save & confirm. Matching uses human-confirmed contract items.
4. **Evidence upload:** add a photo or written evidence note with a descriptive
   title and description. For example, use `Formwork slab soffit L3 complete`
   to demonstrate keyword matching. The browser does not analyse image pixels.
5. **Deterministic matching:** Upload & match simulates processing and produces
   suggestions from text overlap. Open Review to inspect reasoning and gaps.
6. **Human decisions:** Confirm or Reject a suggestion; Reopen a reviewed link
   to return it to suggested status. Rejected links are available in the rejected
   suggestions section. Decisions persist locally across page reloads.
7. **Readiness and gaps:** open Claims, then Claim #7. Inspect strong, partial,
   weak and missing support, outstanding suggestions and evidence gaps. Only
   confirmed links count as approved support; reopening removes that approval.
8. **Draft package:** open Evidence package and download structured JSON or use
   Export claim pack (PDF) to open browser printing, where PDF saving depends on
   the browser. The draft includes approved evidence references and metadata,
   not original source files. Unreviewed suggestions are not approved support.
9. **Audit trail:** inspect locally persisted review decisions and download/print
   initiation events. Seeded examples are labelled. A print event does not prove
   a PDF was saved; this browser history is not tamper-proof.

Optional: Profile & settings includes a simulated AI outage control for showing
manual-review fallback. All inference in this browser walkthrough is simulated.

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

## AI Architecture

- **Browser demo:** `apps/web/lib/ai.ts` provides simulated extraction,
  deterministic text matching and rule-based potential-variation flags. It does
  not call a hosted model or perform live vision inference. Confidence values
  are placeholder heuristics, not calibrated probabilities.
- **Optional AI service:** `services/ai` exposes `/ai/v1` through FastAPI.
  `app/providers/base.py` defines provider protocols; `openai.py` and
  `openrouter.py` implement configurable hosted vision adapters alongside mocks.
  The default model identifiers are `gpt-4o-mini` for OpenAI and
  `openai/gpt-4o-mini` for OpenRouter. These use a pretrained model to request
  construction-relevant visual observations; they are not part of the browser demo.
- **Deterministic service rules:** matching uses token overlap and returns up to
  three suggestions. Completeness and variation detection are rule-based, not
  trained classifiers. Service matching and browser demo matching have different
  thresholds and inputs; they are not identical implementations.
- **Training and validation:** SubPay has not trained or fine-tuned a custom
  model. Fictional seed data and test fixtures are not training data. Automated
  software tests do not establish real-world AI accuracy, precision or recall;
  no such performance metrics have been established.
- **Human review:** suggestions require review, and only human-confirmed links
  count as approved support in demo readiness and exports. Confirmation of a link
  does not certify that the work satisfies a contractual requirement.

AI configuration is described by `services/ai/.env.example`; mock vision needs
no external key. Real provider keys are server-only and are unnecessary for
assessment demo setup. `services/ai/README.md` describes the earlier foundation
phase and has not yet been updated for the optional hosted vision adapters.

## Live Integration Status

Frontend adapters exist for Supabase Auth, profiles, members, projects, contracts,
evidence and match review. Application data is intended to flow through FastAPI;
the browser Supabase client handles authentication. See `apps/web/lib/auth.ts`,
`projects.ts`, `contracts.ts`, `evidence.ts` and `matches.ts`.

**Live database integration is unverified.** The deterministic walkthrough does
not demonstrate an authenticated database-backed deployment. Live claims,
readiness, export and audit are incomplete and unavailable in their frontend
views; notifications remain locally simulated. Backend and migration setup is
separate development work, not a prerequisite for this assessment demo. Do not
apply migrations to an unknown project merely to run the frontend.

## Limitations and Review Safeguards

- Contract extraction uses simulated schedules selected by filename; uploaded
  PDF/DOCX contents are not actually extracted in the current mock implementation.
- Demo records and decisions are stored locally in browser localStorage, not in
  a shared database. Clearing browser data or resetting the demo loses changes.
- Original uploaded files are **not durably retained in demo mode**. Metadata
  and small image previews may be retained; exports do not bundle original files.
  Use fictional or non-sensitive uploads for the demonstration.
- The generated evidence-support package is a **draft for human review**, not
  a certified claim or proof of contractual compliance. SubPay does not determine
  legal entitlement, guarantee payment, certify claims or submit them automatically.
- Evidence support coverage is the rounded share of claimed value with strong,
  human-confirmed support. It is neither model accuracy nor claim validity.
- AI suggestions, possible variations and notice flags require human checking.
  Local audit history records demo activity, not a tamper-proof legal record.
