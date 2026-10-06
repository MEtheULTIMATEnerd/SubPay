"""Everything served under /api/v1.

Each workstream adds its own router module in this package and includes it
here. Endpoint naming and response shapes: docs/api-contracts.md.
"""

from fastapi import APIRouter

from app.api.v1 import contracts, evidence, health, me, organisation, projects

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(me.router)
api_router.include_router(projects.router)
api_router.include_router(organisation.router)
api_router.include_router(contracts.router)
api_router.include_router(evidence.router)
