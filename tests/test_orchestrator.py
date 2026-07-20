"""
编排器工具函数单元测试
"""
import pytest, sys, uuid
import json
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

    def test_format_history_filters_relationship_claims_that_conflict_with_graph(self):
        from types import SimpleNamespace
        from memoria.core import multi_character_orchestrator

        orch = multi_character_orchestrator.MultiCharacterOrchestrator.__new__(
            multi_character_orchestrator.MultiCharacterOrchestrator
        )
        orch.session_id = "session-rel-history"
        orch.player_name = "Player"
        orch.character_ids = ["npc_wuxian", "npc_wanjiji"]
        orch.character_cards = {
            "npc_wuxian": SimpleNamespace(
                meta=SimpleNamespace(name="无限", display_name="无限", aliases=[])
            ),
            "npc_wanjiji": SimpleNamespace(
                meta=SimpleNamespace(name="晚叽叽", display_name="晚叽叽", aliases=[])
            ),
        }
        history = [
            {"role": "user", "content": "你们是什么关系？"},
            {
                "role": "assistant",
                "content": "我和晚叽叽是师徒。",
                "character_id": "npc_wuxian",
                "character_name": "无限",
            },
            {
                "role": "assistant",
                "content": "我们现在是敌人。",
                "character_id": "npc_wanjiji",
                "character_name": "晚叽叽",
            },
            {
                "role": "assistant",
                "content": "我会检查周围。",
                "character_id": "npc_wuxian",
                "character_name": "无限",
            },
        ]

        formatted = orch._format_history_for_llm(
            history,
            "npc_wuxian",
            character_relationships={
                "npc_wanjiji_npc_wuxian": {
                    "relationship_type": "enemy",
                    "affinity": 100,
                }
            },
        )
        contents = [msg["content"] for msg in formatted]

        assert any("你们是什么关系" in content for content in contents)
        assert not any("师徒" in content for content in contents)
        assert any("敌人" in content for content in contents)
        assert any("检查周围" in content for content in contents)

    def test_format_history_filters_deleted_graph_edge_relationship_claims(self):
        from types import SimpleNamespace
        from memoria.core import multi_character_orchestrator

        orch = multi_character_orchestrator.MultiCharacterOrchestrator.__new__(
            multi_character_orchestrator.MultiCharacterOrchestrator
        )
        orch.session_id = "session-undefined-history"
        orch.player_name = "Player"
        orch.character_ids = ["c1", "c2"]
        orch.character_cards = {
            "c1": SimpleNamespace(meta=SimpleNamespace(name="甲", display_name="甲", aliases=[])),
            "c2": SimpleNamespace(meta=SimpleNamespace(name="乙", display_name="乙", aliases=[])),
        }

        formatted = orch._format_history_for_llm(
            [
                {
                    "role": "assistant",
                    "content": "我们已经是师徒了。",
                    "character_id": "c1",
                    "character_name": "甲",
                },
                {
                    "role": "assistant",
                    "content": "刚才的线索在门边。",
                    "character_id": "c1",
                    "character_name": "甲",
                },
            ],
            "c1",
            character_relationships={},
        )

        contents = [msg["content"] for msg in formatted]
        assert not any("师徒" in content for content in contents)
        assert any("门边" in content for content in contents)

class TestLoadRelationships:
    def test_load_all_relationships(self):
        from memoria.core.multi_character_orchestrator import MultiCharacterOrchestrator
        from memoria.db import repository
        sid = str(uuid.uuid4())
        for cid in ("a", "b", "c"):
            card = json.dumps({"character_id": cid, "meta": {"name": cid, "display_name": cid}})
            repository.save_character_card_to_db("p", cid, card, name=cid, display_name=cid)
        repository.create_multi_character_session(sid,"p","Player",["a","b","c"])
        repository.save_character_relationship("p","a","b","friend",50.0)
        orch = MultiCharacterOrchestrator(sid)
        rels = orch._load_all_relationships()
        assert len(rels) >= 1

class TestCharacterInteraction:
    def test_select_character_for_interaction(self):
        from memoria.core.multi_character_orchestrator import MultiCharacterOrchestrator
        from memoria.db import repository
        sid = str(uuid.uuid4())
        for cid in ("x", "y", "z"):
            card = json.dumps({"character_id": cid, "meta": {"name": cid, "display_name": cid}})
            repository.save_character_card_to_db("p", cid, card, name=cid, display_name=cid)
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

    def test_load_memory_context_filters_relationship_memories_conflicting_with_graph(self, monkeypatch):
        from types import SimpleNamespace
        from memoria.core import multi_character_orchestrator

        orch = multi_character_orchestrator.MultiCharacterOrchestrator.__new__(
            multi_character_orchestrator.MultiCharacterOrchestrator
        )
        orch.session_id = "session-graph-memory"
        orch.player_id = "player-1"
        orch.character_ids = ["c1", "c2"]
        orch.character_cards = {
            "c1": SimpleNamespace(meta=SimpleNamespace(name="甲", display_name="甲", aliases=[])),
            "c2": SimpleNamespace(meta=SimpleNamespace(name="乙", display_name="乙", aliases=[])),
        }

        monkeypatch.setattr(
            multi_character_orchestrator.multi_character_memory,
            "integrate_multi_character_context",
            lambda **kwargs: {
                "group_memories": ["甲和乙是师徒", "大家决定调查旧仓库"],
                "character_impressions": {"c2": ["甲认为乙是徒弟", "行动很谨慎"]},
            },
        )

        memory_context = orch._load_memory_context(
            "c1",
            character_relationships={
                "c1_c2": {
                    "relationship_type": "enemy",
                    "affinity": 100,
                }
            },
        )

        assert not any("师徒" in item or "徒弟" in item for item in memory_context)
        assert "群体记忆：大家决定调查旧仓库" in memory_context
        assert "对乙的印象：行动很谨慎" in memory_context

    def test_load_runtime_state_filters_conflicting_relation_facts_only(self, monkeypatch):
        from types import SimpleNamespace
        from memoria.core import multi_character_orchestrator

        orch = multi_character_orchestrator.MultiCharacterOrchestrator.__new__(
            multi_character_orchestrator.MultiCharacterOrchestrator
        )
        orch.player_id = "player-1"
        orch.session_id = "group-session-1"
        orch.character_ids = ["c1", "c2"]
        orch.character_cards = {
            "c1": SimpleNamespace(meta=SimpleNamespace(name="甲", display_name="甲", aliases=[])),
            "c2": SimpleNamespace(meta=SimpleNamespace(name="乙", display_name="乙", aliases=[])),
        }
        captured = {}

        monkeypatch.setattr(
            multi_character_orchestrator.repository,
            "get_runtime_state",
            lambda *args, **kwargs: {
                "affection_level": 0,
                "trust_level": 0,
                "current_mood": "neutral",
            },
        )
        monkeypatch.setattr(
            multi_character_orchestrator.multi_character_memory,
            "load_player_memories_for_relationship_graph",
            lambda **kwargs: captured.update(kwargs)
            or ["甲和乙是师徒", "玩家喜欢猫", "大家一起调查旧仓库"],
        )

        state = orch._load_runtime_state_for_prompt(
            "c1",
            card=object(),
            character_relationships={
                "c1_c2": {
                    "relationship_type": "enemy",
                    "affinity": 100,
                }
            },
        )

        assert "甲和乙是师徒" not in state["known_player_facts"]
        assert "玩家喜欢猫" in state["known_player_facts"]
        assert "大家一起调查旧仓库" in state["known_player_facts"]
        assert captured["session_id"] == "group-session-1"

    def test_process_player_message_does_not_save_group_memory(self, monkeypatch):
        from memoria.core import multi_character_orchestrator

        save_called = False

        def fake_save_group_event_memory(**kwargs):
            nonlocal save_called
            save_called = True

        monkeypatch.setattr(
            multi_character_orchestrator.repository,
            "claim_dialogue_turn",
            lambda **kwargs: {"completed": False, "lease_owner": "lease"},
        )
        monkeypatch.setattr(
            multi_character_orchestrator.repository,
            "commit_dialogue_turn",
            lambda **kwargs: kwargs["dialogue_turn"]["response"],
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
        orch.player_id = "player-1"
        orch.player_name = "Player"
        orch.participants = [{"character_id": "c1"}, {"character_id": "c2"}]
        orch.character_ids = ["c1", "c2"]
        orch._decide_next_speaker = (
            lambda player_message, turn_context=None: "c1"
        )
        orch._build_pulse_state = lambda *args, **kwargs: {}
        orch._generate_character_response = lambda character_id, player_message, **kwargs: {
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
            "claim_dialogue_turn",
            lambda **kwargs: {"completed": False, "lease_owner": "lease"},
        )
        monkeypatch.setattr(
            multi_character_orchestrator.repository,
            "commit_dialogue_turn",
            lambda **kwargs: kwargs["dialogue_turn"]["response"],
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
        orch.player_id = "player-1"
        orch.player_name = "Player"
        orch.participants = [{"character_id": "c1"}, {"character_id": "c2"}, {"character_id": "c3"}]
        orch.character_ids = ["c1", "c2", "c3"]
        orch.character_cards = {}
        orch._generate_group_discussion = lambda player_message, max_responses, **kwargs: [
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


def test_start_session_marker_blocks_legacy_when_claim_retrieval_fails(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from memoria.core import orchestrator
    from memoria.db import repository

    player_id = f"marker-player-{uuid.uuid4().hex}"
    character_id = f"marker-character-{uuid.uuid4().hex}"
    legacy_fact = "旧系统记录：玩家知道北闸门口令。"
    marker = repository.LONG_TERM_FACT_BACKFILL_MIGRATION
    captured = {}
    card = SimpleNamespace(
        meta=SimpleNamespace(
            name="Marker Character",
            display_name="Marker Character",
            aliases=[],
        ),
        runtime_state_schema=SimpleNamespace(
            affection_level=0,
            trust_level=10,
            current_mood=SimpleNamespace(default_mood="neutral"),
        ),
        action_vocabulary=SimpleNamespace(default_action="idle"),
    )
    clock_snapshot = SimpleNamespace(
        world_now=datetime.now(timezone.utc),
        prompt_context=lambda *args, **kwargs: "time context",
    )

    repository.save_long_term_fact(character_id, player_id, legacy_fact)
    with repository.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO data_migration (migration_key, metadata, applied_at)
            VALUES (?, '{}', ?)
            ON CONFLICT(migration_key) DO UPDATE SET applied_at = excluded.applied_at
            """,
            (marker, datetime.now(timezone.utc).isoformat()),
        )

    monkeypatch.setattr(
        repository,
        "get_prompt_memory_fact_records",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("ledger unavailable")),
    )
    monkeypatch.setattr(
        orchestrator,
        "_load_player_character",
        lambda *args, **kwargs: {
            "display_name": "Marker Player",
            "node_id": repository.player_node_id(player_id),
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "_load_character_card",
        lambda *args, **kwargs: card,
    )
    monkeypatch.setattr(
        orchestrator.world_clock,
        "get_clock_snapshot",
        lambda *args, **kwargs: clock_snapshot,
    )
    monkeypatch.setattr(
        repository,
        "get_last_character_interaction_world_at",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(repository, "get_recent_summaries", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        orchestrator,
        "_build_system_prompt",
        lambda card, runtime_state, *args, **kwargs: (
            captured.update(runtime_state=runtime_state) or "system prompt"
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "_build_opening_line_prompt",
        lambda *args, **kwargs: "\nopening",
    )
    monkeypatch.setattr(
        orchestrator.llm_client,
        "call_role_turn",
        lambda **kwargs: {"dialogue": "你好", "action": "idle"},
    )
    monkeypatch.setattr(
        orchestrator,
        "_append_short_term_message",
        lambda *args, **kwargs: 1,
    )

    try:
        orchestrator.start_session(
            character_id,
            player_id,
            "Marker Player",
        )
    finally:
        with repository.get_conn() as conn:
            conn.execute(
                "DELETE FROM data_migration WHERE migration_key = ?",
                (marker,),
            )

    assert legacy_fact not in captured["runtime_state"]["known_player_facts"]


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
        saved_claims = []
        queued_jobs = []
        legacy_writes = []

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
        monkeypatch.setattr(orchestrator.character_loader, "load_character_card", lambda character_id, owner_user_id=None: card)
        monkeypatch.setattr(orchestrator.repository, "get_runtime_state", lambda *args, **kwargs: {
            "affection_level": 0,
            "trust_level": 0,
            "current_mood": "neutral",
        })
        monkeypatch.setattr(
            orchestrator.repository,
            "get_short_term_history",
            lambda *args, **kwargs: [
                {"role": role, "content": content}
                for _, role, content in saved_messages
            ],
        )
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
            "claim_dialogue_turn",
            lambda **kwargs: {"completed": False, "lease_owner": "lease"},
        )

        def commit_turn(*, dialogue_turn, runtime_states):
            state = runtime_states[0]
            saved_state.update(
                character_id=state["character_id"],
                player_id=dialogue_turn["player_id"],
                affection_level=state["affection_level"],
                trust_level=state["trust_level"],
                current_mood=state["current_mood"],
            )
            saved_messages.extend(
                (dialogue_turn["session_id"], message["role"], message["content"])
                for message in dialogue_turn["messages"]
            )
            dialogue_turn["response"]["user_message_id"] = 1
            dialogue_turn["response"]["assistant_message_id"] = 2
            queued_jobs.extend(dialogue_turn.get("background_jobs") or [])
            return dialogue_turn["response"]

        monkeypatch.setattr(orchestrator.repository, "commit_dialogue_turn", commit_turn)
        monkeypatch.setattr(
            orchestrator.repository,
            "get_session_user_turn_count",
            lambda session_id: orchestrator.configs.long_term_memory_interval_turns - 1,
        )
        extracted_histories = []
        monkeypatch.setattr(
            orchestrator.repository,
            "save_long_term_fact",
            lambda *args, **kwargs: legacy_writes.append((args, kwargs)),
        )
        def fail_list_event_definitions(*args, **kwargs):
            raise RuntimeError("event storage unavailable")

        monkeypatch.setattr(orchestrator.repository, "list_event_definitions", fail_list_event_definitions)

        orchestrator.performance.reset()
        result = orchestrator.run_dialogue_turn(
            "sid",
            "你好",
            request_id="req-single-memory",
        )

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
        assert extracted_histories == []
        assert saved_claims == []
        assert queued_jobs == []
        assert (
            orchestrator.performance.snapshot()["counters"][
                "llm.calls_avoided.memory_gate"
            ]
            == 1
        )
        assert legacy_writes == []

    def test_single_dialogue_prompt_uses_graph_and_cross_mode_memories(self, monkeypatch):
        """单聊 prompt 应读取当前关系图谱，并共享同角色的群聊/共享记忆。"""
        from types import SimpleNamespace
        from memoria.core import orchestrator

        captured = {}
        saved_messages = []
        card = SimpleNamespace(
            meta=SimpleNamespace(name="甲", display_name="甲", aliases=[]),
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
            "character_id": "char_a",
            "player_id": "player",
            "player_name": "Tester",
            "created_at": None,
            "status": "active",
        })
        monkeypatch.setattr(orchestrator.character_loader, "load_character_card", lambda *args, **kwargs: card)
        monkeypatch.setattr(orchestrator.repository, "get_runtime_state", lambda *args, **kwargs: {
            "affection_level": 0,
            "trust_level": 10,
            "current_mood": "neutral",
            "known_player_facts": ["未过滤的默认记忆"],
        })
        monkeypatch.setattr(orchestrator.repository, "get_short_term_history", lambda *args, **kwargs: [])
        monkeypatch.setattr(orchestrator.repository, "get_recent_summaries", lambda *args, **kwargs: [
            {"summary_text": "单聊旧摘要"}
        ])
        monkeypatch.setattr(orchestrator.repository, "list_character_relationships", lambda *args, **kwargs: [
            {
                "character_id_a": "char_a",
                "character_id_b": "char_b",
                "relationship_type": "血盟契约",
                "affinity": 80,
                "description": "当前图谱确认的自定义关系",
                "updated_at": "2026-01-03T00:00:00+00:00",
            }
        ])
        monkeypatch.setattr(orchestrator.repository, "get_character_relationship_updated_at", lambda *args, **kwargs: "2026-01-03T00:00:00+00:00")
        monkeypatch.setattr(orchestrator.repository, "get_character_card_from_db", lambda *args, **kwargs: {
            "name": "乙",
            "display_name": "乙",
            "card_data": json.dumps({"meta": {"name": "乙", "display_name": "乙", "aliases": ["小乙"]}}),
        })
        monkeypatch.setattr(orchestrator.repository, "get_character_shared_memories", lambda *args, **kwargs: [
            {
                "character_a_id": "char_a",
                "character_b_id": "char_b",
                "memory_text": "甲和乙是师徒。",
                "created_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "character_a_id": "char_a",
                "character_b_id": "char_b",
                "memory_text": "甲和乙一起巡逻。",
                "created_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "character_a_id": "char_a",
                "character_b_id": "char_b",
                "memory_text": "一起调查旧仓库",
                "created_at": "2026-01-04T00:00:00+00:00",
            }
        ])

        def fake_group_memories(character_id, limit=20, created_after=None, owner_user_id=None):
            captured["group_owner"] = owner_user_id
            return [
                {
                    "memory_text": "甲和乙是师徒。",
                    "participants": json.dumps(["char_a", "char_b"]),
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "memory_text": "甲和乙一起调查仓库。",
                    "participants": json.dumps(["char_a", "char_b"]),
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "memory_text": "群聊里约好保管钥匙",
                    "participants": json.dumps(["char_a", "char_b"]),
                    "created_at": "2026-01-04T00:00:00+00:00",
                }
            ]

        monkeypatch.setattr(orchestrator.repository, "get_character_group_memories", fake_group_memories)

        def fake_get_prompt_memory_fact_records(*args, **kwargs):
            captured["memory_query_context"] = kwargs.get("query_context")
            captured["prompt_session_id"] = kwargs.get("session_id")
            return [
                {
                    "fact_text": "甲和乙是师徒。",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "fact_text": "玩家喜欢猫。",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "fact_text": "甲喜欢猫。",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
            ]

        monkeypatch.setattr(
            orchestrator.repository,
            "get_prompt_memory_fact_records",
            fake_get_prompt_memory_fact_records,
        )

        def fake_build_system_prompt(card_arg, runtime_state, player_name, past_summaries=None, relationship_graph_lines=None):
            captured["runtime_state"] = runtime_state
            captured["past_summaries"] = past_summaries
            captured["relationship_graph_lines"] = relationship_graph_lines
            return "prompt"

        monkeypatch.setattr(orchestrator.prompt_builder, "build_system_prompt", fake_build_system_prompt)
        monkeypatch.setattr(orchestrator.llm_client, "call_role_turn", lambda *args, **kwargs: {
            "dialogue": "记得。",
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
            lambda session_id, role, content, **kwargs: saved_messages.append((role, content, kwargs)) or len(saved_messages),
        )

        result = orchestrator.run_dialogue_turn("sid", "你还记得群聊的事吗？")

        assert result["dialogue"] == "记得。"
        assert captured["group_owner"] == "player"
        graph_text = "\n".join(captured["relationship_graph_lines"])
        assert "当前关系类型 = 血盟契约" in graph_text
        assert "关系强度 = 80/100" in graph_text
        assert "你还记得群聊的事吗？" in captured["memory_query_context"]
        assert captured["prompt_session_id"] == "sid"
        assert "当前关系类型 = 血盟契约" in captured["memory_query_context"]
        assert not any("甲和乙是师徒" in fact for fact in captured["runtime_state"]["known_player_facts"])
        assert "玩家喜欢猫。" in captured["runtime_state"]["known_player_facts"]
        assert "甲喜欢猫。" in captured["runtime_state"]["known_player_facts"]
        assert not any("师徒" in summary for summary in captured["past_summaries"])
        assert "共享记忆（与乙）：甲和乙一起巡逻。" in captured["past_summaries"]
        assert "共享记忆（与乙）：一起调查旧仓库" in captured["past_summaries"]
        assert "群体记忆：甲和乙一起调查仓库。" in captured["past_summaries"]
        assert "群体记忆：群聊里约好保管钥匙" in captured["past_summaries"]

    def test_event_state_changes_are_included_in_relationship_delta(self, monkeypatch):
        """事件改变信任/好感时，返回和保存的 delta 应反映最终总变化。"""
        from types import SimpleNamespace
        from memoria.core import orchestrator

        saved_messages = []
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
        monkeypatch.setattr(orchestrator.character_loader, "load_character_card", lambda *args, **kwargs: card)
        monkeypatch.setattr(orchestrator.repository, "get_runtime_state", lambda *args, **kwargs: {
            "affection_level": 10,
            "trust_level": 20,
            "current_mood": "neutral",
        })
        monkeypatch.setattr(orchestrator.repository, "get_short_term_history", lambda *args, **kwargs: [])
        monkeypatch.setattr(orchestrator.repository, "get_recent_summaries", lambda *args, **kwargs: [])
        monkeypatch.setattr(orchestrator.prompt_builder, "build_system_prompt", lambda *args, **kwargs: "prompt")
        monkeypatch.setattr(orchestrator.llm_client, "call_role_turn", lambda *args, **kwargs: {
            "dialogue": "可以",
            "action": "idle",
            "affinity_delta": 1,
            "trust_delta": 0,
            "mood_after": "neutral",
            "memory_worth_keeping": None,
        })
        monkeypatch.setattr(orchestrator.event_runtime, "detect_and_execute_events", lambda *args, **kwargs: [object()])
        monkeypatch.setattr(
            orchestrator.event_runtime,
            "apply_event_results_to_dialogue_state",
            lambda event_results, dialogue, affinity, trust, mood: (
                dialogue,
                affinity + 2,
                trust + 5,
                "happy",
                [{"event_id": "evt"}],
                "信任提升",
            ),
        )
        monkeypatch.setattr(orchestrator.repository, "save_runtime_state", lambda *args, **kwargs: None)

        def commit_turn(*, dialogue_turn, runtime_states):
            saved_messages.extend(dialogue_turn["messages"])
            return dialogue_turn["response"]

        monkeypatch.setattr(
            orchestrator.repository,
            "claim_dialogue_turn",
            lambda **kwargs: {"completed": False, "lease_owner": "lease"},
        )
        monkeypatch.setattr(orchestrator.repository, "commit_dialogue_turn", commit_turn)

        result = orchestrator.run_dialogue_turn("sid", "你好")

        assert result["current_affinity"] == 13
        assert result["current_trust"] == 25
        assert result["affinity_delta"] == 3
        assert result["trust_delta"] == 5
        assert saved_messages[1]["affinity_delta"] == 3
        assert saved_messages[1]["trust_delta"] == 5
        assert saved_messages[1]["current_trust"] == 25

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
        monkeypatch.setattr(orchestrator.character_loader, "load_character_card", lambda character_id, owner_user_id=None: card)
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
        monkeypatch.setattr(
            orchestrator.repository,
            "commit_dialogue_turn",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db write failed")),
        )
        monkeypatch.setattr(
            orchestrator.repository,
            "claim_dialogue_turn",
            lambda **kwargs: {"completed": False, "lease_owner": "lease"},
        )
        monkeypatch.setattr(orchestrator.repository, "fail_dialogue_turn", lambda *args: None)

        with pytest.raises(RuntimeError, match="db write failed"):
            orchestrator.run_dialogue_turn("sid", "你好")


def test_group_dialogue_saves_one_logical_thread_player_memory(monkeypatch):
    from types import SimpleNamespace
    from memoria.core import multi_character_orchestrator as module

    orchestrator = module.MultiCharacterOrchestrator.__new__(
        module.MultiCharacterOrchestrator
    )
    orchestrator.session_id = "group-session"
    orchestrator.player_id = "player"
    orchestrator.participants = [{"character_id": "char-a"}, {"character_id": "char-b"}]
    orchestrator.character_ids = ["char-a", "char-b"]

    clock_snapshot = SimpleNamespace(
        world_now=SimpleNamespace(isoformat=lambda: "2026-07-12T12:00:00+08:00")
    )
    extracted_histories = []
    saved_claims = []
    queued_jobs = []
    legacy_writes = []
    operation_order = []

    monkeypatch.setattr(module, "_clock_snapshot_for_player", lambda player_id: clock_snapshot)
    monkeypatch.setattr(
        module.repository,
        "claim_dialogue_turn",
        lambda **kwargs: {"completed": False, "lease_owner": "lease"},
    )
    monkeypatch.setattr(
        module.repository,
        "commit_dialogue_turn",
        lambda **kwargs: operation_order.append("commit")
        or queued_jobs.extend(kwargs["dialogue_turn"].get("background_jobs") or [])
        or kwargs["dialogue_turn"]["response"],
    )
    monkeypatch.setattr(
        module.repository,
        "get_session_user_turn_count",
        lambda session_id: module.configs.long_term_memory_interval_turns - 1,
    )
    monkeypatch.setattr(
        module.repository,
        "get_multi_character_thread_history",
        lambda *args, **kwargs: [{"role": "assistant", "content": "上次聊到饮料。"}],
    )

    def generate_group_discussion(player_message, response_count, **kwargs):
        return [{"dialogue": "记住了"}]

    monkeypatch.setattr(
        module.multi_character_memory,
        "resolve_generated_fact_scope",
        lambda session_id: ("group_thread", "thread-1"),
    )
    monkeypatch.setattr(
        module.repository,
        "save_long_term_fact",
        lambda *args, **kwargs: legacy_writes.append((args, kwargs)),
    )
    monkeypatch.setattr(orchestrator, "_ensure_has_active_participants", lambda: None)
    monkeypatch.setattr(orchestrator, "_decide_group_response_count", lambda *args: 2)
    monkeypatch.setattr(orchestrator, "_generate_group_discussion", generate_group_discussion)

    result = orchestrator.process_player_message(
        "我喜欢茉莉花茶",
        allow_multiple_responses=True,
        request_id="req-group-memory",
    )

    assert result == [{"dialogue": "记住了"}]
    assert extracted_histories == []
    assert saved_claims == []
    assert queued_jobs == [{
        "job_type": "group_checkpoint_memory",
        "dedupe_key": (
            "group_checkpoint_memory:group-session:"
            f"{module.configs.long_term_memory_interval_turns}"
        ),
        "payload": {
            "owner_user_id": "player",
            "scope_type": "group_thread",
            "scope_id": "thread-1",
            "session_id": "group-session",
            "history": [
                {"role": "assistant", "content": "上次聊到饮料。"},
                {"role": "user", "content": "我喜欢茉莉花茶"},
                {"role": "assistant", "content": "记住了"},
            ],
        },
    }]
    assert legacy_writes == []
    assert operation_order == ["commit"]


def test_group_dialogue_single_response_saves_one_logical_thread_claim(monkeypatch):
    from types import SimpleNamespace
    from memoria.core import multi_character_orchestrator as module

    orchestrator = module.MultiCharacterOrchestrator.__new__(
        module.MultiCharacterOrchestrator
    )
    orchestrator.session_id = "group-session"
    orchestrator.player_id = "player"
    orchestrator.participants = [
        {"character_id": "speaker"},
        {"character_id": "listener-a"},
        {"character_id": "listener-b"},
    ]
    orchestrator.character_ids = ["speaker", "listener-a", "listener-b"]

    clock_snapshot = SimpleNamespace(
        world_now=SimpleNamespace(isoformat=lambda: "2026-07-12T12:00:00+08:00")
    )
    saved_claims = []
    queued_jobs = []
    legacy_writes = []

    monkeypatch.setattr(module, "_clock_snapshot_for_player", lambda player_id: clock_snapshot)
    monkeypatch.setattr(
        module.repository,
        "claim_dialogue_turn",
        lambda **kwargs: {"completed": False, "lease_owner": "lease"},
    )
    monkeypatch.setattr(
        module.repository,
        "commit_dialogue_turn",
        lambda **kwargs: queued_jobs.extend(
            kwargs["dialogue_turn"].get("background_jobs") or []
        )
        or kwargs["dialogue_turn"]["response"],
    )
    monkeypatch.setattr(
        module.repository,
        "get_session_user_turn_count",
        lambda session_id: module.configs.long_term_memory_interval_turns - 1,
    )
    monkeypatch.setattr(
        module.repository,
        "get_multi_character_thread_history",
        lambda *args, **kwargs: [{"role": "assistant", "content": "上次约好周末见。"}],
    )
    monkeypatch.setattr(
        module.multi_character_memory,
        "resolve_generated_fact_scope",
        lambda session_id: ("group_thread", "thread-1"),
    )
    monkeypatch.setattr(
        module.repository,
        "save_long_term_fact",
        lambda *args, **kwargs: legacy_writes.append((args, kwargs)),
    )
    monkeypatch.setattr(orchestrator, "_ensure_has_active_participants", lambda: None)
    monkeypatch.setattr(
        orchestrator,
        "_decide_next_speaker",
        lambda player_message, turn_context=None: "speaker",
    )
    monkeypatch.setattr(orchestrator, "_build_pulse_state", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        orchestrator,
        "_generate_character_response",
        lambda character_id, player_message, **kwargs: {
            "character_id": character_id,
            "dialogue": "我等你。",
        },
    )

    result = orchestrator.process_player_message(
        "我周末会带蛋糕来",
        request_id="req-group-single-memory",
    )

    assert result["character_id"] == "speaker"
    assert saved_claims == []
    assert queued_jobs == [{
        "job_type": "group_checkpoint_memory",
        "dedupe_key": (
            "group_checkpoint_memory:group-session:"
            f"{module.configs.long_term_memory_interval_turns}"
        ),
        "payload": {
            "owner_user_id": "player",
            "scope_type": "group_thread",
            "scope_id": "thread-1",
            "session_id": "group-session",
            "history": [
                {"role": "assistant", "content": "上次约好周末见。"},
                {"role": "user", "content": "我周末会带蛋糕来"},
                {"role": "assistant", "content": "我等你。"},
            ],
        },
    }]
    assert legacy_writes == []


def test_single_dialogue_turn_emits_stream_events(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from memoria.core import orchestrator, performance

    card = SimpleNamespace(
        meta=SimpleNamespace(name="角色一", display_name="角色一"),
        speech_style=SimpleNamespace(language="zh-CN"),
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
    clock = SimpleNamespace(
        world_now=datetime(2026, 7, 15, tzinfo=timezone.utc),
        prompt_context=lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "get_session",
        lambda session_id: {
            "session_id": session_id,
            "character_id": "char-1",
            "player_id": "player-1",
            "player_name": "玩家",
            "status": "active",
            "locale": "zh-CN",
        },
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "claim_dialogue_turn",
        lambda **kwargs: {"completed": False, "lease_owner": "lease"},
    )
    monkeypatch.setattr(orchestrator, "_load_character_card", lambda *args: card)
    monkeypatch.setattr(
        orchestrator.world_clock,
        "get_clock_snapshot",
        lambda player_id: clock,
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "get_last_character_interaction_world_at",
        lambda *args: None,
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "get_runtime_state",
        lambda *args, **kwargs: {
            "affection_level": 0,
            "trust_level": 0,
            "current_mood": "neutral",
            "known_player_facts": [],
        },
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "get_short_term_history",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        orchestrator,
        "retrieve_knowledge",
        lambda **kwargs: SimpleNamespace(prompt_section="", sources=[]),
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "get_recent_summaries",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        orchestrator,
        "_load_player_character",
        lambda *args: {"display_name": "玩家"},
    )
    monkeypatch.setattr(
        orchestrator,
        "_load_single_character_prompt_context",
        lambda *args, **kwargs: {
            "known_player_facts": [],
            "cross_mode_memories": [],
            "relationship_graph_lines": [],
            "character_relationships": {},
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "_build_system_prompt",
        lambda *args, **kwargs: "prompt",
    )

    def fake_role_turn(*args, on_dialogue_delta=None, **kwargs):
        on_dialogue_delta("你")
        on_dialogue_delta("好")
        return {
            "dialogue": "你好",
            "action": "idle",
            "affinity_delta": 0,
            "trust_delta": 0,
            "mood_after": "neutral",
        }

    monkeypatch.setattr(orchestrator.llm_client, "call_role_turn", fake_role_turn)
    monkeypatch.setattr(
        orchestrator.event_runtime,
        "detect_and_execute_events",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "commit_dialogue_turn",
        lambda *, dialogue_turn, runtime_states: dialogue_turn["response"],
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "is_long_term_memory_checkpoint",
        lambda *args, **kwargs: False,
    )

    events = []
    performance.reset()
    result = orchestrator.run_dialogue_turn(
        "session-1",
        "你好",
        request_id="req-1",
        event_sink=lambda event_type, data: events.append((event_type, data)),
    )

    assert result["dialogue"] == "你好"
    assert [event_type for event_type, _ in events if event_type != "stage"] == [
        "character_started",
        "dialogue_delta",
        "dialogue_delta",
        "character_completed",
    ]
    assert events[-1][1]["response"]["dialogue"] == "你好"
    assert (
        performance.snapshot()["durations"]["dialogue.turn.total"]["count"]
        == 1
    )
    assert (
        performance.snapshot()["durations"]["dialogue.turn.prepare"]["count"]
        == 1
    )
    assert (
        performance.snapshot()["durations"]["dialogue.turn.prompt"]["count"]
        == 1
    )


def test_multi_character_turn_propagates_event_sink(monkeypatch):
    from memoria.core import multi_character_orchestrator as module, performance

    events = []

    class FakeOrchestrator:
        def __init__(self, session_id):
            self.session_id = session_id

        def process_player_message(self, player_message, **kwargs):
            kwargs["event_sink"](
                "dialogue_delta",
                {"stream_id": "req-1:0", "delta": "收到"},
            )
            return {"dialogue": "收到"}

    monkeypatch.setattr(module, "MultiCharacterOrchestrator", FakeOrchestrator)

    performance.reset()
    result = module.process_multi_character_turn(
        "session-1",
        "行动",
        request_id="req-1",
        event_sink=lambda event_type, data: events.append((event_type, data)),
    )

    assert result == {"dialogue": "收到"}
    assert events == [
        ("dialogue_delta", {"stream_id": "req-1:0", "delta": "收到"})
    ]
    assert (
        performance.snapshot()["durations"]["multi_dialogue.turn.total"]["count"]
        == 1
    )


def test_unpersisted_group_pulse_loads_base_history_once(monkeypatch):
    from types import SimpleNamespace

    from memoria.core import multi_character_orchestrator as module

    orchestrator = module.MultiCharacterOrchestrator.__new__(
        module.MultiCharacterOrchestrator
    )
    orchestrator.session_id = "session-1"
    orchestrator.player_id = "player-1"
    orchestrator.player_name = "玩家"
    orchestrator.player_character = {"display_name": "玩家"}
    orchestrator.participants = [
        {"character_id": "c1"},
        {"character_id": "c2"},
    ]
    orchestrator.character_ids = ["c1", "c2"]
    orchestrator.character_cards = {}
    orchestrator.last_speaker_id = None

    history_reads = 0
    observed_histories = []
    decisions = iter([
        module.DialogueDecision(
            action="speak",
            speaker_id="c1",
            reply_to_message_id=-1,
            intent="answer",
        ),
        module.DialogueDecision(
            action="speak",
            speaker_id="c2",
            reply_to_message_id=-2,
            reply_to_character_id="c1",
            intent="agree",
        ),
        module.DialogueDecision(action="wait", wait_for_player=True),
    ])

    def load_history(*args, **kwargs):
        nonlocal history_reads
        history_reads += 1
        return [{"message_id": 1, "role": "user", "content": "上一轮"}]

    def decide(**kwargs):
        observed_histories.append([
            message["content"] for message in kwargs["history"]
        ])
        return next(decisions)

    def generate(character_id, player_message, **kwargs):
        return {
            "character_id": character_id,
            "character_name": character_id,
            "dialogue": "先侦查" if character_id == "c1" else "我来接应",
            "reply_to_message_id": kwargs["decision"].reply_to_message_id,
        }

    monkeypatch.setattr(
        module.repository,
        "get_multi_character_thread_history",
        load_history,
    )
    monkeypatch.setattr(orchestrator, "_decide_dialogue_action", decide)
    monkeypatch.setattr(orchestrator, "_generate_character_response", generate)
    monkeypatch.setattr(orchestrator, "_refresh_player_character", lambda: {})
    monkeypatch.setattr(orchestrator, "_load_all_relationships", lambda: {})
    monkeypatch.setattr(
        module.repository,
        "get_group_thread_id",
        lambda session_id: "thread-1",
    )
    monkeypatch.setattr(
        module.repository,
        "get_authorized_knowledge_base_ids",
        lambda *args, **kwargs: [],
    )

    responses = orchestrator.run_dialogue_pulse(
        trigger_source="event",
        trigger_text="制定计划",
        max_messages=3,
        persist_state=False,
        persist_messages=False,
        staged_history=[
            {"message_id": -1, "role": "user", "content": "制定计划"}
        ],
        clock_snapshot=SimpleNamespace(
            world_now=SimpleNamespace(isoformat=lambda: "now")
        ),
    )

    assert history_reads == 1
    assert [response["dialogue"] for response in responses] == [
        "先侦查",
        "我来接应",
    ]
    assert observed_histories == [
        ["上一轮", "制定计划"],
        ["上一轮", "制定计划", "先侦查"],
        ["上一轮", "制定计划", "先侦查", "我来接应"],
    ]


def test_group_pulse_reuses_shared_context_and_preauthorizes_kb_ids(monkeypatch):
    from types import SimpleNamespace

    from memoria.core import multi_character_orchestrator as module

    orchestrator = module.MultiCharacterOrchestrator.__new__(
        module.MultiCharacterOrchestrator
    )
    orchestrator.session_id = "session-1"
    orchestrator.player_id = "player-1"
    orchestrator.player_name = "玩家"
    orchestrator.player_character = {"display_name": "旧名字"}
    orchestrator.participants = [
        {"character_id": "c1"},
        {"character_id": "c2"},
    ]
    orchestrator.character_ids = ["c1", "c2"]
    orchestrator.character_cards = {}
    orchestrator.last_speaker_id = None

    reads = {
        "player_character": 0,
        "relationships": 0,
        "group_thread_id": 0,
    }
    authorization_reads = []
    generated_contexts = []
    decisions = iter([
        module.DialogueDecision(
            action="speak",
            speaker_id="c1",
            reply_to_message_id=1,
            intent="answer",
        ),
        module.DialogueDecision(
            action="speak",
            speaker_id="c2",
            reply_to_message_id=-1,
            reply_to_character_id="c1",
            intent="agree",
        ),
    ])

    def refresh_player_character():
        reads["player_character"] += 1
        orchestrator.player_character = {"display_name": "玩家"}
        return orchestrator.player_character

    def load_relationships():
        reads["relationships"] += 1
        return {"c1_c2": {"relationship_type": "ally", "affinity": 50}}

    def load_group_thread_id(session_id):
        reads["group_thread_id"] += 1
        return "thread-1"

    def load_authorized_ids(owner_user_id, *, character_id, group_thread_id):
        authorization_reads.append((character_id, group_thread_id))
        return [f"kb-{character_id}"]

    def generate(character_id, player_message, **kwargs):
        generated_contexts.append(kwargs.get("turn_context"))
        return {
            "character_id": character_id,
            "character_name": character_id,
            "dialogue": f"reply-{character_id}",
            "reply_to_message_id": kwargs["decision"].reply_to_message_id,
        }

    monkeypatch.setattr(orchestrator, "_refresh_player_character", refresh_player_character)
    monkeypatch.setattr(orchestrator, "_load_all_relationships", load_relationships)
    monkeypatch.setattr(module.repository, "get_group_thread_id", load_group_thread_id)
    monkeypatch.setattr(
        module.repository,
        "get_authorized_knowledge_base_ids",
        load_authorized_ids,
    )
    monkeypatch.setattr(
        module.repository,
        "get_multi_character_thread_history",
        lambda *args, **kwargs: [
            {"message_id": 1, "role": "user", "content": "继续"}
        ],
    )
    monkeypatch.setattr(
        orchestrator,
        "_decide_dialogue_action",
        lambda **kwargs: next(decisions),
    )
    monkeypatch.setattr(orchestrator, "_generate_character_response", generate)

    responses = orchestrator.run_dialogue_pulse(
        trigger_source="player",
        trigger_text="继续",
        max_messages=2,
        persist_state=False,
        persist_messages=False,
        clock_snapshot=SimpleNamespace(
            world_now=SimpleNamespace(isoformat=lambda: "now")
        ),
    )

    assert len(responses) == 2
    assert reads == {
        "player_character": 1,
        "relationships": 1,
        "group_thread_id": 1,
    }
    assert authorization_reads == [
        ("c1", "thread-1"),
        ("c2", "thread-1"),
    ]
    assert generated_contexts[0] is generated_contexts[1]
    assert generated_contexts[0].player_character == {"display_name": "玩家"}
    assert generated_contexts[0].character_relationships == {
        "c1_c2": {"relationship_type": "ally", "affinity": 50}
    }
    assert generated_contexts[0].authorized_knowledge_base_ids["c1"] == ["kb-c1"]
    assert generated_contexts[0].authorized_knowledge_base_ids["c2"] == ["kb-c2"]


def test_single_group_turn_reuses_context_across_selection_generation_and_commit(
    monkeypatch,
):
    from types import SimpleNamespace

    from memoria.core import multi_character_orchestrator as module

    orchestrator = module.MultiCharacterOrchestrator.__new__(
        module.MultiCharacterOrchestrator
    )
    orchestrator.session_id = "session-1"
    orchestrator.player_id = "player-1"
    orchestrator.player_name = "玩家"
    orchestrator.player_character = {"display_name": "玩家"}
    orchestrator.participants = [{"character_id": "c1"}]
    orchestrator.character_ids = ["c1"]
    orchestrator.character_cards = {}
    orchestrator.last_speaker_id = None

    context_users = []
    monkeypatch.setattr(
        module.repository,
        "claim_dialogue_turn",
        lambda **kwargs: {"completed": False, "lease_owner": "lease"},
    )
    monkeypatch.setattr(
        module.repository,
        "get_multi_character_thread_history",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        module.repository,
        "get_group_thread_id",
        lambda session_id: "thread-1",
    )
    monkeypatch.setattr(
        module.repository,
        "get_authorized_knowledge_base_ids",
        lambda *args, **kwargs: ["kb-1"],
    )
    monkeypatch.setattr(orchestrator, "_refresh_player_character", lambda: {})
    monkeypatch.setattr(orchestrator, "_load_all_relationships", lambda: {})
    monkeypatch.setattr(
        orchestrator,
        "_decide_next_speaker",
        lambda player_message, turn_context=None: (
            context_users.append(turn_context) or "c1"
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "_generate_character_response",
        lambda character_id, player_message, turn_context=None, **kwargs: (
            context_users.append(turn_context)
            or {"character_id": character_id, "dialogue": "收到"}
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "_apply_group_event_results",
        lambda *args, turn_context=None, **kwargs: context_users.append(
            turn_context
        ),
    )
    monkeypatch.setattr(
        module,
        "_clock_snapshot_for_player",
        lambda player_id: SimpleNamespace(
            world_now=SimpleNamespace(isoformat=lambda: "now")
        ),
    )

    result = orchestrator.process_player_message(
        "继续",
        request_id="request-1",
    )

    assert result["dialogue"] == "收到"
    assert len(context_users) == 3
    assert context_users[0] is not None
    assert context_users[0] is context_users[1] is context_users[2]


def test_group_response_passes_preauthorized_kb_ids_to_retrieval(monkeypatch):
    from types import SimpleNamespace

    from memoria.core import multi_character_orchestrator as module

    orchestrator = module.MultiCharacterOrchestrator.__new__(
        module.MultiCharacterOrchestrator
    )
    orchestrator.session_id = "session-1"
    orchestrator.player_id = "player-1"
    orchestrator.player_name = "玩家"
    orchestrator.player_character = {"display_name": "玩家"}
    orchestrator.participants = [{"character_id": "c1"}]
    orchestrator.character_ids = ["c1"]
    orchestrator.character_cards = {
        "c1": SimpleNamespace(
            meta=SimpleNamespace(name="甲", display_name="甲"),
            speech_style=SimpleNamespace(language="zh-CN"),
            action_vocabulary=SimpleNamespace(default_action="idle"),
        )
    }

    retrieval_calls = []
    clock_snapshot = SimpleNamespace(
        world_now=SimpleNamespace(isoformat=lambda: "now"),
        prompt_context=lambda *args, **kwargs: {},
    )
    turn_context = module.GroupTurnContext(
        player_character={"display_name": "玩家"},
        character_relationships={},
        group_thread_id="thread-1",
        authorized_knowledge_base_ids={"c1": ["kb-1", "kb-2"]},
    )

    monkeypatch.setattr(
        module.multi_character_memory,
        "get_relationship_history_cutoff",
        lambda *args, **kwargs: "2026-07-16T08:00:00+00:00",
    )
    monkeypatch.setattr(
        orchestrator,
        "_load_runtime_state_for_prompt",
        lambda *args, **kwargs: {
            "affection_level": 0,
            "trust_level": 0,
            "current_mood": "neutral",
        },
    )
    monkeypatch.setattr(
        module.repository,
        "get_last_character_interaction_world_at",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        module,
        "retrieve_knowledge",
        lambda **kwargs: (
            retrieval_calls.append(kwargs)
            or SimpleNamespace(prompt_section="", sources=[])
        ),
    )
    monkeypatch.setattr(
        module,
        "_build_multi_character_system_prompt",
        lambda **kwargs: "prompt",
    )
    monkeypatch.setattr(orchestrator, "_load_memory_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        orchestrator,
        "_format_history_for_llm",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        module.llm_client,
        "call_role_turn",
        lambda **kwargs: {
            "dialogue": "收到",
            "action": "idle",
            "affinity_delta": 0,
            "trust_delta": 0,
            "mood_after": "neutral",
        },
    )

    result = orchestrator._generate_character_response(
        "c1",
        "继续",
        clock_snapshot=clock_snapshot,
        history_override=[
            {
                "message_id": 1,
                "role": "user",
                "content": "已被关系修订失效的历史",
                "created_at": "2026-07-16T07:59:59+00:00",
            },
            {
                "message_id": 2,
                "role": "assistant",
                "content": "仍然有效的历史",
                "created_at": "2026-07-16T08:00:00+00:00",
            },
            {"message_id": -1, "role": "user", "content": "继续"},
        ],
        persist=False,
        turn_context=turn_context,
    )

    assert result["dialogue"] == "收到"
    assert retrieval_calls[0]["group_thread_id"] == "thread-1"
    assert retrieval_calls[0]["preauthorized_knowledge_base_ids"] == [
        "kb-1",
        "kb-2",
    ]
    assert [item["content"] for item in retrieval_calls[0]["recent_history"]] == [
        "仍然有效的历史",
        "继续",
    ]
