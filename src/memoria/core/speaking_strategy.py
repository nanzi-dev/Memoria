"""
角色发言策略系统

提供默认混合发言策略，基于上下文、角色关系和显式提及选择接话角色。
"""

import logging
import random
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全转换为 float。"""
    try:
        return float(value)
    except Exception:
        return default


def _relationship_between(character_relationships: dict, char_a: str, char_b: str) -> dict | None:
    """按双向关系查找角色关系。"""
    rel_key = f"{char_a}_{char_b}"
    rel_key_rev = f"{char_b}_{char_a}"
    return character_relationships.get(rel_key) or character_relationships.get(rel_key_rev)


def _relationship_turn_score(relationship: dict | None) -> float:
    """
    根据关系强度和文本语义计算接话倾向。

    关系类型允许用户自定义，因此关系强度是主信号；类型和描述只作为语义提示。
    """
    if not relationship:
        return 0.0

    affinity = max(-100.0, min(100.0, _safe_float(relationship.get("affinity", 0))))
    magnitude = abs(affinity) / 100.0

    if affinity >= 25:
        score = 10.0 + magnitude * 16.0
    elif affinity <= -25:
        score = 12.0 + magnitude * 18.0
    else:
        score = 4.0 + magnitude * 8.0

    rel_text = " ".join(
        str(relationship.get(key) or "")
        for key in ("relationship_type", "description")
    ).lower()

    close_cues = (
        "friend", "family", "lover", "love", "ally", "partner", "companion",
        "朋友", "好友", "挚友", "家人", "亲人", "恋", "爱", "伴侣", "同伴", "盟友",
    )
    conflict_cues = (
        "enemy", "rival", "opponent", "competitor", "hostile",
        "敌", "仇", "宿敌", "对手", "竞争", "冲突", "死敌",
    )
    guidance_cues = (
        "mentor", "teacher", "student", "master", "apprentice",
        "导师", "老师", "师父", "师徒", "学生", "弟子", "同门",
    )

    if any(cue in rel_text for cue in close_cues):
        score += 7.0
    if any(cue in rel_text for cue in conflict_cues):
        score += 9.0
    if any(cue in rel_text for cue in guidance_cues):
        score += 5.0

    return score


def _names_for_card(card: Any) -> list[str]:
    """收集角色可被提及的名字。"""
    if not card:
        return []
    meta = getattr(card, "meta", None)
    if not meta:
        return []
    names = [
        getattr(meta, "name", None),
        getattr(meta, "display_name", None),
    ]
    names.extend(getattr(meta, "aliases", []) or [])
    return [str(name) for name in names if name]


# =========================
# 发言策略基类
# =========================

class SpeakingStrategy(ABC):
    """发言策略抽象基类"""
    
    @abstractmethod
    def select_speaker(
        self,
        participants: list[dict],
        character_cards: dict,
        context: dict
    ) -> str:
        """
        选择下一个发言者
        
        Args:
            participants: 参与者列表
            character_cards: 角色卡字典 {character_id: card}
            context: 上下文信息（包含player_message、history等）
        
        Returns:
            str: 选中的角色 ID
        """
        pass


# =========================
# 智能选择策略
# =========================

class SmartSelectionStrategy(SpeakingStrategy):
    """
    智能选择策略：综合考虑多种因素
    
    评分因素：
    1. 关键词匹配（被提及）
    2. 角色关系（与最近发言者的关系）
    3. 发言频率配置
    4. 发言均衡性（避免某角色过度发言）
    5. 情绪和状态匹配
    
    适用场景：
    - 追求最自然的对话流
    - 复杂的多角色互动
    """
    
    def __init__(self, balance_factor: float = 1.0):
        """
        初始化智能策略
        
        Args:
            balance_factor: 均衡因子（0-2），越高越倾向于让发言少的角色说话
        """
        self.balance_factor = balance_factor
    
    def select_speaker(
        self,
        participants: list[dict],
        character_cards: dict,
        context: dict
    ) -> str:
        """智能选择发言者"""
        if not participants:
            raise ValueError("没有可用的参与者")
        
        player_message = context.get("player_message", "")
        last_speaker_id = context.get("last_speaker_id")
        character_relationships = context.get("character_relationships", {})
        
        candidates = []
        
        for p in participants:
            char_id = p["character_id"]
            card = character_cards.get(char_id)
            
            if not card:
                continue
            
            score = 0.0
            
            # 1. 关键词匹配（玩家提到角色）
            if player_message:
                if any(n in player_message for n in _names_for_card(card)):
                    score += 50.0
                    logger.debug(f"[智能策略] {char_id} 被提及，+50")
            
            # 2. 角色关系（与最后发言者的关系）
            if last_speaker_id and last_speaker_id != char_id:
                relationship = _relationship_between(character_relationships, last_speaker_id, char_id)
                relation_score = _relationship_turn_score(relationship)
                if relation_score:
                    score += relation_score
                    logger.debug(f"[智能策略] {char_id} 与 {last_speaker_id} 关系接话权重，+{relation_score:.1f}")
            
            # 3. 前文提及：其他角色刚刚点名时更容易接话
            previous_responses = context.get("previous_responses") or []
            if previous_responses:
                recent_text = "\n".join(str(r.get("dialogue", "")) for r in previous_responses[-2:])
                if recent_text and any(n in recent_text for n in _names_for_card(card)):
                    score += 28.0
                    logger.debug(f"[智能策略] {char_id} 被上一轮角色提及，+28")
                for response in previous_responses[-2:]:
                    prev_id = response.get("character_id")
                    if prev_id and prev_id != char_id:
                        relation_score = _relationship_turn_score(
                            _relationship_between(character_relationships, prev_id, char_id)
                        ) * 0.35
                        if relation_score:
                            score += relation_score
                            logger.debug(f"[智能策略] {char_id} 与前序发言者 {prev_id} 关系延续，+{relation_score:.1f}")
            
            # 4. 发言频率配置
            frequency = p.get("speak_frequency", 1.0)
            score += frequency * 15.0
            logger.debug(f"[智能策略] {char_id} 频率权重 {frequency}，+{frequency * 15.0:.1f}")
            
            # 5. 发言均衡性（发言少的角色优先）
            message_count = p.get("message_count", 0)
            balance_score = max(0, (10 - message_count) * self.balance_factor)
            score += balance_score
            logger.debug(f"[智能策略] {char_id} 发言次数 {message_count}，均衡分 +{balance_score:.1f}")
            
            # 6. 避免连续发言
            if char_id == last_speaker_id:
                score -= 30.0
                logger.debug(f"[智能策略] {char_id} 刚发言过，-30")
            
            # 7. 随机因子（增加不可预测性）
            random_bonus = random.uniform(0, 8)
            score += random_bonus
            
            candidates.append((char_id, score))
            logger.debug(f"[智能策略] {char_id} 总分: {score:.2f}")
        
        if not candidates:
            return participants[0]["character_id"]
        
        # 选择得分最高的
        candidates.sort(key=lambda x: x[1], reverse=True)
        selected = candidates[0][0]
        
        logger.info(f"[智能策略] 选中 {selected}，得分 {candidates[0][1]:.2f}")
        return selected


# =========================
# 混合策略
# =========================

class HybridStrategy(SpeakingStrategy):
    """
    混合策略：结合多种策略的优点
    
    流程：
    1. 先检查触发条件（强制优先级）
    2. 如果有强提及（关键词），直接选择
    3. 否则使用智能选择
    
    这是推荐的默认策略
    """
    
    def __init__(self, balance_factor: float = 1.0):
        self.keyword_triggers = {}
        self.smart_strategy = SmartSelectionStrategy(balance_factor)
    
    def add_keyword_trigger(self, keyword: str, character_id: str):
        """添加关键词触发"""
        self.keyword_triggers[keyword] = character_id
    
    def select_speaker(
        self,
        participants: list[dict],
        character_cards: dict,
        context: dict
    ) -> str:
        """混合策略选择"""
        if not participants:
            raise ValueError("没有可用的参与者")
        
        player_message = context.get("player_message", "")
        
        # 1. 检查强关键词触发
        for keyword, char_id in self.keyword_triggers.items():
            if keyword in player_message:
                if any(p["character_id"] == char_id for p in participants):
                    logger.info(f"[混合策略] 关键词触发 {char_id}")
                    return char_id
        
        # 2. 检查角色名被提及（强匹配）
        for p in participants:
            char_id = p["character_id"]
            card = character_cards.get(char_id)
            if not card:
                continue
            
            # 完整名字匹配
            if player_message and any(name in player_message for name in _names_for_card(card)):
                logger.info(f"[混合策略] 强提及触发 {char_id}")
                return char_id
        
        # 3. 使用智能策略
        logger.debug("[混合策略] 使用智能选择")
        return self.smart_strategy.select_speaker(participants, character_cards, context)
