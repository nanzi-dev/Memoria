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
        })

        def fail_list_event_definitions(*args, **kwargs):
            raise RuntimeError("event storage unavailable")

        monkeypatch.setattr(orchestrator.repository, "list_event_definitions", fail_list_event_definitions)

        result = orchestrator.run_dialogue_turn("sid", "你好")

        assert result["dialogue"] == "你好"
        assert result["user_message_id"] is None
        assert result["assistant_message_id"] is None
