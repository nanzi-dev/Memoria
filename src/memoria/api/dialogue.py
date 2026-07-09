"""
API 路由层

用途：
1. HTTP 参数校验
2. 调用 orchestrator
3. 返回标准 DTO
"""

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from memoria.core import character_loader, orchestrator
from memoria.core.memory_extractor import summarize_session
from memoria.db import repository

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
    triggered_events: list[dict] = []
    event_notification: str | None = None

class SessionEndRequest(BaseModel):
    session_id: str

class SessionEndResponse(BaseModel):
    session_id: str
    summary: str | None
    message_count: int

class SessionSummaryInfo(BaseModel):
    id: int
    session_id: str
    summary_text: str
    message_count: int
    created_at: str | None = None
    session_created_at: str | None = None


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
    ended_at: str | None = None
    status: str
    is_multi_character: bool = False
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


@router.get("/dialogue/sessions/player", response_model=list[SessionInfo])
def get_player_sessions(player_id: str):
    """获取玩家所有会话（单聊 + 群聊）"""
    sessions = repository.get_all_player_sessions(player_id)
    return [SessionInfo(**s) for s in sessions]


# =========================
# History
# =========================
@router.get("/dialogue/history", response_model=HistoryResponse)
def get_history(character_id: str, player_id: str, offset: int = 0, limit: int = 20, exclude_session_id: str | None = None):
    """分页获取跨会话历史消息（排除指定会话）"""

    messages, has_more = repository.get_messages_by_player_and_character(
        character_id=character_id,
        player_id=player_id,
        offset=offset,
        limit=limit,
        exclude_session_id=exclude_session_id,
    )

    # 尝试加载角色卡片（可能不存在于磁盘）
    current_affinity = 0
    current_mood = "neutral"
    try:
        card = character_loader.load_character_card(character_id)
        runtime_state = repository.get_runtime_state(
            character_id,
            player_id,
            card,
        )
        current_affinity = runtime_state.get("affection_level", 0)
        current_mood = runtime_state.get("current_mood", "neutral")
    except Exception:
        pass  # 角色卡片不存在时使用默认值

    return HistoryResponse(
        messages=[
            HistoryMessage(
                role=m["role"],
                content=m["content"],
                created_at=m.get("created_at"),
            )
            for m in messages
        ],
        has_more=has_more,
        current_affinity=current_affinity,
        current_mood=current_mood,
    )

# =========================
# Session end
# =========================
@router.post("/dialogue/session/end", response_model=SessionEndResponse)
def session_end(req: SessionEndRequest):
    """结束会话并生成摘要"""
    
    session = repository.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 检查会话是否已经结束
    if session.get("status") == "ended":
        # 获取已有的摘要
        existing_summary = repository.get_session_summary(req.session_id)
        return SessionEndResponse(
            session_id=req.session_id,
            summary=existing_summary.get("summary_text") if existing_summary else None,
            message_count=existing_summary.get("message_count", 0) if existing_summary else 0
        )
    
    # 获取完整对话历史
    history = repository.get_short_term_history(req.session_id, limit_turns=1000)
    
    # 生成摘要
    summary_text = None
    if len(history) > 0:
        try:
            summary_text = summarize_session(history)
        except Exception as e:
            print(f"[ERROR] summarize_session failed: {e}")
    
    # 保存摘要
    if summary_text:
        try:
            repository.save_session_summary(
                session_id=req.session_id,
                character_id=session["character_id"],
                player_id=session["player_id"],
                summary_text=summary_text,
                message_count=len(history)
            )
        except Exception as e:
            print(f"[ERROR] Failed to save summary: {e}")
    
    # 标记会话结束
    repository.end_session(req.session_id)
    
    return SessionEndResponse(
        session_id=req.session_id,
        summary=summary_text,
        message_count=len(history)
    )


# =========================
# Session summaries
# =========================
@router.get("/dialogue/summaries", response_model=list[SessionSummaryInfo])
def get_summaries(character_id: str, player_id: str, limit: int = 5):
    """获取角色与玩家的最近会话摘要"""
    
    summaries = repository.get_recent_summaries(
        character_id=character_id,
        player_id=player_id,
        limit=limit
    )
    
    return [SessionSummaryInfo(**s) for s in summaries]
