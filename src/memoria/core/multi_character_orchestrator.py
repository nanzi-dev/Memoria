"""
多角色对话编排核心逻辑

功能：
1. 管理多角色发言顺序
2. 构建多角色上下文
3. 处理角色间互动
4. 协调记忆系统
5. 应用角色关系网络
"""

import json
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any

from memoria.core import character_loader, llm_client, multi_character_memory, prompt_builder
from memoria.core.speaking_strategy import StrategyFactory, SpeakingStrategy
from memoria.db import repository

logger = logging.getLogger(__name__)


# =========================
# 工具函数
# =========================

def _clip(value: float, lo: float, hi: float) -> float:
    """数值裁剪"""
    return max(lo, min(hi, value))


def _safe_float(value, default: float = 0.0) -> float:
    """安全 float 转换"""
    try:
        return float(value)
    except Exception:
        return default


# =========================
# 多角色对话编排器
# =========================

class MultiCharacterOrchestrator:
    """
    多角色对话编排器
    
    负责：
    - 决定哪个角色发言
    - 构建多角色上下文
    - 处理角色间关系
    - 管理发言轮次
    """
    
    def __init__(self, session_id: str, strategy_type: str = "hybrid"):
        """
        初始化编排器
        
        Args:
            session_id: 会话 ID
            strategy_type: 发言策略类型（round_robin/weighted/smart/trigger/hybrid）
        """
        self.session_id = session_id
        self.session = repository.get_session(session_id)
        
        if not self.session:
            raise ValueError(f"会话不存在: {session_id}")
        
        if not self.session.get("is_multi_character"):
            raise ValueError(f"会话 {session_id} 不是多角色会话")
        if self.session.get("status") == "ended":
            raise ValueError("会话已经结束")
        
        self.player_id = self.session["player_id"]
        self.player_name = self.session["player_name"]
        
        # 加载参与者
        self.participants = repository.get_session_participants(session_id, only_active=True)
        self.character_ids = [p["character_id"] for p in self.participants]
        
        # 加载角色卡
        self.character_cards = {}
        for char_id in self.character_ids:
            try:
                card = character_loader.load_character_card(char_id)
                self.character_cards[char_id] = card
            except Exception as e:
                logger.error(f"加载角色卡失败 {char_id}: {e}")
        
        # 初始化发言策略
        self.speaking_strategy = StrategyFactory.create_strategy(strategy_type)
        
        # 缓存最后发言者
        self.last_speaker_id = None
        
        logger.info(f"多角色编排器已初始化: session={session_id}, 参与角色={self.character_ids}, 策略={strategy_type}")
    
    
    def start_conversation(self) -> dict:
        """
        开始多角色对话
        
        Returns:
            dict: 包含开场白的响应
        """
        # 选择第一个角色发言（按加入顺序）
        if not self.participants:
            raise ValueError("没有可用的参与者")
        
        first_speaker = self.participants[0]
        character_id = first_speaker["character_id"]
        
        # 生成开场白
        result = self._generate_opening(character_id)
        
        return result
    
    
    def process_player_message(self, player_message: str, allow_multiple_responses: bool = False,
                                max_responses: int | None = None) -> dict | list[dict]:
        """
        处理玩家消息，决定哪个角色回应
        
        Args:
            player_message: 玩家消息内容
            allow_multiple_responses: 是否允许多个角色连续回应（讨论模式）
            max_responses: 最多允许几个角色回应；实际人数会按群聊语境动态决定
        
        Returns:
            dict | list[dict]: 单个角色回应或多个角色回应列表
        """
        # 记录玩家消息
        repository.append_multi_character_message(
            self.session_id,
            role="user",
            content=player_message
        )
        
        if not allow_multiple_responses:
            # 单角色回应模式（原有逻辑）
            speaker_id = self._decide_next_speaker(player_message)
            result = self._generate_character_response(speaker_id, player_message)
            return result
        
        else:
            # 多角色讨论模式
            response_count = self._decide_group_response_count(player_message, max_responses)
            responses = self._generate_group_discussion(player_message, response_count)
            return responses


    def _decide_group_response_count(self, player_message: str, max_responses: int | None = None) -> int:
        """按普通群聊节奏决定本轮实际接话人数。"""
        participant_count = len(self.participants)
        if participant_count <= 1:
            return participant_count

        requested_cap = max_responses or participant_count
        try:
            requested_cap = int(requested_cap)
        except Exception:
            requested_cap = participant_count
        cap = min(max(1, requested_cap), participant_count, 4)

        text = (player_message or "").strip()
        if not text:
            return 1

        mentioned = 0
        for card in self.character_cards.values():
            names = [card.meta.name, card.meta.display_name] + list(getattr(card.meta, "aliases", []) or [])
            if any(name and name in text for name in names):
                mentioned += 1

        if mentioned == 1:
            return 1
        if mentioned >= 2:
            return min(cap, max(2, mentioned))

        broad_cues = (
            "大家", "你们", "各位", "都", "一起", "商量", "讨论", "投票", "选择",
            "怎么办", "怎么看", "意见", "想法", "谁", "有没有", "要不要", "为什么",
        )
        short_ack = text in {"好", "好的", "嗯", "哦", "行", "可以", "知道了", "明白", "没事"}
        is_question = any(mark in text for mark in ("?", "？", "吗", "呢"))

        if short_ack:
            weights = [(1, 0.9), (2, 0.1)]
        elif any(cue in text for cue in broad_cues):
            weights = [(1, 0.2), (2, 0.5), (3, 0.25), (4, 0.05)]
        elif is_question:
            weights = [(1, 0.55), (2, 0.35), (3, 0.1)]
        else:
            weights = [(1, 0.7), (2, 0.25), (3, 0.05)]

        available = [(count, weight) for count, weight in weights if count <= cap]
        total = sum(weight for _, weight in available)
        pick = random.uniform(0, total)
        upto = 0.0
        for count, weight in available:
            upto += weight
            if pick <= upto:
                return count
        return available[-1][0]
    
    
    def _generate_group_discussion(self, player_message: str, max_responses: int = 3) -> list[dict]:
        """
        生成多角色讨论（多个角色连续发言）
        
        Args:
            player_message: 玩家消息
            max_responses: 最多几个角色发言
        
        Returns:
            list[dict]: 角色回应列表
        """
        responses = []
        used_speakers = set()
        
        # 限制回应数量不超过参与者数量
        max_responses = min(max_responses, len(self.participants))
        
        for i in range(max_responses):
            # 选择下一个发言角色（排除已发言的）
            available_participants = [
                p for p in self.participants 
                if p["character_id"] not in used_speakers
            ]
            
            if not available_participants:
                break
            
            # 构建上下文（包含前面角色的发言）
            context = {
                "player_message": player_message,
                "last_speaker_id": self.last_speaker_id,
                "character_relationships": self._load_all_relationships(),
                "previous_responses": responses  # 添加之前的回应作为上下文
            }
            
            # 使用策略选择发言角色
            speaker_id = self.speaking_strategy.select_speaker(
                available_participants,
                self.character_cards,
                context
            )
            
            # 生成回应
            result = self._generate_character_response(speaker_id, player_message)
            responses.append(result)
            
            # 标记已使用
            used_speakers.add(speaker_id)
            self.last_speaker_id = speaker_id
            
            # 判断是否需要继续（基于对话内容的自然结束）
            dialogue = result.get("dialogue", "")
            
            # 如果对话包含明确的结束语或疑问句，可能不需要更多回应
            ending_phrases = ["就这样吧", "好的", "明白了", "我知道了", "没问题"]
            if i >= 1 and any(phrase in dialogue for phrase in ending_phrases):
                # 至少有2个角色发言后，如果出现结束语，可以停止
                break
        
        return responses
    
    
    def trigger_character_interaction(self, trigger_character_id: str = None) -> dict:
        """
        触发角色间互动（角色主动发言）
        
        Args:
            trigger_character_id: 触发角色ID，如果为None则自动选择
        
        Returns:
            dict: 角色发言结果
        """
        if trigger_character_id is None:
            trigger_character_id = self._select_character_for_interaction()
        
        # 生成角色间互动对话
        result = self._generate_character_interaction(trigger_character_id)
        
        return result
    
    
    def _decide_next_speaker(self, player_message: str) -> str:
        """
        决定下一个发言的角色（使用策略系统）
        
        Args:
            player_message: 玩家消息
        
        Returns:
            str: 选中的角色 ID
        """
        # 构建上下文
        context = {
            "player_message": player_message,
            "last_speaker_id": self.last_speaker_id,
            "character_relationships": self._load_all_relationships()
        }
        
        # 使用策略选择
        selected_id = self.speaking_strategy.select_speaker(
            self.participants,
            self.character_cards,
            context
        )
        
        # 更新缓存
        self.last_speaker_id = selected_id
        
        return selected_id
    
    
    def _load_all_relationships(self) -> dict:
        """
        加载所有参与角色之间的关系
        
        Returns:
            dict: {f"{char_a}_{char_b}": relationship_dict}
        """
        relationships = {}
        
        for i, char_a in enumerate(self.character_ids):
            for char_b in self.character_ids[i+1:]:
                rel = self._get_character_relationship(char_a, char_b)
                if rel:
                    relationships[f"{char_a}_{char_b}"] = rel
        
        return relationships


    def _load_memory_context(self, character_id: str, query_context: str | None = None) -> list[str]:
        """加载多角色记忆上下文，供 prompt 的历史记录区使用。"""
        other_character_ids = [cid for cid in self.character_ids if cid != character_id]

        try:
            context = multi_character_memory.integrate_multi_character_context(
                character_id=character_id,
                player_id=self.player_id,
                session_id=self.session_id,
                other_character_ids=other_character_ids,
                query_context=query_context,
            )
        except Exception as e:
            logger.warning(f"加载多角色记忆上下文失败: {e}")
            return []

        memory_lines = []

        for memory in context.get("group_memories", [])[:5]:
            memory_lines.append(f"群体记忆：{memory}")

        impressions = context.get("character_impressions", {})
        for other_id, memories in impressions.items():
            other_card = self.character_cards.get(other_id)
            other_name = other_card.meta.display_name if other_card else other_id
            for memory in memories[:2]:
                memory_lines.append(f"对{other_name}的印象：{memory}")

        return memory_lines


    def _select_character_for_interaction(self) -> str:
        """
        选择一个角色发起互动（用于角色主动发言）
        
        Returns:
            str: 选中的角色 ID
        """
        # 简单策略：选择最久没发言的角色
        candidates = []
        
        for participant in self.participants:
            char_id = participant["character_id"]
            last_spoke = participant.get("last_spoke_at")
            message_count = participant.get("message_count", 0)
            
            # 计算权重：发言次数少的优先
            weight = 100.0 - message_count * 5
            
            # 最近没发言的优先
            if not last_spoke:
                weight += 50.0
            
            candidates.append((char_id, weight))
        
        if not candidates:
            return self.character_ids[0]
        
        # 加权随机选择
        total_weight = sum(w for _, w in candidates)
        rand = random.uniform(0, total_weight)
        
        cumulative = 0
        for char_id, weight in candidates:
            cumulative += weight
            if rand <= cumulative:
                return char_id
        
        return candidates[0][0]
    
    
    def _generate_opening(self, character_id: str) -> dict:
        """
        生成多角色对话开场白
        
        Args:
            character_id: 发言角色 ID
        
        Returns:
            dict: 开场白结果
        """
        card = self.character_cards[character_id]
        runtime_state = repository.get_runtime_state(character_id, self.player_id, card)
        
        # 准备其他角色信息
        other_characters = []
        for other_id in self.character_ids:
            if other_id != character_id:
                other_card = self.character_cards.get(other_id)
                if other_card:
                    other_characters.append({
                        "character_id": other_id,
                        "name": other_card.meta.name,
                        "display_name": other_card.meta.display_name,
                        "occupation": other_card.identity.occupation
                    })
        
        # 使用 prompt_builder 构建系统提示
        system_prompt = prompt_builder.build_multi_character_system_prompt(
            card=card,
            runtime_state=runtime_state,
            player_name=self.player_name,
            other_characters=other_characters,
            character_relationships=self._load_all_relationships(),
            is_opening=True
        )
        
        # 生成开场白
        result = llm_client.call_role_turn(
            system_prompt=system_prompt,
            history=[]
        )
        
        dialogue = result.get("dialogue", "")
        action = result.get("action", card.action_vocabulary.default_action)
        
        # 记录消息
        character_name = card.meta.display_name or card.meta.name
        repository.append_multi_character_message(
            self.session_id,
            role="assistant",
            content=dialogue,
            character_id=character_id,
            character_name=character_name
        )
        
        return {
            "character_id": character_id,
            "character_name": character_name,
            "dialogue": dialogue,
            "action": action,
            "current_affinity": runtime_state.get("affection_level", 0),
            "current_mood": runtime_state.get("current_mood", "neutral")
        }
    
    
    def _generate_character_response(self, character_id: str, player_message: str) -> dict:
        """
        生成角色对玩家的回应
        
        Args:
            character_id: 发言角色 ID
            player_message: 玩家消息
        
        Returns:
            dict: 角色回应结果
        """
        card = self.character_cards[character_id]
        runtime_state = repository.get_runtime_state(
            character_id,
            self.player_id,
            card
        )
        
        # 准备其他角色信息
        other_characters = []
        for other_id in self.character_ids:
            if other_id != character_id:
                other_card = self.character_cards.get(other_id)
                if other_card:
                    other_characters.append({
                        "character_id": other_id,
                        "name": other_card.meta.name,
                        "display_name": other_card.meta.display_name,
                        "occupation": other_card.identity.occupation
                    })
        
        # 使用 prompt_builder 构建系统提示
        system_prompt = prompt_builder.build_multi_character_system_prompt(
            card=card,
            runtime_state=runtime_state,
            player_name=self.player_name,
            other_characters=other_characters,
            character_relationships=self._load_all_relationships(),
            past_summaries=self._load_memory_context(character_id)
        )
        
        # 获取对话历史
        history = repository.get_multi_character_history(
            self.session_id,
            limit_messages=20
        )
        
        # 转换为 LLM 格式
        messages = self._format_history_for_llm(history, character_id)
        messages.append({"role": "user", "content": player_message})
        
        # 调用 LLM
        result = llm_client.call_role_turn(
            system_prompt=system_prompt,
            history=messages
        )
        
        dialogue = result.get("dialogue", "")
        action = result.get("action", card.action_vocabulary.default_action)
        
        # 状态更新
        affinity_delta = _clip(_safe_float(result.get("affinity_delta", 0)), -10, 10)
        new_affinity = _clip(
            runtime_state.get("affection_level", 0) + affinity_delta,
            -100,
            100
        )
        
        trust_delta = _clip(_safe_float(result.get("trust_delta", 0)), -10, 10)
        new_trust = _clip(
            runtime_state.get("trust_level", 0) + trust_delta,
            0,
            100
        )
        
        mood_after = result.get("mood_after") or runtime_state.get("current_mood", "neutral")
        
        # 持久化状态
        repository.save_runtime_state(
            character_id,
            self.player_id,
            new_affinity,
            new_trust,
            mood_after
        )
        
        # 记录消息
        character_name = card.meta.display_name or card.meta.name
        repository.append_multi_character_message(
            self.session_id,
            role="assistant",
            content=dialogue,
            character_id=character_id,
            character_name=character_name
        )
        
        # 记忆萃取
        memory_fact = result.get("memory_worth_keeping")
        if memory_fact and str(memory_fact).strip().lower() not in ("none", "null", ""):
            repository.save_long_term_fact(
                character_id,
                self.player_id,
                str(memory_fact).strip()
            )
        
        return {
            "character_id": character_id,
            "character_name": character_name,
            "dialogue": dialogue,
            "action": action,
            "affinity_delta": affinity_delta,
            "current_affinity": new_affinity,
            "current_mood": mood_after
        }
    
    
    def _generate_character_interaction(self, trigger_character_id: str) -> dict:
        """
        生成角色间互动（角色主动发言）
        
        Args:
            trigger_character_id: 触发角色 ID
        
        Returns:
            dict: 角色互动结果
        """
        card = self.character_cards[trigger_character_id]
        runtime_state = repository.get_runtime_state(
            trigger_character_id,
            self.player_id,
            card
        )
        
        # 准备其他角色信息
        other_characters = []
        for other_id in self.character_ids:
            if other_id != trigger_character_id:
                other_card = self.character_cards.get(other_id)
                if other_card:
                    other_characters.append({
                        "character_id": other_id,
                        "name": other_card.meta.name,
                        "display_name": other_card.meta.display_name,
                        "occupation": other_card.identity.occupation
                    })
        
        # 使用 prompt_builder 构建系统提示
        system_prompt = prompt_builder.build_multi_character_system_prompt(
            card=card,
            runtime_state=runtime_state,
            player_name=self.player_name,
            other_characters=other_characters,
            character_relationships=self._load_all_relationships(),
            past_summaries=self._load_memory_context(trigger_character_id),
            is_interaction=True
        )
        
        # 获取对话历史
        history = repository.get_multi_character_history(
            self.session_id,
            limit_messages=20
        )
        
        messages = self._format_history_for_llm(history, trigger_character_id)
        
        # 添加互动提示
        interaction_prompt = "（现在可以主动说些什么，或者对其他角色的发言做出反应）"
        messages.append({"role": "user", "content": interaction_prompt})
        
        # 调用 LLM
        result = llm_client.call_role_turn(
            system_prompt=system_prompt,
            history=messages
        )
        
        dialogue = result.get("dialogue", "")
        action = result.get("action", card.action_vocabulary.default_action)
        
        # 记录消息
        character_name = card.meta.display_name or card.meta.name
        repository.append_multi_character_message(
            self.session_id,
            role="assistant",
            content=dialogue,
            character_id=trigger_character_id,
            character_name=character_name
        )
        
        return {
            "character_id": trigger_character_id,
            "character_name": character_name,
            "dialogue": dialogue,
            "action": action
        }
    
    
    def _format_history_for_llm(self, history: list[dict], current_character_id: str) -> list[dict]:
        """
        将多角色历史转换为 LLM 格式
        
        Args:
            history: 原始历史记录
            current_character_id: 当前发言角色 ID
        
        Returns:
            list[dict]: 格式化后的消息列表
        """
        messages = []
        
        for msg in history:
            role = msg["role"]
            content = msg["content"]
            char_id = msg.get("character_id")
            char_name = msg.get("character_name")
            
            if role == "user":
                # 玩家消息
                formatted_content = f"[{self.player_name}]: {content}"
                messages.append({"role": "user", "content": formatted_content})
            
            elif role == "assistant":
                # 角色消息
                if char_id == current_character_id:
                    # 自己的历史消息
                    messages.append({"role": "assistant", "content": content})
                else:
                    # 其他角色的消息（作为用户消息呈现）
                    if char_name:
                        formatted_content = f"[{char_name}]: {content}"
                    else:
                        formatted_content = f"[其他角色]: {content}"
                    messages.append({"role": "user", "content": formatted_content})
        
        return messages
    
    
    def _get_character_relationship(self, char_id_a: str, char_id_b: str) -> dict | None:
        """
        获取两个角色之间的关系
        
        Args:
            char_id_a: 角色 A ID
            char_id_b: 角色 B ID
        
        Returns:
            dict: 关系信息，不存在则返回 None
        """
        try:
            # 尝试正向查询
            rel = repository.get_character_relationship(char_id_a, char_id_b)
            if rel:
                return rel
            
            # 尝试反向查询（关系是双向的）
            rel = repository.get_character_relationship(char_id_b, char_id_a)
            return rel
        
        except Exception as e:
            logger.debug(f"查询角色关系失败: {e}")
            return None


# =========================
# 便捷函数
# =========================

def start_multi_character_session(
    player_id: str,
    player_name: str,
    character_ids: list[str],
    speak_frequencies: dict[str, float] = None,
    strategy_type: str = "hybrid",
    group_name: str | None = None,
) -> dict:
    """
    创建并启动多角色会话
    
    Args:
        player_id: 玩家 ID
        player_name: 玩家名称
        character_ids: 参与角色 ID 列表
        speak_frequencies: 角色发言频率配置
        strategy_type: 发言策略类型（round_robin/weighted/smart/trigger/hybrid）
    
    Returns:
        dict: 包含 session_id 和开场白的结果
    """
    session_id = str(uuid.uuid4())
    
    # 创建会话
    success = repository.create_multi_character_session(
        session_id=session_id,
        player_id=player_id,
        player_name=player_name,
        character_ids=character_ids,
        speak_frequencies=speak_frequencies,
        group_name=group_name,
    )
    
    if not success:
        raise ValueError("创建多角色会话失败")
    
    # 初始化编排器
    orchestrator = MultiCharacterOrchestrator(session_id, strategy_type=strategy_type)
    
    # 生成开场白
    opening_result = orchestrator.start_conversation()
    
    return {
        "session_id": session_id,
        "opening": opening_result,
        "strategy_type": strategy_type,
        "group_name": group_name,
    }


def process_multi_character_turn(
    session_id: str,
    player_message: str,
    strategy_type: str = "hybrid",
    discussion_mode: bool = True,
    max_responses: int | None = None
) -> dict | list[dict]:
    """
    处理多角色对话轮次
    
    Args:
        session_id: 会话 ID
        player_message: 玩家消息
        strategy_type: 发言策略类型
        discussion_mode: 是否启用讨论模式（多角色连续发言）
        max_responses: 可选的人数上限；不传时按语境动态决定
    
    Returns:
        dict | list[dict]: 角色回应结果（单个或多个）
    """
    orchestrator = MultiCharacterOrchestrator(session_id, strategy_type=strategy_type)
    result = orchestrator.process_player_message(
        player_message, 
        allow_multiple_responses=discussion_mode,
        max_responses=max_responses
    )
    return result
