# services/ai

AI / intelligence service for SubPay. Owner: Arya.

This service serves `/ai/v1` and owns the model-facing side of:

- contract / claim schedule extraction
- evidence understanding
- evidence-to-contract matching
- evidence support completeness assessment
- potential variation detection

The browser never calls this service directly. The application API
(`services/api`) calls it server-to-server and remains responsible for storage,
workflow state, human review, and database writes.

## Current Phase

Phase A foundation is implemented here:

- FastAPI app in `app/main.py`
- `/ai/v1` routes in `app/api/v1/router.py`
- Pydantic schemas in `app/schemas/`
- provider abstractions in `app/providers/base.py`
- deterministic mock providers in `app/providers/mock.py`
- mock domain services in `app/services/`
- pytest coverage in `tests/`

No paid AI provider is required. No pgvector, embedding tables, or
`evidence_matches` migration is created in this phase.

## API Endpoints

The service exposes the documented AI boundary:

| Method | Path | Purpose |
|---|---|---|
| GET | `/ai/v1/health` | Service health and provider mode |
| POST | `/ai/v1/contracts/{contract_id}/extract` | Contract document to extracted schedule items |
| POST | `/ai/v1/evidence/{evidence_id}/understand` | Evidence metadata/file reference to structured evidence signals |
| POST | `/ai/v1/matches` | Evidence signals to candidate contract-item matches |
| POST | `/ai/v1/completeness` | Evidence support completeness for one contract item |
| POST | `/ai/v1/variations/detect` | Potential variation review flag |

Request and response shapes are based on `docs/api-contracts.md` and the
existing API-side providers in `services/api/app/ai/`.

## Provider Abstraction

The app uses provider protocols instead of hard-coding a model vendor:

- `LLMProvider`
- `EmbeddingProvider`
- `VisionProvider`

Phase A includes deterministic mock implementations:

- `MockLLMProvider`
- `MockEmbeddingProvider`
- `MockVisionProvider`

Future real providers should adapt to these interfaces instead of changing the
API routes.

## Mock Mode

Mock behavior is deterministic so tests and demos are repeatable.

- Extraction returns one of two fictional SubPay schedules based on the
  filename.
- Evidence understanding derives simple structured signals from supplied
  metadata and text.
- Matching uses deterministic token overlap.
- Completeness reports evidence support only, not claim validity.
- Variation detection flags review-worthy wording such as "extra" or
  "variation" when there is no strong match.

The AI recommends, explains, and flags. It does not determine legal
entitlement, adjudication outcomes, specification compliance, payment
liability, or claim submission.

## Run

```bash
cd services/ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8001
```

Health check:

```bash
curl http://localhost:8001/ai/v1/health
```

## Tests

```bash
cd services/ai
pytest
ruff check .
```

Tests use only local deterministic mocks and do not call external AI APIs.

## Limitations

This is not the production AI implementation yet. The following are deliberately
out of scope for Phase A:

- real LLM calls
- OCR or vision models
- embeddings generated from production data
- vector search or pgvector
- evidence match persistence
- final evaluation datasets and metrics
- background workers for long-running model jobs
