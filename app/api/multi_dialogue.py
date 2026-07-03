"""
多角色对话 API

提供多角色群聊功能的 RESTful 接口
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
import logging

from app.core.multi_character_orchestrator import (
    start_multi_character_session,
    process_multi_character_turn,
    MultiCharacterOrchestrator
)
from app.db import repository

logger = logging.getLogger(__name__)

router = APIRouter()


# =========================
# 请求/响应模型
# =========================

class StartMultiSessionRequest(BaseModel):
    """开始多角色会话请求"""
    player_id: str = Field(..., description="玩家ID")
    player_name: str = Field(..., description="玩家名称")
    character_ids: list[str] = Field(..., min_items=2, description="参与角色ID列表（至少2个）")
    speak_frequencies: Optional[dict[str, float]] = Field(
        None, 
        description="角色发言频率配置 {character_id: frequency}"
    )
    strategy_type: str = Field(
        "hybrid",
        description="发言策略类型：round_robin/weighted/smart/trigger/hybrid"
    )


class StartMultiSessionResponse(BaseModel):
    """开始多角色会话响应"""
    session_id: str
    strategy_type: str
    opening: dict = Field(..., description="开场白信息")


class MultiDialogueTurnRequest(BaseModel):
    """多角色对话轮次请求"""
    session_id: str = Field(..., description="会话ID")
    player_message: str = Field(..., description="玩家消息")
    strategy_type: str = Field(
        "hybrid",
        description="发言策略类型"
    )
    discussion_mode: bool = Field(
        False, 
        description="是否启用讨论模式（多角色连续发言）"
    )
    max_responses: int = Field(
        3, 
        ge=1, 
        le=5, 
        description="讨论模式下最多几个角色回应"
    )


class MultiDialogueTurnResponse(BaseModel):
    """多角色对话轮次响应"""
    character_id: str
    character_name: str
    dialogue: str
    action: str
    affinity_delta: Optional[float] = None
    current_affinity: Optional[float] = None
    current_mood: Optional[str] = None


class MultiDialogueGroupResponse(BaseModel):
    """多角色群体讨论响应（讨论模式）"""
    responses: list[MultiDialogueTurnResponse] = Field(..., description="所有角色的回应列表")
    total_speakers: int = Field(..., description="发言角色数量")
    discussion_mode: bool = Field(True, description="讨论模式标识")


class AddParticipantRequest(BaseModel):
    """添加参与者请求"""
    session_id: str
    character_id: str
    speak_frequency: float = Field(1.0, ge=0.0, le=2.0)


class UpdateParticipantRequest(BaseModel):
    """更新参与者配置请求"""
    session_id: str
    character_id: str
    speak_frequency: Optional[float] = Field(None, ge=0.0, le=2.0)
    is_active: Optional[bool] = None


class TriggerInteractionRequest(BaseModel):
    """触发角色互动请求"""
    session_id: str
    trigger_character_id: Optional[str] = Field(
        None,
        description="触发角色ID，留空则自动选择"
    )


class SessionParticipant(BaseModel):
    """会话参与者信息"""
    character_id: str
    name: str
    display_name: Optional[str]
    join_order: int
    speak_frequency: float
    is_active: bool
    message_count: int
    last_spoke_at: Optional[str]


class MultiSessionInfo(BaseModel):
    """多角色会话信息"""
    session_id: str
    player_id: str
    player_name: str
    created_at: str
    status: str
    participants: list[SessionParticipant]


class MultiDialogueHistory(BaseModel):
    """多角色对话历史"""
    messages: list[dict]
    session_info: dict


# =========================
# API 端点
# =========================

@router.post("/session/start", response_model=StartMultiSessionResponse)
async def start_multi_session(request: StartMultiSessionRequest):
    """
    开始多角色群聊会话
    
    创建一个新的多角色对话会话，支持2个或更多NPC同时参与。
    
    - **player_id**: 玩家唯一标识
    - **player_name**: 玩家显示名称
    - **character_ids**: 参与的角色ID列表（至少2个）
    - **speak_frequencies**: 可选的发言频率配置
    - **strategy_type**: 发言策略（推荐使用hybrid）
    
    返回会话ID和第一个角色的开场白。
    """
    try:
        logger.info(f"开始多角色会话: player={request.player_id}, characters={request.character_ids}")
        
        # 验证角色ID
        if len(request.character_ids) < 2:
            raise HTTPException(
                status_code=400,
                detail="多角色会话至少需要2个角色"
            )
        
        # 创建会话
        result = start_multi_character_session(
            player_id=request.player_id,
            player_name=request.player_name,
            character_ids=request.character_ids,
            speak_frequencies=request.speak_frequencies,
            strategy_type=request.strategy_type
        )
        
        return StartMultiSessionResponse(
            session_id=result["session_id"],
            strategy_type=result["strategy_type"],
            opening=result["opening"]
        )
    
    except ValueError as e:
        logger.error(f"创建多角色会话失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    
    except Exception as e:
        logger.error(f"创建多角色会话异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/turn")
async def multi_dialogue_turn(request: MultiDialogueTurnRequest):
    """
    处理多角色对话轮次
    
    玩家发送消息后，系统会根据策略选择一个或多个角色回应。
    
    - **session_id**: 会话ID
    - **player_message**: 玩家消息内容
    - **strategy_type**: 发言策略（可覆盖会话默认策略）
    - **discussion_mode**: 是否启用讨论模式（多角色连续发言）
    - **max_responses**: 讨论模式下最多几个角色回应（1-5）
    
    返回选中角色的回应（单个或多个）。
    """
    try:
        logger.info(f"处理多角色对话: session={request.session_id}, discussion={request.discussion_mode}")
        
        # 验证会话
        session = repository.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        if not session.get("is_multi_character"):
            raise HTTPException(status_code=400, detail="该会话不是多角色会话")
        
        if session.get("status") != "active":
            raise HTTPException(status_code=400, detail="会话已结束")
        
        # 处理对话
        result = process_multi_character_turn(
            session_id=request.session_id,
            player_message=request.player_message,
            strategy_type=request.strategy_type,
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
async def trigger_interaction(request: TriggerInteractionRequest):
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
        session = repository.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        if not session.get("is_multi_character"):
            raise HTTPException(status_code=400, detail="该会话不是多角色会话")
        
        # 触发互动
        orchestrator = MultiCharacterOrchestrator(request.session_id)
        result = orchestrator.trigger_character_interaction(
            trigger_character_id=request.trigger_character_id
        )
        
        return result
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"触发角色互动异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/session/{session_id}", response_model=MultiSessionInfo)
async def get_multi_session_info(session_id: str):
    """
    获取多角色会话信息
    
    返回会话详情和所有参与者信息。
    """
    try:
        # 获取会话
        session = repository.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        if not session.get("is_multi_character"):
            raise HTTPException(status_code=400, detail="该会话不是多角色会话")
        
        # 获取参与者
        participants = repository.get_session_participants(session_id, only_active=False)
        
        return MultiSessionInfo(
            session_id=session["session_id"],
            player_id=session["player_id"],
            player_name=session["player_name"],
            created_at=session["created_at"],
            status=session["status"],
            participants=[SessionParticipant(**p) for p in participants]
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"获取会话信息异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/history/{session_id}", response_model=MultiDialogueHistory)
async def get_multi_dialogue_history(
    session_id: str,
    limit: int = Query(50, ge=1, le=200, description="消息数量限制")
):
    """
    获取多角色对话历史
    
    返回会话的完整对话记录，包含每条消息的发言者信息。
    
    - **session_id**: 会话ID
    - **limit**: 返回的最大消息数（默认50，最多200）
    """
    try:
        # 验证会话
        session = repository.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        if not session.get("is_multi_character"):
            raise HTTPException(status_code=400, detail="该会话不是多角色会话")
        
        # 获取历史
        messages = repository.get_multi_character_history(session_id, limit_messages=limit)
        
        # 获取参与者信息
        participants = repository.get_session_participants(session_id, only_active=False)
        
        return MultiDialogueHistory(
            messages=messages,
            session_info={
                "session_id": session["session_id"],
                "player_name": session["player_name"],
                "created_at": session["created_at"],
                "status": session["status"],
                "participants": participants
            }
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"获取对话历史异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/participant/add")
async def add_participant(request: AddParticipantRequest):
    """
    向会话添加新参与者
    
    动态向现有多角色会话中添加新的NPC。
    
    - **session_id**: 会话ID
    - **character_id**: 要添加的角色ID
    - **speak_frequency**: 发言频率（0.0-2.0，默认1.0）
    """
    try:
        logger.info(f"添加参与者: session={request.session_id}, character={request.character_id}")
        
        # 验证会话
        session = repository.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        if not session.get("is_multi_character"):
            raise HTTPException(status_code=400, detail="该会话不是多角色会话")
        
        if session.get("status") != "active":
            raise HTTPException(status_code=400, detail="会话已结束，无法添加参与者")
        
        # 添加参与者
        success = repository.add_participant_to_session(
            session_id=request.session_id,
            character_id=request.character_id,
            speak_frequency=request.speak_frequency
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="添加参与者失败")
        
        return {
            "success": True,
            "message": f"角色 {request.character_id} 已加入会话"
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"添加参与者异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/participant/remove")
async def remove_participant(session_id: str, character_id: str):
    """
    从会话移除参与者
    
    将指定角色从多角色会话中移除（软删除，标记为不活跃）。
    
    - **session_id**: 会话ID
    - **character_id**: 要移除的角色ID
    """
    try:
        logger.info(f"移除参与者: session={session_id}, character={character_id}")
        
        # 验证会话
        session = repository.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        if not session.get("is_multi_character"):
            raise HTTPException(status_code=400, detail="该会话不是多角色会话")
        
        # 检查是否至少保留2个活跃参与者
        active_participants = repository.get_session_participants(session_id, only_active=True)
        if len(active_participants) <= 2:
            raise HTTPException(
                status_code=400,
                detail="多角色会话至少需要2个活跃参与者"
            )
        
        # 移除参与者
        success = repository.remove_participant_from_session(
            session_id=session_id,
            character_id=character_id
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="移除参与者失败")
        
        return {
            "success": True,
            "message": f"角色 {character_id} 已从会话中移除"
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"移除参与者异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.put("/participant/update")
async def update_participant(request: UpdateParticipantRequest):
    """
    更新参与者配置
    
    修改参与者的发言频率或活跃状态。
    
    - **session_id**: 会话ID
    - **character_id**: 角色ID
    - **speak_frequency**: 新的发言频率（可选）
    - **is_active**: 是否活跃（可选）
    """
    try:
        logger.info(f"更新参与者: session={request.session_id}, character={request.character_id}")
        
        # 验证会话
        session = repository.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        if not session.get("is_multi_character"):
            raise HTTPException(status_code=400, detail="该会话不是多角色会话")
        
        # 更新发言频率
        if request.speak_frequency is not None:
            success = repository.update_participant_frequency(
                session_id=request.session_id,
                character_id=request.character_id,
                speak_frequency=request.speak_frequency
            )
            
            if not success:
                raise HTTPException(status_code=500, detail="更新发言频率失败")
        
        # 更新活跃状态
        if request.is_active is not None:
            if request.is_active:
                # 激活参与者（从不活跃变为活跃）
                # TODO: 需要添加相应的数据库函数
                pass
            else:
                # 停用参与者
                success = repository.remove_participant_from_session(
                    session_id=request.session_id,
                    character_id=request.character_id
                )
                
                if not success:
                    raise HTTPException(status_code=500, detail="停用参与者失败")
        
        return {
            "success": True,
            "message": "参与者配置已更新"
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"更新参与者异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/session/end")
async def end_multi_session(session_id: str):
    """
    结束多角色会话
    
    标记会话为已结束状态。
    
    - **session_id**: 会话ID
    """
    try:
        logger.info(f"结束多角色会话: session={session_id}")
        
        # 验证会话
        session = repository.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        if not session.get("is_multi_character"):
            raise HTTPException(status_code=400, detail="该会话不是多角色会话")
        
        if session.get("status") == "ended":
            return {
                "success": True,
                "message": "会话已经是结束状态"
            }
        
        # 结束会话
        repository.end_session(session_id)
        
        return {
            "success": True,
            "message": "多角色会话已结束",
            "session_id": session_id
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"结束会话异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")
