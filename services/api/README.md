# services/api

FastAPI application that serves `/api/v1`. Foundation owner: platform. Each
workstream adds its own routers.

## Run it

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

Without Supabase values the server still starts and `/health` works, but every
authenticated request is rejected.

## Checks

```bash
pytest
ruff check .
ruff format --check .
```

Tests never call Supabase. Tokens are signed in the tests with throwaway keys.

## Layout

```
app/
  main.py            create_app(): CORS, error handlers, routers
  core/
    config.py        Settings, read from environment variables or .env
    errors.py        ApiError and the single error shape
    security.py      Supabase access-token verification
  api/
    deps.py          CurrentUser, UserSupabase and Platform dependencies
    v1/
      router.py      Everything under /api/v1
      health.py      GET /api/v1/health
      me.py          GET, PATCH /api/v1/me
      projects.py    /api/v1/projects
      contracts.py   Contract upload, list, get, extraction retry, items
      evidence.py    Evidence upload, library, get, edit, archive, reprocess
  schemas/           Request and response shapes (Pydantic)
  db/
    supabase.py      SupabaseRest: data access as the signed-in user
    storage.py       SupabaseStorage: file upload and signed URLs as the signed-in user
  repositories/      One class per feature area, built on SupabaseRest
  services/          Workflows that combine repositories, storage and AI
    uploads.py       File checks shared by every upload
    contracts.py     Upload, store, extract, save items
    evidence.py      Upload, store, list with previews, edit, send for AI processing
  ai/
    extraction.py    The AI boundary: ExtractionProvider, mock and HTTP providers
    evidence.py      The AI boundary for evidence: EvidenceProcessor, mock and HTTP
tests/
  fakes.py           In-memory repositories and storage used by the endpoint tests
  files.py           Small valid sample files for upload tests
```

## Adding endpoints

`app/api/v1/projects.py` with `app/repositories/platform.py` is the worked
example to copy.

1. Put request and response shapes in `app/schemas/<feature>.py`.
2. Put data access in `app/repositories/<feature>.py`, built on `SupabaseRest`.
3. Create `app/api/v1/<feature>.py` with an `APIRouter` and include it in `app/api/v1/router.py`.
4. Raise errors with the helpers in `app/core/errors.py`.
5. Test the endpoints with an in-memory fake repository, as `tests/fakes.py` does.

```python
from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, UserSupabase
from app.core import errors

router = APIRouter(tags=["contracts"])


@router.get("/contracts/{contract_id}")
def get_contract(contract_id: UUID, user: CurrentUser, supabase: UserSupabase):
    # user.id is the verified Supabase user id.
    # supabase queries as that user, so Row Level Security hides other
    # organisations' rows. A hidden row and a missing row both come back empty.
    rows = supabase.select("contracts", {"id": f"eq.{contract_id}"}, limit=1)
    if not rows:
        raise errors.not_found("Contract")
    return rows[0]
```

`SupabaseRest` has `select`, `insert` and `update`. Filters use PostgREST
syntax: `{"status": "eq.active"}`. It never uses the service-role key.

Rules, in full in [docs/api-contracts.md](../../docs/api-contracts.md):

- Identity comes from the verified token only. Never accept `user_id` or `organisation_id` from the client.
- A record in another organisation is a `404`, the same as one that does not exist.
- Every error uses `{ "error": { "code", "message" } }`.
