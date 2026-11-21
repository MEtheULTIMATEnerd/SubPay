# SubPay — MVP prototype

> Evidence support for progress claims, with human review.

A **deterministic frontend MVP demo** for FIT3195 Assessment 3. The complete
demonstration workflow runs in the browser using fictional seed data,
localStorage and simulated AI behaviour. It is not a verified live deployment.
The submitted public source is maintained on the `master` branch of the
repository linked below.

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

## Running the Integrated SubPay MVP

This is the local, three-service workflow for tutor evaluation. It is separate
from the deterministic browser demo above and does not require Supabase,
Docker, database migrations or public deployment.

The complete integrated MVP is on the `master` branch of the public repository:

```text
https://github.com/MEtheULTIMATEnerd/SubPay
```

### Prerequisites

- Git.
- Node.js 22.12 or newer (Node.js 24 also works) and npm.
- Python 3.10 or newer.
- A modern browser.
- Internet access to install dependencies and, only for genuine analysis, to
  call the selected AI provider.

The integrated workflow uses SQLite and private local files under
`services/api/.local-data`. It is a single-user localhost prototype, not
production authentication or a multi-user deployment.

### Install dependencies

Run these commands from the repository root after cloning:

```bash
cd apps/web
npm install

cd ../../services/api
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

cd ../ai
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

cd ../..
```

On Windows, create each environment with `py -3 -m venv .venv` and use
`.venv\Scripts\python.exe -m pip install -r requirements.txt` from the
corresponding service directory. The commands below use macOS/Linux syntax;
PowerShell uses `$env:NAME="value"` instead of `export NAME=value` and
`.venv\Scripts\python.exe` instead of `.venv/bin/python`.

### Environment variables and credentials

The local integrated path does not use the Supabase variables. Leave
`NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` unset or empty.
Never put a private token or provider key in a `NEXT_PUBLIC_*` variable.

API terminal variables (`services/api`):

| Variable | Required | Purpose |
|---|---|---|
| `SUBPAY_LOCAL_ENABLED=true` | Yes | Enables the `/api/v1/integrated` SQLite application; it is disabled by default. |
| `SUBPAY_LOCAL_ACCESS_TOKEN` | Yes | A private ASCII bearer token of at least 32 characters. Generate one with the command below and use the same value in the AI terminal. |
| `SUBPAY_LOCAL_VISION_PROVIDER=mock` or `openai` | Yes | `mock` is the safe default and makes no provider request. Use `openai` for genuine image analysis. |
| `SUBPAY_LOCAL_VISION_MODEL=gpt-4o-mini` | For OpenAI | Must match the AI service model for provenance validation. |
| `SUBPAY_LOCAL_DATA_DIR` | Optional | Private alternative to the default `services/api/.local-data`; do not point it at a shared or committed directory. |

AI terminal variables (`services/ai`):

| Variable | Required | Purpose |
|---|---|---|
| `AI_LOCAL_VISION_ENABLED=true` | For OpenAI | Enables the authenticated loopback bridge at `/ai/v1/local/vision`. |
| `AI_LOCAL_ACCESS_TOKEN` | For OpenAI | Must equal `SUBPAY_LOCAL_ACCESS_TOKEN`; it authenticates the API-to-AI loopback call. |
| `AI_VISION_PROVIDER=openai` | For OpenAI | Explicitly selects the OpenAI provider. `mock` is the default for non-paid checks. |
| `AI_OPENAI_API_KEY` | For OpenAI | Server-only OpenAI credential. Obtain it from [OpenAI API keys](https://platform.openai.com/api-keys). |
| `AI_OPENAI_MODEL=gpt-4o-mini` | For OpenAI | The vision model used by the AI service. |
| `AI_OPENAI_BASE_URL` | Optional | Defaults to `https://api.openai.com/v1`. |
| `AI_VISION_TIMEOUT_SECONDS` | Optional | Defaults to `30.0`. |

OpenAI API usage may incur charges. Do not use a real key in this README, in
the frontend, in a committed `.env` file or in browser storage. Configure the
key only in the AI service process or an ignored `services/ai/.env` based on
`services/ai/.env.example`. A fresh clone can run mock mode without an OpenAI
key. Genuine analysis requires a valid key, explicit browser confirmation and
an approved image.

The frontend terminal uses one additional server-side flag:

```text
SUBPAY_INTEGRATED_UI_ENABLED=true
```

This enables the restricted same-origin Next.js bridge. `NEXT_PUBLIC_API_URL`
is not needed by `/integrated`; the bridge forwards to the fixed loopback API
at `127.0.0.1:8000`. The Supabase variables and `NEXT_PUBLIC_API_URL` in
`apps/web/.env.example` are for the separate demo/live adapters.

### Start the three services

Generate a private token once in the API terminal. Keep it out of source,
URLs, committed files and browser storage:

```bash
export SUBPAY_LOCAL_ACCESS_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Terminal 1 — AI service (required for genuine OpenAI analysis; omit this
terminal for mock mode):

```bash
cd services/ai
export AI_LOCAL_VISION_ENABLED=true
export AI_LOCAL_ACCESS_TOKEN="<paste the same private token>"
export AI_VISION_PROVIDER=openai
export AI_OPENAI_API_KEY="<your OpenAI API key>"
export AI_OPENAI_MODEL=gpt-4o-mini
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-proxy-headers
```

Terminal 2 — FastAPI backend:

```bash
cd services/api
export SUBPAY_LOCAL_ENABLED=true
export SUBPAY_LOCAL_ACCESS_TOKEN="<the same private token>"
export SUBPAY_LOCAL_VISION_PROVIDER=openai
export SUBPAY_LOCAL_VISION_MODEL=gpt-4o-mini
.venv/bin/python -m app.run_local
```

The API listens only on `127.0.0.1:8000`. For a no-charge plumbing check,
set `SUBPAY_LOCAL_VISION_PROVIDER=mock` and do not start the AI service; mock
observations are labelled and cannot produce real-evidence matches.

Terminal 3 — Next.js frontend:

```bash
cd apps/web
SUBPAY_INTEGRATED_UI_ENABLED=true npm run dev -- --webpack --hostname 127.0.0.1 --port 3101
```

Open [http://127.0.0.1:3101/integrated](http://127.0.0.1:3101/integrated).
Enter the same private token in the Local access form. If port 3101 is
occupied, use `--port 3102` and open
[http://127.0.0.1:3102/integrated](http://127.0.0.1:3102/integrated). The
bridge permits only ports 3101 and 3102 and the API remains fixed at port
8000. Stop each service with Ctrl+C. Do not bind these services to a public
interface or expose them through a tunnel.

### Complete integrated workflow

1. Connect with the configured local bearer token and create a construction
   project.
2. Upload a text-bearing PDF or DOCX contract. The backend extracts supported
   text and numbered/table-row candidate items. Scanned PDFs have no OCR and
   may produce no candidates.
3. Select the contract, inspect the extracted text and items, edit draft
   descriptions where needed, then explicitly confirm the relevant items.
   Reject clauses that are not claim lines. A contract or item can also be
   permanently deleted from the interface; deletion removes its related items,
   match suggestions and stored original.
4. Upload a JPEG, PNG or single-frame WEBP construction photograph. Uploading
   does not analyse the image.
5. Select **Analyse with AI**, read the confirmation dialog and approve one
   non-sensitive image only when a genuine provider request is intended. The
   request uses the configured OpenAI service and may incur a charge.
6. Review the persisted observations, provider/model provenance and processing
   status. Empty results are valid; mock results are explicitly marked and are
   not genuine image understanding.
7. Select **Generate Match Suggestions**. Matching uses the deterministic
   `construction-lexical-v1` relevance method and makes no additional AI call.
8. Review the supporting observation text and explanation, then explicitly
   confirm, reject or reopen each suggestion. Only current, human-confirmed
   matches are eligible support.
9. Download the draft claim-support package as JSON or HTML. Use the browser's
   Print command for the print-friendly HTML report if a PDF copy is needed.

### Important limitations

- AI observations describe visible signals; they do not certify construction
  completion, specification compliance or payment entitlement.
- Matching scores are explainable relevance heuristics, not confidence scores,
  completion percentages, compliance decisions or payment percentages.
- Human confirmation is required for contract items and evidence matches.
- Exports are draft evidence-support packages, not payment certifications,
  invoices, legal claims or approvals.
- Mock observations are clearly labelled and are not equivalent to genuine
  OpenAI observations or eligible real-evidence matching.
- Fresh genuine analysis requires a valid server-side OpenAI key, the AI
  service, the shared local token and explicit browser approval. No request is
  made during startup, upload, refresh or match generation.
- Matching is lexical and has limited vocabulary; it does not assess location,
  quantity, completion percentage or compliance.
- Local authentication is one shared development bearer token, not production
  identity or multi-user access control. Keep uploaded files non-sensitive.

### Troubleshooting

- **Missing/invalid OpenAI key:** confirm `AI_VISION_PROVIDER=openai`, set
  `AI_OPENAI_API_KEY` in the AI process only, and restart the AI service. Never
  place it in the browser or a `NEXT_PUBLIC_*` variable.
- **Authentication failed:** confirm the token is at least 32 ASCII characters
  and exactly the same in the API, AI service and browser form. Reconnect after
  changing it; reload clears the browser's in-memory token.
- **Backend unavailable:** confirm Terminal 2 is running on
  `127.0.0.1:8000`, `SUBPAY_LOCAL_ENABLED=true` is set, and the frontend is
  using port 3101 or 3102.
- **AI service unavailable:** for genuine analysis, confirm Terminal 1 is on
  `127.0.0.1:8001`, the shared token is set, and
  `AI_LOCAL_VISION_ENABLED=true`. Mock mode does not need this service.
- **Port conflict:** stop the process using 3101/3102, or start Next.js on the
  other permitted port and open the matching URL. The API and AI ports are
  fixed at 8000 and 8001 for this bridge.
- **Missing dependencies:** recreate the relevant Python `.venv` and install
  its `requirements.txt`; run `npm install` again from `apps/web`.
- **Unsupported file:** contracts must be PDF or DOCX, and evidence must be
  JPEG, PNG or single-frame WEBP within the documented size limits.
- **Empty extraction:** the document may be scanned, encrypted, malformed,
  non-numbered or too complex. OCR is not implemented; add or edit items
  manually outside the current integrated page if necessary.
- **No match suggestions:** confirm contract items, use the newest genuine
  non-mock analysis, and ensure its observations share specific construction
  terms with the item description. Rejected, stale, empty and mock analyses
  cannot produce eligible suggestions.
- **Export failed:** confirm the API is running, the token is valid, and the
  project still has its records. Refresh after changing review decisions and
  generate the package again.

For the detailed endpoint, storage and security contract, see
[apps/web/INTEGRATED.md](apps/web/INTEGRATED.md) and
[services/api/LOCAL_INTEGRATION.md](services/api/LOCAL_INTEGRATION.md).

The deterministic demo remains a separate browser-only experience using
fictional data and simulated AI. Its instructions and limitations below do
not describe the local SQLite workflow.

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
