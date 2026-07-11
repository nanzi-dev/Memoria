"""
API 路由层

用途：
1. HTTP 参数校验
2. 调用 orchestrator
3. 返回标准 DTO
"""

from datetime import datetime, timedelta, timezone
import uuid

from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from memoria.core import character_loader, orchestrator
from memoria.core.memory_extractor import summarize_session
from memoria.api.user import require_current_user_id
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
class HistoryMessage(BaseModel):
    role: str
    content: str
    created_at: str | None = None
    message_id: int | None = None


class SessionStartResponse(BaseModel):
    session_id: str
    opening_line: str
    action: str
    current_affinity: int
    current_trust: int
    assistant_message_id: int | None = None
    recovered: bool = False
    messages: list[HistoryMessage] = []


class DialogueTurnResponse(BaseModel):
    dialogue: str
    action: str
    affinity_delta: int
    trust_delta: int = 0
    current_affinity: int
    current_trust: int
    current_mood: str
    triggered_events: list[dict] = []
    event_notification: str | None = None
    user_message_id: int | None = None
    assistant_message_id: int | None = None

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
    group_name: str | None = None
    is_multi_character: bool = False
    last_message: str | None = None
    last_message_at: str | None = None
    message_count: int = 0
    name: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None


class HistoryResponse(BaseModel):
    messages: list[HistoryMessage]
    has_more: bool
    current_affinity: int
    current_trust: int
    current_mood: str
    

# =========================
# Session recovery（断线恢复）
# =========================
class SessionRecoveryResponse(BaseModel):
    """恢复最近 active session 的响应"""
    found: bool = False
    session_id: str | None = None
    character_id: str | None = None
    character: dict | None = None  # 角色摘要信息
    messages: list[HistoryMessage] = []


IDLE_SESSION_TIMEOUT = timedelta(minutes=5)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _session_activity_at(session: dict) -> datetime | None:
    return _parse_iso_datetime(session.get("last_message_at") or session.get("created_at"))


def _messages_for_session(session_id: str, limit: int = 100) -> list[HistoryMessage]:
    messages, _ = repository.get_messages_paginated(session_id, offset=0, limit=limit)
    return [HistoryMessage(**m) for m in messages]


def _current_character_state(character_id: str, player_id: str) -> tuple[int, int, str]:
    current_affinity = 0
    current_trust = 0
    current_mood = "neutral"
    try:
        card = character_loader.load_character_card(character_id)
        runtime_state = repository.get_runtime_state(character_id, player_id, card)
        current_affinity = runtime_state.get("affection_level", 0)
        current_trust = runtime_state.get("trust_level", 0)
        current_mood = runtime_state.get("current_mood", "neutral")
    except Exception:
        pass
    return current_affinity, current_trust, current_mood


def _start_empty_session(character_id: str, player_id: str, player_name: str) -> SessionStartResponse:
    """创建会话但不阻塞等待开场白生成。"""
    card = character_loader.load_character_card(character_id)
    runtime_state = repository.get_runtime_state(character_id, player_id, card)
    session_id = str(uuid.uuid4())
    repository.create_session(session_id, character_id, player_id, player_name)
    return SessionStartResponse(
        session_id=session_id,
        opening_line="",
        action="",
        current_affinity=runtime_state.get("affection_level", 0),
        current_trust=runtime_state.get("trust_level", 0),
        assistant_message_id=None,
        recovered=False,
        messages=[],
    )


def _generate_session_summary(session_id: str) -> None:
    """后台生成会话摘要，避免阻塞聊天启动/关闭请求。"""
    session = repository.get_session(session_id)
    if not session:
        return

    history = repository.get_short_term_history(session_id, limit_turns=1000)
    if len(history) == 0:
        return

    summary_text = None
    summary_status = "failed"
    try:
        summary_text = summarize_session(history)
        if summary_text:
            summary_status = "completed"
    except Exception as e:
        print(f"[ERROR] summarize_session failed: {e}")

    try:
        repository.save_session_summary(
            session_id=session_id,
            character_id=session["character_id"],
            player_id=session["player_id"],
            summary_text=summary_text or "",
            message_count=len(history),
            summary_status=summary_status
        )
    except Exception as e:
        print(f"[ERROR] Failed to save summary: {e}")


def _end_session(session_id: str, background_tasks: BackgroundTasks | None = None) -> SessionEndResponse:
    """快速结束会话，并把摘要生成交给后台任务。"""
    session = repository.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    if session.get("is_multi_character"):
        from memoria.api.multi_dialogue import finish_multi_character_session
        result = finish_multi_character_session(session_id, background_tasks)
        summary = repository.get_session_summary(session_id)
        return SessionEndResponse(
            session_id=result["session_id"],
            summary=summary.get("summary_text") if summary and summary.get("summary_status") == "completed" else None,
            message_count=summary.get("message_count", 0) if summary else 0,
        )

    if session.get("status") == "ended":
        existing_summary = repository.get_session_summary(session_id)
        return SessionEndResponse(
            session_id=session_id,
            summary=existing_summary.get("summary_text") if existing_summary else None,
            message_count=existing_summary.get("message_count", 0) if existing_summary else 0
        )

    history = repository.get_short_term_history(session_id, limit_turns=1000)

    if len(history) > 0:
        repository.save_session_summary(
            session_id=session_id,
            character_id=session["character_id"],
            player_id=session["player_id"],
            summary_text="",
            message_count=len(history),
            summary_status="generating"
        )

    repository.end_session(session_id)

    if len(history) > 0 and background_tasks is not None:
        background_tasks.add_task(_generate_session_summary, session_id)

    return SessionEndResponse(
        session_id=session_id,
        summary=None,
        message_count=len(history)
    )


def _close_idle_sessions(player_id: str, background_tasks: BackgroundTasks | None = None) -> None:
    """懒清理：进入列表/恢复前关闭 5 分钟未活跃的 active session。"""
    now = datetime.now(timezone.utc)
    for session in repository.get_all_player_sessions(player_id):
        if session.get("status") != "active":
            continue
        activity_at = _session_activity_at(session)
        if activity_at is None:
            continue
        if activity_at.tzinfo is None:
            activity_at = activity_at.replace(tzinfo=timezone.utc)
        if now - activity_at >= IDLE_SESSION_TIMEOUT:
            try:
                _end_session(session["session_id"], background_tasks)
            except Exception as e:
                print(f"[ERROR] Failed to close idle session {session.get('session_id')}: {e}")


def _require_player_access(player_id: str, current_user_id: str) -> None:
    if player_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该玩家的对话")


def _get_owned_session(session_id: str, current_user_id: str) -> dict:
    session = repository.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    _require_player_access(session["player_id"], current_user_id)
    return session


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
def session_start(
    req: SessionStartRequest,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(require_current_user_id),
):
    try:
        _require_player_access(req.player_id, current_user_id)
        _close_idle_sessions(req.player_id, background_tasks)
        active_session = repository.get_latest_active_session(req.player_id, req.character_id)
        if active_session:
            current_affinity, current_trust, _ = _current_character_state(req.character_id, req.player_id)
            return SessionStartResponse(
                session_id=active_session["session_id"],
                opening_line="",
                action="",
                current_affinity=current_affinity,
                current_trust=current_trust,
                assistant_message_id=None,
                recovered=True,
                messages=_messages_for_session(active_session["session_id"]),
            )

        return _start_empty_session(req.character_id, req.player_id, req.player_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

# =========================
# Dialogue turn
# =========================
@router.post("/dialogue/turn", response_model=DialogueTurnResponse)
def dialogue_turn(
    req: DialogueTurnRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    try:
        _get_owned_session(req.session_id, current_user_id)
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
def get_sessions(
    character_id: str,
    player_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    """获取玩家与角色的所有会话"""
    _require_player_access(player_id, current_user_id)

    sessions = repository.get_sessions_by_player_and_character(
        character_id,
        player_id
    )

    # SQLite Row → dict 安全转换
    return [SessionInfo(**dict(s)) for s in sessions]


@router.get("/dialogue/sessions/player", response_model=list[SessionInfo])
def get_player_sessions(
    player_id: str,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(require_current_user_id),
):
    """获取玩家所有会话（单聊 + 群聊）"""
    _require_player_access(player_id, current_user_id)
    _close_idle_sessions(player_id, background_tasks)
    sessions = repository.get_all_player_sessions(player_id)
    return [SessionInfo(**s) for s in sessions]


# =========================
# Session recovery
# =========================
@router.get("/dialogue/session/latest", response_model=SessionRecoveryResponse)
def latest_session(
    background_tasks: BackgroundTasks,
    player_id: str,
    character_id: str | None = None,
    current_user_id: str = Depends(require_current_user_id),
):
    """恢复最近 active session。"""
    _require_player_access(player_id, current_user_id)
    _close_idle_sessions(player_id, background_tasks)
    session = repository.get_latest_active_session(player_id, character_id)
    if not session:
        return SessionRecoveryResponse(found=False)

    return SessionRecoveryResponse(
        found=True,
        session_id=session["session_id"],
        character_id=session["character_id"],
        messages=_messages_for_session(session["session_id"]),
    )


# =========================
# History
# =========================
@router.get("/dialogue/history", response_model=HistoryResponse)
def get_history(
    character_id: str,
    player_id: str,
    offset: int = 0,
    limit: int = 20,
    exclude_session_id: str | None = None,
    current_user_id: str = Depends(require_current_user_id),
):
    """分页获取跨会话历史消息（排除指定会话）"""
    _require_player_access(player_id, current_user_id)

    messages, has_more = repository.get_messages_by_player_and_character(
        character_id=character_id,
        player_id=player_id,
        offset=offset,
        limit=limit,
        exclude_session_id=exclude_session_id,
    )

    # 尝试加载角色卡片（可能不存在于磁盘）
    current_affinity, current_trust, current_mood = _current_character_state(character_id, player_id)

    return HistoryResponse(
        messages=[
            HistoryMessage(
                role=m["role"],
                content=m["content"],
                created_at=m.get("created_at"),
                message_id=m.get("message_id"),
            )
            for m in messages
        ],
        has_more=has_more,
        current_affinity=current_affinity,
        current_trust=current_trust,
        current_mood=current_mood,
    )

# =========================
# Session end
# =========================
@router.post("/dialogue/session/end", response_model=SessionEndResponse)
def session_end(
    req: SessionEndRequest,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(require_current_user_id),
):
    """结束会话并生成摘要"""
    _get_owned_session(req.session_id, current_user_id)
    return _end_session(req.session_id, background_tasks)


# =========================
# Session summaries
# =========================
@router.get("/dialogue/summaries", response_model=list[SessionSummaryInfo])
def get_summaries(
    character_id: str,
    player_id: str,
    limit: int = 5,
    current_user_id: str = Depends(require_current_user_id),
):
    """获取角色与玩家的最近会话摘要"""
    _require_player_access(player_id, current_user_id)
    
    summaries = repository.get_recent_summaries(
        character_id=character_id,
        player_id=player_id,
        limit=limit
    )
    
    return [SessionSummaryInfo(**s) for s in summaries]
