"""
编排器工具函数单元测试
"""
import pytest, sys, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unittest.mock import Mock, MagicMock, patch

class TestClipping:
    def test_clip(self):
        from memoria.core.multi_character_orchestrator import _clip
        assert _clip(150, -100, 100) == 100
        assert _clip(-150, -100, 100) == -100
        assert _clip(0, -100, 100) == 0
        assert _clip(99, -100, 100) == 99

    def test_safe_float(self):
        from memoria.core.multi_character_orchestrator import _safe_float
        assert _safe_float("3.14") == 3.14
        assert _safe_float("invalid") == 0.0
        assert _safe_float(None) == 0.0
        assert _safe_float(5.5, 99.0) == 5.5
        assert _safe_float("abc", -1.0) == -1.0

class TestHistoryFormatting:
    def test_format_single_role(self):
        from memoria.core.multi_character_orchestrator import MultiCharacterOrchestrator
        orch = type('obj',(object,),{'player_name':'Player','session_id':'s','player_id':'p'})()

    def test_format_with_character_names(self):
        from memoria.core.multi_character_orchestrator import MultiCharacterOrchestrator
        from memoria.db import repository
        sid = str(uuid.uuid4())
        repository.create_multi_character_session(sid,"p","Player",["c1","c2"])
        orch = MultiCharacterOrchestrator(sid)
        hist = [
            {"role":"user","content":"Hi","character_id":None,"character_name":None},
            {"role":"assistant","content":"Hi!","character_id":"c1","character_name":"Char1"},
            {"role":"assistant","content":"Hello!","character_id":"c2","character_name":"Char2"},
        ]
        formatted = orch._format_history_for_llm(hist, "c1")
        assert len(formatted) == 3
        assert formatted[0]["role"] == "user"
        assert formatted[1]["role"] == "assistant"  # own msg
        assert formatted[2]["role"] == "user"  # other char msg

class TestLoadRelationships:
    def test_load_all_relationships(self):
        from memoria.core.multi_character_orchestrator import MultiCharacterOrchestrator
        from memoria.db import repository
        sid = str(uuid.uuid4())
        repository.create_multi_character_session(sid,"p","Player",["a","b","c"])
        repository.save_character_relationship("a","b","friend",50.0)
        orch = MultiCharacterOrchestrator(sid)
        rels = orch._load_all_relationships()
        assert len(rels) >= 1

class TestCharacterInteraction:
    def test_select_character_for_interaction(self):
        from memoria.core.multi_character_orchestrator import MultiCharacterOrchestrator
        from memoria.db import repository
        sid = str(uuid.uuid4())
        repository.create_multi_character_session(sid,"p","Player",["x","y","z"])
        orch = MultiCharacterOrchestrator(sid)
        selected = orch._select_character_for_interaction()
        assert selected in ["x","y","z"]

    def test_decide_group_response_count_uses_discussion_pressure(self, monkeypatch):
        from types import SimpleNamespace
        from memoria.core import multi_character_orchestrator

        orch = multi_character_orchestrator.MultiCharacterOrchestrator.__new__(
            multi_character_orchestrator.MultiCharacterOrchestrator
        )
        orch.participants = [{"character_id": "a"}, {"character_id": "b"}, {"character_id": "c"}]
        orch.character_cards = {
            "a": SimpleNamespace(meta=SimpleNamespace(name="甲", display_name="甲", aliases=[])),
            "b": SimpleNamespace(meta=SimpleNamespace(name="乙", display_name="乙", aliases=[])),
            "c": SimpleNamespace(meta=SimpleNamespace(name="丙", display_name="丙", aliases=[])),
        }
        orch._load_all_relationships = lambda: {
            "a_b": {"affinity": 85, "relationship_type": "宿敌"},
            "b_c": {"affinity": 60, "relationship_type": "盟友"},
        }
        monkeypatch.setattr(multi_character_orchestrator.random, "uniform", lambda a, b: a + 0.2)

        count = orch._decide_group_response_count("大家马上商量一个调查计划，线索很危险，怎么办？", 3)

        assert count >= 2

    def test_decide_group_response_count_single_mention(self):
        from types import SimpleNamespace
        from memoria.core import multi_character_orchestrator

        orch = multi_character_orchestrator.MultiCharacterOrchestrator.__new__(
            multi_character_orchestrator.MultiCharacterOrchestrator
        )
        orch.participants = [{"character_id": "a"}, {"character_id": "b"}, {"character_id": "c"}]
        orch.character_cards = {
            "a": SimpleNamespace(meta=SimpleNamespace(name="甲", display_name="甲", aliases=[])),
            "b": SimpleNamespace(meta=SimpleNamespace(name="乙", display_name="乙", aliases=[])),
            "c": SimpleNamespace(meta=SimpleNamespace(name="丙", display_name="丙", aliases=[])),
        }

        assert orch._decide_group_response_count("乙，你怎么看？", 3) == 1


class TestMultiCharacterGroupMemory:
    def test_load_memory_context_includes_group_memories(self, monkeypatch):
        from types import SimpleNamespace
        from memoria.core import multi_character_orchestrator

        orch = multi_character_orchestrator.MultiCharacterOrchestrator.__new__(
            multi_character_orchestrator.MultiCharacterOrchestrator
        )
        orch.session_id = "session-1"
        orch.player_id = "player-1"
        orch.character_ids = ["c1", "c2"]
        orch.character_cards = {
            "c2": SimpleNamespace(meta=SimpleNamespace(display_name="角色二"))
        }

        def fake_integrate(**kwargs):
            assert kwargs["session_id"] == "session-1"
            assert kwargs["character_id"] == "c1"
            return {
                "group_memories": ["大家决定一起调查旧仓库"],
                "character_impressions": {"c2": ["行动很谨慎"]},
            }

        monkeypatch.setattr(
            multi_character_orchestrator.multi_character_memory,
            "integrate_multi_character_context",
            fake_integrate,
        )

        memory_context = orch._load_memory_context("c1", "旧仓库")

        assert "群体记忆：大家决定一起调查旧仓库" in memory_context
        assert "对角色二的印象：行动很谨慎" in memory_context

    def test_process_player_message_does_not_save_group_memory(self, monkeypatch):
        from memoria.core import multi_character_orchestrator

        save_called = False

        def fake_save_group_event_memory(**kwargs):
            nonlocal save_called
            save_called = True

        monkeypatch.setattr(
            multi_character_orchestrator.repository,
            "append_multi_character_message",
            lambda *args, **kwargs: 1,
        )
        monkeypatch.setattr(
            multi_character_orchestrator.multi_character_memory,
            "save_group_event_memory",
            fake_save_group_event_memory,
        )

        orch = multi_character_orchestrator.MultiCharacterOrchestrator.__new__(
            multi_character_orchestrator.MultiCharacterOrchestrator
        )
        orch.session_id = "session-2"
        orch.player_name = "Player"
        orch.character_ids = ["c1", "c2"]
        orch._decide_next_speaker = lambda player_message: "c1"
        orch._generate_character_response = lambda character_id, player_message: {
            "character_id": character_id,
            "character_name": "角色一",
            "dialogue": "我们马上出发。",
        }

        result = orch.process_player_message("去旧仓库看看")

        assert result["dialogue"] == "我们马上出发。"
        assert save_called is False

    def test_process_player_message_discussion_does_not_save_group_memory(self, monkeypatch):
        from memoria.core import multi_character_orchestrator

        monkeypatch.setattr(
            multi_character_orchestrator.repository,
            "append_multi_character_message",
            lambda *args, **kwargs: 1,
        )
        monkeypatch.setattr(
            multi_character_orchestrator.multi_character_memory,
            "save_group_event_memory",
            lambda **kwargs: (_ for _ in ()).throw(AssertionError("不应在每轮群聊保存群体记忆")),
        )

        orch = multi_character_orchestrator.MultiCharacterOrchestrator.__new__(
            multi_character_orchestrator.MultiCharacterOrchestrator
        )
        orch.session_id = "session-3"
        orch.player_name = "Player"
        orch.participants = [{"character_id": "c1"}, {"character_id": "c2"}, {"character_id": "c3"}]
        orch.character_ids = ["c1", "c2", "c3"]
        orch.character_cards = {}
        orch._generate_group_discussion = lambda player_message, max_responses: [
            {"character_id": "c1", "character_name": "角色一", "dialogue": "我去侦查。"},
            {"character_id": "c2", "character_name": "角色二", "dialogue": "我准备装备。"},
        ]

        result = orch.process_player_message(
            "制定一个计划", allow_multiple_responses=True, max_responses=2
        )

        assert len(result) == 2

    def test_load_memory_context_returns_empty_on_failure(self, monkeypatch):
        from memoria.core import multi_character_orchestrator

        monkeypatch.setattr(
            multi_character_orchestrator.multi_character_memory,
            "integrate_multi_character_context",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db unavailable")),
        )

        orch = multi_character_orchestrator.MultiCharacterOrchestrator.__new__(
            multi_character_orchestrator.MultiCharacterOrchestrator
        )
        orch.session_id = "session-6"
        orch.player_id = "player-1"
        orch.character_ids = ["c1", "c2"]
        orch.character_cards = {}

        assert orch._load_memory_context("c1", "旧仓库") == []

class TestSessionLifecycle:
    """P0-1: Session 状态检查 — 结束后不能继续对话"""

    @pytest.fixture(autouse=True)
    def setup(self):
        import uuid
        from memoria.db import repository
        self.sid = str(uuid.uuid4())
        repository.create_session(self.sid, "lcC", "lcP", "Tester")
        repository.end_session(self.sid)

    def test_run_dialogue_turn_raises_on_ended(self):
        """已结束的 session 调用 run_dialogue_turn 应抛出 ValueError"""
        import pytest
        from memoria.core.orchestrator import run_dialogue_turn
        with pytest.raises(ValueError, match="会话已经结束"):
            run_dialogue_turn(self.sid, "你好")


class TestDialogueTurn:
    def test_event_system_failure_keeps_message_ids_defined(self, monkeypatch):
        """事件系统失败时不应因 message_id 未赋值导致二次崩溃"""
        from types import SimpleNamespace
        from memoria.core import orchestrator

        saved_state = {}
        saved_messages = []
        saved_facts = []

        card = SimpleNamespace(
            action_vocabulary=SimpleNamespace(
                default_action="idle",
                greeting_actions=[],
                farewell_actions=[],
                agreement_actions=[],
                disagreement_actions=[],
                emotional_reactions=[],
            ),
            runtime_state_schema=SimpleNamespace(
                current_mood=SimpleNamespace(emotions=["neutral", "happy"])
            ),
        )

        monkeypatch.setattr(orchestrator.repository, "get_session", lambda session_id: {
            "session_id": session_id,
            "character_id": "char",
            "player_id": "player",
            "player_name": "Tester",
            "created_at": None,
            "status": "active",
        })
        monkeypatch.setattr(orchestrator.character_loader, "load_character_card", lambda character_id: card)
        monkeypatch.setattr(orchestrator.repository, "get_runtime_state", lambda *args, **kwargs: {
            "affection_level": 0,
            "trust_level": 0,
            "current_mood": "neutral",
        })
        monkeypatch.setattr(orchestrator.repository, "get_short_term_history", lambda *args, **kwargs: [])
        monkeypatch.setattr(orchestrator.repository, "get_recent_summaries", lambda *args, **kwargs: [])
        monkeypatch.setattr(orchestrator.prompt_builder, "build_system_prompt", lambda *args, **kwargs: "prompt")
        monkeypatch.setattr(orchestrator.llm_client, "call_role_turn", lambda *args, **kwargs: {
            "dialogue": "你好",
            "action": "idle",
            "affinity_delta": 0,
            "trust_delta": 0,
            "mood_after": "neutral",
            "memory_worth_keeping": "玩家主动打招呼",
        })

        monkeypatch.setattr(
            orchestrator.repository,
            "save_runtime_state",
            lambda character_id, player_id, affection_level, trust_level, current_mood: saved_state.update(
                character_id=character_id,
                player_id=player_id,
                affection_level=affection_level,
                trust_level=trust_level,
                current_mood=current_mood,
            ),
        )
        monkeypatch.setattr(
            orchestrator.repository,
            "append_short_term_message",
            lambda session_id, role, content: saved_messages.append((session_id, role, content)) or len(saved_messages),
        )
        monkeypatch.setattr(
            orchestrator.repository,
            "save_long_term_fact",
            lambda character_id, player_id, fact_text: saved_facts.append((character_id, player_id, fact_text)) or 1,
        )

        def fail_list_event_definitions(*args, **kwargs):
            raise RuntimeError("event storage unavailable")

        monkeypatch.setattr(orchestrator.repository, "list_event_definitions", fail_list_event_definitions)

        result = orchestrator.run_dialogue_turn("sid", "你好")

        assert result["dialogue"] == "你好"
        assert result["current_trust"] == 0
        assert result["user_message_id"] == 1
        assert result["assistant_message_id"] == 2
        assert saved_state == {
            "character_id": "char",
            "player_id": "player",
            "affection_level": 0,
            "trust_level": 0,
            "current_mood": "neutral",
        }
        assert saved_messages == [("sid", "user", "你好"), ("sid", "assistant", "你好")]
        assert saved_facts == [("char", "player", "玩家主动打招呼")]

    def test_persistence_failure_raises(self, monkeypatch):
        """核心对话持久化失败时不应返回成功响应"""
        from types import SimpleNamespace
        from memoria.core import orchestrator

        card = SimpleNamespace(
            action_vocabulary=SimpleNamespace(
                default_action="idle",
                greeting_actions=[],
                farewell_actions=[],
                agreement_actions=[],
                disagreement_actions=[],
                emotional_reactions=[],
            ),
            runtime_state_schema=SimpleNamespace(
                current_mood=SimpleNamespace(emotions=["neutral"])
            ),
        )

        monkeypatch.setattr(orchestrator.repository, "get_session", lambda session_id: {
            "session_id": session_id,
            "character_id": "char",
            "player_id": "player",
            "player_name": "Tester",
            "created_at": None,
            "status": "active",
        })
        monkeypatch.setattr(orchestrator.character_loader, "load_character_card", lambda character_id: card)
        monkeypatch.setattr(orchestrator.repository, "get_runtime_state", lambda *args, **kwargs: {
            "affection_level": 0,
            "trust_level": 0,
            "current_mood": "neutral",
        })
        monkeypatch.setattr(orchestrator.repository, "get_short_term_history", lambda *args, **kwargs: [])
        monkeypatch.setattr(orchestrator.repository, "get_recent_summaries", lambda *args, **kwargs: [])
        monkeypatch.setattr(orchestrator.prompt_builder, "build_system_prompt", lambda *args, **kwargs: "prompt")
        monkeypatch.setattr(orchestrator.llm_client, "call_role_turn", lambda *args, **kwargs: {
            "dialogue": "你好",
            "action": "idle",
            "affinity_delta": 0,
            "trust_delta": 0,
            "mood_after": "neutral",
            "memory_worth_keeping": None,
        })
        monkeypatch.setattr(orchestrator.event_runtime, "detect_and_execute_events", lambda *args, **kwargs: [])
        monkeypatch.setattr(
            orchestrator.event_runtime,
            "apply_event_results_to_dialogue_state",
            lambda event_results, dialogue, affinity, trust, mood: (dialogue, affinity, trust, mood, [], None),
        )
        monkeypatch.setattr(orchestrator.repository, "save_runtime_state", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            orchestrator.repository,
            "append_short_term_message",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db write failed")),
        )

        with pytest.raises(RuntimeError, match="对话持久化失败"):
            orchestrator.run_dialogue_turn("sid", "你好")
