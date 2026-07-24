"""
角色发言策略系统

提供默认混合发言策略，基于上下文、角色关系和显式提及选择接话角色。
"""

import hashlib
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

_RECENT_MESSAGE_WINDOW = 12
_EXPERTISE_DOMAINS = (
    (
        ("医生", "医师", "护士", "治疗师", "药师", "医疗", "急救", "doctor", "medic", "nurse", "healer"),
        ("急救", "受伤", "伤口", "包扎", "治疗", "诊断", "中毒", "药物", "生病", "medical", "injury", "wound", "heal"),
    ),
    (
        ("侦探", "调查员", "警察", "记者", "情报", "侦查", "detective", "investigator", "police", "journalist"),
        ("调查", "线索", "证据", "推理", "嫌疑", "真相", "追踪", "案发", "investigate", "clue", "evidence", "suspect"),
    ),
    (
        ("工程师", "机械师", "程序员", "科学家", "技术员", "engineer", "mechanic", "programmer", "scientist"),
        ("机械", "机器", "设备", "修理", "故障", "代码", "系统", "技术", "engine", "machine", "repair", "code", "system"),
    ),
    (
        ("战士", "士兵", "骑士", "护卫", "军人", "保镖", "warrior", "soldier", "knight", "guard"),
        ("战斗", "敌人", "攻击", "防守", "武器", "护送", "危险", "作战", "fight", "enemy", "attack", "defend", "weapon"),
    ),
    (
        ("法师", "巫师", "术士", "魔法师", "牧师", "wizard", "mage", "sorcerer", "priest"),
        ("魔法", "法术", "咒语", "诅咒", "灵异", "仪式", "神术", "magic", "spell", "curse", "ritual"),
    ),
    (
        ("向导", "导航员", "船长", "猎人", "斥候", "guide", "navigator", "captain", "hunter", "scout"),
        ("路线", "地图", "方向", "带路", "追踪", "野外", "航行", "迷路", "route", "map", "navigate", "track"),
    ),
    (
        ("外交官", "律师", "商人", "谈判专家", "贵族", "diplomat", "lawyer", "merchant", "negotiator"),
        ("谈判", "交易", "价格", "法律", "协议", "交涉", "合同", "外交", "negotiate", "trade", "law", "contract"),
    ),
)


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


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            values.extend(_text_values(item))
        return values
    return []


def _character_topic_text(card: Any) -> tuple[str, str]:
    """Return compact role text and broader topic text for local relevance."""
    identity = getattr(card, "identity", None)
    personality = getattr(card, "personality", None)
    goals = getattr(card, "goals_and_motivations", None)
    rules = getattr(card, "interaction_rules", None)

    role_values = []
    for field in ("occupation", "core_identity_summary", "social_status"):
        role_values.extend(_text_values(getattr(identity, field, None)))
    role_values.extend(
        _text_values(getattr(rules, "topics_he_or_she_loves_to_discuss", None))
    )

    topic_values = list(role_values)
    for field in ("core_traits", "values_and_beliefs"):
        topic_values.extend(_text_values(getattr(personality, field, None)))
    for field in (
        "current_goals",
        "long_term_goals",
        "what_triggers_anger",
        "what_brings_joy",
    ):
        topic_values.extend(_text_values(getattr(goals, field, None)))

    return " ".join(role_values).lower(), " ".join(topic_values).lower()


def _topic_units(text: str) -> set[str]:
    normalized = str(text or "").lower()
    units = {
        word
        for word in re.findall(r"[a-z0-9]+", normalized)
        if len(word) >= 3
    }
    for sequence in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if 2 <= len(sequence) <= 8:
            units.add(sequence)
        if len(sequence) >= 2:
            units.update(
                sequence[index:index + 2]
                for index in range(len(sequence) - 1)
            )
    return units


def _topic_relevance_score(player_message: str, card: Any) -> float:
    message = str(player_message or "").strip().lower()
    if not message or not card:
        return 0.0

    role_text, topic_text = _character_topic_text(card)
    overlap = _topic_units(message) & _topic_units(topic_text)
    score = min(24.0, len(overlap) * 4.0)

    for role_cues, topic_cues in _EXPERTISE_DOMAINS:
        if (
            any(cue in role_text for cue in role_cues)
            and any(cue in message for cue in topic_cues)
        ):
            score += 30.0
            break
    return score


def _stable_jitter(context: dict, character_id: str) -> float:
    seed = str(
        context.get("selection_seed")
        or (
            str(context.get("player_message") or ""),
            str(context.get("last_speaker_id") or ""),
            len(context.get("previous_responses") or []),
        )
    )
    digest = hashlib.blake2b(
        f"{seed}:{character_id}".encode("utf-8"),
        digest_size=4,
    ).digest()
    return int.from_bytes(digest, "big") / 0xFFFFFFFF * 2.0


def _recent_message_counts(history: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for message in history[-_RECENT_MESSAGE_WINDOW:]:
        if message.get("role") != "assistant":
            continue
        character_id = message.get("character_id")
        if character_id:
            counts[character_id] = counts.get(character_id, 0) + 1
    return counts


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
        recent_counts = _recent_message_counts(context.get("history") or [])
        max_recent_count = max(recent_counts.values(), default=0)
        lifetime_counts = [
            max(0, int(_safe_float(participant.get("message_count", 0))))
            for participant in participants
        ]
        max_lifetime_count = max(lifetime_counts, default=0)
        
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

            relevance_score = _topic_relevance_score(player_message, card)
            if relevance_score:
                score += relevance_score
                logger.debug(
                    "[智能策略] %s 话题相关性，+%.1f",
                    char_id,
                    relevance_score,
                )
            
            # 2. 角色关系（与最后发言者的关系）
            if last_speaker_id and last_speaker_id != char_id:
                relationship = _relationship_between(character_relationships, last_speaker_id, char_id)
                relation_score = _relationship_turn_score(relationship) * 0.45
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
                        ) * 0.20
                        if relation_score:
                            score += relation_score
                            logger.debug(f"[智能策略] {char_id} 与前序发言者 {prev_id} 关系延续，+{relation_score:.1f}")
            
            # 4. 发言频率配置
            frequency = p.get("speak_frequency", 1.0)
            score += frequency * 15.0
            logger.debug(f"[智能策略] {char_id} 频率权重 {frequency}，+{frequency * 15.0:.1f}")
            
            # 5. 最近窗口与全会话的相对均衡，累计超过 10 条后仍然有效
            recent_count = recent_counts.get(char_id, 0)
            recent_balance = min(
                14.0,
                max(0, max_recent_count - recent_count)
                * 4.0
                * self.balance_factor,
            )
            message_count = max(0, int(_safe_float(p.get("message_count", 0))))
            lifetime_balance = min(
                6.0,
                max(0, max_lifetime_count - message_count)
                * 0.75
                * self.balance_factor,
            )
            balance_score = recent_balance + lifetime_balance
            score += balance_score
            logger.debug(
                "[智能策略] %s 最近发言 %s、累计 %s，均衡分 +%.1f",
                char_id,
                recent_count,
                message_count,
                balance_score,
            )
            
            # 6. 避免连续发言
            if char_id == last_speaker_id:
                score -= 30.0
                logger.debug(f"[智能策略] {char_id} 刚发言过，-30")
            
            # 7. 小幅可复现扰动，避免同分时永久偏向参与者顺序
            jitter = _stable_jitter(context, char_id)
            score += jitter
            
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
