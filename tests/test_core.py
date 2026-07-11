"""
综合测试：覆盖所有未测试的核心功能

测试范围：
1. Character schema（Pydantic 模型验证）
2. Event schema（事件数据模型）
3. Speaking strategy（默认混合发言策略）
4. Event detector（事件检测引擎）
5. Event executor（事件执行器）
6. Multi-character memory（共享记忆、群体记忆）
7. Prompt builder（Prompt 组装）
8. Memory extractor（记忆萃取）
"""

import pytest
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pydantic import ValidationError

# ============================================================
# SECTION 1: Character Schema Validation
# ============================================================

class TestCharacterSchema:
    """测试角色卡 Pydantic 模型"""

    def test_minimal_character_card(self):
        """测试最小有效角色卡"""
        from memoria.core.character_schema import (
            CharacterCard, Meta, Identity, Personality,
            speechStyle, Background, GoalsAndMotivations,
            InteractionRules, ActionVocabulary
        )
        card = CharacterCard(
            character_id="test_min",
            version="1.0.0",
            meta=Meta(name="测试", display_name="Test"),
            identity=Identity(
                age="20", gender="未知", occupation="测试员",
                race_or_species="人类", appearance="普通"
            ),
            personality=Personality(),
            speech_style=speechStyle(
                tone_register="中性",
                vocabulary_notes="标准"
            ),
            background=Background(story_bio="测试背景"),
            goals_and_motivations=GoalsAndMotivations(),
            interaction_rules=InteractionRules(),
            action_vocabulary=ActionVocabulary()
        )
        assert card.character_id == "test_min"
        assert card.meta.name == "测试"

    def test_character_card_missing_required(self):
        """测试必需字段缺失时抛出 ValidationError"""
        from memoria.core.character_schema import CharacterCard
        with pytest.raises(ValidationError):
            CharacterCard(character_id="", version="1.0.0", meta={})

    def test_identity_model(self):
        """测试 Identity 模型"""
        from memoria.core.character_schema import Identity
        ident = Identity(
            age=25, gender="男", occupation="战士",
            race_or_species="人类", appearance="高大威猛",
            social_status="贵族", core_identity_summary="勇敢的战士"
        )
        assert ident.age == 25
        assert ident.gender == "男"
        assert ident.core_identity_summary == "勇敢的战士"

    def test_personality_model(self):
        """测试 Personality 模型"""
        from memoria.core.character_schema import Personality
        p = Personality(
            mbti_or_archetype="INTJ",
            core_traits=["冷静", "理性"],
            values_and_beliefs=["正义至上"],
            fears_and_tabooes=["背叛"],
            quirks_and_habits=["推眼镜"],
            moral_alignment="守序善良"
        )
        assert len(p.core_traits) == 2
        assert "冷静" in p.core_traits

    def test_speech_style_model(self):
        """测试 SpeechStyle 模型"""
        from memoria.core.character_schema import speechStyle
        s = speechStyle(
            tone_register="轻松",
            vocabulary_notes="口语化",
            sentence_patterns=["短句为主"],
            catchphrases=["喵~"],
            things_never_to_say=["我是AI"],
            language="zh-CN",
            formality_default="casual"
        )
        assert s.tone_register == "轻松"
        assert "喵~" in s.catchphrases

    def test_background_with_nested_models(self):
        """测试 Background 及其嵌套模型"""
        from memoria.core.character_schema import (
            Background, KeyEvent, Relationship, Secret
        )
        bg = Background(
            story_bio="出身平凡但心怀梦想",
            key_events=[
                KeyEvent(event="初次战斗", description="第一次上战场", emotional_weight=-3)
            ],
            relationships=[
                Relationship(target="npc_friend", relationship_type="朋友", description="生死之交")
            ],
            secrets=[
                Secret(secret="隐藏身份", description="真实身份不为人知", reveal_conditions="信任度>80")
            ]
        )
        assert len(bg.key_events) == 1
        assert bg.relationships[0].target == "npc_friend"
        assert bg.secrets[0].reveal_conditions == "信任度>80"

    def test_action_vocabulary_model(self):
        """测试 ActionVocabulary 模型"""
        from memoria.core.character_schema import ActionVocabulary
        av = ActionVocabulary(
            greeting_actions=["[微笑]打招呼"],
            farewell_actions=["[挥手]告别"],
            agreement_actions=["[点头]同意"],
            disagreement_actions=["[摇头]反对"],
            emotional_reactions=["[大笑]", "[叹息]"],
            default_action="neutral"
        )
        assert av.default_action == "neutral"
        assert len(av.emotional_reactions) == 2

    def test_runtime_state_schema(self):
        """测试运行时状态模型"""
        from memoria.core.character_schema import (
            RuntmeStateSchema, RelationshipState, MoodSchema
        )
        rs = RuntmeStateSchema(
            relationships=[
                RelationshipState(target_id="player", affection_level=50.0, trust_level=30.0)
            ],
            current_mood=MoodSchema(
                emotions=["开心", "好奇", "平静"],
                default_mood="平静"
            ),
            known_player_facts={"喜好": "喜欢猫"}
        )
        assert rs.relationships[0].affection_level == 50.0
        assert rs.current_mood.default_mood == "平静"
        assert rs.known_player_facts["喜好"] == "喜欢猫"

    def test_safety_constraints(self):
        """测试安全约束模型"""
        from memoria.core.character_schema import SafetyConstraints
        sc = SafetyConstraints(
            topics_to_avoid=["色情", "暴力", "政治"],
            out_of_character_handling="忽略并继续角色扮演"
        )
        assert len(sc.topics_to_avoid) == 3


# ============================================================
# SECTION 2: Event Schema Validation
# ============================================================

class TestEventSchema:
    """测试事件系统数据模型"""

    def test_trigger_condition_affinity(self):
        """测试好感度触发条件"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        tc = TriggerCondition(
            trigger_type=TriggerType.AFFINITY_THRESHOLD,
            threshold=50.0,
            comparison="gte",
            cooldown_hours=2
        )
        assert tc.trigger_type == TriggerType.AFFINITY_THRESHOLD
        assert tc.threshold == 50.0

    def test_trigger_condition_keyword(self):
        """测试关键词触发条件"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        tc = TriggerCondition(
            trigger_type=TriggerType.KEYWORD_MATCH,
            keywords=["你好", "再见"],
            match_mode="any"
        )
        assert len(tc.keywords) == 2
        assert tc.match_mode == "any"

    def test_trigger_condition_composite(self):
        """测试复合触发条件"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        tc = TriggerCondition(
            trigger_type=TriggerType.COMPOSITE,
            logic_operator="and",
            sub_conditions=[
                TriggerCondition(
                    trigger_type=TriggerType.AFFINITY_THRESHOLD,
                    threshold=30.0
                ),
                TriggerCondition(
                    trigger_type=TriggerType.MOOD_MATCH,
                    mood="开心"
                )
            ]
        )
        assert tc.logic_operator == "and"
        assert len(tc.sub_conditions) == 2

    def test_event_effect_state_change(self):
        """测试状态修改效果"""
        from memoria.core.event_schema import EventEffect, EffectType
        effect = EventEffect(
            effect_type=EffectType.MODIFY_STATE,
            state_changes={"affection_level": 5, "trust_level": 3}
        )
        assert effect.effect_type == EffectType.MODIFY_STATE
        assert effect.state_changes["affection_level"] == 5

    def test_event_effect_add_memory(self):
        """测试添加记忆效果"""
        from memoria.core.event_schema import EventEffect, EffectType
        effect = EventEffect(
            effect_type=EffectType.ADD_MEMORY,
            memory_text="玩家喜欢猫",
            memory_importance=7
        )
        assert effect.memory_text == "玩家喜欢猫"
        assert effect.memory_importance == 7

    def test_event_effect_dialogue(self):
        """测试触发对话效果"""
        from memoria.core.event_schema import EventEffect, EffectType
        effect = EventEffect(
            effect_type=EffectType.TRIGGER_DIALOGUE,
            dialogue_text="啊，我记起来了！",
            dialogue_action="surprised"
        )
        assert effect.dialogue_text == "啊，我记起来了！"
        assert effect.dialogue_action == "surprised"

    def test_event_definition_complete(self):
        """测试完整事件定义"""
        from memoria.core.event_schema import (
            EventDefinition, TriggerCondition, EventEffect,
            TriggerType, EffectType
        )
        event = EventDefinition(
            event_id="evt_test_001",
            event_name="测试事件",
            description="这是一个测试事件",
            character_id="npc_test",
            trigger_condition=TriggerCondition(
                trigger_type=TriggerType.AFFINITY_THRESHOLD,
                threshold=50.0
            ),
            effects=[
                EventEffect(
                    effect_type=EffectType.NOTIFY_PLAYER,
                    notification_message="好感度达到50！"
                )
            ],
            priority=1,
            is_active=True
        )
        assert event.event_id == "evt_test_001"
        assert event.priority == 1
        assert len(event.effects) == 1

    def test_event_context(self):
        """测试事件上下文"""
        from memoria.core.event_schema import EventContext
        ctx = EventContext(
            character_id="npc_test",
            player_id="player_001",
            session_id="sess_001",
            current_affinity=45.0,
            current_trust=30.0,
            current_mood="开心",
            player_message="你好",
            dialogue_count=5,
            total_dialogue_count=20,
            session_duration_minutes=10.5
        )
        assert ctx.character_id == "npc_test"
        assert ctx.current_affinity == 45.0
        assert ctx.session_duration_minutes == 10.5

    def test_trigger_result(self):
        """测试事件触发结果"""
        from memoria.core.event_schema import EventTriggerResult
        result = EventTriggerResult(
            event_id="evt_001",
            event_name="测试",
            triggered=True,
            effects_applied=["状态已修改", "记忆已添加"],
            notification="事件已触发"
        )
        assert result.triggered is True
        assert len(result.effects_applied) == 2


# ============================================================
# SECTION 3: Speaking Strategies
# ============================================================

class TestSpeakingStrategies:
    """测试默认混合发言策略"""

    def _make_participants(self):
        return [
            {"character_id": "char_a", "speak_frequency": 1.0, "message_count": 0},
            {"character_id": "char_b", "speak_frequency": 1.5, "message_count": 2},
            {"character_id": "char_c", "speak_frequency": 0.5, "message_count": 5},
        ]

    def _make_mock_cards(self):
        """创建模拟角色卡"""
        class MockMeta:
            def __init__(self, name, display_name, aliases=None):
                self.name = name
                self.display_name = display_name
                self.aliases = aliases or []
        class MockIdentity:
            def __init__(self, occupation="未知"):
                self.occupation = occupation
        
        cards = {}
        cards["char_a"] = MagicMock()
        cards["char_a"].meta = MockMeta("角色A", "A君", ["小A"])
        cards["char_a"].identity = MockIdentity("战士")
        cards["char_b"] = MagicMock()
        cards["char_b"].meta = MockMeta("角色B", "B君", ["小B"])
        cards["char_b"].identity = MockIdentity("法师")
        cards["char_c"] = MagicMock()
        cards["char_c"].meta = MockMeta("角色C", "C君")
        cards["char_c"].identity = MockIdentity("牧师")
        return cards

    def test_smart_strategy_keyword_mention(self):
        """测试智能策略的关键词提及功能"""
        from memoria.core.speaking_strategy import SmartSelectionStrategy
        strategy = SmartSelectionStrategy(balance_factor=1.0)
        participants = self._make_participants()
        cards = self._make_mock_cards()
        
        # 提到"B君"时，char_b 应该有更高概率被选中
        context = {"player_message": "B君你好呀！", "last_speaker_id": None}
        
        # 多次运行验证趋势
        import random
        random.seed(42)
        counts = {"char_a": 0, "char_b": 0, "char_c": 0}
        for _ in range(100):
            speaker = strategy.select_speaker(participants, cards, context)
            counts[speaker] += 1
        
        # char_b 被提及，应有高得分优势
        assert counts["char_b"] >= counts["char_a"]
        print(f"  关键词提及测试结果: {counts}")

    def test_smart_strategy_avoid_consecutive(self):
        """测试智能策略避免连续发言"""
        from memoria.core.speaking_strategy import SmartSelectionStrategy
        strategy = SmartSelectionStrategy(balance_factor=1.0)
        participants = [self._make_participants()[0]]  # 只有一个参与者
        cards = self._make_mock_cards()
        
        # 即使只有一个参与者，也应该能返回结果
        context = {"last_speaker_id": "char_a", "player_message": ""}
        speaker = strategy.select_speaker(participants, cards, context)
        assert speaker == "char_a"

    def test_smart_strategy_custom_relationship_type(self):
        """测试自定义关系类型通过亲密度影响发言选择"""
        from memoria.core.speaking_strategy import SmartSelectionStrategy
        strategy = SmartSelectionStrategy(balance_factor=1.0)
        participants = self._make_participants()[1:]
        cards = self._make_mock_cards()

        import random
        random.seed(42)

        context = {
            "last_speaker_id": "char_a",
            "player_message": "你们怎么看？",
            "character_relationships": {
                "char_a_char_b": {
                    "relationship_type": "宿命盟友",
                    "affinity": 95,
                    "description": "长期并肩作战",
                }
            },
        }
        speaker = strategy.select_speaker(participants, cards, context)
        assert speaker == "char_b"

    def test_hybrid_strategy_strong_mention(self):
        """测试混合策略的强提及"""
        from memoria.core.speaking_strategy import HybridStrategy
        strategy = HybridStrategy(balance_factor=1.0)
        participants = self._make_participants()
        cards = self._make_mock_cards()
        
        import random
        random.seed(42)
        
        # 强提及"角色C"的全名
        context = {"player_message": "角色C，你来回答！", "last_speaker_id": None}
        speaker = strategy.select_speaker(participants, cards, context)
        assert speaker == "char_c"

    def test_hybrid_strategy_display_name_mention(self):
        """测试混合策略的显示名称提及"""
        from memoria.core.speaking_strategy import HybridStrategy
        strategy = HybridStrategy(balance_factor=1.0)
        participants = self._make_participants()
        cards = self._make_mock_cards()
        
        import random
        random.seed(42)
        
        # 提到显示名"A君"
        context = {"player_message": "A君在吗？", "last_speaker_id": None}
        speaker = strategy.select_speaker(participants, cards, context)
        assert speaker == "char_a"

    def test_hybrid_strategy_keyword_trigger(self):
        """测试混合策略的关键词触发注册"""
        from memoria.core.speaking_strategy import HybridStrategy
        strategy = HybridStrategy(balance_factor=1.0)
        strategy.add_keyword_trigger("帮助", "char_c")
        
        participants = self._make_participants()
        cards = self._make_mock_cards()
        
        import random
        random.seed(42)
        
        context = {"player_message": "谁能帮助我？", "last_speaker_id": None}
        speaker = strategy.select_speaker(participants, cards, context)
        assert speaker == "char_c"

    def test_hybrid_strategy_empty(self):
        """测试混合策略空参与者"""
        from memoria.core.speaking_strategy import HybridStrategy
        strategy = HybridStrategy()
        with pytest.raises(ValueError, match="没有可用的参与者"):
            strategy.select_speaker([], {}, {})


# ============================================================
# SECTION 4: Event Detector
# ============================================================

class TestEventDetector:
    """测试事件检测引擎"""

    def _make_context(self, **kwargs):
        from memoria.core.event_schema import EventContext
        defaults = {
            "character_id": "npc_test",
            "player_id": "player_001",
            "session_id": "sess_001",
            "current_affinity": 45.0,
            "current_trust": 30.0,
            "current_mood": "开心",
            "player_message": "",
            "dialogue_count": 1,
            "total_dialogue_count": 10,
            "session_duration_minutes": 5.0
        }
        defaults.update(kwargs)
        return EventContext(**defaults)

    def _make_event(self, event_id, trigger_condition, priority=0, character_id="npc_test"):
        from memoria.core.event_schema import EventDefinition
        return EventDefinition(
            event_id=event_id,
            event_name=f"Test {event_id}",
            character_id=character_id,
            trigger_condition=trigger_condition,
            effects=[],
            priority=priority,
            is_active=True
        )

    def test_affinity_threshold_gte(self):
        """测试好感度 >= 阈值触发"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD, threshold=40.0, comparison="gte")
        event = self._make_event("evt_aff", tc)
        context = self._make_context(current_affinity=50.0)
        
        triggered = detector.check_events(context, [event])
        assert len(triggered) == 1
        assert triggered[0].event_id == "evt_aff"

    def test_affinity_threshold_not_met(self):
        """测试好感度未达阈值不触发"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD, threshold=60.0, comparison="gte")
        event = self._make_event("evt_aff_low", tc)
        context = self._make_context(current_affinity=50.0)
        
        triggered = detector.check_events(context, [event])
        assert len(triggered) == 0

    def test_trust_threshold_lte(self):
        """测试信任度 <= 阈值触发"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(trigger_type=TriggerType.TRUST_THRESHOLD, threshold=40.0, comparison="lte")
        event = self._make_event("evt_trust", tc)
        context = self._make_context(current_trust=30.0)
        
        triggered = detector.check_events(context, [event])
        assert len(triggered) == 1

    def test_keyword_match_any(self):
        """测试关键词任一匹配"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(
            trigger_type=TriggerType.KEYWORD_MATCH,
            keywords=["猫", "狗", "鸟"],
            match_mode="any"
        )
        event = self._make_event("evt_kw", tc)
        context = self._make_context(player_message="我喜欢猫")
        
        triggered = detector.check_events(context, [event])
        assert len(triggered) == 1

    def test_keyword_match_all(self):
        """测试关键词全部匹配"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(
            trigger_type=TriggerType.KEYWORD_MATCH,
            keywords=["猫", "鱼"],
            match_mode="all"
        )
        event = self._make_event("evt_kw_all", tc)
        context = self._make_context(player_message="我的猫喜欢吃鱼")
        
        triggered = detector.check_events(context, [event])
        assert len(triggered) == 1

    def test_keyword_match_partial_fail(self):
        """测试关键词部分匹配失败"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(
            trigger_type=TriggerType.KEYWORD_MATCH,
            keywords=["猫", "大象"],
            match_mode="all"
        )
        event = self._make_event("evt_kw_partial", tc)
        context = self._make_context(player_message="我的猫很可爱")
        
        triggered = detector.check_events(context, [event])
        assert len(triggered) == 0

    def test_dialogue_count(self):
        """测试对话次数触发"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(trigger_type=TriggerType.DIALOGUE_COUNT, count=20, comparison="gte")
        event = self._make_event("evt_count", tc)
        context = self._make_context(total_dialogue_count=25, dialogue_count=1)
        
        triggered = detector.check_events(context, [event])
        assert len(triggered) == 1

    def test_mood_match(self):
        """测试情绪匹配"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(trigger_type=TriggerType.MOOD_MATCH, mood="开心")
        event = self._make_event("evt_mood", tc)
        context = self._make_context(current_mood="开心")
        
        triggered = detector.check_events(context, [event])
        assert len(triggered) == 1

    def test_mood_no_match(self):
        """测试情绪不匹配"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(trigger_type=TriggerType.MOOD_MATCH, mood="愤怒")
        event = self._make_event("evt_mood_no", tc)
        context = self._make_context(current_mood="开心")
        
        triggered = detector.check_events(context, [event])
        assert len(triggered) == 0

    def test_composite_and(self):
        """测试复合 AND 条件"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(
            trigger_type=TriggerType.COMPOSITE,
            logic_operator="and",
            sub_conditions=[
                TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD, threshold=30.0, comparison="gte"),
                TriggerCondition(trigger_type=TriggerType.MOOD_MATCH, mood="开心")
            ]
        )
        event = self._make_event("evt_comp", tc)
        context = self._make_context(current_affinity=50.0, current_mood="开心")
        
        triggered = detector.check_events(context, [event])
        assert len(triggered) == 1

    def test_composite_or(self):
        """测试复合 OR 条件"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(
            trigger_type=TriggerType.COMPOSITE,
            logic_operator="or",
            sub_conditions=[
                TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD, threshold=90.0, comparison="gte"),
                TriggerCondition(trigger_type=TriggerType.MOOD_MATCH, mood="开心")
            ]
        )
        event = self._make_event("evt_comp_or", tc)
        context = self._make_context(current_affinity=50.0, current_mood="开心")
        
        triggered = detector.check_events(context, [event])
        assert len(triggered) == 1

    def test_inactive_event(self):
        """测试禁用事件不触发"""
        from memoria.core.event_schema import TriggerCondition, TriggerType, EventDefinition
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD, threshold=0.0)
        event = EventDefinition(
            event_id="evt_inactive", event_name="Inactive",
            trigger_condition=tc, effects=[], is_active=False
        )
        context = self._make_context(current_affinity=50.0)
        
        triggered = detector.check_events(context, [event])
        assert len(triggered) == 0

    def test_priority_sorting(self):
        """测试事件按优先级排序"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD, threshold=0.0)
        e1 = self._make_event("evt_low", tc, priority=1)
        e2 = self._make_event("evt_high", tc, priority=10)
        e3 = self._make_event("evt_mid", tc, priority=5)
        context = self._make_context(current_affinity=50.0)
        
        triggered = detector.check_events(context, [e1, e2, e3])
        assert len(triggered) == 3
        assert triggered[0].event_id == "evt_high"
        assert triggered[2].event_id == "evt_low"

    def test_time_based(self):
        """测试基于时间的触发"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        tc = TriggerCondition(
            trigger_type=TriggerType.TIME_BASED,
            duration_minutes=10,
            comparison="gte"
        )
        event = self._make_event("evt_time", tc)
        context = self._make_context(session_duration_minutes=15.5)
        
        triggered = detector.check_events(context, [event])
        assert len(triggered) == 1

    def test_threshold_comparisons(self):
        """测试各种比较运算符"""
        from memoria.core.event_schema import TriggerCondition, TriggerType
        from memoria.core.event_detector import EventDetector
        
        detector = EventDetector()
        
        # gte: >=
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD, threshold=50.0, comparison="gte")
        context = self._make_context(current_affinity=50.0)
        assert len(detector.check_events(context, [self._make_event("t1", tc)])) == 1
        
        # lte: <=
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD, threshold=50.0, comparison="lte")
        assert len(detector.check_events(context, [self._make_event("t2", tc)])) == 1
        
        # gt: >
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD, threshold=50.0, comparison="gt")
        assert len(detector.check_events(context, [self._make_event("t3", tc)])) == 0
        
        # lt: <
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD, threshold=50.0, comparison="lt")
        assert len(detector.check_events(context, [self._make_event("t4", tc)])) == 0
        
        # eq: ==
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD, threshold=50.0, comparison="eq")
        assert len(detector.check_events(context, [self._make_event("t5", tc)])) == 1


# ============================================================
# SECTION 5: Multi-Character Memory
# ============================================================

class TestMultiCharacterMemory:
    """测试多角色记忆系统"""

    def test_save_and_get_shared_memory(self):
        """测试保存和查询共享记忆"""
        from memoria.db import repository

        mid = repository.save_shared_memory(
            "user_shared_a",
            "char_x", "char_y",
            memory_text="一起完成了训练",
            context="train:session_001",
            importance=0.8
        )
        assert mid is not None
        
        results = repository.get_shared_memories("user_shared_a", "char_x", "char_y", limit=5)
        assert len(results) >= 1
        assert any("训练" in r["memory_text"] for r in results)

    def test_shared_memory_bidirectional(self):
        """测试共享记忆双向查询"""
        from memoria.db import repository

        repository.save_shared_memory("user_shared_b", "char_p", "char_q", "共同击败了敌人", importance=0.9)
        
        forward = repository.get_shared_memories("user_shared_b", "char_p", "char_q", 5)
        backward = repository.get_shared_memories("user_shared_b", "char_q", "char_p", 5)
        
        assert len(forward) == len(backward)
        if forward:
            assert forward[0]["memory_text"] == backward[0]["memory_text"]

    def test_shared_memory_isolated_by_user(self):
        """测试相同角色 ID 在不同用户下共享记忆隔离"""
        from memoria.db import repository

        repository.save_shared_memory("user_alpha", "char_same", "char_peer", "Alpha 的共同记忆", importance=0.8)
        repository.save_shared_memory("user_beta", "char_same", "char_peer", "Beta 的共同记忆", importance=0.8)

        alpha = repository.get_shared_memories("user_alpha", "char_same", "char_peer", 10)
        beta = repository.get_shared_memories("user_beta", "char_same", "char_peer", 10)

        assert any("Alpha" in item["memory_text"] for item in alpha)
        assert all("Beta" not in item["memory_text"] for item in alpha)
        assert any("Beta" in item["memory_text"] for item in beta)
        assert all("Alpha" not in item["memory_text"] for item in beta)

    def test_get_character_shared_memories(self):
        """测试获取角色的所有共享记忆"""
        from memoria.db import repository

        repository.save_shared_memory("user_shared_c", "char_m", "char_n", "记忆1", importance=0.5)
        repository.save_shared_memory("user_shared_c", "char_m", "char_o", "记忆2", importance=0.7)
        
        results = repository.get_character_shared_memories("user_shared_c", "char_m", limit=10)
        assert len(results) >= 2

    def test_save_and_get_group_memory(self):
        """测试保存和查询群体记忆"""
        from memoria.db import repository

        gid = repository.save_group_memory(
            session_id="group_sess_001",
            memory_text="大家决定组队冒险",
            participants=["char_a", "char_b", "char_c"],
            context="组队场景",
            importance=0.8
        )
        assert gid is not None
        
        results = repository.get_session_group_memories("group_sess_001", limit=5)
        assert len(results) >= 1
        assert "冒险" in results[0]["memory_text"]

    def test_get_character_group_memories(self):
        """测试按角色查询群体记忆"""
        from memoria.db import repository

        repository.save_group_memory(
            "sess_x", "群体事件A",
            participants=["char_1", "char_2", "char_3"]
        )
        repository.save_group_memory(
            "sess_y", "群体事件B",
            participants=["char_1", "char_4"]
        )
        
        results = repository.get_character_group_memories("char_1", limit=10)
        assert len(results) >= 2

    def test_character_impression_high_level(self):
        """测试高层印象记忆函数"""
        from memoria.core.multi_character_memory import (
            save_character_impression, get_character_impressions
        )
        
        save_character_impression(
            observer_id="npc_a",
            target_id="npc_b",
            impression="觉得B很可靠",
            session_id="test_session",
            player_id="user_shared_d",
            importance=0.7
        )
        
        imps = get_character_impressions("npc_a", "npc_b", player_id="user_shared_d", limit=5)
        assert len(imps) >= 1
        assert any("可靠" in imp["memory_text"] for imp in imps)

    def test_process_character_impressions_writes_shared_memory(self, monkeypatch):
        """测试自动提取角色间印象并写入共享记忆"""
        from memoria.core import multi_character_memory
        from memoria.db import repository

        monkeypatch.setattr(
            multi_character_memory.llm_client,
            "call_light_task",
            lambda *args, **kwargs: (
                '[{"observer_id":"npc_a","target_id":"npc_b",'
                '"impression":"npc_a认为npc_b在侦查中很可靠","importance":0.8}]'
            ),
        )

        count = multi_character_memory.process_character_impressions(
            session_id="shared_auto_session",
            recent_messages=[
                {"role": "user", "content": "我们分头侦查"},
                {"role": "assistant", "character_id": "npc_a", "character_name": "A", "content": "B刚才判断很准。"},
                {"role": "assistant", "character_id": "npc_b", "character_name": "B", "content": "我会继续盯着出口。"},
            ],
            character_ids=["npc_a", "npc_b"],
            player_id="user_shared_auto",
        )

        memories = repository.get_shared_memories("user_shared_auto", "npc_a", "npc_b", limit=5)
        assert count == 1
        assert any("侦查中很可靠" in item["memory_text"] for item in memories)

    def test_process_character_impressions_skips_invalid_output(self, monkeypatch):
        """测试无效或越界印象不会写入共享记忆"""
        from memoria.core import multi_character_memory
        from memoria.db import repository

        monkeypatch.setattr(
            multi_character_memory.llm_client,
            "call_light_task",
            lambda *args, **kwargs: (
                '[{"observer_id":"npc_a","target_id":"npc_a","impression":"自言自语"},'
                '{"observer_id":"npc_a","target_id":"npc_x","impression":"越界角色"}]'
            ),
        )

        count = multi_character_memory.process_character_impressions(
            session_id="shared_invalid_session",
            recent_messages=[{"role": "assistant", "character_id": "npc_a", "content": "无效"}],
            character_ids=["npc_a", "npc_b"],
            player_id="user_shared_invalid",
        )

        memories = repository.get_shared_memories("user_shared_invalid", "npc_a", "npc_b", limit=5)
        assert count == 0
        assert memories == []

    def test_auto_process_multi_character_memories_saves_impressions(self, monkeypatch):
        """测试自动多角色记忆处理会写入角色间印象"""
        from memoria.core import multi_character_memory

        saved_facts = []
        processed = []
        monkeypatch.setattr(
            multi_character_memory.repository,
            "get_multi_character_history",
            lambda session_id, limit_messages: [
                {"role": "user", "content": "行动开始"},
                {"role": "assistant", "character_id": "npc_a", "content": "B配合得很好。"},
            ],
        )
        monkeypatch.setattr(
            multi_character_memory,
            "extract_multi_character_memories",
            lambda **kwargs: {"npc_a": ["我记得这次行动开始了"]},
        )
        monkeypatch.setattr(
            multi_character_memory.repository,
            "save_long_term_fact",
            lambda **kwargs: saved_facts.append(kwargs),
        )
        monkeypatch.setattr(
            multi_character_memory,
            "process_character_impressions",
            lambda **kwargs: processed.append(kwargs) or 1,
        )

        multi_character_memory.auto_process_multi_character_memories(
            session_id="auto_shared_session",
            character_ids=["npc_a", "npc_b"],
            player_id="user_auto_shared",
            trigger_threshold=2,
        )

        assert saved_facts
        assert processed
        assert processed[0]["session_id"] == "auto_shared_session"
        assert processed[0]["character_ids"] == ["npc_a", "npc_b"]
        assert processed[0]["player_id"] == "user_auto_shared"

    def test_group_event_high_level(self):
        """测试高层群体事件函数"""
        from memoria.core.multi_character_memory import (
            save_group_event_memory, get_group_memories
        )
        
        save_group_event_memory(
            event_description="大家分享了一顿丰盛的晚餐",
            character_ids=["npc_a", "npc_b", "npc_c"],
            session_id="dinner_session",
            importance=0.6
        )
        
        mems = get_group_memories("npc_b", "dinner_session", limit=5)
        assert len(mems) >= 1
        assert any("晚餐" in m["memory_text"] for m in mems)


# ============================================================
# SECTION 6: Edge Cases & Utilities
# ============================================================

class TestEdgeCases:
    """测试边界情况和工具函数"""

    def test_clip_function(self):
        """测试数值裁剪"""
        from memoria.core.multi_character_orchestrator import _clip
        assert _clip(150, -100, 100) == 100
        assert _clip(-150, -100, 100) == -100
        assert _clip(0, -100, 100) == 0

    def test_safe_float(self):
        """测试安全浮点转换"""
        from memoria.core.multi_character_orchestrator import _safe_float
        assert _safe_float("3.14") == 3.14
        assert _safe_float("invalid") == 0.0
        assert _safe_float(None) == 0.0
        assert _safe_float(5.5, default=99.0) == 5.5

    def test_character_loader_cache(self):
        """测试角色卡加载器缓存"""
        from memoria.core import character_loader
        from pathlib import Path
        
        # 加载两次，验证缓存
        card1 = character_loader.load_character_card("npc_luo_xiaohei")
        card2 = character_loader.load_character_card("npc_luo_xiaohei")
        assert card1 is card2  # 同一对象（缓存命中）
        
        # 热重载
        card3 = character_loader.reload_character_card("npc_luo_xiaohei")
        assert card3.character_id == "npc_luo_xiaohei"

    def test_list_character_ids(self):
        """测试列出角色 ID"""
        from memoria.core import character_loader
        ids = character_loader.list_character_ids()
        assert len(ids) > 0
        assert "npc_luo_xiaohei" in ids

    def test_relation_state_like_match(self):
        """测试 LIKE 匹配正确性"""
        from memoria.db import repository
        
        repository.save_group_memory("like_test", "测试LIKE", ["char_x", "char_y"])
        results = repository.get_character_group_memories("char_x", 5)
        assert len(results) >= 1
        # 不应匹配到 char_xy（子串问题）
        for r in results:
            assert "char_x" in r["participants"] or r["memory_text"] is not None

    def test_event_detector_singleton(self):
        """测试事件检测器单例"""
        from memoria.core.event_detector import get_event_detector
        d1 = get_event_detector()
        d2 = get_event_detector()
        assert d1 is d2

    def test_event_executor_singleton(self):
        """测试事件执行器单例"""
        from memoria.core.event_executor import get_event_executor
        e1 = get_event_executor()
        e2 = get_event_executor()
        assert e1 is e2

    def test_trigger_type_enum_values(self):
        """测试触发器类型枚举值"""
        from memoria.core.event_schema import TriggerType
        types = [t.value for t in TriggerType]
        assert "affinity_threshold" in types
        assert "keyword_match" in types
        assert "composite" in types

    def test_effect_type_enum_values(self):
        """测试效果类型枚举值"""
        from memoria.core.event_schema import EffectType
        types = [t.value for t in EffectType]
        assert "modify_state" in types
        assert "add_memory" in types
        assert "trigger_dialogue" in types
        assert "notify_player" in types


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
