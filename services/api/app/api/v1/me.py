"""The signed-in user's profile and organisation (F01)."""

from fastapi import APIRouter

from app.api.deps import Platform
from app.core import errors
from app.repositories.platform import NO_PROFILE_MESSAGE
from app.schemas.platform import Me, MeUpdate

router = APIRouter(tags=["platform"])


@router.get("/me", response_model=Me, summary="Signed-in profile and organisation")
def get_me(platform: Platform) -> Me:
    me = platform.get_me()
    if me is None:
        raise errors.forbidden(NO_PROFILE_MESSAGE)
    return me


@router.patch("/me", response_model=Me, summary="Update your own name")
def update_me(body: MeUpdate, platform: Platform) -> Me:
    me = platform.update_my_name(body.full_name)
    if me is None:
        raise errors.forbidden(NO_PROFILE_MESSAGE)
    return me
