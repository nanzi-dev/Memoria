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
