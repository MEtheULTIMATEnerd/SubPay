# Development guide

Living document. Last updated: 2026-10-04.

How to set up, run, test and contribute to SubPay. Sections marked
**(coming)** describe pieces that are agreed but not in the repository yet.
They are updated in the same merge request that adds the piece.

## 1. Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Git | any recent | Everything |
| Node.js | 22.12 or newer (24 also works) | `apps/web` |
| npm | ships with Node | `apps/web` |
| Python | 3.10 or newer | `services/api`, `services/ai` |
| Supabase project | shared team project | Database, Auth, Storage |
| Supabase CLI | latest, run with `npx supabase` | Applying migrations |
| `psql` | any recent | Running the database checks (optional) |

## 2. Get the code

```bash
git clone https://git.infotech.monash.edu/fit3195/fit3195-s2-2026/DTE303.git
cd DTE303
git switch main
```

`main` is the integration branch. The repository also has an old `master`
branch that holds only the initial empty commit. Do not use it and do not merge
it into `main`.

## 3. Run the web app

```bash
cd apps/web
npm install
npm run dev          # http://localhost:3000
```

**Demo mode (default).** With no `.env.local`, the web app runs entirely in
the browser on mock data. Choose **Continue as demo user** on the login page.
Data is saved in `localStorage`. To start over, go to **Profile & settings →
Reset demo data**.

**Live mode.** Real sign-up and sign-in through Supabase, with the profile
loaded from the API:

```bash
cd apps/web
cp .env.example .env.local      # then fill in the Supabase URL and anon key
npm run dev
```

Live mode also needs the API running (section 4) and the migrations applied to
the Supabase project (section 6). Restart `npm run dev` after changing
`.env.local`.

In the Supabase dashboard, under Authentication:

- URL Configuration: set the Site URL to `http://localhost:3000` for local development.
- Sign-in providers > Email: with "Confirm email" on, a new user must click the emailed link before signing in, and the sign-up page says so. Turn it off for quicker local testing.

Sign-in, the profile, projects, contracts, contract item review and evidence
are live. Evidence matching, claims, the audit trail and notifications still
use mock data in the browser, in both modes. A new live account starts
with no projects, because the seeded demo project belongs to the demo
organisation.

## 4. Run the API

```bash
cd services/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # then fill in the Supabase values
uvicorn app.main:app --reload --port 8000
```

- Health check: http://localhost:8000/api/v1/health
- Interactive docs: http://localhost:8000/api/v1/docs

The server starts without Supabase values, and `/health` works, but every
authenticated request is rejected until `SUPABASE_URL` is set. Today the API
has the foundation only. Feature endpoints arrive with each workstream.

## 5. Environment variables

Real values go in untracked `.env` files. Only `.env.example` files, with
placeholder values, are committed. Never commit a real key.

**Web app (`apps/web/.env.local`)**, template in `apps/web/.env.example`

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL. Empty means demo mode. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Public (anon / publishable) key. Safe for the browser. Empty means demo mode. |
| `NEXT_PUBLIC_API_URL` | Base URL of the FastAPI service. Defaults to `http://localhost:8000`. |

**API (`services/api/.env`)**, template in `services/api/.env.example`

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Public key, used with the caller's JWT so RLS applies |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-only key that bypasses RLS. Never in the web app. |
| `SUPABASE_JWT_SECRET` | Only for projects that still sign JWTs with the legacy shared secret. Leave empty otherwise. |
| `CORS_ORIGINS` | Allowed web origins, e.g. `http://localhost:3000` |
| `AI_SERVICE_URL` | Base URL of the AI service |
| `AI_EXTRACTION_PROVIDER` | `mock` (default) uses the built-in deterministic extraction. `http` calls the AI service. |
| `AI_EVIDENCE_PROVIDER` | `mock` (default) marks evidence ready without an AI service. `http` calls the AI service for each record. |

Anything prefixed `NEXT_PUBLIC_` is shipped to the browser. The service-role
key must never have that prefix and must never appear under `apps/web`.

## 6. Database

### Apply migrations to the shared Supabase project

One person creates the Supabase project and shares the project reference and
database password with the team (not in Git). Then, from the repository root:

```bash
npx supabase login
npx supabase link --project-ref <project-ref>
npx supabase db push                  # applies migrations not yet applied
npx supabase db push --include-seed   # same, and also runs supabase/seed/*.sql
```

No CLI? Open the Supabase dashboard, go to the SQL editor, and run each file in
`supabase/migrations/` in filename order.

### Demo data

1. In the Supabase dashboard, go to Authentication > Users > Add user and create `ollie@kearneyformwork.test` with a password of your choice. Optionally also create `sam@othersubbie.test`, a second organisation used to show isolation.
2. Run `supabase/seed/001_demo_platform.sql` (with `--include-seed` above, or in the SQL editor).

Seed files never contain passwords. They are safe to run more than once.

### Check the security rules

```bash
psql "<database connection string>" -v ON_ERROR_STOP=1 -f supabase/tests/platform_foundation.sql
psql "<database connection string>" -v ON_ERROR_STOP=1 -f supabase/tests/contracts_and_evidence.sql
psql "<database connection string>" -v ON_ERROR_STOP=1 -f supabase/tests/storage_buckets.sql
```

Each ends with `<name>: all checks passed`. Any other ending is a failure. The
scripts run in a transaction that is rolled back, so they leave no data
behind. They can also be pasted into the SQL editor, where "no error" means
they passed.

### Run Supabase locally (optional, needs Docker)

```bash
npx supabase start       # local Postgres, Auth and Storage
npx supabase db reset    # rebuild from migrations, then run the seed files
```

### Making a database change

1. Add a new file in `supabase/migrations/` named `<YYYYMMDDHHMMSS>_<short_name>.sql`.
2. Follow the conventions in [database-schema.md](database-schema.md): UUID keys, timestamps, foreign keys, indexes, explicit grants, RLS enabled in the same file.
3. Add or extend a checks file in `supabase/tests/`.
4. Update `database-schema.md` in the same merge request.
5. Never edit a merged migration. Add a new one.

## 7. Checks

Run these before opening a merge request. All of them must pass.

**Web (`apps/web`)**

```bash
npm run lint
npm run build        # also generates the route types that typecheck needs
npm run typecheck
npm test             # Vitest unit tests
npm run test:e2e     # Playwright browser tests, desktop and phone-sized
```

The browser tests need a one-off `npx playwright install chromium`. They build
the app and run it in demo mode on port 3100, so they need no Supabase project
and no API, and they ignore your `.env.local`.

On a fresh clone, run `npm run build` (or `npm run dev` once) before
`npm run typecheck`. Next.js generates route types such as `LayoutProps` at
that point, and typecheck fails without them.

**API (`services/api`, with the virtual environment active)**

```bash
pytest
ruff check .
ruff format --check .
```

New screens add their own Playwright tests under `apps/web/e2e/`, in files
named `*.e2e.ts`.

## 8. Git workflow

### Branches

Never commit directly to `main`. Work on a branch and merge through a merge request.

| Prefix | Use | Example |
|---|---|---|
| `feature/` | New product capability | `feature/contract-management` |
| `fix/` | Bug fix | `fix/project-date-validation` |
| `chore/` | Tooling, structure, docs, config | `chore/platform-foundation` |

Agreed branch names by workstream:

| Workstream | Branches |
|---|---|
| Platform | `chore/platform-foundation`, `feature/auth-platform`, `feature/project-management` |
| Data | `feature/contracts-and-evidence` |
| AI | chosen by Arya, under `feature/` |
| Claim experience | chosen by Rehan, under `feature/` |

### Commits

- Small, focused and reviewable. One logical change per commit.
- Title in the imperative, under about 70 characters: `Add project archive endpoint`.
- Body explains what changed and why, when the title is not enough.

### Before opening a merge request

1. Pull the latest `main` and rebase or merge it into your branch.
2. Run tests.
3. Run type checking.
4. Run linting.
5. Run the build.
6. Review your own changed files.
7. Explain any migration changes.
8. Confirm no other developer's files were changed unnecessarily.

### Merge request description

- Summary of the change
- Files or areas changed
- Database migrations, if any, and what they do
- Tests added or updated
- Integration notes for teammates (new endpoints, changed shapes, new env vars)

At least one teammate reviews before merging.

## 9. Team rules

- Organise by application and feature, not by person.
- Agree API contracts and database schemas before building in parallel. They live in [api-contracts.md](api-contracts.md) and [database-schema.md](database-schema.md).
- Do not change another teammate's core interface or data contract without agreement.
- Every feature needs acceptance criteria and relevant tests.
- Use seeded, fictional demo data for repeatable integration testing.
- AI results include confidence and reasoning sufficient for human review.
- Human confirmation is required before an AI suggestion becomes authoritative.
- Do not send confidential customer or project data to external AI services without permission and appropriate controls.
- Do not expose secrets. The service-role key stays on the server.

## 10. Where things are documented

| Question | Document |
|---|---|
| How the system fits together | [architecture.md](architecture.md) |
| Endpoints, request and response shapes, error format | [api-contracts.md](api-contracts.md) |
| Tables, columns, RLS, migration rules | [database-schema.md](database-schema.md) |
| Setup, checks, Git workflow | this file |
