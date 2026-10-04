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
    deps.py          CurrentUser dependency
    v1/
      router.py      Everything under /api/v1
      health.py      GET /api/v1/health
tests/
```

## Adding endpoints

1. Create `app/api/v1/<feature>.py` with an `APIRouter`.
2. Include it in `app/api/v1/router.py`.
3. Take `user: CurrentUser` on every endpoint that needs a signed-in user.
4. Raise errors with the helpers in `app/core/errors.py`.

```python
from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core import errors

router = APIRouter(tags=["contracts"])


@router.get("/contracts/{contract_id}")
def get_contract(contract_id: str, user: CurrentUser):
    # user.id is the verified Supabase user id.
    # user.access_token is forwarded to Supabase so Row Level Security applies.
    raise errors.not_found("Contract")
```

Rules, in full in [docs/api-contracts.md](../../docs/api-contracts.md):

- Identity comes from the verified token only. Never accept `user_id` or `organisation_id` from the client.
- A record in another organisation is a `404`, the same as one that does not exist.
- Every error uses `{ "error": { "code", "message" } }`.
