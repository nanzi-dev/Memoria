"""
角色发言策略系统

提供多种发言策略：
1. 轮询策略（Round Robin）
2. 权重策略（Weighted Random）
3. 智能策略（Smart Selection）- 基于上下文和关系
4. 触发策略（Trigger Based）- 基于关键词和事件
"""

import logging
import random
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


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
# 轮询策略
# =========================

class RoundRobinStrategy(SpeakingStrategy):
    """
    轮询策略：按顺序轮流发言
    
    适用场景：
    - 需要确保每个角色都有机会发言
    - 对话流程比较规整的场景
    """
    
    def select_speaker(
        self,
        participants: list[dict],
        character_cards: dict,
        context: dict
    ) -> str:
        """按加入顺序轮流选择"""
        if not participants:
            raise ValueError("没有可用的参与者")
        
        # 获取最后发言的角色
        last_speaker_id = context.get("last_speaker_id")
        
        if not last_speaker_id:
            # 第一次发言，选择第一个参与者
            return participants[0]["character_id"]
        
        # 找到最后发言者的索引
        char_ids = [p["character_id"] for p in participants]
        try:
            last_index = char_ids.index(last_speaker_id)
            # 选择下一个（循环）
            next_index = (last_index + 1) % len(char_ids)
            return char_ids[next_index]
        except ValueError:
            # 找不到，返回第一个
            return char_ids[0]


# =========================
# 权重随机策略
# =========================

class WeightedRandomStrategy(SpeakingStrategy):
    """
    权重随机策略：根据speak_frequency权重随机选择
    
    适用场景：
    - 需要控制某些角色的活跃度
    - 希望保持一定的随机性
    """
    
    def select_speaker(
        self,
        participants: list[dict],
        character_cards: dict,
        context: dict
    ) -> str:
        """根据权重随机选择"""
        if not participants:
            raise ValueError("没有可用的参与者")
        
        # 构建权重列表
        weights = []
        char_ids = []
        
        for p in participants:
            char_id = p["character_id"]
            frequency = p.get("speak_frequency", 1.0)
            
            # 如果是刚发言过的角色，降低权重
            if char_id == context.get("last_speaker_id"):
                frequency *= 0.3
            
            weights.append(max(frequency, 0.1))  # 确保最小权重
            char_ids.append(char_id)
        
        # 加权随机选择
        total_weight = sum(weights)
        rand = random.uniform(0, total_weight)
        
        cumulative = 0
        for char_id, weight in zip(char_ids, weights):
            cumulative += weight
            if rand <= cumulative:
                return char_id
        
        return char_ids[0]


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
                name = card.meta.name
                display_name = card.meta.display_name
                aliases = getattr(card.meta, "aliases", [])
                all_names = [name, display_name] + aliases
                
                if any(n and n in player_message for n in all_names):
                    score += 50.0
                    logger.debug(f"[智能策略] {char_id} 被提及，+50")
            
            # 2. 角色关系（与最后发言者的关系）
            if last_speaker_id and last_speaker_id != char_id:
                rel_key = f"{last_speaker_id}_{char_id}"
                rel_key_rev = f"{char_id}_{last_speaker_id}"
                
                relationship = character_relationships.get(rel_key) or character_relationships.get(rel_key_rev)
                
                if relationship:
                    rel_type = relationship.get("relationship_type", "")
                    affinity = relationship.get("affinity", 0)
                    
                    # 关系亲密度影响
                    if rel_type in ["friend", "family", "lover"]:
                        score += 15.0 + (affinity / 100.0) * 10.0
                        logger.debug(f"[智能策略] {char_id} 与 {last_speaker_id} 关系亲密，+{15.0 + (affinity / 100.0) * 10.0:.1f}")
                    elif rel_type in ["rival", "enemy"]:
                        score += 20.0  # 对手更可能互怼
                        logger.debug(f"[智能策略] {char_id} 与 {last_speaker_id} 是对手，+20")
            
            # 3. 发言频率配置
            frequency = p.get("speak_frequency", 1.0)
            score += frequency * 15.0
            logger.debug(f"[智能策略] {char_id} 频率权重 {frequency}，+{frequency * 15.0:.1f}")
            
            # 4. 发言均衡性（发言少的角色优先）
            message_count = p.get("message_count", 0)
            balance_score = max(0, (10 - message_count) * self.balance_factor)
            score += balance_score
            logger.debug(f"[智能策略] {char_id} 发言次数 {message_count}，均衡分 +{balance_score:.1f}")
            
            # 5. 避免连续发言
            if char_id == last_speaker_id:
                score -= 30.0
                logger.debug(f"[智能策略] {char_id} 刚发言过，-30")
            
            # 6. 随机因子（增加不可预测性）
            random_bonus = random.uniform(0, 12)
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
# 触发策略
# =========================

class TriggerBasedStrategy(SpeakingStrategy):
    """
    触发策略：基于特定条件触发角色发言
    
    触发条件：
    1. 关键词触发（强制）
    2. 情绪触发（某角色状态适合发言）
    3. 事件触发（特定事件发生）
    
    如果没有触发条件满足，回退到默认策略
    
    适用场景：
    - 需要精确控制某些场景的发言
    - 事件驱动的对话
    """
    
    def __init__(self, fallback_strategy: SpeakingStrategy = None):
        """
        初始化触发策略
        
        Args:
            fallback_strategy: 回退策略（无触发时使用）
        """
        self.fallback_strategy = fallback_strategy or WeightedRandomStrategy()
        
        # 触发规则配置（可以动态配置）
        self.keyword_triggers = {}  # {keyword: character_id}
        self.emotion_triggers = {}  # {emotion: character_id}
    
    def add_keyword_trigger(self, keyword: str, character_id: str):
        """添加关键词触发规则"""
        self.keyword_triggers[keyword] = character_id
    
    def add_emotion_trigger(self, emotion: str, character_id: str):
        """添加情绪触发规则"""
        self.emotion_triggers[emotion] = character_id
    
    def select_speaker(
        self,
        participants: list[dict],
        character_cards: dict,
        context: dict
    ) -> str:
        """基于触发条件选择发言者"""
        if not participants:
            raise ValueError("没有可用的参与者")
        
        player_message = context.get("player_message", "")
        
        # 1. 检查关键词触发
        if player_message:
            for keyword, char_id in self.keyword_triggers.items():
                if keyword in player_message:
                    # 检查该角色是否在参与者中
                    if any(p["character_id"] == char_id for p in participants):
                        logger.info(f"[触发策略] 关键词'{keyword}'触发 {char_id}")
                        return char_id
        
        # 2. 检查情绪触发（TODO: 需要runtime_state支持）
        
        # 3. 没有触发，使用回退策略
        logger.debug("[触发策略] 无触发条件，使用回退策略")
        return self.fallback_strategy.select_speaker(participants, character_cards, context)


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
        self.trigger_strategy = TriggerBasedStrategy()
        self.smart_strategy = SmartSelectionStrategy(balance_factor)
    
    def add_keyword_trigger(self, keyword: str, character_id: str):
        """添加关键词触发"""
        self.trigger_strategy.add_keyword_trigger(keyword, character_id)
    
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
        for keyword, char_id in self.trigger_strategy.keyword_triggers.items():
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
            
            name = card.meta.name
            display_name = card.meta.display_name
            
            # 完整名字匹配
            if player_message and (name in player_message or display_name in player_message):
                logger.info(f"[混合策略] 强提及触发 {char_id}")
                return char_id
        
        # 3. 使用智能策略
        logger.debug("[混合策略] 使用智能选择")
        return self.smart_strategy.select_speaker(participants, character_cards, context)


# =========================
# 策略工厂
# =========================

class StrategyFactory:
    """发言策略工厂"""
    
    @staticmethod
    def create_strategy(strategy_type: str = "hybrid", **kwargs) -> SpeakingStrategy:
        """
        创建发言策略
        
        Args:
            strategy_type: 策略类型
                - "round_robin": 轮询
                - "weighted": 权重随机
                - "smart": 智能选择
                - "trigger": 触发式
                - "hybrid": 混合策略（推荐）
            **kwargs: 策略特定参数
        
        Returns:
            SpeakingStrategy: 策略实例
        """
        strategy_map = {
            "round_robin": RoundRobinStrategy,
            "weighted": WeightedRandomStrategy,
            "smart": SmartSelectionStrategy,
            "trigger": TriggerBasedStrategy,
            "hybrid": HybridStrategy
        }
        
        strategy_class = strategy_map.get(strategy_type)
        if not strategy_class:
            logger.warning(f"未知策略类型 {strategy_type}，使用默认混合策略")
            strategy_class = HybridStrategy
        
        # 传递参数
        if strategy_type == "smart" or strategy_type == "hybrid":
            balance_factor = kwargs.get("balance_factor", 1.0)
            return strategy_class(balance_factor=balance_factor)
        elif strategy_type == "trigger":
            fallback = kwargs.get("fallback_strategy")
            return strategy_class(fallback_strategy=fallback)
        else:
            return strategy_class()


# =========================
# 便捷函数
# =========================

def select_next_speaker(
    participants: list[dict],
    character_cards: dict,
    context: dict,
    strategy_type: str = "hybrid"
) -> str:
    """
    选择下一个发言者（便捷函数）
    
    Args:
        participants: 参与者列表
        character_cards: 角色卡字典
        context: 上下文信息
        strategy_type: 策略类型
    
    Returns:
        str: 选中的角色 ID
    """
    strategy = StrategyFactory.create_strategy(strategy_type)
    return strategy.select_speaker(participants, character_cards, context)
