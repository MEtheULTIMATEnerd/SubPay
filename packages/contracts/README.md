# packages/contracts

Shared API and type contracts that more than one workstream depends on.

Source of truth today:

- Human-readable contracts: [docs/api-contracts.md](../../docs/api-contracts.md)
- TypeScript entity shapes used by the web app: `apps/web/lib/types.ts`

When the FastAPI service publishes its OpenAPI schema, generated or shared
types go here so the web app and services stop keeping separate copies.
Do not change a shared shape without agreement from the owner of that resource.
