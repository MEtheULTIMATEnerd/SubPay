# Local Integrated MVP: Stages 1–6B

This optional single-user localhost workflow uses SQLite, not Supabase.
It is disabled by default. It does not change the deterministic frontend demo.
Implemented capabilities include SQLite-backed projects, real PDF/DOCX text
extraction, contract-item review, actual image storage, optional OpenAI image
analysis, deterministic matching, persistent human review and JSON/HTML draft
exports. The integrated browser interface is `/integrated`; follow
[the frontend setup guide](../../apps/web/INTEGRATED.md) to start the required
local services. Mock vision remains the explicit default for safe plumbing
checks and is not accepted as real AI evidence by matching.

Not implemented: production authentication, cloud deployment, certified claim
approval, payment processing, automated compliance verification or
production-grade operational controls. This shared-token, local-filesystem
prototype does not establish completion, compliance or payment entitlement.

Real OpenAI integration passed limited positive (C1 electrical equipment) and
negative (N1 unrelated photograph) image smoke tests, including schema and
SQLite persistence checks. These are not comprehensive model accuracy results.
Browser end-to-end verification cancelled inference and replayed previously
persisted real OpenAI observations in an isolated database; fresh browser-triggered
paid inference was not tested. Every future paid request still needs explicit
approval for the selected image; startup/upload/refresh never initiates one.

From `services/api`, with the existing virtual environment active:

```bash
export SUBPAY_LOCAL_ENABLED=true
export SUBPAY_LOCAL_ACCESS_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m app.run_local
```

The launcher binds to `127.0.0.1:8000` and disables proxy-header trust. Do not
rebind to a public interface or expose through a proxy/tunnel. Integrated routes
also reject non-loopback client addresses. Stop with Ctrl+C. Do not print or
commit the token or put it in frontend source or NEXT_PUBLIC variables.

All integrated routes require `Authorization: Bearer <locally configured token>`:

- POST `/api/v1/integrated/projects`: JSON `name` (trimmed, 1-200 characters),
  optional `description` (up to 5000 characters). Returns the project, HTTP 201.
- GET `/api/v1/integrated/projects`: returns an array of projects.
- GET `/api/v1/integrated/projects/{id}`: returns a project or HTTP 404.

Projects have UUID IDs and UTC creation/update timestamps. Every operation uses
a fresh SQLite connection with foreign keys enabled and parameterised writes.
The default database is `services/api/.local-data/projects.sqlite3`; the entire
directory, including future uploads, is Git-ignored. Override with
`SUBPAY_LOCAL_DATA_DIR` only to a private, ignored location. Back up the directory
for durability; this is not encrypted storage or production authentication.

Only browser origins `http://localhost:3101` and `http://127.0.0.1:3101` are
permitted for integrated requests. CLI requests without Origin still require
the token and loopback address. CORS preflight is token-free but does not grant
data access. Existing Supabase routes retain their authentication requirements.
These are the direct FastAPI browser origins. The integrated Next.js bridge
also permits its frontend on port 3102 and forwards authenticated server-to-server
requests to loopback FastAPI without a browser Origin header; it does not expand
the backend's direct-origin allowlist.

## Contracts and Review

Install the declared dependencies into the existing API virtual environment:
`.venv/bin/python -m pip install -r requirements.txt`.

Under `/api/v1/integrated/projects/{project_id}/contracts`:

- POST: multipart `file`, PDF or DOCX, matching extension and MIME type, up to
  20 MiB. Originals are stored with UUID filenames under `.local-data/uploads/contracts`.
- GET: list this project's uploaded contracts.
- GET `/{contract_id}`: metadata, extracted text, source blocks and limitations.
- GET `/{contract_id}/original`: authenticated original-file download.
- GET `/{contract_id}/items`: persisted extracted/manual items.
- POST `/{contract_id}/items`: manual item; JSON description required (3-2000
  characters), optional item_code (up to 50), quantity/unit/rate/amount. New items
  always start as drafts. Numeric fields must be finite and nonnegative.
- PATCH `/{contract_id}/items/{item_id}`: edit a draft with description required
  and optional fields as above. Source references and extracted descriptions
  cannot be overwritten. Reviewed items must first be reopened.
- DELETE `/{contract_id}`: delete the contract, its items, their match
  suggestions and the stored original. Returns 204.
- DELETE `/{contract_id}/items/{item_id}`: delete one item (any review status)
  and its match suggestions. Returns 204. Deletion is permanent.
- POST `/{contract_id}/items/{item_id}/review`: JSON status `confirmed`, `rejected`
  or `draft`. Draft reopens and clears review metadata. Decisions record the
  shared local identity `local-development-user`, not an independently verified person.

`pypdf` reads text-bearing PDF pages; `python-docx` reads top-level paragraphs
and table rows. Limits: 100 PDF pages, 50 MiB expanded DOCX content, one million
extracted characters and 1000 candidate items. Encrypted/malformed documents are
rejected. Empty/scanned PDFs are retained with an explicit OCR limitation.
No OCR, external model calls or filename-selected schedules are used.

Only identifiable numbered lines/table rows become draft items. Numerical values
remain null rather than guessing column meanings; reviewers can enter values.
Raw text, PDF page/DOCX block references, original extracted description and
source contract ID remain available. Non-numbered or complex schedules may need
manual entry. All drafts require explicit confirmation; numbered legal clauses
can be candidates and should be rejected if they are not claim lines.

Database errors roll back metadata/items and remove the just-written original;
ordinary parsing errors create no original or contract record. A hard process
crash between filesystem write and database commit can still leave an orphaned
file; this prototype does not claim cross-filesystem/database crash atomicity.

Tests: `.venv/bin/python -m pytest tests/test_integrated.py tests/test_local_contracts.py`
from `services/api`.

## Evidence Images and Analysis (Mock Default, OpenAI Optional)

Install requirements into the API virtual environment as above (Pillow is used
to verify and fully decode image contents). `SUBPAY_LOCAL_VISION_PROVIDER=mock`
is the default. Explicit `openai` uses the authenticated loopback AI-service
bridge below. Other selections fail closed. Mock mode does not load or use
AI-service credentials; failed OpenAI analysis never substitutes mock output.

Under `/api/v1/integrated/projects/{project_id}/evidence`:

- POST: multipart `file`; JPEG, PNG or single-frame WEBP, up to 10 MiB and
  20 million pixels. Actual decoded format determines the stored extension;
  declared MIME must match. Filename extensions are not evidence of type.
- GET: project-scoped evidence metadata list.
- GET `/{evidence_id}`: metadata and current processing status.
- POST `/{evidence_id}/analyse`: synchronous analysis of actual stored bytes using
  the explicitly configured provider. Returns attempt ID, status, provider/model
  and structured results. Mock mode is labelled and makes no paid request;
  OpenAI mode sends the image through the local AI-service bridge and may incur
  a charge. Calling this endpoint is an explicit action, not an upload side effect.
- GET `/{evidence_id}/observations`: persisted attempt history, including
  provider, model, structured data, processing timestamp and safe error status.

Original bytes are preserved under `.local-data/uploads/evidence` with UUID
filenames. No static mount or unauthenticated file URLs expose that directory.
The adapter revalidates stored bytes and constructs an inline image data URL
matching the existing vision provider `describe(document_url, text_hint)`
interface. It validates all four certain/possible object/activity groups and
also stores the established API `EvidenceUnderstandingResult`/`EvidenceSignals`
shape. Certainty groups are retained alongside the flattened signals.

Mock model `local-mock-v1` reports `MOCK: source image supplied` as a possible
object and confidence zero, not a construction finding. `mock=true` and
`not_real_vision=true` explicitly distinguish test plumbing from real analysis.
The limited real-provider smoke tests above do not validate mock output. Do not
use mock observations as evidence of scene understanding, work completion,
compliance or payment entitlement.

Each explicit completed/retried analysis creates a new history record; it is
not deduplicated. A second request while processing returns 409. Provider or
response-validation failure persists a failed attempt with generic error text
and returns 502, without mock fallback or leaked provider exception details.
Inference runs outside database transactions. Processing interrupted by a hard
crash may remain stuck in processing; automatic recovery is not implemented.

All routes use the same local token/origin restrictions. Project IDs are checked
on every evidence/observation lookup. This is one shared local identity, not
multi-user ownership or production authorisation. Uploads are private local
files, not encrypted storage; avoid confidential images. Hard-crash orphan-file
limitations described for contracts also apply here.

Stage 3A tests: `.venv/bin/python -m pytest tests/test_local_evidence.py`.

## Stage 3B: Real Vision Approval Gate

Real-provider integration is implemented and has passed the limited image
smoke tests described above, not a comprehensive accuracy evaluation.
Do not run an analysis against OpenAI until the operator explicitly approves
the exact non-sensitive image and one paid request. Never send private site
images/documents without their owner's explicit permission. Automated tests use
mocked transports; prior live-test approvals do not authorise further requests.

After approval only, configure the same local access token in both processes.
Keep the OpenAI key in `services/ai/.env`, server-side. Do not print the token
or key. Example commands from the repository root (no inference on startup):

```bash
export SUBPAY_LOCAL_ENABLED=true
export SUBPAY_LOCAL_ACCESS_TOKEN="$(services/api/.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SUBPAY_LOCAL_VISION_PROVIDER=openai
export SUBPAY_LOCAL_VISION_MODEL=gpt-4o-mini
export AI_LOCAL_ACCESS_TOKEN="$SUBPAY_LOCAL_ACCESS_TOKEN"
export AI_LOCAL_VISION_ENABLED=true
export AI_VISION_PROVIDER=openai
export AI_OPENAI_MODEL=gpt-4o-mini
```

In separate terminals with those same environment values, run from
`services/ai`: `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-proxy-headers`;
from `services/api`: `.venv/bin/python -m app.run_local`.

Upload the approved image through the existing evidence endpoint, then make
ONE request (replace PROJECT_ID and EVIDENCE_ID with the returned UUIDs):

```bash
curl --fail-with-body --request POST \
  --header "Authorization: Bearer $SUBPAY_LOCAL_ACCESS_TOKEN" \
  http://127.0.0.1:8000/api/v1/integrated/projects/PROJECT_ID/evidence/EVIDENCE_ID/analyse
```

Inspect `/observations` and repeat GET after restarting the API. Do not repeat
POST automatically on timeout or error: the provider may already have billed
an attempted request. Neither adapter implements automatic retries.

API-to-AI bridge: POST `/ai/v1/local/vision`, fixed loopback destination with
the local token. It is disabled by default and requires explicit OpenAI
selection. The AI service reuses `OpenAIVisionProvider`, configured model/key,
and prompt; strict response mode rejects malformed JSON/observations instead
of invoking its permissive text parser. Images use inline base64 with low
detail and at most 500 output tokens. Provider/model mismatch fails closed.
Certainty groups and real-vs-mock provenance persist in SQLite. Confidence zero
in the compatibility schema means no calibrated score is provided, not a
measured probability of incorrectness.

The AI bridge trusts the token-authenticated API's decoded-image validation;
do not expose either service beyond loopback. No production auth or automatic
cost-budget enforcement is provided. Stage 3B tests mock HTTP transports and
never require OpenAI credentials or paid calls.

### C1 Empty-Observation Investigation (Offline)

The first real C1 result was structurally valid and persisted, but empty despite
visible electrical components. Its raw model response, finish reason and usage
were not retained, so the cause remains unresolved. Do not describe the prompt
clarification below as an empirically proven fix or report mocks as recognition.

The stored C1 JPEG still matches its manifest SHA-256; offline base64 round-trip
and mocked HTTP tests preserve bytes and non-empty labels. Local strict mode
already disabled permissive parsing/fallback. A valid empty model array remains
allowed; a four-group JSON object where a model array is expected fails closed.

Local strict mode now uses a true system instruction (`LOCAL_SYSTEM_PROMPT`)
and a separate user image message. It explicitly asks for visible installed
electrical components/materials, separates objects from observable activities,
defines certain/possible categories and clarifies that unknown completion or
compliance must not suppress visible objects. Unrelated/unreadable images may
still return []. The legacy non-local prompt is unchanged.

Strict mode also rejects explicit non-stop finish reasons and refusals, even if
content happens to be syntactically valid JSON. Previously these flags were not
checked, so truncation cannot be excluded retrospectively. No raw provider
response is fabricated or recovered by this change.

Image detail remains low, consistently selected by the local bridge; no evidence
establishes it as C1's cause. Output remains the same four observation groups.
Any C1 retest requires fresh explicit approval; do not reuse the previous run's
approval or automatically retry. No inference is performed by offline tests.

## Stage 4: Persisted Evidence Matching and Review

All routes below use `/api/v1/integrated/projects/{project_id}/matches`,
the existing loopback/origin restrictions and local bearer token:

- POST `/generate`: generate suggestions; returns `created` and `method`.
- GET the base route: list suggestions, including historical records.
- GET `/{match_id}`: retrieve one project-scoped suggestion.
- POST `/{match_id}/confirm`, `/reject`, `/reopen`: review a suggestion.

Only confirmed contract items and the most recently inserted analysis attempt
for each evidence record are eligible. The newest attempt must be ready,
schema-valid, OpenAI-sourced and explicitly non-mock. A newer empty, failed or
mock analysis never causes an older positive result to be reused. No provider
request is made during matching; empty observations produce no suggestions.

`construction-lexical-v1` normalises a small construction synonym dictionary,
removes generic terms, and requires a shared specific term. Its score is the
fraction of distinct contract-description terms found in supporting labels,
with a 0.34 minimum. It is a relevance heuristic, not a calibrated probability,
completion percentage, compliance decision or measured matching accuracy.
Labels containing explicit negative markers are conservatively excluded.
Certain and possible groups remain identified in the stored supporting text;
both can suggest relevance and neither establishes completion.

`local_matches` retains UUID references to the project, item, evidence and
analysis, original supporting text, explanation, score, method, provider/model,
item-description snapshot, review metadata and timestamps. Foreign keys, an
insert guard and a unique item/evidence/analysis constraint protect references
and prevent duplicate suggestions. Regeneration never overwrites decisions.

Suggestions start pending. Confirm/reject stores `local-development-user` and
a timestamp; reopen clears both. Changing a reviewed decision requires reopen.
This shared development identity is not multi-user production authentication.
`is_current` becomes false after a newer analysis, item-description change or
loss of item confirmation. Stale suggestions cannot be newly confirmed.
Historical decisions remain visible, not endorsements of newer evidence.
An edited item does not refresh its existing same-analysis suggestion: obtain
a newly authorised analysis if a new suggestion is needed. No automatic paid
analysis is initiated by this module.

Limitations include limited English vocabulary, lexical false positives,
missing synonyms, conservative negative-label filtering, equal relevance
weight for certain/possible labels, and no location/quantity/completion checks.
Run `.venv/bin/python -m pytest tests/test_local_matching.py -q` from
`services/api`; tests use isolated SQLite files and prohibit external HTTP.

## Stage 5: Draft Claim-Support Exports

Authenticated, loopback-only downloads:

- GET `/api/v1/integrated/projects/{project_id}/claim-package.json`
- GET `/api/v1/integrated/projects/{project_id}/claim-package.html`

Send the existing local bearer token in the Authorization header, never in the
URL. Responses use attachment filenames `subpay-{project_id}-draft.json` or
`.html`, `Cache-Control: no-store`, and JSON/HTML content types respectively.
The standalone HTML escapes persisted text, uses inline print-friendly CSS,
loads no external resources, and includes a restrictive content security policy.
Downloaded packages contain potentially sensitive records: share them only
with authorised reviewers. Authentication does not protect a downloaded copy.

### JSON Schema v1

`schema_version` is `subpay.draft-claim-support.v1`. UUIDs and timestamps are
strings; quantities/rates/amounts are numbers or null exactly as recorded.
Arrays use deterministic ID ordering (matches use creation timestamp then ID).
Each generation has a new package UUID and UTC timestamp; exports are not stored
and are not a historical audit log.

- `package_id`, `generated_at`, `status` (always `draft`), `schema_version`.
- `project`: `id`, `name`, `description`, `created_at`, `updated_at`.
- `contracts`: project contracts, each with `id`, `project_id`,
  `original_filename`, `mime_type`, `size_bytes`, `limitation`, `created_at`.
- `contract_items`: currently confirmed items with `id`, `contract_id`,
  `item_code`, `description`, `quantity`, `unit`, `rate`, `amount`,
  `source_reference`, `origin`, `review_status`, `reviewed_by`, `reviewed_at`,
  `created_at`, `updated_at`, and `supporting_evidence`.
- Each supporting link has `evidence` (`id`, `original_filename`, `content_type`,
  `size`, `uploaded_at`), `analysis` (`id`, `provider`, `model`, `processed_at`,
  `mock: false`, `observations` containing the four existing certainty/category
  arrays), and `match` (`id`, `score`, `score_kind`, `explanation`, `method`,
  `review_status`, `reviewed_by`, `reviewed_at`, `created_at`, `updated_at`,
  `supporting_observations` with original `group`/`text` pairs).
- `coverage`: `total_confirmed_items`, `supported_items`, `unsupported_items`,
  `unsupported_item_ids`, `unlinked_evidence_count`, `unlinked_evidence_ids`.
  Counts refer to distinct items/evidence, not the number of supporting links.
- `limitations`: explicit draft, AI, heuristic, human-review and entitlement
  disclaimers. Recorded amounts are not a calculated or certified payable sum.

Only human-confirmed, current Stage 4 matches with review metadata qualify.
Items, contracts, evidence and analyses must still exist in the same project.
The latest analysis must be ready, non-mock, OpenAI-sourced, schema-valid and
non-empty. Pending/rejected/reopened matches, superseded analyses, changed item
descriptions and unconfirmed items are excluded from support. Unsupported
confirmed items remain in the package with empty support arrays; zero support
is a valid draft, not an error. All evidence lacking an eligible link is counted
as unlinked, including unrelated images.

Both formats read one explicit SQLite transaction using a read-only connection;
no business records, review states, tables or package records are written.
Exports include provenance and current timestamps, not a complete event history.
Private storage paths, file bytes, raw provider responses and configuration
secrets are not exported. Original filename and observation text remain visible.
No AI request, PDF renderer or additional dependency is needed.

Run `.venv/bin/python -m pytest tests/test_local_packages.py -q` from
`services/api`. Tests use isolated databases and the matching fixture's external
HTTP guard. The deterministic frontend remains separate from these routes.

## Stage 6: Integrated Browser Interface

The Next.js `/integrated` route provides projects, contract review, evidence and
analysis, match review and draft package downloads through a restricted
same-origin bridge. The development token is supplied by the user and held only
in memory, never browser storage or URLs. FastAPI continues to validate it.
Use [the integrated frontend guide](../../apps/web/INTEGRATED.md) for startup,
OpenAI configuration, the exact bridge allowlist scope and download safeguards.

`Analyse with AI` requires confirmation of the selected image, API-charge risk
and limitations. There is no automatic inference, bulk analysis, automatic retry
or mock substitution on real-provider failure. Match generation is a separate
explicit action and does not call OpenAI. Confirm/reject/reopen decisions persist
in SQLite. Draft exports use only eligible current, human-confirmed matches and
identify unsupported items; they are not certified claims or independent proof.
