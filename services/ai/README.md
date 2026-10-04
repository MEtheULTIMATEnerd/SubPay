# services/ai

AI / intelligence service that serves `/ai/v1`. Owner: Arya.

Contract extraction, evidence understanding, evidence-to-contract matching,
completeness assessment and potential-variation detection live here. The
interface the rest of the app relies on is in
[docs/api-contracts.md](../../docs/api-contracts.md#6-ai-service-interface-aiv1).

Until this exists, the web prototype uses the deterministic mock in
`apps/web/lib/ai.ts`.
