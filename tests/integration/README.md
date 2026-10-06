# tests/integration

Cross-service tests that exercise the end-to-end MVP journey:

create project → upload contract → review claim schedule → upload evidence →
AI-suggested matches → human confirmation → readiness → export.

Unit tests stay next to the code they test (`apps/web`, `services/api`,
`services/ai`). Only tests that need more than one service belong here.
Use seeded demo data so runs are repeatable.
