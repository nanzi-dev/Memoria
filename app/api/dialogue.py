"""
API 路由层

用途：
1. HTTP 参数校验
2. 调用 orchestrator
3. 返回标准 DTO
"""

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.core import character_loader, orchestrator
from app.db import repository

router = APIRouter()


# =========================
# 请求模型
# =========================
class SessionStartRequest(BaseModel):
    character_id: str
    player_id: str
    player_name: str = "旅行者"
    
class DialogueTurnRequest(BaseModel):
    session_id: str
    player_message: str
    

# =========================
# 响应模型
# =========================
class SessionStartResponse(BaseModel):
    session_id: str
    opening_line: str
    action: str
    current_affinity: int


class DialogueTurnResponse(BaseModel):
    dialogue: str
    action: str
    affinity_delta: int
    current_affinity: int
    current_mood: str
    triggered_events: list[str]


class CharacterSummary(BaseModel):
    character_id: str
    name: str
    display_name: str
    core_identity_summary: str


class SessionInfo(BaseModel):
    session_id: str
    character_id: str
    player_id: str
    player_name: str
    created_at: str | None = None
    last_message: str | None = None
    message_count: int = 0


class HistoryMessage(BaseModel):
    role: str
    content: str
    created_at: str | None = None


class HistoryResponse(BaseModel):
    messages: list[HistoryMessage]
    has_more: bool
    current_affinity: int
    current_mood: str
    
    
# =========================
# Characters
# =========================
@router.get("/characters", response_model = list[CharacterSummary])
def list_characters():
    """获取所有角色摘要"""
    
    results = []
    
    for cid in character_loader.list_character_ids():
        try:
            card = character_loader.load_character_card(cid)
            
            results.append(CharacterSummary(
                character_id = card.character_id,
                name = card.meta.name,
                display_name = card.meta.display_name,
                core_identity_summary = card.identity.core_identity_summary,
            ))
        except Exception:
            continue
    return results

# =========================
# Session start
# =========================
@router.post("/dialogue/session/start", response_model=SessionStartResponse)
def session_start(req: SessionStartRequest):
    try:
        result = orchestrator.start_session(
            req.character_id,
            req.player_id,
            req.player_name
        )
        return SessionStartResponse(**result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

# =========================
# Dialogue turn
# =========================
@router.post("/dialogue/turn", response_model=DialogueTurnResponse)
def dialogue_turn(req: DialogueTurnRequest):
    try:
        result = orchestrator.run_dialogue_turn(
            req.session_id,
            req.player_message
        )
        return DialogueTurnResponse(**result)

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

# =========================
# Session list
# =========================
@router.get("/dialogue/sessions", response_model=list[SessionInfo])
def get_sessions(character_id: str, player_id: str):
    """获取玩家与角色的所有会话"""

    sessions = repository.get_sessions_by_player_and_character(
        character_id,
        player_id
    )

    # SQLite Row → dict 安全转换
    return [SessionInfo(**dict(s)) for s in sessions]

# =========================
# History
# =========================
@router.get("/dialogue/history", response_model=HistoryResponse)
def get_history(session_id: str, offset: int = 0, limit: int = 20):
    """分页获取对话历史"""

    session = repository.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages, has_more = repository.get_messages_paginated(
        session_id,
        offset,
        limit
    )

    card = character_loader.load_character_card(session["character_id"])

    runtime_state = repository.get_runtime_state(
        session["character_id"],
        session["player_id"],
        card
    )

    return HistoryResponse(
        messages=[HistoryMessage(**m) for m in messages],
        has_more=has_more,
        current_affinity=runtime_state.get("affection_level", 0),
        current_mood=runtime_state.get("current_mood", "neutral"),
    )