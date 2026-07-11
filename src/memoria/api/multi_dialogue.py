"""
多角色对话 API

提供多角色群聊功能的 RESTful 接口
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
import logging
import uuid

from memoria.core import multi_character_memory
from memoria.core.multi_character_orchestrator import (
    start_multi_character_session,
    process_multi_character_turn,
    MultiCharacterOrchestrator
)
from memoria.api.user import require_current_user_id
from memoria.db import repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/multi-dialogue")

SUMMARY_CHUNK_MESSAGE_LIMIT = 80


# =========================
# 请求/响应模型
# =========================

class StartMultiSessionRequest(BaseModel):
    """开始多角色会话请求"""
    player_id: str = Field(..., description="玩家ID")
    player_name: str = Field(..., description="玩家名称")
    group_name: Optional[str] = Field(None, description="群聊名称")
    character_ids: list[str] = Field(..., min_items=2, description="参与角色ID列表（至少2个）")


class StartMultiSessionResponse(BaseModel):
    """开始多角色会话响应"""
    session_id: str
    group_name: Optional[str] = None
    group_thread_id: Optional[str] = None
    opening: dict = Field(..., description="开场白信息")


class MultiDialogueTurnRequest(BaseModel):
    """多角色对话轮次请求"""
    session_id: str = Field(..., description="会话ID")
    player_message: str = Field(..., description="玩家消息")
    discussion_mode: bool = Field(
        True,
        description="是否启用群聊接话，普通群聊默认启用"
    )
    max_responses: Optional[int] = Field(
        None,
        ge=1,
        le=5,
        description="群聊接话人数上限；不传时按语境动态决定"
    )


class MultiDialogueTurnResponse(BaseModel):
    """多角色对话轮次响应"""
    character_id: str
    character_name: str
    dialogue: str
    action: str
    affinity_delta: Optional[float] = None
    trust_delta: Optional[float] = None
    current_affinity: Optional[float] = None
    current_trust: Optional[float] = None
    current_mood: Optional[str] = None


class MultiDialogueGroupResponse(BaseModel):
    """多角色群体讨论响应（讨论模式）"""
    responses: list[MultiDialogueTurnResponse] = Field(..., description="所有角色的回应列表")
    total_speakers: int = Field(..., description="发言角色数量")
    discussion_mode: bool = Field(True, description="群聊接话标识")


class TriggerInteractionRequest(BaseModel):
    """触发角色互动请求"""
    session_id: str
    trigger_character_id: Optional[str] = Field(
        None,
        description="触发角色ID，留空则自动选择"
    )
    prompt: Optional[str] = Field(None, description="主动发言提示")


class EndMultiSessionRequest(BaseModel):
    """结束多角色会话请求"""
    session_id: str


class SessionParticipant(BaseModel):
    """会话参与者信息"""
    character_id: str
    name: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    join_order: int
    speak_frequency: float
    is_active: bool
    message_count: int
    last_spoke_at: Optional[str] = None


class MultiSessionInfo(BaseModel):
    """多角色会话信息"""
    session_id: str
    player_id: str
    player_name: str
    group_name: Optional[str] = None
    group_thread_id: Optional[str] = None
    created_at: str
    status: str
    participants: list[SessionParticipant]


class ContinueMultiSessionResponse(BaseModel):
    """继续群聊会话响应"""
    session_id: str
    group_name: Optional[str] = None
    group_thread_id: str
    status: str
    participants: list[SessionParticipant]


class MultiDialogueHistory(BaseModel):
    """多角色对话历史"""
    messages: list[dict]
    session_info: dict


def _chunk_messages(messages: list[dict], chunk_size: int = SUMMARY_CHUNK_MESSAGE_LIMIT) -> list[list[dict]]:
    """按消息数切分长会话，避免一次摘要超过模型上下文。"""
    if chunk_size <= 0:
        return [messages]
    return [messages[i:i + chunk_size] for i in range(0, len(messages), chunk_size)]


def _require_player_access(player_id: str, current_user_id: str) -> None:
    if player_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该玩家的群聊")


def _get_owned_multi_session(session_id: str, current_user_id: str) -> dict:
    session = repository.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    _require_player_access(session["player_id"], current_user_id)
    if not session.get("is_multi_character"):
        raise HTTPException(status_code=400, detail="该会话不是多角色会话")
    return session


def _generate_bounded_session_summary(
    session_id: str,
    messages: list[dict],
    character_names: dict[str, str],
    player_name: str,
) -> str:
    """长会话先分块摘要，再合并为最终群聊摘要。"""
    chunks = _chunk_messages(messages)
    if len(chunks) <= 1:
        return multi_character_memory.generate_multi_character_summary(
            session_id=session_id,
            messages=messages,
            character_names=character_names,
            player_name=player_name,
        ).strip()

    chunk_summaries = []
    for index, chunk in enumerate(chunks, start=1):
        summary = multi_character_memory.generate_multi_character_summary(
            session_id=f"{session_id}:chunk:{index}",
            messages=chunk,
            character_names=character_names,
            player_name=player_name,
        ).strip()
        if summary:
            chunk_summaries.append(summary)

    if not chunk_summaries:
        return ""

    summary_character_id = next(iter(character_names), "summary")
    merge_messages = [
        {
            "role": "assistant",
            "character_id": summary_character_id,
            "content": f"第{index}段摘要：{summary}",
        }
        for index, summary in enumerate(chunk_summaries, start=1)
    ]
    return multi_character_memory.generate_multi_character_summary(
        session_id=session_id,
        messages=merge_messages,
        character_names=character_names,
        player_name=player_name,
    ).strip()


def _save_session_summary_on_end(session_id: str, session: dict) -> None:
    """结束多角色会话时，将整场群聊统一摘要后保存。"""
    existing_summary = repository.get_session_summary(session_id)
    if existing_summary and existing_summary.get("summary_status") == "completed":
        summary_text = str(existing_summary.get("summary_text") or "").strip()
        if summary_text:
            logger.info(f"多角色会话摘要已存在，跳过重复保存: session={session_id}")
            return

    messages = repository.get_multi_character_history(session_id, limit_messages=None)
    meaningful_messages = [m for m in messages if str(m.get("content") or "").strip()]
    if not meaningful_messages:
        logger.info(f"多角色会话无可摘要消息，跳过保存: session={session_id}")
        return

    participants = repository.get_session_participants(session_id, only_active=False)
    character_ids = [p["character_id"] for p in participants if p.get("character_id")]
    if not character_ids:
        logger.info(f"多角色会话无参与角色，跳过摘要保存: session={session_id}")
        return

    character_names = {
        p["character_id"]: p.get("display_name") or p.get("name") or p["character_id"]
        for p in participants
        if p.get("character_id")
    }
    summary = _generate_bounded_session_summary(
        session_id=session_id,
        messages=meaningful_messages,
        character_names=character_names,
        player_name=session.get("player_name") or "玩家",
    )
    if not summary:
        raise RuntimeError("多角色会话摘要为空")

    multi_character_memory.save_multi_character_summary(
        session_id=session_id,
        character_ids=character_ids,
        player_id=session["player_id"],
        summary_text=summary,
        message_count=len(meaningful_messages),
    )


def _save_multi_summary_placeholder(session_id: str, session: dict, summary_status: str) -> int:
    """为后台群聊摘要写入占位状态，返回有效消息数。"""
    messages = repository.get_multi_character_history(session_id, limit_messages=None)
    meaningful_messages = [m for m in messages if str(m.get("content") or "").strip()]
    if not meaningful_messages:
        return 0

    participants = repository.get_session_participants(session_id, only_active=False)
    character_ids = [p["character_id"] for p in participants if p.get("character_id")]
    for character_id in character_ids:
        repository.save_session_summary(
            session_id=session_id,
            character_id=character_id,
            player_id=session["player_id"],
            summary_text="",
            message_count=len(meaningful_messages),
            summary_status=summary_status,
        )
    return len(meaningful_messages)


def _generate_multi_session_summary_task(session_id: str, session: dict) -> None:
    """后台生成群聊摘要；失败不影响会话结束状态。"""
    try:
        _save_session_summary_on_end(session_id, session)
    except Exception as e:
        logger.error(f"后台生成多角色摘要失败: session={session_id}, error={e}", exc_info=True)
        try:
            _save_multi_summary_placeholder(session_id, session, "failed")
        except Exception as save_error:
            logger.error(f"标记多角色摘要失败状态失败: session={session_id}, error={save_error}", exc_info=True)


def finish_multi_character_session(
    session_id: str,
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    """快速结束多角色会话，并把摘要生成交给后台任务。"""
    session = repository.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    if not session.get("is_multi_character"):
        raise HTTPException(status_code=400, detail="该会话不是多角色会话")

    message_count = 0
    existing_summary = repository.get_session_summary(session_id)
    has_completed_summary = (
        existing_summary
        and existing_summary.get("summary_status") == "completed"
        and str(existing_summary.get("summary_text") or "").strip()
    )
    if not has_completed_summary:
        try:
            message_count = _save_multi_summary_placeholder(session_id, session, "generating")
        except Exception as e:
            logger.error(f"写入多角色摘要占位失败: session={session_id}, error={e}", exc_info=True)

    if session.get("status") != "ended":
        repository.end_session(session_id)

    if not has_completed_summary and message_count > 0:
        if background_tasks is not None:
            background_tasks.add_task(_generate_multi_session_summary_task, session_id, session)
        else:
            _generate_multi_session_summary_task(session_id, session)

    return {
        "success": True,
        "message": "多角色会话已结束" if session.get("status") != "ended" else "会话已经是结束状态",
        "session_id": session_id,
    }


# =========================
# API 端点
# =========================

@router.post("/session/start", response_model=StartMultiSessionResponse)
async def start_multi_session(
    request: StartMultiSessionRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    开始多角色群聊会话
    
    创建一个新的多角色对话会话，支持2个或更多NPC同时参与。
    
    - **player_id**: 玩家唯一标识
    - **player_name**: 玩家显示名称
    - **character_ids**: 参与的角色ID列表（至少2个）
    返回会话ID和第一个角色的开场白。
    """
    try:
        _require_player_access(request.player_id, current_user_id)
        logger.info(f"开始多角色会话: player={request.player_id}, characters={request.character_ids}")
        
        # 验证角色ID
        if len(request.character_ids) < 2:
            raise HTTPException(
                status_code=400,
                detail="多角色会话至少需要2个角色"
            )

        clean_group_name = (request.group_name or "").strip()
        if clean_group_name and repository.player_group_name_exists(request.player_id, clean_group_name):
            raise HTTPException(status_code=400, detail="群聊名称已存在，请换一个名称")
        
        # 创建会话
        result = start_multi_character_session(
            player_id=request.player_id,
            player_name=request.player_name,
            character_ids=request.character_ids,
            group_name=clean_group_name or request.group_name,
        )
        
        return StartMultiSessionResponse(
            session_id=result["session_id"],
            group_name=result.get("group_name"),
            group_thread_id=result.get("group_thread_id"),
            opening=result["opening"]
        )
    
    except HTTPException:
        raise

    except ValueError as e:
        logger.error(f"创建多角色会话失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    
    except Exception as e:
        logger.error(f"创建多角色会话异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/turn")
async def multi_dialogue_turn(
    request: MultiDialogueTurnRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    处理多角色对话轮次
    
    玩家发送消息后，系统会模拟普通群聊，选择少量角色接话。
    
    - **session_id**: 会话ID
    - **player_message**: 玩家消息内容
    - **discussion_mode**: 是否启用群聊接话，默认启用
    - **max_responses**: 可选的人数上限；不传时按语境动态决定
    
    返回选中角色的回应（单个或多个）。
    """
    try:
        logger.info(f"处理多角色对话: session={request.session_id}, discussion={request.discussion_mode}")
        
        # 验证会话
        session = _get_owned_multi_session(request.session_id, current_user_id)
        
        if session.get("status") != "active":
            raise HTTPException(status_code=400, detail="会话已结束")
        
        # 处理对话
        result = process_multi_character_turn(
            session_id=request.session_id,
            player_message=request.player_message,
            discussion_mode=request.discussion_mode,
            max_responses=request.max_responses
        )
        
        # 根据是否为讨论模式返回不同格式
        if request.discussion_mode:
            # 讨论模式：返回多个角色的回应
            if isinstance(result, list):
                return MultiDialogueGroupResponse(
                    responses=[MultiDialogueTurnResponse(**r) for r in result],
                    total_speakers=len(result),
                    discussion_mode=True
                )
            else:
                # 如果只有一个回应，也包装成列表
                return MultiDialogueGroupResponse(
                    responses=[MultiDialogueTurnResponse(**result)],
                    total_speakers=1,
                    discussion_mode=True
                )
        else:
            # 单角色模式：返回单个回应
            return MultiDialogueTurnResponse(**result)
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"处理多角色对话异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/interaction/trigger")
async def trigger_interaction(
    request: TriggerInteractionRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    触发角色间互动
    
    让角色主动发言，而不是回应玩家消息。可用于：
    - 角色间的自发对话
    - 场景氛围营造
    - 推进剧情
    
    - **session_id**: 会话ID
    - **trigger_character_id**: 指定触发角色（可选，留空则自动选择）
    
    返回角色的主动发言。
    """
    try:
        logger.info(f"触发角色互动: session={request.session_id}")
        
        # 验证会话
        _get_owned_multi_session(request.session_id, current_user_id)
        
        # 触发互动
        orchestrator = MultiCharacterOrchestrator(request.session_id)
        result = orchestrator.trigger_character_interaction(
            trigger_character_id=request.trigger_character_id,
            prompt=request.prompt,
        )
        
        return result
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"触发角色互动异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/session/{session_id}", response_model=MultiSessionInfo)
async def get_multi_session_info(
    session_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    获取多角色会话信息
    
    返回会话详情和所有参与者信息。
    """
    try:
        # 获取会话
        session = _get_owned_multi_session(session_id, current_user_id)
        
        # 获取参与者
        participants = repository.get_session_participants(session_id, only_active=False)
        
        return MultiSessionInfo(
            session_id=session["session_id"],
            player_id=session["player_id"],
            player_name=session["player_name"],
            group_name=session.get("group_name"),
            group_thread_id=session.get("group_thread_id") or session["session_id"],
            created_at=session["created_at"],
            status=session["status"],
            participants=[SessionParticipant(**p) for p in participants]
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"获取会话信息异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/session/{session_id}/continue", response_model=ContinueMultiSessionResponse)
async def continue_multi_session(
    session_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    """从已结束的群聊段继续，创建同一逻辑群聊的新 active session。"""
    try:
        source_session = _get_owned_multi_session(session_id, current_user_id)
        thread_sessions = repository.get_multi_character_thread_sessions(session_id)

        active_session = next(
            (s for s in reversed(thread_sessions) if s.get("status") == "active"),
            None,
        )
        if active_session:
            target_session_id = active_session["session_id"]
            participants = repository.get_session_participants(target_session_id, only_active=False)
            return ContinueMultiSessionResponse(
                session_id=target_session_id,
                group_name=active_session.get("group_name") or source_session.get("group_name"),
                group_thread_id=active_session.get("group_thread_id") or source_session.get("group_thread_id") or session_id,
                status="active",
                participants=[SessionParticipant(**p) for p in participants],
            )

        participants = repository.get_session_participants(session_id, only_active=False)
        character_ids = [p["character_id"] for p in participants if p.get("character_id")]
        if len(character_ids) < 2:
            raise HTTPException(status_code=400, detail="群聊至少需要2个角色才能继续")

        new_session_id = str(uuid.uuid4())
        group_thread_id = source_session.get("group_thread_id") or source_session["session_id"]
        ok = repository.create_multi_character_session(
            session_id=new_session_id,
            player_id=source_session["player_id"],
            player_name=source_session["player_name"],
            character_ids=character_ids,
            group_name=source_session.get("group_name"),
            group_thread_id=group_thread_id,
        )
        if not ok:
            raise HTTPException(status_code=500, detail="继续群聊失败")

        new_participants = repository.get_session_participants(new_session_id, only_active=False)
        return ContinueMultiSessionResponse(
            session_id=new_session_id,
            group_name=source_session.get("group_name"),
            group_thread_id=group_thread_id,
            status="active",
            participants=[SessionParticipant(**p) for p in new_participants],
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"继续群聊异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/history/{session_id}", response_model=MultiDialogueHistory)
async def get_multi_dialogue_history(
    session_id: str,
    limit: int = Query(50, ge=1, le=200, description="消息数量限制"),
    current_user_id: str = Depends(require_current_user_id),
):
    """
    获取多角色对话历史
    
    返回会话的完整对话记录，包含每条消息的发言者信息。
    
    - **session_id**: 会话ID
    - **limit**: 返回的最大消息数（默认50，最多200）
    """
    try:
        # 验证会话
        session = _get_owned_multi_session(session_id, current_user_id)
        
        # 获取同一逻辑群聊下的跨 session 历史
        messages = repository.get_multi_character_thread_history(session_id, limit_messages=limit)
        
        # 获取参与者信息
        participants = repository.get_session_participants(session_id, only_active=False)
        
        return MultiDialogueHistory(
            messages=messages,
            session_info={
                "session_id": session["session_id"],
                "current_session_id": session["session_id"],
                "group_thread_id": session.get("group_thread_id") or session["session_id"],
                "player_name": session["player_name"],
                "group_name": session.get("group_name"),
                "created_at": session["created_at"],
                "status": session["status"],
                "participants": participants,
                "sessions": repository.get_multi_character_thread_sessions(session_id),
            }
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"获取对话历史异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/session/end")
async def end_multi_session(
    request: EndMultiSessionRequest,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    结束多角色会话
    
    标记会话为已结束状态。
    
    - **session_id**: 会话ID
    """
    try:
        session_id = request.session_id
        logger.info(f"结束多角色会话: session={session_id}")
        _get_owned_multi_session(session_id, current_user_id)
        
        return finish_multi_character_session(session_id, background_tasks)
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"结束会话异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")
