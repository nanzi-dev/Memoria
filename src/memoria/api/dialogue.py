"""
API 路由层

用途：
1. HTTP 参数校验
2. 调用 orchestrator
3. 返回标准 DTO
"""

from datetime import datetime, timedelta, timezone
import uuid

from pydantic import BaseModel, Field
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from memoria.core import character_loader, orchestrator, performance, world_clock
from memoria.core.memory_extractor import summarize_session
from memoria.core.locale import DEFAULT_LOCALE, Locale
from memoria.api.user import require_current_user_id
from memoria.api.knowledge_models import KnowledgeSource
from memoria.api.streaming import create_sse_response
from memoria.db import repository

router = APIRouter()
SUMMARY_MIN_MESSAGE_COUNT = 6


# =========================
# 请求模型
# =========================
class SessionStartRequest(BaseModel):
    character_id: str
    player_id: str
    player_name: str = "旅行者"
    locale: Locale = DEFAULT_LOCALE
    
class DialogueTurnRequest(BaseModel):
    session_id: str
    player_message: str
    request_id: str | None = None
    

# =========================
# 响应模型
# =========================
class HistoryMessage(BaseModel):
    session_id: str | None = None
    role: str
    content: str
    action: str | None = None
    affinity_delta: float | None = None
    trust_delta: float | None = None
    current_affinity: float | None = None
    current_trust: float | None = None
    current_mood: str | None = None
    event_notification: str | None = None
    created_at: str | None = None
    world_created_at: str | None = None
    message_id: int | None = None
    knowledge_sources: list[KnowledgeSource] = Field(default_factory=list)


class SessionStartResponse(BaseModel):
    session_id: str
    opening_line: str
    action: str
    current_affinity: float
    current_trust: float
    world_created_at: str | None = None
    assistant_message_id: int | None = None
    recovered: bool = False
    messages: list[HistoryMessage] = []
    locale: Locale = DEFAULT_LOCALE


class DialogueTurnResponse(BaseModel):
    dialogue: str
    action: str
    affinity_delta: float
    trust_delta: float = 0
    current_affinity: float
    current_trust: float
    current_mood: str
    triggered_events: list[dict] = []
    event_executions: list[dict] = []
    event_notifications: list[dict] = []
    event_notification: str | None = None
    user_message_id: int | None = None
    assistant_message_id: int | None = None
    world_created_at: str | None = None
    knowledge_sources: list[KnowledgeSource] = Field(default_factory=list)

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
    group_thread_id: str | None = None
    is_multi_character: bool = False
    last_message: str | None = None
    last_message_at: str | None = None
    latest_message_id: int | None = None
    message_count: int = 0
    unread_count: int = 0
    name: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    locale: Locale = DEFAULT_LOCALE


class HistoryResponse(BaseModel):
    messages: list[HistoryMessage]
    has_more: bool
    current_affinity: float
    current_trust: float
    current_mood: str
    locale: Locale = DEFAULT_LOCALE
    

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
    locale: Locale = DEFAULT_LOCALE


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


def _ensure_character_can_chat(character_id: str, player_id: str) -> None:
    if not repository.is_character_card_active(player_id, character_id):
        raise HTTPException(status_code=400, detail="角色卡已禁用，不能新建或继续单聊")


def _load_character_card(character_id: str, player_id: str, locale: Locale):
    try:
        return character_loader.load_character_card(character_id, player_id, locale)
    except TypeError as exc:
        if "positional" not in str(exc) and "unexpected keyword argument" not in str(exc):
            raise
        return character_loader.load_character_card(character_id, player_id)


def _current_character_state(
    character_id: str,
    player_id: str,
    locale: Locale = DEFAULT_LOCALE,
) -> tuple[int, int, str]:
    current_affinity = 0
    current_trust = 0
    current_mood = "neutral"
    try:
        card = _load_character_card(character_id, player_id, locale)
        runtime_state = repository.get_runtime_state(character_id, player_id, card)
        current_affinity = runtime_state.get("affection_level", 0)
        current_trust = runtime_state.get("trust_level", 0)
        current_mood = runtime_state.get("current_mood", "neutral")
    except Exception:
        pass
    return current_affinity, current_trust, current_mood


def _start_empty_session(
    character_id: str,
    player_id: str,
    player_name: str,
    locale: Locale,
) -> SessionStartResponse:
    """创建会话但不阻塞等待开场白生成。"""
    try:
        player_character = repository.get_or_create_user_character_card(player_id)
    except Exception:
        player_character = None
    if player_character:
        player_name = player_character.get("display_name") or player_name
    _ensure_character_can_chat(character_id, player_id)
    card = _load_character_card(character_id, player_id, locale)
    runtime_state = repository.get_runtime_state(character_id, player_id, card)
    world_created_at = world_clock.get_clock_snapshot(player_id).world_now.isoformat()
    session_id = str(uuid.uuid4())
    active_session, created = repository.get_or_create_active_session(
        session_id=session_id,
        character_id=character_id,
        player_id=player_id,
        player_name=player_name,
        locale=locale,
    )
    if not created:
        return _recovered_session_response(
            active_session,
            character_id=character_id,
            player_id=player_id,
        )
    return SessionStartResponse(
        session_id=active_session["session_id"],
        opening_line="",
        action="",
        current_affinity=runtime_state.get("affection_level", 0),
        current_trust=runtime_state.get("trust_level", 0),
        world_created_at=world_created_at,
        assistant_message_id=None,
        recovered=False,
        messages=[],
        locale=locale,
    )


def _recovered_session_response(
    active_session: dict,
    *,
    character_id: str,
    player_id: str,
) -> SessionStartResponse:
    locale = active_session.get("locale") or DEFAULT_LOCALE
    current_affinity, current_trust, _ = _current_character_state(
        character_id,
        player_id,
        locale,
    )
    messages = _messages_for_session(active_session["session_id"])
    world_created_at = next(
        (
            message.world_created_at
            for message in reversed(messages)
            if message.world_created_at
        ),
        None,
    )
    if world_created_at is None:
        world_created_at = world_clock.get_clock_snapshot(player_id).world_now.isoformat()
    return SessionStartResponse(
        session_id=active_session["session_id"],
        opening_line="",
        action="",
        current_affinity=current_affinity,
        current_trust=current_trust,
        world_created_at=world_created_at,
        assistant_message_id=None,
        recovered=True,
        messages=messages,
        locale=locale,
    )


def _generate_session_summary(session_id: str) -> None:
    """后台生成会话摘要，避免阻塞聊天启动/关闭请求。"""
    session = repository.get_session(session_id)
    if not session:
        return

    history = repository.get_short_term_history(session_id, limit_turns=1000)
    if len(history) <= SUMMARY_MIN_MESSAGE_COUNT:
        return
    existing_summary = repository.get_session_summary(session_id)
    if (
        existing_summary
        and existing_summary.get("summary_status") == "completed"
        and str(existing_summary.get("summary_text") or "").strip()
        and existing_summary.get("message_count") == len(history)
    ):
        performance.increment("llm.calls_avoided.summary_reuse")
        return

    try:
        summary_text = summarize_session(history)
    except Exception as e:
        print(f"[ERROR] summarize_session failed: {e}")
        return

    summary_text = str(summary_text or "").strip()
    if not summary_text:
        return

    try:
        repository.save_session_summary(
            session_id=session_id,
            character_id=session["character_id"],
            player_id=session["player_id"],
            summary_text=summary_text,
            message_count=len(history),
            summary_status="completed"
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

    repository.end_session(session_id)

    if len(history) > SUMMARY_MIN_MESSAGE_COUNT and background_tasks is not None:
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
def list_characters(current_user_id: str = Depends(require_current_user_id)):
    """获取所有角色摘要"""
    
    results = []
    
    for cid in character_loader.list_character_ids(current_user_id):
        try:
            card = character_loader.load_character_card(cid, current_user_id)
            
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
            return _recovered_session_response(
                active_session,
                character_id=req.character_id,
                player_id=req.player_id,
            )

        return _start_empty_session(
            req.character_id, req.player_id, req.player_name, req.locale
        )
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
        session = _get_owned_session(req.session_id, current_user_id)
        _ensure_character_can_chat(session["character_id"], session["player_id"])
        result = orchestrator.run_dialogue_turn(
            req.session_id,
            req.player_message,
            request_id=req.request_id,
        )
        return DialogueTurnResponse(**result)

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except repository.DialogueTurnConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/dialogue/turn/stream")
async def dialogue_turn_stream(
    req: DialogueTurnRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    session = _get_owned_session(req.session_id, current_user_id)
    _ensure_character_can_chat(session["character_id"], session["player_id"])
    request_id = req.request_id or uuid.uuid4().hex

    def worker(event_sink):
        return orchestrator.run_dialogue_turn(
            req.session_id,
            req.player_message,
            request_id=request_id,
            event_sink=event_sink,
        )

    return create_sse_response(
        worker,
        started_data={
            "session_id": req.session_id,
            "request_id": request_id,
            "turn_kind": "single",
        },
        completion_mapper=lambda result: DialogueTurnResponse(
            **result
        ).model_dump(mode="json"),
    )

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
        locale=session.get("locale") or DEFAULT_LOCALE,
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
    locale = repository.get_latest_session_locale(
        character_id,
        player_id,
        preferred_session_id=exclude_session_id,
    )
    current_affinity, current_trust, current_mood = _current_character_state(
        character_id, player_id, locale
    )

    return HistoryResponse(
        messages=[HistoryMessage(**m) for m in messages],
        has_more=has_more,
        current_affinity=current_affinity,
        current_trust=current_trust,
        current_mood=current_mood,
        locale=locale,
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
