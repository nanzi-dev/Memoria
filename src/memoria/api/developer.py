"""
开发者体验 API。
"""

from datetime import datetime, timezone
import json

from pydantic import BaseModel
from fastapi import APIRouter, Depends, Query, HTTPException

from memoria.api.user import require_admin_user_id, require_current_user_id
from memoria.core import (
    character_loader,
    memory_curve,
    performance,
    quality_scorer,
    replay,
    world_clock,
)
from memoria.db import repository


router = APIRouter(prefix="/developer", dependencies=[Depends(require_current_user_id)])


class QualityScoreRequest(BaseModel):
    session_id: str | None = None
    character_id: str | None = None
    messages: list[dict] | None = None
    use_llm: bool = False


def _owned_session(session_id: str, current_user_id: str) -> dict:
    session = repository.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.get("player_id") != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该玩家的对话")
    return session


def _diagnostic_world_now(current_user_id: str) -> str:
    """Read the clock without creating or updating any persistent state."""
    real_now = datetime.now(timezone.utc)
    row = repository.get_player_world_clock(current_user_id)
    if not row:
        return real_now.isoformat()
    return world_clock.calculate_world_now(
        row["anchor_real_utc"],
        row["anchor_world_utc"],
        row["time_scale"],
        real_now,
    ).isoformat()


def _memory_participants(record: dict) -> set[str]:
    raw = record.get("participants")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = []
    return {str(value) for value in (raw or []) if str(value).strip()}


@router.get("/replay/{session_id}")
def replay_session(
    session_id: str,
    step: int | None = None,
    limit: int = Query(default=1000, ge=1, le=5000),
    current_user_id: str = Depends(require_current_user_id),
):
    """加载历史 session，并返回可逐步查看的消息和状态时间线。"""
    session = _owned_session(session_id, current_user_id)
    messages = repository.get_session_messages(session_id, limit=limit)
    return replay.build_replay(session, messages, step=step)


@router.get("/performance")
def performance_snapshot(_current_user_id: str = Depends(require_admin_user_id)):
    """查看关键路径耗时分布。"""
    return {
        "metrics": performance.snapshot(),
        "sample_window": performance.sample_window(),
    }


@router.post("/performance/reset")
def reset_performance_metrics(_current_user_id: str = Depends(require_admin_user_id)):
    """重置开发者性能采样。"""
    performance.reset()
    return {"status": "reset"}


@router.post("/quality-score")
def quality_score(
    req: QualityScoreRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    """对 session 或直接传入的消息进行质量评分。"""
    messages = req.messages
    character_id = req.character_id

    if req.session_id:
        session = _owned_session(req.session_id, current_user_id)
        messages = repository.get_session_messages(req.session_id, limit=1000)
        character_id = character_id or session.get("character_id")

    if not messages:
        raise HTTPException(status_code=400, detail="需要提供 session_id 或 messages")

    return quality_scorer.score_dialogue(
        messages=messages,
        character_id=character_id,
        owner_user_id=current_user_id,
        use_llm=req.use_llm,
    )


@router.get("/memory-curve")
def memory_curve_diagnostics(
    character_id: str = Query(..., min_length=1, max_length=128),
    session_id: str | None = Query(default=None, max_length=128),
    recall_key: str | None = Query(default=None, max_length=256),
    include_forgotten: bool = False,
    current_user_id: str = Depends(require_current_user_id),
):
    """Inspect recall decisions without advancing or initializing curve rows."""
    try:
        character_loader.load_character_card(character_id, current_user_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="角色不存在") from None

    session = None
    if session_id:
        session = _owned_session(session_id, current_user_id)
        if session.get("is_multi_character"):
            participant_ids = {
                row["character_id"]
                for row in repository.get_session_participants(
                    session_id, only_active=False
                )
            }
            if character_id not in participant_ids:
                raise HTTPException(status_code=403, detail="角色不属于该会话")
        elif session.get("character_id") != character_id:
            raise HTTPException(status_code=403, detail="角色不属于该会话")

    fact_records = repository.get_prompt_memory_fact_records(
        character_id=character_id,
        player_id=current_user_id,
        session_id=session_id,
        limit=200,
    )
    impression_records = repository.get_observer_character_impressions(
        owner_user_id=current_user_id,
        observer_character_id=character_id,
        limit=200,
    )
    if session_id:
        group_records = [
            record
            for record in repository.get_session_group_memories(
                session_id=session_id, limit=200
            )
            if character_id in _memory_participants(record)
        ]
    else:
        group_records = repository.get_character_group_memories(
            character_id=character_id,
            owner_user_id=current_user_id,
            limit=200,
        )

    world_now = _diagnostic_world_now(current_user_id)
    effective_recall_key = recall_key or (
        f"diagnostic:{session_id or character_id}"
    )
    items = []
    for records, memory_type, text_key in (
        (fact_records, "player_fact", "fact_text"),
        (impression_records, "character_impression", "memory_text"),
        (group_records, "group_experience", "memory_text"),
    ):
        items.extend(memory_curve.inspect_records(
            records,
            owner_user_id=current_user_id,
            character_id=character_id,
            memory_type=memory_type,
            world_now=world_now,
            recall_key=effective_recall_key,
            text_key=text_key,
        ))
    if not include_forgotten:
        items = [item for item in items if item["clarity"] != "forgotten"]
    return {
        "character_id": character_id,
        "session_id": session_id,
        "recall_key": effective_recall_key,
        "world_now": world_now,
        "items": items,
    }
