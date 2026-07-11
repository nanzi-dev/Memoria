"""
开发者体验 API。
"""

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException

from memoria.api.user import require_current_user_id
from memoria.core import performance, quality_scorer, replay
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


@router.get("/replay/{session_id}")
def replay_session(
    session_id: str,
    step: int | None = None,
    limit: int = 1000,
    current_user_id: str = Depends(require_current_user_id),
):
    """加载历史 session，并返回可逐步查看的消息和状态时间线。"""
    session = _owned_session(session_id, current_user_id)
    messages = repository.get_session_messages(session_id, limit=limit)
    return replay.build_replay(session, messages, step=step)


@router.get("/performance")
def performance_snapshot(_current_user_id: str = Depends(require_current_user_id)):
    """查看关键路径耗时分布。"""
    return {
        "metrics": performance.snapshot(),
        "sample_window": 200,
    }


@router.post("/performance/reset")
def reset_performance_metrics(_current_user_id: str = Depends(require_current_user_id)):
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
        use_llm=req.use_llm,
    )
