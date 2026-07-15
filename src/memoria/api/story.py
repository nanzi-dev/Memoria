from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from memoria.api.user import require_current_user_id
from memoria.db import repository


router = APIRouter(prefix="/stories", tags=["stories"])


class StoryStateResponse(BaseModel):
    owner_user_id: str
    story_id: str
    status: str
    progress: float
    terminal_reason: str | None
    ledger_version: int
    started_at: str
    updated_at: str
    completed_at: str | None
    failed_at: str | None


@router.get("/{story_id}/state", response_model=StoryStateResponse)
def get_story_state(
    story_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    state = repository.get_story_state(current_user_id, story_id)
    if state is None:
        raise HTTPException(status_code=404, detail="剧情状态不存在")
    return state
