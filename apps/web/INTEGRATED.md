# Integrated MVP: Stages 6A and 6B

This optional local development route uses actual FastAPI responses, SQLite
records and uploaded files. It is separate from the deterministic demo.
It is not production authentication or a deployed multi-user application.

## Start Locally

Use the existing Node dependencies in `apps/web` and Python virtual environment
in `services/api`, with the already-declared PDF/DOCX/image dependencies available.
The mock-mode startup below needs no Supabase setup, AI service or external API
key. Real OpenAI analysis requires the AI service and configuration described
later; use each service's declared dependency manifests when setting up a clone.

In an API terminal, from the repository root:

```bash
export SUBPAY_LOCAL_ENABLED=true
export SUBPAY_LOCAL_ACCESS_TOKEN="$(services/api/.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SUBPAY_LOCAL_VISION_PROVIDER=mock
cd services/api
.venv/bin/python -m app.run_local
```

Keep the token private. Enter that same token in the page's password field.
On macOS, before starting the server, it can be copied without printing it:
`printf '%s' "$SUBPAY_LOCAL_ACCESS_TOKEN" | pbcopy`.
Clear the clipboard afterwards. Do not put it in source, URLs, browser storage,
NEXT_PUBLIC variables or committed environment files.

In another terminal, from the repository root:

```bash
cd apps/web
SUBPAY_INTEGRATED_UI_ENABLED=true npm run dev -- --webpack --hostname 127.0.0.1 --port 3101
```

Open <http://127.0.0.1:3101/integrated>, enter the local token, and connect.
If 3101 is occupied, use 3102 and open the corresponding URL; the local bridge
explicitly permits those two frontend ports only. Do not replace another running
service. The bridge's backend target is fixed at `127.0.0.1:8000`.
Stop each server with Ctrl+C. Never bind either server to a public interface or
expose it through a tunnel. This interface should only handle approved local data.

## Workflow

1. Create/select a project and inspect its persisted metadata.
2. Upload a real PDF or DOCX (up to 20 MiB). Select a contract to inspect its
   extracted text and source-backed items. Extraction can require manual review;
   scanned PDFs require OCR outside this stage. Complex/non-numbered documents
   may produce no items. This page does not yet provide manual item creation.
3. Edit draft descriptions, save, then explicitly confirm/reject. Reopen a
   reviewed item to edit it. Quantities/prices are shown only when recorded;
   editing those numeric fields is not implemented here.
4. Upload JPEG, PNG or WebP evidence (up to 10 MiB) and inspect stored metadata.
   Newly uploaded evidence is labelled "Uploaded — awaiting analysis".
   Existing processing statuses are displayed as stored, not treated as proof
   that a particular provider ran. Refresh lists to see other local changes.

Uploads show an indeterminate busy state, not a measured percentage. Analysis,
matching review and draft-package exports are available as explicit actions.
Originals are stored by FastAPI
under its private local data directory, not in browser storage. The default is
`services/api/.local-data`; SQLite records and originals persist across restarts.
Use `SUBPAY_LOCAL_DATA_DIR` to select an explicitly separate ignored test directory
when testing. Existing files/records are never automatically reset by this page.

## Access Boundary

The user-supplied token exists only in React memory and Authorization headers.
Disconnect/reload clears the session; reconnect and select the project again.
No token is written to localStorage, sessionStorage or cookies. Do not save it
with a password manager on a shared machine. This is a shared development token,
not independently verified reviewer identity or production account security.

`/api/integrated/[...path]` is disabled unless the server-side
`SUBPAY_INTEGRATED_UI_ENABLED=true` flag is set. It checks loopback Host,
same-origin requests and a supplied bearer header before forwarding. FastAPI
still validates the token. It forwards only project/contract/item/evidence
(including contract and item deletion),
observation, single-image analysis, match generation/review and JSON/HTML package
endpoints to a fixed loopback address. There is no general URL proxy, cookie
forwarding, token injection or CORS broadening.
Requests have a bounded body and timeout; no request is automatically retried.

If an upload times out, refresh the list before retrying: the backend may have
saved it even though the response was lost. Failed requests never substitute
demo fixtures. Existing `/login`, `/dashboard` and `/projects/...` demo services
are unchanged; the shared shell only bypasses demo login for exact `/integrated`.

## Verification

From `apps/web`: `npm test`, `npm run typecheck`, `npm run lint`.
The focused client/bridge tests mock fetch; they do not establish real connectivity.
Real browser verification must use a separately configured local API and safe
test files. No OpenAI request is necessary for development or automated tests.

## Stage 6B: Analysis, Matching and Draft Packages

The five sections are Projects, Contracts, Evidence & AI Analysis, Match
Suggestions, and Draft Claim Package. Refresh/load/upload never triggers inference
or match generation. Observations are loaded from SQLite and show the four
certainty/activity groups, status, provider/model and processing timestamp.
Empty completed results are valid; mock results are explicitly labelled MOCK.

`Analyse with AI` opens a native confirmation dialog naming the image, provider,
charge risk and limitations. Cancel sends no analysis request. Each confirmed
action sends one request, with an in-flight lock and no automatic retries.
After failure, refresh status before considering another deliberate request:
the provider may already have processed/billed the first attempt. Disconnecting
or navigating away does not cancel a provider request already accepted.

The default startup above uses mock mode and makes no paid requests. Real vision
requires the existing server-side OpenAI configuration and all three services.
From the repository root, configure the following in the API and AI terminals
using the SAME private local token (never set NEXT_PUBLIC credentials):

```bash
export SUBPAY_LOCAL_ENABLED=true
export SUBPAY_LOCAL_ACCESS_TOKEN="<your privately configured local token>"
export SUBPAY_LOCAL_VISION_PROVIDER=openai
export SUBPAY_LOCAL_VISION_MODEL=gpt-4o-mini
export AI_LOCAL_ACCESS_TOKEN="$SUBPAY_LOCAL_ACCESS_TOKEN"
export AI_LOCAL_VISION_ENABLED=true
export AI_VISION_PROVIDER=openai
export AI_OPENAI_MODEL=gpt-4o-mini
```

Keep the existing `AI_OPENAI_API_KEY` server-side in the AI service's normal
configuration. Do not print it or paste it into the browser. In separate terminals:

```bash
# API, from repository root
cd services/api
.venv/bin/python -m app.run_local

# AI service, from repository root (separate terminal)
cd services/ai
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-proxy-headers

# Frontend, from repository root (separate terminal)
cd apps/web
SUBPAY_INTEGRATED_UI_ENABLED=true npm run dev -- --webpack --hostname 127.0.0.1 --port 3101
```

Only send an approved image after reading the confirmation. Neither clicking
upload nor running verification authorises a paid request. The frontend cannot
preflight provider configuration; actual persisted results identify mock versus
real provider/model. A configured real-provider failure never substitutes mocks.

`Generate Match Suggestions` calls the deterministic backend, not OpenAI.
Matches show exact support text, lexical relevance score, provenance, human
review status and stale/current source flags. Only explicit Confirm/Reject/
Reopen actions change review decisions. Failed requests do not optimistically
change displayed states. Refresh matches after changing contract items or analyses.

JSON downloads use authenticated backend bytes and a temporary object URL. HTML
is also fetched with authentication; its escaped backend report is displayed in
a sandboxed iframe. `Open printable report` opens a token-free blob document with
no opener and a restrictive embedded CSP, because response CSP headers do not
survive blob conversion. Use the browser's Print command in that report tab.
Temporary report URLs are revoked on replacement or disconnect/unmount.
Report contents are generated snapshots: regenerate after changing review records.
Do not share downloaded records with unauthorised people. Tokens never appear in
download URLs, filenames or browser storage.

Drafts include unsupported confirmed items and explicit limitations. They are not
certified claims, completion assessments, invoices or payment-entitlement decisions.
Browser smoke verification replays a previously persisted real C1 OpenAI analysis
in isolated SQLite data, remapping only its evidence UUID to the freshly uploaded
same image. That is fixture replay, NOT fresh live inference or an accuracy study.
